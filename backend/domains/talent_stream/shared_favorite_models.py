"""TS-B5 command identities for explicit SavedJob sharing and withdrawal."""
from dataclasses import dataclass
from hashlib import sha256
import json

from domains.shared.ids import CandidateId, IdempotencyKey, IntentEventId, JobId


MAX_CALLER_IDEMPOTENCY_KEY_LENGTH = 256
SHARE_IDENTITY_VERSION = "ts-b5-share-v1"
WITHDRAW_IDENTITY_VERSION = "ts-b5-withdraw-v1"


def persisted_identifier(value, field_name):
    """Validate an A11-persisted opaque ID without changing its representation."""
    if (
        type(value) is not str
        or not value
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must satisfy the A11 identifier contract")
    return value


def caller_key(value):
    """Validate, but never normalize or persist, the caller-owned key."""
    if type(value) is not str or not value or not value.strip():
        raise ValueError("caller_idempotency_key must be a nonblank string")
    if len(value) > MAX_CALLER_IDEMPOTENCY_KEY_LENGTH:
        raise ValueError("caller_idempotency_key is too long")
    return value


def canonical_identity_json(version, candidate_id, caller_idempotency_key):
    persisted_identifier(candidate_id, "candidate_id")
    caller_key(caller_idempotency_key)
    return json.dumps(
        [version, candidate_id, caller_idempotency_key],
        ensure_ascii=True,
        separators=(",", ":"),
    )


def deterministic_identity(version, candidate_id, caller_idempotency_key):
    encoded = canonical_identity_json(
        version, candidate_id, caller_idempotency_key,
    ).encode("utf-8")
    digest = sha256(encoded).hexdigest()
    action = "share" if version == SHARE_IDENTITY_VERSION else "withdraw"
    return (
        IntentEventId(f"ts-b5-{action}-event-v1:sha256:{digest}"),
        IdempotencyKey(f"ts-b5-{action}-v1:sha256:{digest}"),
    )


@dataclass(frozen=True, slots=True, repr=False)
class ShareSavedJobCommand:
    """Trusted domain command; ``saved_job_id`` is still verified in Mongo."""

    candidate_id: CandidateId
    job_id: JobId
    saved_job_id: str
    caller_idempotency_key: str

    def __post_init__(self):
        persisted_identifier(self.candidate_id, "candidate_id")
        persisted_identifier(self.job_id, "job_id")
        persisted_identifier(self.saved_job_id, "saved_job_id")
        caller_key(self.caller_idempotency_key)

    @property
    def event_id(self):
        return deterministic_identity(
            SHARE_IDENTITY_VERSION, self.candidate_id, self.caller_idempotency_key,
        )[0]

    @property
    def stored_idempotency_key(self):
        return deterministic_identity(
            SHARE_IDENTITY_VERSION, self.candidate_id, self.caller_idempotency_key,
        )[1]

    @property
    def opposite_stored_idempotency_key(self):
        return deterministic_identity(
            WITHDRAW_IDENTITY_VERSION, self.candidate_id, self.caller_idempotency_key,
        )[1]


@dataclass(frozen=True, slots=True, repr=False)
class WithdrawSharedFavoriteCommand:
    """Withdraw one exact B5 share without trusting a caller correlation ID."""

    candidate_id: CandidateId
    job_id: JobId
    share_event_id: IntentEventId
    caller_idempotency_key: str

    def __post_init__(self):
        persisted_identifier(self.candidate_id, "candidate_id")
        persisted_identifier(self.job_id, "job_id")
        persisted_identifier(self.share_event_id, "share_event_id")
        caller_key(self.caller_idempotency_key)

    @property
    def event_id(self):
        return deterministic_identity(
            WITHDRAW_IDENTITY_VERSION, self.candidate_id, self.caller_idempotency_key,
        )[0]

    @property
    def stored_idempotency_key(self):
        return deterministic_identity(
            WITHDRAW_IDENTITY_VERSION, self.candidate_id, self.caller_idempotency_key,
        )[1]

    @property
    def opposite_stored_idempotency_key(self):
        return deterministic_identity(
            SHARE_IDENTITY_VERSION, self.candidate_id, self.caller_idempotency_key,
        )[1]
