"""TS-B5 explicit SavedJob sharing; no route, Permission or recruiter exposure."""
from datetime import datetime, timezone
import re

from campaign_lifecycle import is_job_publicly_visible
from domains.intent.serialization import SCHEMA_VERSION, event_from_document
from domains.intent.service import IntentEventConflictError
from domains.shared.ids import (
    CandidateId,
    CausationId,
    CorrelationId,
    IntentEventType,
    IntentSourceType,
    JobId,
)
from domains.shared.versioning import SchemaVersion
from domains.talent_stream.declared_interest_repository import canonical_campaign_id
from domains.talent_stream.events import (
    IntentKind,
    IntentOrigin,
    IntentSubject,
    TalentIntentEvent,
)
from domains.talent_stream.shared_favorite_models import (
    ShareSavedJobCommand,
    WithdrawSharedFavoriteCommand,
    persisted_identifier,
)
from domains.talent_stream.shared_favorite_repository import SharedFavoriteRepository


SHARE_EVENT_TYPE = "job_favorite_shared_declared"
WITHDRAW_EVENT_TYPE = "job_favorite_share_withdrawn"
SOURCE_TYPE = "candidate_declared"


class SharedFavoriteAccessError(LookupError):
    pass


class SharedFavoriteNotEligibleError(LookupError):
    pass


class SharedFavoriteConflictError(RuntimeError):
    pass


def _server_utc_millisecond(clock):
    value = clock()
    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError("shared-favorite clock must return an aware datetime")
    try:
        if value.utcoffset() is None:
            raise ValueError
        value = value.astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError):
        raise ValueError("shared-favorite clock returned an invalid datetime") from None
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _mongo_datetime(value, field_name):
    if type(value) is not datetime:
        raise ValueError(f"{field_name} must be a Mongo datetime")
    try:
        if value.tzinfo is None:
            canonical = value.replace(tzinfo=timezone.utc)
        else:
            if value.utcoffset() is None:
                raise ValueError
            canonical = value.astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid Mongo datetime") from None
    if canonical.microsecond % 1000:
        raise ValueError(f"{field_name} must have BSON millisecond precision")
    return canonical


def _canonical_saved_job(document, command):
    required = {"_id", "user_id", "job_id", "created_at", "updated_at"}
    if type(document) is not dict or set(document) != required:
        raise SharedFavoriteNotEligibleError("SavedJob is not eligible for sharing")
    try:
        identity = (
            persisted_identifier(document["_id"], "saved_job._id"),
            persisted_identifier(document["user_id"], "saved_job.user_id"),
            persisted_identifier(document["job_id"], "saved_job.job_id"),
        )
        created_at = _mongo_datetime(document["created_at"], "saved_job.created_at")
        updated_at = _mongo_datetime(document["updated_at"], "saved_job.updated_at")
    except ValueError as exc:
        raise SharedFavoriteNotEligibleError("SavedJob is not eligible for sharing") from exc
    expected = (
        str(command.saved_job_id),
        str(command.candidate_id),
        str(command.job_id),
    )
    if identity != expected or updated_at < created_at:
        raise SharedFavoriteNotEligibleError("SavedJob is not eligible for sharing")
    return (identity, created_at, updated_at)


def _event_identity(command, event_type, correlation_id, causation_id):
    return (
        str(command.event_id),
        SCHEMA_VERSION,
        IntentSubject(candidate_id=CandidateId(command.candidate_id)),
        IntentKind.JOB,
        IntentOrigin.DECLARED,
        event_type,
        SOURCE_TYPE,
        str(command.stored_idempotency_key),
        str(command.job_id),
        str(correlation_id),
        None if causation_id is None else str(causation_id),
    )


def _validate_event(event, command, *, event_type, correlation_id, causation_id):
    actual = (
        str(event.event_id),
        str(event.schema_version),
        event.subject,
        event.intent_kind,
        event.origin,
        str(event.event_type),
        str(event.source_type),
        None if event.idempotency_key is None else str(event.idempotency_key),
        None if event.job_id is None else str(event.job_id),
        None if event.correlation_id is None else str(event.correlation_id),
        None if event.causation_id is None else str(event.causation_id),
    )
    forbidden = (
        event.role_dna_id,
        event.source_organization_id,
        event.source_campaign_id,
        event.consent_context,
        event.privacy_context,
        event.retention_until,
        event.target_organization_id,
    )
    if (
        actual != _event_identity(
            command, event_type, correlation_id, causation_id,
        )
        or any(value is not None for value in forbidden)
        or event.occurred_at != event.created_at
    ):
        raise SharedFavoriteConflictError("shared-favorite command identity conflict")
    return event


