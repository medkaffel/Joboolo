"""Strict BSON contracts for the B9 Contact Governor ledger.

This module is pure persistence mapping: it performs no Mongo I/O, never reads
a clock and never repairs malformed data. Mongo's UTC-naive BSON datetimes are
normalized only while rehydrating documents; domain inputs remain subject to
the existing aware, whole-millisecond governor time contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json

from bson.int64 import Int64

from domains.trust.contact_governor_models import (
    ContactGovernorRequest,
    GovernorDuplicateScope,
    GovernorReservationCommand,
    GovernorReservationState,
    require_governor_time,
)


CONTACT_GOVERNOR_RESERVATION_SCHEMA_VERSION = "contact-governor-reservation-v1"
CONTACT_GOVERNOR_CANDIDATE_GUARD_SCHEMA_VERSION = (
    "contact-governor-candidate-guard-v1"
)
TS_B9_DEDUP_PREFIX = "ts-b9-dedup-v1"

RESERVATION_REQUIRED_FIELDS = {
    "_id",
    "schema_version",
    "request_fingerprint",
    "idempotency_key",
    "candidate_id",
    "stream_id",
    "generation_id",
    "projection_state_version",
    "stream_version",
    "requirement_version",
    "role_dna_id",
    "role_dna_version",
    "opportunity_spec_id",
    "opportunity_spec_version",
    "recruiter_user_id",
    "requesting_organization_id",
    "hiring_company_id",
    "policy_version",
    "dedup_scope",
    "dedup_key",
    "activity_at",
    "expires_at",
    "status",
}
RESERVATION_OPTIONAL_FIELDS = {"mandate_id", "contact_request_id"}
GUARD_FIELDS = {"_id", "schema_version", "revision", "updated_at"}


def _shape(value, required, optional, field):
    if type(value) is not dict:
        raise ValueError(f"{field} must be a BSON object")
    if value.keys() - required - optional:
        raise ValueError(f"{field} has unknown fields")
    if not required <= value.keys():
        raise ValueError(f"{field} is missing required fields")


def _nonblank(value, field):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")
    return value


def _positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, Int64)) or value < 1:
        raise ValueError(f"{field} must be a positive int")
    return int(value)


def _storage_time(value, field):
    if type(value) is not datetime:
        raise ValueError(f"{field} must be a datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return require_governor_time(value, field)


def _digest(value, prefix, field):
    value = _nonblank(value, field)
    expected = f"{prefix}:"
    if not value.startswith(expected):
        raise ValueError(f"invalid {field}")
    digest = value[len(expected):]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"invalid {field}")
    return value


def derive_dedup_key(
    request: ContactGovernorRequest,
    scope: GovernorDuplicateScope,
) -> str:
    """Canonical B9 duplicate identity for one configured duplicate scope."""
    if type(request) is not ContactGovernorRequest:
        raise ValueError("request must be ContactGovernorRequest")
    if type(scope) is not GovernorDuplicateScope:
        raise ValueError("scope must be GovernorDuplicateScope")
    actor = request.recruiting_actor
    scoped_actor = {
        GovernorDuplicateScope.STREAM_CANDIDATE_RECRUITER: str(
            actor.recruiter_user_id
        ),
        GovernorDuplicateScope.STREAM_CANDIDATE_REQUESTING_ORGANIZATION: str(
            actor.requesting_organization_id
        ),
        GovernorDuplicateScope.STREAM_CANDIDATE_HIRING_COMPANY: str(
            actor.hiring_company_id
        ),
    }[scope]
    canonical = json.dumps(
        [
            TS_B9_DEDUP_PREFIX,
            scope.value,
            str(request.stream_id),
            str(request.candidate_id),
            scoped_actor,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return f"{TS_B9_DEDUP_PREFIX}:{sha256(canonical.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True, repr=False)
class ContactGovernorReservationRecord:
    reservation_id: str
    request_fingerprint: str
    idempotency_key: str
    candidate_id: str
    stream_id: str
    generation_id: str
    projection_state_version: int
    stream_version: int
    requirement_version: int
    role_dna_id: str
    role_dna_version: int
    opportunity_spec_id: str
    opportunity_spec_version: int
    recruiter_user_id: str
    requesting_organization_id: str
    hiring_company_id: str
    mandate_id: str | None
    policy_version: str
    dedup_scope: GovernorDuplicateScope | None
    dedup_key: str | None
    activity_at: datetime
    expires_at: datetime
    status: GovernorReservationState
    contact_request_id: str | None = None
    schema_version: str = CONTACT_GOVERNOR_RESERVATION_SCHEMA_VERSION

    def __post_init__(self):
        _digest(self.reservation_id, "ts-b9-reservation-v1", "reservation_id")
        _digest(
            self.request_fingerprint,
            "ts-b9-request-v1",
            "request_fingerprint",
        )
        for field in (
            "idempotency_key",
            "candidate_id",
            "stream_id",
            "generation_id",
            "role_dna_id",
            "opportunity_spec_id",
            "recruiter_user_id",
            "requesting_organization_id",
            "hiring_company_id",
            "policy_version",
        ):
            _nonblank(getattr(self, field), field)
        if self.mandate_id is not None:
            _nonblank(self.mandate_id, "mandate_id")
        for field in (
            "projection_state_version",
            "stream_version",
            "requirement_version",
            "role_dna_version",
            "opportunity_spec_version",
        ):
            object.__setattr__(self, field, _positive_int(getattr(self, field), field))
        activity_at = require_governor_time(self.activity_at, "activity_at")
        expires_at = require_governor_time(self.expires_at, "expires_at")
        object.__setattr__(self, "activity_at", activity_at)
        object.__setattr__(self, "expires_at", expires_at)
        if expires_at <= activity_at:
            raise ValueError("expires_at must be after activity_at")
        if type(self.status) is not GovernorReservationState:
            raise ValueError("status must be GovernorReservationState")
        if self.dedup_scope is None:
            if self.dedup_key is not None:
                raise ValueError("dedup key requires a scope")
        else:
            if type(self.dedup_scope) is not GovernorDuplicateScope:
                raise ValueError("dedup_scope must be GovernorDuplicateScope")
            _digest(self.dedup_key, TS_B9_DEDUP_PREFIX, "dedup_key")
        if self.status is GovernorReservationState.CONSUMED:
            _nonblank(self.contact_request_id, "contact_request_id")
        elif self.contact_request_id is not None:
            raise ValueError("only consumed reservations may bind a contact request")
        if self.schema_version != CONTACT_GOVERNOR_RESERVATION_SCHEMA_VERSION:
            raise ValueError("unsupported reservation schema version")


@dataclass(frozen=True, slots=True, repr=False)
class ContactGovernorCandidateGuard:
    candidate_id: str
    revision: int
    updated_at: datetime
    schema_version: str = CONTACT_GOVERNOR_CANDIDATE_GUARD_SCHEMA_VERSION

    def __post_init__(self):
        _nonblank(self.candidate_id, "candidate_id")
        object.__setattr__(self, "revision", _positive_int(self.revision, "revision"))
        object.__setattr__(
            self,
            "updated_at",
            require_governor_time(self.updated_at, "updated_at"),
        )
        if self.schema_version != CONTACT_GOVERNOR_CANDIDATE_GUARD_SCHEMA_VERSION:
            raise ValueError("unsupported candidate guard schema version")


def reservation_record_from_command(
    command: GovernorReservationCommand,
) -> ContactGovernorReservationRecord:
    if type(command) is not GovernorReservationCommand:
        raise ValueError("command must be GovernorReservationCommand")
    request = command.request
    actor = request.recruiting_actor
    duplicate = command.policy.duplicate_protection_policy
    scope = duplicate.scope if duplicate.enabled else None
    dedup_key = derive_dedup_key(request, scope) if scope is not None else None
    return ContactGovernorReservationRecord(
        reservation_id=command.reservation_id,
        request_fingerprint=command.request_fingerprint,
        idempotency_key=str(request.idempotency_key),
        candidate_id=str(request.candidate_id),
        stream_id=str(request.stream_id),
        generation_id=request.generation_id,
        projection_state_version=request.projection_state_version,
        stream_version=request.stream_version,
        requirement_version=request.requirement_version,
        role_dna_id=str(request.role_dna_id),
        role_dna_version=request.role_dna_version,
        opportunity_spec_id=str(request.opportunity_spec_id),
        opportunity_spec_version=request.opportunity_spec_version,
        recruiter_user_id=str(actor.recruiter_user_id),
        requesting_organization_id=str(actor.requesting_organization_id),
        hiring_company_id=str(actor.hiring_company_id),
        mandate_id=None if actor.mandate_id is None else str(actor.mandate_id),
        policy_version=str(command.policy.policy_version),
        dedup_scope=scope,
        dedup_key=dedup_key,
        activity_at=command.evaluated_at,
        expires_at=command.reservation_expires_at,
        status=GovernorReservationState.RESERVED,
    )


def reservation_to_document(record: ContactGovernorReservationRecord) -> dict:
    if type(record) is not ContactGovernorReservationRecord:
        raise ValueError("expected ContactGovernorReservationRecord")
    document = {
        "_id": record.reservation_id,
        "schema_version": record.schema_version,
        "request_fingerprint": record.request_fingerprint,
        "idempotency_key": record.idempotency_key,
        "candidate_id": record.candidate_id,
        "stream_id": record.stream_id,
        "generation_id": record.generation_id,
        "projection_state_version": record.projection_state_version,
        "stream_version": record.stream_version,
        "requirement_version": record.requirement_version,
        "role_dna_id": record.role_dna_id,
        "role_dna_version": record.role_dna_version,
        "opportunity_spec_id": record.opportunity_spec_id,
        "opportunity_spec_version": record.opportunity_spec_version,
        "recruiter_user_id": record.recruiter_user_id,
        "requesting_organization_id": record.requesting_organization_id,
        "hiring_company_id": record.hiring_company_id,
        "policy_version": record.policy_version,
        "dedup_scope": None if record.dedup_scope is None else record.dedup_scope.value,
        "dedup_key": record.dedup_key,
        "activity_at": record.activity_at,
        "expires_at": record.expires_at,
        "status": record.status.value,
    }
    if record.mandate_id is not None:
        document["mandate_id"] = record.mandate_id
    if record.contact_request_id is not None:
        document["contact_request_id"] = record.contact_request_id
    return document


def reservation_from_document(document: dict) -> ContactGovernorReservationRecord:
    _shape(
        document,
        RESERVATION_REQUIRED_FIELDS,
        RESERVATION_OPTIONAL_FIELDS,
        "contact governor reservation",
    )
    if document["schema_version"] != CONTACT_GOVERNOR_RESERVATION_SCHEMA_VERSION:
        raise ValueError("unsupported reservation schema version")
    try:
        status = GovernorReservationState(document["status"])
    except (TypeError, ValueError):
        raise ValueError("unknown reservation status") from None
    scope_value = document["dedup_scope"]
    if scope_value is None:
        scope = None
    else:
        if type(scope_value) is not str:
            raise ValueError("dedup_scope must be a string or null")
        try:
            scope = GovernorDuplicateScope(scope_value)
        except ValueError:
            raise ValueError("unknown dedup scope") from None
    return ContactGovernorReservationRecord(
        reservation_id=document["_id"],
        request_fingerprint=document["request_fingerprint"],
        idempotency_key=document["idempotency_key"],
        candidate_id=document["candidate_id"],
        stream_id=document["stream_id"],
        generation_id=document["generation_id"],
        projection_state_version=document["projection_state_version"],
        stream_version=document["stream_version"],
        requirement_version=document["requirement_version"],
        role_dna_id=document["role_dna_id"],
        role_dna_version=document["role_dna_version"],
        opportunity_spec_id=document["opportunity_spec_id"],
        opportunity_spec_version=document["opportunity_spec_version"],
        recruiter_user_id=document["recruiter_user_id"],
        requesting_organization_id=document["requesting_organization_id"],
        hiring_company_id=document["hiring_company_id"],
        mandate_id=document.get("mandate_id"),
        policy_version=document["policy_version"],
        dedup_scope=scope,
        dedup_key=document["dedup_key"],
        activity_at=_storage_time(document["activity_at"], "activity_at"),
        expires_at=_storage_time(document["expires_at"], "expires_at"),
        status=status,
        contact_request_id=document.get("contact_request_id"),
        schema_version=document["schema_version"],
    )


def guard_to_document(guard: ContactGovernorCandidateGuard) -> dict:
    if type(guard) is not ContactGovernorCandidateGuard:
        raise ValueError("expected ContactGovernorCandidateGuard")
    return {
        "_id": guard.candidate_id,
        "schema_version": guard.schema_version,
        "revision": guard.revision,
        "updated_at": guard.updated_at,
    }


def guard_from_document(document: dict) -> ContactGovernorCandidateGuard:
    _shape(document, GUARD_FIELDS, set(), "contact governor candidate guard")
    return ContactGovernorCandidateGuard(
        candidate_id=document["_id"],
        revision=document["revision"],
        updated_at=_storage_time(document["updated_at"], "updated_at"),
        schema_version=document["schema_version"],
    )
