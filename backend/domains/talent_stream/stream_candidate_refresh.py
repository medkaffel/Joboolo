"""B7 Stream Candidate projection refresh orchestration (TS-B7 STEP 4).

Owns no collections and no write path of its own: the same deterministic
generation identity is derived for one command against one immutable scope,
the candidates are rebuilt through the aggregation, staged through the
repository in bounded batches sorted by candidate_id ascending, the B1/B3
scope is revalidated before and after staging, and the publication is a
compare-and-swap against the projection state captured before the build.

Every failure is mapped to one of four fixed redacted messages. Retrying a
completed command is idempotent: the same generation identity is reused, the
staged candidate documents are identical, and the published pointer is
returned without advancing its state version.
"""
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from domains.talent_stream.application_source_repository import (
    ApplicationSourceReadinessError,
    ApplicationSourceRepositoryError,
)
from domains.talent_stream.application_source_service import (
    ApplicationSourceAccessError,
    ApplicationSourceConflictError,
    ApplicationSourceStoredDataError,
)
from domains.talent_stream.stream_candidate_aggregation import (
    StreamCandidateAggregationAccessError,
    StreamCandidateAggregationConflictError,
    StreamCandidateAggregationReadinessError,
    StreamCandidateAggregationService,
    StreamCandidateAggregationStoredDataError,
)
from domains.talent_stream.stream_candidate_repository import (
    StreamCandidateConflictError,
    StreamCandidateReadinessError,
    StreamCandidateRepository,
    StreamCandidateRepositoryError,
)
from domains.talent_stream.stream_models import (
    nonblank_identifier,
    positive_entity_version,
    utc_millisecond,
)
from domains.talent_stream.stream_repository import TalentStreamStoredDataError

STAGING_BATCH_SIZE = 500

_REFRESH_NOT_AUTHORIZED_MSG = "stream candidate refresh not authorized"
_REFRESH_STORAGE_NOT_READY_MSG = "stream candidate refresh storage is not ready"
_REFRESH_STORED_MSG = "invalid stored stream candidate projection"
_REFRESH_SCOPE_CHANGED_MSG = "stream candidate refresh scope changed"

_GENERATION_ID_VERSION = "ts-b7-generation-v1"
_GENERATION_ID_PREFIX = "ts-b7-generation-v1"


class StreamCandidateRefreshError(RuntimeError):
    pass


class StreamCandidateRefreshNotAuthorizedError(StreamCandidateRefreshError):
    pass


class StreamCandidateRefreshStorageNotReadyError(StreamCandidateRefreshError):
    pass


class StreamCandidateRefreshStoredDataError(StreamCandidateRefreshError):
    pass


class StreamCandidateRefreshConflictError(StreamCandidateRefreshError):
    pass


