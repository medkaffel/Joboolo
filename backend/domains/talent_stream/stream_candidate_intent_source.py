"""Pure reducer for B4/B5 Intent sources into B7 Stream Candidate evidence.

No Mongo I/O. No network. No writes. Fail closed on invalid events.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from domains.intent.serialization import event_from_document
from domains.talent_stream.events import (
    IntentEventType,
    IntentKind,
    IntentOrigin,
    IntentSourceType,
    TalentIntentEvent,
)
from domains.talent_stream.stream_candidate_models import (
    DeclaredInterestEvidence,
    SharedFavoriteEvidence,
)
from domains.shared.ids import (
    CandidateId,
    JobId,
)
from domains.shared.versioning import SchemaVersion
from domains.talent_stream.stream_models import nonblank_identifier


class B4ValidationError(ValueError):
    """Fail closed for invalid B4 events."""


class B5ValidationError(ValueError):
    """Fail closed for invalid B5 events."""


B4_EVENT_TYPE = IntentEventType("job_interest_declared")
B5_SHARE_EVENT_TYPE = IntentEventType("job_favorite_shared_declared")
B5_WITHDRAW_EVENT_TYPE = IntentEventType("job_favorite_share_withdrawn")

B4_EVENT_ID_PREFIX = "ts-b4-event-v1:sha256:"
B4_IDEMPOTENCY_PREFIX = "ts-b4-v1:sha256:"
B5_SHARE_EVENT_ID_PREFIX = "ts-b5-share-event-v1:sha256:"
B5_SHARE_IDEMPOTENCY_PREFIX = "ts-b5-share-v1:sha256:"
B5_WITHDRAW_EVENT_ID_PREFIX = "ts-b5-withdraw-event-v1:sha256:"
B5_WITHDRAW_IDEMPOTENCY_PREFIX = "ts-b5-withdraw-v1:sha256:"

INTENT_EVENT_SCHEMA_VERSION = SchemaVersion("intent-event-v1")

B4_FORBIDDEN_FIELDS = {
    "role_dna_id",
    "source_organization_id",
    "source_campaign_id",
    "consent_context",
    "privacy_context",
    "retention_until",
    "correlation_id",
    "causation_id",
    "target_organization_id",
}

B5_SHARE_FORBIDDEN_FIELDS = B4_FORBIDDEN_FIELDS - {"correlation_id"}
B5_WITHDRAW_FORBIDDEN_FIELDS = B4_FORBIDDEN_FIELDS - {"correlation_id", "causation_id"}


def _extract_sha256_digest(value: str, prefix: str) -> str:
    """Extract and validate SHA256 digest from prefixed identifier."""
    if not value.startswith(prefix):
        raise ValueError(f"invalid prefix, expected {prefix}")
    digest = value[len(prefix):]
    if len(digest) != 64 or not all(c in "0123456789abcdef" for c in digest):
        raise ValueError("invalid sha256 digest")
    return digest


def _validate_b4_event(event: TalentIntentEvent, expected_job_id: JobId, expected_candidate_id: CandidateId) -> None:
    """Strict B4 canonical contract validation. Fail closed on any violation."""
    if event.event_type != B4_EVENT_TYPE:
        raise B4ValidationError("event_type must be job_interest_declared")
    if event.intent_kind != IntentKind.JOB:
        raise B4ValidationError("intent_kind must be JOB")
    if event.origin != IntentOrigin.DECLARED:
        raise B4ValidationError("origin must be DECLARED")
    if event.source_type != IntentSourceType("candidate_declared"):
        raise B4ValidationError("source_type must be candidate_declared")
    if event.job_id != expected_job_id:
        raise B4ValidationError("job_id mismatch")
    if event.subject.candidate_id != expected_candidate_id:
        raise B4ValidationError("subject candidate_id mismatch")
    if event.occurred_at != event.created_at:
        raise B4ValidationError("occurred_at must equal created_at")
    if not event.idempotency_key:
        raise B4ValidationError("idempotency_key required")

    event_id_digest = _extract_sha256_digest(event.event_id, B4_EVENT_ID_PREFIX)
    idempotency_digest = _extract_sha256_digest(event.idempotency_key, B4_IDEMPOTENCY_PREFIX)
    if event_id_digest != idempotency_digest:
        raise B4ValidationError("event_id and idempotency_key digest mismatch")

    for field in B4_FORBIDDEN_FIELDS:
        if getattr(event, field) is not None:
            raise B4ValidationError(f"forbidden field present: {field}")


def _validate_b5_share_event(event: TalentIntentEvent, expected_job_id: JobId, expected_candidate_id: CandidateId) -> None:
    """Strict B5 share canonical contract validation. Fail closed on any violation."""
    if event.schema_version != INTENT_EVENT_SCHEMA_VERSION:
        raise B5ValidationError("schema_version must be intent-event-v1")
    if event.event_type != B5_SHARE_EVENT_TYPE:
        raise B5ValidationError("event_type must be job_favorite_shared_declared")
    if event.intent_kind != IntentKind.JOB:
        raise B5ValidationError("intent_kind must be JOB")
    if event.origin != IntentOrigin.DECLARED:
        raise B5ValidationError("origin must be DECLARED")
    if event.source_type != IntentSourceType("candidate_declared"):
        raise B5ValidationError("source_type must be candidate_declared")
    if event.job_id != expected_job_id:
        raise B5ValidationError("job_id mismatch")
    if event.subject.candidate_id != expected_candidate_id:
        raise B5ValidationError("subject candidate_id mismatch")
    if event.occurred_at != event.created_at:
        raise B5ValidationError("occurred_at must equal created_at")
    if not event.idempotency_key:
        raise B5ValidationError("idempotency_key required")
    if not event.correlation_id:
        raise B5ValidationError("correlation_id required")
    if event.causation_id is not None:
        raise B5ValidationError("causation_id must be absent for share")

    event_id_digest = _extract_sha256_digest(event.event_id, B5_SHARE_EVENT_ID_PREFIX)
    idempotency_digest = _extract_sha256_digest(event.idempotency_key, B5_SHARE_IDEMPOTENCY_PREFIX)
    if event_id_digest != idempotency_digest:
        raise B5ValidationError("event_id and idempotency_key digest mismatch")

    for field in B5_SHARE_FORBIDDEN_FIELDS:
        if getattr(event, field) is not None:
            raise B5ValidationError(f"forbidden field present: {field}")


@dataclass(frozen=True, slots=True, repr=False)
class ReducedIntentSources:
    """Output of the pure reducer, grouped by candidate_id."""
    
    by_candidate: Tuple[Tuple[CandidateId, "CandidateIntentSources"], ...]
    
    def __post_init__(self) -> None:
        if type(self.by_candidate) is not tuple:
            raise ValueError("by_candidate must be a tuple")
        seen = set()
        for candidate_id, sources in self.by_candidate:
            if candidate_id in seen:
                raise ValueError("duplicate candidate_id in reducer output")
            seen.add(candidate_id)
            if type(sources) is not CandidateIntentSources:
                raise ValueError("invalid CandidateIntentSources")


@dataclass(frozen=True, slots=True, repr=False)
class CandidateIntentSources:
    """Deterministic B4/B5 evidence for a single candidate/job pair."""
    
    candidate_id: CandidateId
    declared_interest: Optional[DeclaredInterestEvidence]
    shared_favorites: Tuple[SharedFavoriteEvidence, ...]
    
    def __post_init__(self) -> None:
        nonblank_identifier(self.candidate_id, "candidate_id")
        if self.declared_interest is not None:
            if type(self.declared_interest) is not DeclaredInterestEvidence:
                raise ValueError("invalid declared_interest_evidence")
        if type(self.shared_favorites) is not tuple:
            raise ValueError("shared_favorites must be a tuple")
        for ev in self.shared_favorites:
            if type(ev) is not SharedFavoriteEvidence:
                raise ValueError("invalid shared_favorite_evidence")


def _validate_b5_withdrawal_event(
    event: TalentIntentEvent,
    expected_job_id: JobId,
    expected_candidate_id: CandidateId,
    all_shares: Dict[str, TalentIntentEvent],
) -> None:
    """Strict B5 withdrawal validation. Fail closed on any violation.

    Shares are looked up by their canonical event_id through the causation_id.
    Unlike the share validation, this does not require the share to be already
    processed: it validates against all shares for this candidate/job.
    """
    if event.schema_version != INTENT_EVENT_SCHEMA_VERSION:
        raise B5ValidationError("schema_version must be intent-event-v1")
    if event.event_type != B5_WITHDRAW_EVENT_TYPE:
        raise B5ValidationError("event_type must be job_favorite_share_withdrawn")
    if event.intent_kind != IntentKind.JOB:
        raise B5ValidationError("intent_kind must be JOB")
    if event.origin != IntentOrigin.DECLARED:
        raise B5ValidationError("origin must be DECLARED")
    if event.source_type != IntentSourceType("candidate_declared"):
        raise B5ValidationError("source_type must be candidate_declared")
    if event.job_id != expected_job_id:
        raise B5ValidationError("job_id mismatch")
    if event.subject.candidate_id != expected_candidate_id:
        raise B5ValidationError("subject candidate_id mismatch")
    if event.occurred_at != event.created_at:
        raise B5ValidationError("occurred_at must equal created_at")
    if not event.idempotency_key:
        raise B5ValidationError("idempotency_key required")
    if not event.correlation_id:
        raise B5ValidationError("correlation_id required")
    if not event.causation_id:
        raise B5ValidationError("causation_id required for withdrawal")

    event_id_digest = _extract_sha256_digest(event.event_id, B5_WITHDRAW_EVENT_ID_PREFIX)
    idempotency_digest = _extract_sha256_digest(event.idempotency_key, B5_WITHDRAW_IDEMPOTENCY_PREFIX)
    if event_id_digest != idempotency_digest:
        raise B5ValidationError("event_id and idempotency_key digest mismatch")

    for field in B5_WITHDRAW_FORBIDDEN_FIELDS:
        if getattr(event, field) is not None:
            raise B5ValidationError(f"forbidden field present: {field}")

    target_event_key = str(event.causation_id)
    target_share = all_shares.get(target_event_key)
    if target_share is None:
        raise B5ValidationError("withdrawal targets non-existent share")
    if target_share.job_id != expected_job_id:
        raise B5ValidationError("withdrawal targets share for different job")
    if target_share.subject.candidate_id != expected_candidate_id:
        raise B5ValidationError("withdrawal targets share for different candidate")
    if str(target_share.correlation_id) != str(event.correlation_id):
        raise B5ValidationError("withdrawal correlation does not match the target share")
    # B5 canonical temporal invariant: withdrawal cannot predate the targeted share.
    if event.occurred_at < target_share.occurred_at:
        raise B5ValidationError("withdrawal cannot predate the targeted share")


def reduce_intent_sources(
    documents: List[dict],
    job_id: JobId,
) -> ReducedIntentSources:
    """Pure reducer: A11 documents -> deterministic B4/B5 evidence per candidate.
    
    Independent of input order. Fail closed on any invalid event.
    """
    if not isinstance(documents, list):
        raise ValueError("documents must be a list")
    
    events_by_candidate: Dict[CandidateId, List[TalentIntentEvent]] = {}
    
    for doc in documents:
        if not isinstance(doc, dict):
            raise ValueError("each document must be a dict")
        event = event_from_document(doc)
        
        if event.intent_kind != IntentKind.JOB:
            continue
        if event.job_id != job_id:
            continue
        
        candidate_id = event.subject.candidate_id
        if candidate_id is None:
            raise ValueError("subject must have candidate_id")
        
        events_by_candidate.setdefault(candidate_id, []).append(event)
    
    candidate_sources = []
    
    for candidate_id, events in events_by_candidate.items():
        b4_events = []
        b5_shares = {}
        b5_withdrawals = []
        
        # First pass: collect all events (validate B4 and B5 shares immediately)
        for event in events:
            if event.event_type == B4_EVENT_TYPE:
                _validate_b4_event(event, job_id, candidate_id)
                b4_events.append(event)
            elif event.event_type == B5_SHARE_EVENT_TYPE:
                _validate_b5_share_event(event, job_id, candidate_id)
                event_key = str(event.event_id)
                if event_key not in b5_shares:
                    b5_shares[event_key] = event
                else:
                    existing = b5_shares[event_key]
                    if (event.occurred_at, str(event.event_id)) > (existing.occurred_at, str(existing.event_id)):
                        b5_shares[event_key] = event
            elif event.event_type == B5_WITHDRAW_EVENT_TYPE:
                b5_withdrawals.append(event)
        
        # Second pass: validate withdrawals against ALL shares (order-independent)
        for event in b5_withdrawals:
            _validate_b5_withdrawal_event(event, job_id, candidate_id, b5_shares)
        
        declared_interest = None
        if b4_events:
            representative = max(
                b4_events,
                key=lambda e: (e.occurred_at, str(e.event_id))
            )
            declared_interest = DeclaredInterestEvidence(
                event_id=representative.event_id,
                occurred_at=representative.occurred_at,
            )
        
        active_shares = []
        for event_key, share_event in b5_shares.items():
            withdrawn = any(
                str(w.causation_id) == event_key
                for w in b5_withdrawals
            )
            if not withdrawn:
                active_shares.append(
                    SharedFavoriteEvidence(
                        event_id=share_event.event_id,
                        correlation_id=str(share_event.correlation_id),
                        occurred_at=share_event.occurred_at,
                    )
                )
        
        active_shares.sort(key=lambda e: (e.occurred_at, str(e.event_id)))
        
        candidate_sources.append((
            candidate_id,
            CandidateIntentSources(
                candidate_id=candidate_id,
                declared_interest=declared_interest,
                shared_favorites=tuple(active_shares),
            )
        ))
    
    candidate_sources.sort(key=lambda x: str(x[0]))
    
    return ReducedIntentSources(
        by_candidate=tuple(candidate_sources)
    )