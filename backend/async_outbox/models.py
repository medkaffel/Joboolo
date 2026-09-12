"""Strict A14 value contracts, separate from persistence and handler policy.

Operational state is represented as an immutable snapshot of mutable stored
state. No model grants Permission/Trust or guarantees exactly-once effects.
Opaque references are internal only: syntactic validation cannot establish
that a caller supplied a privacy-safe identifier. Never log these objects.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import NewType

from bson.int64 import Int64

from domains.shared.ids import CausationId, CorrelationId, IdempotencyKey
from domains.shared.versioning import SchemaVersion

AsyncJobId = NewType("AsyncJobId", str)
ENVELOPE_SCHEMA_VERSION = "async-outbox-v1"


def opaque_token(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError("invalid opaque token")
    return value


def version_token(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise ValueError("invalid version token")
    return value


def bounded_int(value: int, minimum: int, maximum: int) -> int:
    # Accept BSON's exact integer wrapper, never bool, float or string coercion.
    if type(value) not in (int, Int64) or not minimum <= value <= maximum:
        raise ValueError("integer outside supported bounds")
    return int(value)


def utc_millisecond(value: datetime, *, storage: bool = False) -> datetime:
    if type(value) is not datetime:
        raise ValueError("expected datetime")
    try:
        if value.tzinfo is None:
            if not storage:
                raise ValueError("timezone-aware datetime required")
            value = value.replace(tzinfo=timezone.utc)
        if value.utcoffset() is None:
            raise ValueError("invalid datetime offset")
        result = value.astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError):
        raise ValueError("invalid UTC datetime") from None
    if result.microsecond % 1000:
        raise ValueError("BSON millisecond precision required")
    return result


class JobState(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    COMPLETED = "completed"
    FAILED = "failed"


class FailureCode(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNSUPPORTED_PAYLOAD = "unsupported_payload"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"


@dataclass(frozen=True, slots=True, repr=False)
class JobReference:
    reference_type: str
    reference_id: str
    reference_version: int

    def __post_init__(self):
        opaque_token(self.reference_type)
        opaque_token(self.reference_id)
        bounded_int(self.reference_version, 1, 2**63 - 1)


@dataclass(frozen=True, slots=True, repr=False)
class RetryPolicy:
    max_attempts: int
    initial_delay_seconds: int
    max_delay_seconds: int
    # Closed algorithm version, not a registry of future handlers.
    version: str = "exponential-v1"

    def __post_init__(self):
        bounded_int(self.max_attempts, 1, 100)
        bounded_int(self.initial_delay_seconds, 1, 604800)
        bounded_int(self.max_delay_seconds, self.initial_delay_seconds, 604800)
        if type(self.version) is not str or self.version != "exponential-v1":
            raise ValueError("unsupported retry policy version")

    def delay_seconds(self, attempt_count: int) -> int:
        bounded_int(attempt_count, 1, self.max_attempts)
        return min(self.max_delay_seconds, self.initial_delay_seconds * 2 ** (attempt_count - 1))


@dataclass(frozen=True, slots=True, repr=False)
class JobEnvelope:
    job_id: AsyncJobId
    job_type: str
    idempotency_key: IdempotencyKey
    payload_schema_version: SchemaVersion
    reference: JobReference
    retry_policy: RetryPolicy
    created_at: datetime
    initial_available_at: datetime
    schema_version: SchemaVersion = SchemaVersion(ENVELOPE_SCHEMA_VERSION)
    correlation_id: CorrelationId | None = None
    causation_id: CausationId | None = None

    def __post_init__(self):
        for value in (self.job_id, self.job_type, self.idempotency_key):
            opaque_token(value)
        for value in (self.correlation_id, self.causation_id):
            if value is not None:
                opaque_token(value)
        version_token(self.payload_schema_version)
        if type(self.schema_version) is not str or self.schema_version != ENVELOPE_SCHEMA_VERSION:
            raise ValueError("unsupported envelope schema version")
        if type(self.reference) is not JobReference or type(self.retry_policy) is not RetryPolicy:
            raise ValueError("invalid envelope contracts")
        for name in ("created_at", "initial_available_at"):
            object.__setattr__(self, name, utc_millisecond(getattr(self, name)))
        if self.initial_available_at < self.created_at:
            raise ValueError("availability predates creation")


@dataclass(frozen=True, slots=True, repr=False)
class OperationalState:
    state: JobState
    # Number of successful acquisitions, including acquisitions lost to crash.
    attempt_count: int
    available_at: datetime
    updated_at: datetime
    lease_owner: str | None = None
    lease_token: str | None = None
    lease_until: datetime | None = None
    completion_token: str | None = None
    completed_at: datetime | None = None
    failed_at: datetime | None = None
    failure_code: FailureCode | None = None

    def __post_init__(self):
        if type(self.state) is not JobState:
            raise ValueError("invalid job state")
        bounded_int(self.attempt_count, 0, 100)
        if self.failure_code is not None and type(self.failure_code) is not FailureCode:
            raise ValueError("invalid failure code")
        for name in ("available_at", "updated_at", "lease_until", "completed_at", "failed_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, utc_millisecond(value))
            elif name in ("available_at", "updated_at"):
                raise ValueError("missing operational timestamp")
        for value in (self.lease_owner, self.lease_token, self.completion_token):
            if value is not None:
                opaque_token(value)
        lease = (self.lease_owner, self.lease_token, self.lease_until)
        if self.state is JobState.LEASED:
            if any(value is None for value in lease) or self.attempt_count == 0:
                raise ValueError("leased state requires acquisition and ownership")
            if self.lease_until <= self.updated_at or self.available_at > self.updated_at:
                raise ValueError("invalid lease timestamps")
        elif any(value is not None for value in lease):
            raise ValueError("lease metadata outside leased state")
        if self.state is JobState.COMPLETED:
            if self.completion_token is None or self.completed_at is None or self.attempt_count == 0:
                raise ValueError("completion marker required")
            if self.completed_at != self.updated_at:
                raise ValueError("invalid completion timestamp")
        elif self.completion_token is not None or self.completed_at is not None:
            raise ValueError("completion metadata outside completed state")
        if self.state is JobState.FAILED:
            if self.failed_at != self.updated_at or self.failure_code not in (
                FailureCode.PERMANENT, FailureCode.UNSUPPORTED_PAYLOAD, FailureCode.ATTEMPTS_EXHAUSTED
            ) or self.attempt_count == 0:
                raise ValueError("invalid terminal failure")
        elif self.failed_at is not None:
            raise ValueError("failure timestamp outside failed state")
        if self.state in (JobState.LEASED, JobState.COMPLETED) and self.failure_code is not None:
            raise ValueError("stale failure metadata")
        if self.state is JobState.PENDING:
            expected = FailureCode.TRANSIENT if self.attempt_count else None
            if self.failure_code is not expected:
                raise ValueError("invalid pending failure metadata")


@dataclass(frozen=True, slots=True, repr=False)
class OutboxRecord:
    envelope: JobEnvelope
    operational: OperationalState

    def __post_init__(self):
        if type(self.envelope) is not JobEnvelope or type(self.operational) is not OperationalState:
            raise ValueError("invalid outbox contracts")
        env, op = self.envelope, self.operational
        if op.attempt_count > env.retry_policy.max_attempts:
            raise ValueError("attempt budget exceeded")
        if op.updated_at < env.created_at or op.available_at < env.initial_available_at:
            raise ValueError("operational timestamp predates envelope")
        if op.state is JobState.PENDING:
            if op.attempt_count >= env.retry_policy.max_attempts:
                raise ValueError("exhausted job cannot remain pending")
            if op.attempt_count == 0 and (op.available_at != env.initial_available_at or op.updated_at != env.created_at):
                raise ValueError("invalid initial operational state")
            if op.attempt_count and op.available_at <= op.updated_at:
                raise ValueError("retry must be scheduled after failure")
        if op.failure_code is FailureCode.ATTEMPTS_EXHAUSTED and op.attempt_count != env.retry_policy.max_attempts:
            raise ValueError("attempt budget not exhausted")