def generation_identifier(
    stream_id,
    stream_version,
    requirement_version,
    role_dna_id,
    role_dna_version,
    opportunity_spec_id,
    opportunity_spec_version,
    command_id,
):
    """Deterministic B7 generation identity for one command and one scope.

    The same command idempotently reuses the same identity; any change to the
    immutability-linked scope derives a different identity only through a
    different stream version (never a forged value supplied by the caller).
    """
    try:
        stream_id = nonblank_identifier(stream_id, "stream_id")
        command_id = nonblank_identifier(command_id, "command_id")
        stream_version = positive_entity_version(stream_version, "stream_version")
        requirement_version = positive_entity_version(
            requirement_version, "requirement_version"
        )
        role_dna_id = nonblank_identifier(role_dna_id, "role_dna_id")
        role_dna_version = positive_entity_version(
            role_dna_version, "role_dna_version"
        )
        opportunity_spec_id = nonblank_identifier(
            opportunity_spec_id, "opportunity_spec_id"
        )
        opportunity_spec_version = positive_entity_version(
            opportunity_spec_version, "opportunity_spec_version"
        )
    except ValueError:
        raise ValueError("invalid stream candidate refresh generation identity") from None
    payload = json.dumps(
        [
            _GENERATION_ID_VERSION,
            str(stream_id),
            int(stream_version),
            int(requirement_version),
            str(role_dna_id),
            int(role_dna_version),
            str(opportunity_spec_id),
            int(opportunity_spec_version),
            str(command_id),
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{_GENERATION_ID_PREFIX}:sha256:{digest}"


@dataclass(frozen=True, slots=True, repr=False)
class StreamCandidateRefreshCommand:
    """Idempotent refresh request; never regenerate an identity on retry."""

    stream_id: str
    command_id: str
    refresh_at: datetime

    def __post_init__(self):
        try:
            object.__setattr__(
                self, "stream_id", nonblank_identifier(self.stream_id, "stream_id")
            )
            object.__setattr__(
                self, "command_id", nonblank_identifier(self.command_id, "command_id")
            )
            object.__setattr__(
                self,
                "refresh_at",
                utc_millisecond(self.refresh_at, "refresh_at"),
            )
        except ValueError:
            raise ValueError("invalid stream candidate refresh command") from None


@dataclass(frozen=True, slots=True, repr=False)
class StreamCandidateRefreshResult:
    """Minimal outcome of a refresh; never carries candidate payloads."""

    stream_id: str
    generation_id: str
    candidate_count: int
    state_version: int
    published_at: datetime


def _batches(candidates):
    ordered = sorted(candidates, key=lambda candidate: str(candidate.candidate_id))
    for start in range(0, len(ordered), STAGING_BATCH_SIZE):
        yield ordered[start:start + STAGING_BATCH_SIZE]


class StreamCandidateRefreshService:
    def __init__(self, db, *, aggregation=None, repository=None):
        self.aggregation = (
            aggregation if aggregation is not None else StreamCandidateAggregationService(db)
        )
        self.repository = (
            repository if repository is not None else StreamCandidateRepository(db)
        )

    async def refresh(self, command):
        if type(command) is not StreamCandidateRefreshCommand:
            raise ValueError("invalid stream candidate refresh command")
        stream_id = str(command.stream_id)

        expected_state = await self._current_state(stream_id)

        stream = await self._active_stream(stream_id)
        scope = self.aggregation._scope_snapshot(stream)
        await self._authorize(scope["recruiter_id"], stream_id)

        generation_id = generation_identifier(
            stream_id=scope["stream_id"],
            stream_version=scope["stream_version"],
            requirement_version=scope["requirement_version"],
            role_dna_id=scope["role_dna_id"],
            role_dna_version=scope["role_dna_version"],
            opportunity_spec_id=scope["opportunity_spec_id"],
            opportunity_spec_version=scope["opportunity_spec_version"],
            command_id=str(command.command_id),
        )

        built = await self._build(stream_id, generation_id, command.refresh_at)

        await self._revalidate(built)
        await self._begin(built)
        if built.candidate_count:
            for batch in _batches(built.candidates):
                await self._stage(batch)
        await self._revalidate(built)
        await self._seal(built)

        state = await self._publish(built, expected_state, command.refresh_at)
        return StreamCandidateRefreshResult(
            stream_id=stream_id,
            generation_id=generation_id,
            candidate_count=state.candidate_count,
            state_version=state.state_version,
            published_at=state.published_at,
        )

    async def _current_state(self, stream_id):
        try:
            return await self.repository.get_projection_state(stream_id)
        except StreamCandidateReadinessError:
            raise StreamCandidateRefreshStorageNotReadyError(
                _REFRESH_STORAGE_NOT_READY_MSG
            ) from None
        except StreamCandidateRepositoryError:
            raise StreamCandidateRefreshStoredDataError(
                _REFRESH_STORED_MSG
            ) from None

    async def _active_stream(self, stream_id):
        try:
            return await self.aggregation._active_stream(stream_id)
        except StreamCandidateAggregationAccessError:
            raise StreamCandidateRefreshNotAuthorizedError(
                _REFRESH_NOT_AUTHORIZED_MSG
            ) from None
        except StreamCandidateAggregationReadinessError:
            raise StreamCandidateRefreshStorageNotReadyError(
                _REFRESH_STORAGE_NOT_READY_MSG
            ) from None
        except StreamCandidateAggregationStoredDataError:
            raise StreamCandidateRefreshStoredDataError(
                _REFRESH_STORED_MSG
            ) from None
        except StreamCandidateAggregationConflictError:
            raise StreamCandidateRefreshConflictError(
                _REFRESH_SCOPE_CHANGED_MSG
            ) from None

    async def _authorize(self, recruiter_id, stream_id):
        try:
            await self.aggregation.applications._scope(recruiter_id, stream_id)
        except ApplicationSourceAccessError:
            raise StreamCandidateRefreshNotAuthorizedError(
                _REFRESH_NOT_AUTHORIZED_MSG
            ) from None
        except ApplicationSourceReadinessError:
            raise StreamCandidateRefreshStorageNotReadyError(
                _REFRESH_STORAGE_NOT_READY_MSG
            ) from None
        except (
            ApplicationSourceConflictError,
            ApplicationSourceStoredDataError,
            ApplicationSourceRepositoryError,
            TalentStreamStoredDataError,
        ):
            raise StreamCandidateRefreshStoredDataError(
                _REFRESH_STORED_MSG
            ) from None

    async def _build(self, stream_id, generation_id, computed_at):
        try:
            return await self.aggregation.build_generation(
                stream_id, generation_id=generation_id, computed_at=computed_at
            )
        except StreamCandidateAggregationAccessError:
            raise StreamCandidateRefreshNotAuthorizedError(
                _REFRESH_NOT_AUTHORIZED_MSG
            ) from None
        except StreamCandidateAggregationReadinessError:
            raise StreamCandidateRefreshStorageNotReadyError(
                _REFRESH_STORAGE_NOT_READY_MSG
            ) from None
        except StreamCandidateAggregationStoredDataError:
            raise StreamCandidateRefreshStoredDataError(
                _REFRESH_STORED_MSG
            ) from None
        except StreamCandidateAggregationConflictError:
            raise StreamCandidateRefreshConflictError(
                _REFRESH_SCOPE_CHANGED_MSG
            ) from None

    async def _revalidate(self, built):
        try:
            await self.aggregation.assert_generation_scope_current(built)
        except StreamCandidateAggregationReadinessError:
            raise StreamCandidateRefreshStorageNotReadyError(
                _REFRESH_STORAGE_NOT_READY_MSG
            ) from None
        except StreamCandidateAggregationStoredDataError:
            raise StreamCandidateRefreshStoredDataError(
                _REFRESH_STORED_MSG
            ) from None
        except StreamCandidateAggregationConflictError:
            raise StreamCandidateRefreshConflictError(
                _REFRESH_SCOPE_CHANGED_MSG
            ) from None

    async def _stage(self, batch):
        try:
            await self.repository.stage_candidates(batch)
        except StreamCandidateReadinessError:
            raise StreamCandidateRefreshStorageNotReadyError(
                _REFRESH_STORAGE_NOT_READY_MSG
            ) from None
        except StreamCandidateConflictError:
            raise StreamCandidateRefreshConflictError(
                _REFRESH_SCOPE_CHANGED_MSG
            ) from None
        except StreamCandidateRepositoryError:
            raise StreamCandidateRefreshStoredDataError(
                _REFRESH_STORED_MSG
            ) from None

    async def _begin(self, built):
        try:
            await self.repository.begin_generation(
                stream_id=str(built.stream_id),
                generation_id=str(built.generation_id),
                stream_version=int(built.stream_version),
                requirement_version=int(built.requirement_version),
                role_dna_id=str(built.role_dna_id),
                role_dna_version=int(built.role_dna_version),
                opportunity_spec_id=str(built.opportunity_spec_id),
                opportunity_spec_version=int(built.opportunity_spec_version),
            )
        except StreamCandidateReadinessError:
            raise StreamCandidateRefreshStorageNotReadyError(
                _REFRESH_STORAGE_NOT_READY_MSG
            ) from None
        except StreamCandidateConflictError:
            raise StreamCandidateRefreshConflictError(
                _REFRESH_SCOPE_CHANGED_MSG
            ) from None
        except StreamCandidateRepositoryError:
            raise StreamCandidateRefreshStoredDataError(
                _REFRESH_STORED_MSG
            ) from None

    async def _seal(self, built):
        try:
            await self.repository.seal_generation(
                stream_id=str(built.stream_id),
                generation_id=str(built.generation_id),
                stream_version=int(built.stream_version),
                requirement_version=int(built.requirement_version),
                role_dna_id=str(built.role_dna_id),
                role_dna_version=int(built.role_dna_version),
                opportunity_spec_id=str(built.opportunity_spec_id),
                opportunity_spec_version=int(built.opportunity_spec_version),
                candidate_count=built.candidate_count,
            )
        except StreamCandidateReadinessError:
            raise StreamCandidateRefreshStorageNotReadyError(
                _REFRESH_STORAGE_NOT_READY_MSG
            ) from None
        except StreamCandidateConflictError:
            raise StreamCandidateRefreshConflictError(
                _REFRESH_SCOPE_CHANGED_MSG
            ) from None
        except StreamCandidateRepositoryError:
            raise StreamCandidateRefreshStoredDataError(
                _REFRESH_STORED_MSG
            ) from None

    async def _publish(self, built, expected_state, published_at):
        try:
            return await self.repository.publish_generation(
                stream_id=str(built.stream_id),
                generation_id=str(built.generation_id),
                stream_version=int(built.stream_version),
                requirement_version=int(built.requirement_version),
                role_dna_id=str(built.role_dna_id),
                role_dna_version=int(built.role_dna_version),
                opportunity_spec_id=str(built.opportunity_spec_id),
                opportunity_spec_version=int(built.opportunity_spec_version),
                expected_candidate_count=built.candidate_count,
                expected_state=expected_state,
                published_at=published_at,
            )
        except StreamCandidateReadinessError:
            raise StreamCandidateRefreshStorageNotReadyError(
                _REFRESH_STORAGE_NOT_READY_MSG
            ) from None
        except StreamCandidateConflictError:
            raise StreamCandidateRefreshConflictError(
                _REFRESH_SCOPE_CHANGED_MSG
            ) from None
        except StreamCandidateRepositoryError:
            raise StreamCandidateRefreshStoredDataError(
                _REFRESH_STORED_MSG
            ) from None