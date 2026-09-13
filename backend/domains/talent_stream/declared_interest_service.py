"""TS-B4 explicit Job Intent orchestration; no route, Permission or exposure."""
from datetime import datetime, timezone

from campaign_lifecycle import is_job_publicly_visible
from domains.intent.serialization import SCHEMA_VERSION, event_from_document
from domains.intent.service import IntentEventConflictError
from domains.shared.ids import CandidateId, IntentSourceType, IntentEventType, JobId
from domains.shared.versioning import SchemaVersion
from domains.talent_stream.declared_interest_models import DeclareJobInterestCommand
from domains.talent_stream.declared_interest_repository import (
    DeclaredInterestRepository,
    canonical_campaign_id,
)
from domains.talent_stream.events import (
    IntentKind,
    IntentOrigin,
    IntentSubject,
    TalentIntentEvent,
)


EVENT_TYPE = "job_interest_declared"
SOURCE_TYPE = "candidate_declared"


class DeclaredInterestAccessError(LookupError):
    pass


class DeclaredInterestJobNotEligibleError(LookupError):
    pass


class DeclaredInterestConflictError(RuntimeError):
    pass


def _server_utc_millisecond(clock):
    value = clock()
    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError("declared-interest clock must return an aware datetime")
    try:
        if value.utcoffset() is None:
            raise ValueError
        value = value.astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError):
        raise ValueError("declared-interest clock returned an invalid datetime") from None
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _validate_b4_event(event, command):
    expected_identity = (
        str(command.event_id),
        SCHEMA_VERSION,
        IntentSubject(candidate_id=CandidateId(command.candidate_id)),
        IntentKind.JOB,
        IntentOrigin.DECLARED,
        EVENT_TYPE,
        SOURCE_TYPE,
        str(command.stored_idempotency_key),
        str(command.job_id),
    )
    actual_identity = (
        str(event.event_id),
        str(event.schema_version),
        event.subject,
        event.intent_kind,
        event.origin,
        str(event.event_type),
        str(event.source_type),
        None if event.idempotency_key is None else str(event.idempotency_key),
        None if event.job_id is None else str(event.job_id),
    )
    forbidden_optional = (
        event.role_dna_id,
        event.source_organization_id,
        event.source_campaign_id,
        event.consent_context,
        event.privacy_context,
        event.retention_until,
        event.correlation_id,
        event.causation_id,
        event.target_organization_id,
    )
    if (
        actual_identity != expected_identity
        or any(value is not None for value in forbidden_optional)
        or event.occurred_at != event.created_at
    ):
        raise DeclaredInterestConflictError(
            "declared-interest command identity conflict"
        )
    return event


def _canonical_b4_event(document, command):
    """Load an existing A11 event and prove its complete B4 business identity."""
    try:
        event = event_from_document(document)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise DeclaredInterestConflictError(
            "stored declared-interest event is invalid"
        ) from exc
    return _validate_b4_event(event, command)


class DeclaredInterestService:
    def __init__(self, db, *, clock=None):
        self.repository = DeclaredInterestRepository(db)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def _require_current_candidate(self, candidate_id):
        user = await self.repository.get_user(candidate_id)
        if not (
            type(user) is dict
            and user.get("_id") == candidate_id
            and user.get("is_active") is True
            and user.get("user_type") == "candidate"
        ):
            raise DeclaredInterestAccessError(
                "declared interest requires the current active candidate"
            )

    async def declare(self, candidate_id, job_id, *, caller_idempotency_key):
        command = DeclareJobInterestCommand(
            candidate_id=CandidateId(candidate_id),
            job_id=JobId(job_id),
            caller_idempotency_key=caller_idempotency_key,
        )

        # Current candidate state is required even for recovery of a committed retry.
        await self._require_current_candidate(str(command.candidate_id))
        existing = await self.repository.get_event_by_idempotency_key(
            str(command.stored_idempotency_key),
        )
        if existing is not None:
            return _canonical_b4_event(existing, command)

        # No committed command exists: re-check the actor immediately before the
        # new Job eligibility path, then prove A11 readiness before any insert.
        await self._require_current_candidate(str(command.candidate_id))
        await self.repository.readiness()

        job = await self.repository.get_job(str(command.job_id))
        if type(job) is not dict or job.get("_id") != command.job_id:
            raise DeclaredInterestJobNotEligibleError(
                "Job is not eligible for declared interest"
            )
        campaign = None
        if "campaign_id" in job and job["campaign_id"] is not None:
            try:
                campaign_id = canonical_campaign_id(job["campaign_id"])
            except ValueError:
                raise DeclaredInterestJobNotEligibleError(
                    "Job is not eligible for declared interest"
                ) from None
            campaign = await self.repository.get_campaign(campaign_id)

        occurred_at = _server_utc_millisecond(self.clock)
        if not is_job_publicly_visible(job, campaign, now=occurred_at):
            raise DeclaredInterestJobNotEligibleError(
                "Job is not eligible for declared interest"
            )

        event = TalentIntentEvent(
            event_id=command.event_id,
            schema_version=SchemaVersion(SCHEMA_VERSION),
            subject=IntentSubject(candidate_id=CandidateId(command.candidate_id)),
            intent_kind=IntentKind.JOB,
            origin=IntentOrigin.DECLARED,
            event_type=IntentEventType(EVENT_TYPE),
            occurred_at=occurred_at,
            created_at=occurred_at,
            source_type=IntentSourceType(SOURCE_TYPE),
            idempotency_key=command.stored_idempotency_key,
            job_id=JobId(command.job_id),
        )
        try:
            recorded = await self.repository.record(event)
        except IntentEventConflictError:
            winner = await self.repository.get_event_by_idempotency_key(
                str(command.stored_idempotency_key),
            )
            if winner is None:
                raise DeclaredInterestConflictError(
                    "declared-interest command identity conflict"
                ) from None
            return _canonical_b4_event(winner, command)
        # A11 can return a recovered record when the complete event was identical.
        return _validate_b4_event(recorded, command)
