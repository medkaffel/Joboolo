"""Minimal TS-B4 declared Job Intent command identity."""
from dataclasses import dataclass
from hashlib import sha256
import json

from domains.shared.ids import CandidateId, IdempotencyKey, IntentEventId, JobId


B4_IDENTITY_VERSION = "ts-b4-v1"
MAX_CALLER_IDEMPOTENCY_KEY_LENGTH = 256


def _persisted_identifier(value, field_name):
    """Validate an A11-persisted opaque ID without changing its representation."""
    if (
        type(value) is not str
        or not value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must satisfy the A11 identifier contract")
    return value


def _caller_key(value):
    """Validate, but never normalize, the caller-owned idempotency key."""
    if type(value) is not str or not value or not value.strip():
        raise ValueError("caller_idempotency_key must be a nonblank string")
    if len(value) > MAX_CALLER_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError("caller_idempotency_key is too long")
    return value


def canonical_identity_json(candidate_id, caller_idempotency_key):
    """Return the unambiguous deterministic B4 command identity encoding."""
    candidate_id = _persisted_identifier(candidate_id, "candidate_id")
    caller_idempotency_key = _caller_key(caller_idempotency_key)
    return json.dumps(
        [B4_IDENTITY_VERSION, candidate_id, caller_idempotency_key],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def deterministic_interest_identity(candidate_id, caller_idempotency_key):
    encoded = canonical_identity_json(
        candidate_id, caller_idempotency_key,
    ).encode("utf-8")
    digest = sha256(encoded).hexdigest()
    return (
        IntentEventId(f"ts-b4-event-v1:sha256:{digest}"),
        IdempotencyKey(f"ts-b4-v1:sha256:{digest}"),
    )


@dataclass(frozen=True, slots=True, repr=False)
class DeclareJobInterestCommand:
    """Trusted application-layer command; never an external request payload."""

    candidate_id: CandidateId
    job_id: JobId
    caller_idempotency_key: str

    def __post_init__(self):
        _persisted_identifier(self.candidate_id, "candidate_id")
        _persisted_identifier(self.job_id, "job_id")
        _caller_key(self.caller_idempotency_key)

    @property
    def event_id(self):
        return deterministic_interest_identity(
            self.candidate_id, self.caller_idempotency_key,
        )[0]

    @property
    def stored_idempotency_key(self):
        return deterministic_interest_identity(
            self.candidate_id, self.caller_idempotency_key,
        )[1]