def _canonical_event(document, command, *, event_type, correlation_id, causation_id):
    try:
        event = event_from_document(document)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise SharedFavoriteConflictError("stored shared-favorite event is invalid") from exc
    return _validate_event(
        event,
        command,
        event_type=event_type,
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


def _canonical_share_source(document, command):
    """Prove an existing A11 record is the exact B5 share being withdrawn."""
    try:
        event = event_from_document(document)
        persisted_identifier(event.correlation_id, "share.correlation_id")
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise SharedFavoriteConflictError("withdrawal source event is invalid") from exc
    forbidden = (
        event.role_dna_id,
        event.source_organization_id,
        event.source_campaign_id,
        event.consent_context,
        event.privacy_context,
        event.retention_until,
        event.target_organization_id,
        event.causation_id,
    )
    event_id = str(event.event_id)
    idempotency_key = None if event.idempotency_key is None else str(event.idempotency_key)
    event_match = re.fullmatch(
        r"ts-b5-share-event-v1:sha256:([0-9a-f]{64})", event_id,
    )
    key_match = re.fullmatch(
        r"ts-b5-share-v1:sha256:([0-9a-f]{64})", idempotency_key or "",
    )
    if (
        str(event.event_id) != str(command.share_event_id)
        or event.schema_version != SCHEMA_VERSION
        or event.subject != IntentSubject(candidate_id=CandidateId(command.candidate_id))
        or event.intent_kind is not IntentKind.JOB
        or event.origin is not IntentOrigin.DECLARED
        or event.event_type != SHARE_EVENT_TYPE
        or event.source_type != SOURCE_TYPE
        or event.job_id != command.job_id
        or event.idempotency_key is None
        or event_match is None
        or key_match is None
        or event_match.group(1) != key_match.group(1)
        or any(value is not None for value in forbidden)
        or event.occurred_at != event.created_at
    ):
        raise SharedFavoriteConflictError("withdrawal source is not the requested B5 share")
    return event


class SharedFavoriteService:
    def __init__(self, db, *, clock=None):
        self.repository = SharedFavoriteRepository(db)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def _require_current_candidate(self, candidate_id):
        user = await self.repository.get_user(candidate_id)
        if not (
            type(user) is dict
            and user.get("_id") == candidate_id
            and user.get("is_active") is True
            and user.get("user_type") == "candidate"
        ):
            raise SharedFavoriteAccessError(
                "shared favorite requires the current active candidate"
            )

    async def _reject_opposite_action_key(self, command):
        opposite = await self.repository.get_event_by_idempotency_key(
            str(command.opposite_stored_idempotency_key),
        )
        if opposite is not None:
            raise SharedFavoriteConflictError(
                "caller key was already used for the opposite B5 action"
            )

    async def share(
        self,
        candidate_id,
        job_id,
        saved_job_id,
        *,
        caller_idempotency_key,
    ):
        command = ShareSavedJobCommand(
            candidate_id=CandidateId(candidate_id),
            job_id=JobId(job_id),
            saved_job_id=saved_job_id,
            caller_idempotency_key=caller_idempotency_key,
        )
        await self._require_current_candidate(str(command.candidate_id))
        existing = await self.repository.get_event_by_idempotency_key(
            str(command.stored_idempotency_key),
        )
        if existing is not None:
            await self._reject_opposite_action_key(command)
            return _canonical_event(
                existing,
                command,
                event_type=SHARE_EVENT_TYPE,
                correlation_id=command.saved_job_id,
                causation_id=None,
            )
        await self._reject_opposite_action_key(command)
        await self._require_current_candidate(str(command.candidate_id))
        saved_job = await self.repository.get_saved_job(
            str(command.candidate_id), str(command.job_id), command.saved_job_id,
        )
        first_snapshot = _canonical_saved_job(saved_job, command)
        await self.repository.a11_readiness()
        await self.repository.saved_jobs_readiness()

        job = await self.repository.get_job(str(command.job_id))
        if type(job) is not dict or job.get("_id") != command.job_id:
            raise SharedFavoriteNotEligibleError("Job is not eligible for sharing")
        campaign = None
        if "campaign_id" in job and job["campaign_id"] is not None:
            try:
                campaign_id = canonical_campaign_id(job["campaign_id"])
            except ValueError:
                raise SharedFavoriteNotEligibleError(
                    "Job is not eligible for sharing"
                ) from None
            campaign = await self.repository.get_campaign(campaign_id)

        occurred_at = _server_utc_millisecond(self.clock)
        if not is_job_publicly_visible(job, campaign, now=occurred_at):
            raise SharedFavoriteNotEligibleError("Job is not eligible for sharing")

        current_saved_job = await self.repository.get_saved_job(
            str(command.candidate_id), str(command.job_id), command.saved_job_id,
        )
        if _canonical_saved_job(current_saved_job, command) != first_snapshot:
            raise SharedFavoriteNotEligibleError(
                "SavedJob changed before the share could be recorded"
            )

        event = TalentIntentEvent(
            event_id=command.event_id,
            schema_version=SchemaVersion(SCHEMA_VERSION),
            subject=IntentSubject(candidate_id=CandidateId(command.candidate_id)),
            intent_kind=IntentKind.JOB,
            origin=IntentOrigin.DECLARED,
            event_type=IntentEventType(SHARE_EVENT_TYPE),
            occurred_at=occurred_at,
            created_at=occurred_at,
            source_type=IntentSourceType(SOURCE_TYPE),
            idempotency_key=command.stored_idempotency_key,
            job_id=JobId(command.job_id),
            correlation_id=CorrelationId(command.saved_job_id),
        )
        try:
            recorded = await self.repository.record(event)
        except IntentEventConflictError:
            winner = await self.repository.get_event_by_idempotency_key(
                str(command.stored_idempotency_key),
            )
            if winner is None:
                raise SharedFavoriteConflictError(
                    "shared-favorite command identity conflict"
                ) from None
            return _canonical_event(
                winner,
                command,
                event_type=SHARE_EVENT_TYPE,
                correlation_id=command.saved_job_id,
                causation_id=None,
            )
        return _validate_event(
            recorded,
            command,
            event_type=SHARE_EVENT_TYPE,
            correlation_id=command.saved_job_id,
            causation_id=None,
        )

    async def withdraw(
        self,
        candidate_id,
        job_id,
        share_event_id,
        *,
        caller_idempotency_key,
    ):
        command = WithdrawSharedFavoriteCommand(
            candidate_id=CandidateId(candidate_id),
            job_id=JobId(job_id),
            share_event_id=share_event_id,
            caller_idempotency_key=caller_idempotency_key,
        )
        await self._require_current_candidate(str(command.candidate_id))
        existing = await self.repository.get_event_by_idempotency_key(
            str(command.stored_idempotency_key),
        )
        if existing is not None:
            await self._reject_opposite_action_key(command)
            source_document = await self.repository.get_event(
                str(command.share_event_id)
            )
            if source_document is None:
                raise SharedFavoriteConflictError(
                    "stored withdrawal has no canonical B5 share source"
                )
            source_event = _canonical_share_source(source_document, command)
            correlation_id = str(source_event.correlation_id)
            return _canonical_event(
                existing,
                command,
                event_type=WITHDRAW_EVENT_TYPE,
                correlation_id=correlation_id,
                causation_id=command.share_event_id,
            )
        await self._reject_opposite_action_key(command)
        await self._require_current_candidate(str(command.candidate_id))
        await self.repository.a11_readiness()

        source_document = await self.repository.get_event(str(command.share_event_id))
        if source_document is None:
            raise SharedFavoriteNotEligibleError("B5 share event was not found")
        source_event = _canonical_share_source(source_document, command)
        correlation_id = str(source_event.correlation_id)
        occurred_at = _server_utc_millisecond(self.clock)
        if occurred_at < source_event.occurred_at:
            raise SharedFavoriteConflictError(
                "shared-favorite withdrawal cannot predate its share"
            )
        event = TalentIntentEvent(
            event_id=command.event_id,
            schema_version=SchemaVersion(SCHEMA_VERSION),
            subject=IntentSubject(candidate_id=CandidateId(command.candidate_id)),
            intent_kind=IntentKind.JOB,
            origin=IntentOrigin.DECLARED,
            event_type=IntentEventType(WITHDRAW_EVENT_TYPE),
            occurred_at=occurred_at,
            created_at=occurred_at,
            source_type=IntentSourceType(SOURCE_TYPE),
            idempotency_key=command.stored_idempotency_key,
            job_id=JobId(command.job_id),
            correlation_id=CorrelationId(correlation_id),
            causation_id=CausationId(command.share_event_id),
        )
        try:
            recorded = await self.repository.record(event)
        except IntentEventConflictError:
            winner = await self.repository.get_event_by_idempotency_key(
                str(command.stored_idempotency_key),
            )
            if winner is None:
                raise SharedFavoriteConflictError(
                    "shared-favorite withdrawal identity conflict"
                ) from None
            return _canonical_event(
                winner,
                command,
                event_type=WITHDRAW_EVENT_TYPE,
                correlation_id=correlation_id,
                causation_id=command.share_event_id,
            )
        return _validate_event(
            recorded,
            command,
            event_type=WITHDRAW_EVENT_TYPE,
            correlation_id=correlation_id,
            causation_id=command.share_event_id,
        )
