"""G0 hermetic tests for TS-B7 STEP 4 Stream Candidate refresh orchestration.

Everything here is in-memory only: no Mongo, no network, no external clock.
The refresh service is wired with scripted fakes for the aggregation
dependencies and a faithful in-memory candidate repository that reproduces the
real compare-and-swap staging/publication contract. Deterministic generation
identity, idempotent retries, bounded batched staging, double scope
revalidation, CAS conflicts, scoped error mapping, the absence of any
destructive GC and the minimal result surface are enforced without a database.
"""
import asyncio
import dataclasses
import re
from datetime import datetime, timezone

import pytest

from models import ApplicationStatus

from domains.matching.models import ProfessionalMatchResult
from domains.matching.opportunity_fit_models import (
    HardEligibilityState,
    OpportunityFitResult,
    OpportunityFitState,
)
from domains.talent_stream.application_source_models import ApplicationSource
from domains.talent_stream.application_source_repository import (
    ApplicationSourceReadinessError,
)
from domains.talent_stream.application_source_service import (
    ApplicationSourceAccessError,
    ApplicationSourceConflictError,
    ApplicationSourceStoredDataError,
    MAX_APPLICATION_SOURCE_PAGE_SIZE,
    _SecuredScope,
)
from domains.talent_stream.contracts import (
    DiscoveryState,
    OpportunitySpecificationRef,
    RecruitingActorContext,
    RoleDNARef,
    StreamRequirementSnapshot,
)
from domains.talent_stream.discovery_pool_models import (
    DiscoveryPoolCandidate,
    DiscoveryPoolCursor,
    DiscoveryPoolPage,
)
from domains.talent_stream.discovery_pool_service import (
    DiscoveryPoolAccessError,
    DiscoveryPoolConflictError,
    DiscoveryPoolStoredDataError,
)
from domains.talent_stream.discovery_pool_repository import DiscoveryPoolReadinessError
from domains.talent_stream.shared_favorite_repository import (
    SharedFavoriteReadinessError,
    SharedFavoriteRepositoryError,
)
from domains.talent_stream.stream_candidate_aggregation import (
    StreamCandidateAggregationConflictError,
    StreamCandidateAggregationReadinessError,
    StreamCandidateAggregationService,
    StreamCandidateAggregationStoredDataError,
)
from domains.talent_stream.stream_candidate_persistence import (
    GenerationState,
    ProjectionState,
    StreamCandidateGenerationRecord,
    generation_record_document_id,
    generation_record_from_document,
    generation_record_to_document,
    staging_batch_fingerprint,
    stream_candidate_from_document,
    stream_candidate_to_document,
)
from domains.talent_stream.stream_candidate_refresh import (
    STAGING_BATCH_SIZE,
    StreamCandidateRefreshCommand,
    StreamCandidateRefreshConflictError,
    StreamCandidateRefreshNotAuthorizedError,
    StreamCandidateRefreshResult,
    StreamCandidateRefreshService,
    StreamCandidateRefreshStoredDataError,
    StreamCandidateRefreshStorageNotReadyError,
    generation_identifier,
)
from domains.talent_stream.stream_candidate_repository import (
    StreamCandidateConflictError,
    StreamCandidateReadinessError,
    StreamCandidateRepositoryError,
)
from domains.talent_stream.stream_candidate_source_repository import (
    INTENT_EVENT_PAGE_LIMIT,
    IntentEventCursor,
    OpportunitySpecificationSource,
    StreamCandidateSourceReadinessError,
    StreamCandidateSourceRepositoryError,
    StreamCandidateSourceStoredDataError,
)
from domains.talent_stream.stream_models import (
    StreamCommandHistoryEntry,
    StreamCommandKind,
    TalentStream,
    TalentStreamState,
    utc_millisecond,
)
from domains.talent_stream.stream_repository import (
    TalentStreamReadinessError,
    TalentStreamStoredDataError,
)

NOT_AUTHORIZED_MSG = "stream candidate refresh not authorized"
STORAGE_NOT_READY_MSG = "stream candidate refresh storage is not ready"
STORED_MSG = "invalid stored stream candidate projection"
SCOPE_CHANGED_MSG = "stream candidate refresh scope changed"

STREAM_ID = "stream-123"
STREAM_VERSION = 2
REQUIREMENT_VERSION = 7
ROLE_DNA_ID = "role-dna-1"
ROLE_DNA_VERSION = 4
OPPORTUNITY_SPEC_ID = "spec-1"
OPPORTUNITY_VERSION = 2
SOURCE_REF = "source-ref-1"
JOB_ID = "job-1"
RECRUITER_ID = "recruiter-1"
CMD_ID = "cmd-refresh-1"
GENERATION_PATTERN = re.compile(r"^ts-b7-generation-v1:sha256:[0-9a-f]{64}$")


def _utc(ms: int = 0) -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, ms * 1000, tzinfo=timezone.utc)


REFRESH_AT = _utc(900)


def _run(coro):
    return asyncio.run(coro)


def _make_stream(state: TalentStreamState = TalentStreamState.ACTIVE,
                 *, version: int = STREAM_VERSION) -> TalentStream:
    created_at = _utc(0)
    entries = [
        StreamCommandHistoryEntry(
            command_id=f"cmd-create-{STREAM_ID}",
            command_fingerprint="fp-create",
            command_kind=StreamCommandKind.CREATE,
            from_state=None,
            to_state=TalentStreamState.DRAFT,
            resulting_version=1,
            occurred_at=created_at,
        )
    ]
    if version >= 2:
        entries.append(StreamCommandHistoryEntry(
            command_id=f"cmd-activate-{STREAM_ID}",
            command_fingerprint="fp-activate",
            command_kind=StreamCommandKind.ACTIVATE,
            from_state=TalentStreamState.DRAFT,
            to_state=TalentStreamState.ACTIVE,
            resulting_version=2,
            occurred_at=_utc(10),
        ))
    if version >= 3:
        entries.append(StreamCommandHistoryEntry(
            command_id=f"cmd-close-{STREAM_ID}",
            command_fingerprint="fp-close",
            command_kind=StreamCommandKind.CLOSE,
            from_state=TalentStreamState.ACTIVE,
            to_state=TalentStreamState.CLOSED,
            resulting_version=version,
            occurred_at=_utc(20),
        ))
    return TalentStream(
        stream_id=STREAM_ID,
        version=version,
        recruiting_actor_context=RecruitingActorContext(
            recruiter_user_id=RECRUITER_ID,
            requesting_organization_id="org-r-1",
            hiring_company_id="org-h-1",
            mandate_id=None,
        ),
        requirement_snapshot=StreamRequirementSnapshot(
            role_dna=RoleDNARef(role_dna_id=ROLE_DNA_ID, version=ROLE_DNA_VERSION),
            opportunity_spec=OpportunitySpecificationRef(
                opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                version=OPPORTUNITY_VERSION,
            ),
            requirement_version=REQUIREMENT_VERSION,
            captured_at=created_at,
        ),
        state=state,
        created_at=created_at,
        updated_at=entries[-1].occurred_at,
        history=tuple(entries),
    )


def _make_stream_changed_refs() -> TalentStream:
    """Legal ACTIVE v2 stream whose snapshot diverges from the primary scope."""
    created_at = _utc(0)
    entries = [
        StreamCommandHistoryEntry(
            command_id=f"cmd-create-{STREAM_ID}",
            command_fingerprint="fp-create",
            command_kind=StreamCommandKind.CREATE,
            from_state=None,
            to_state=TalentStreamState.DRAFT,
            resulting_version=1,
            occurred_at=created_at,
        ),
        StreamCommandHistoryEntry(
            command_id=f"cmd-activate-{STREAM_ID}",
            command_fingerprint="fp-activate",
            command_kind=StreamCommandKind.ACTIVATE,
            from_state=TalentStreamState.DRAFT,
            to_state=TalentStreamState.ACTIVE,
            resulting_version=2,
            occurred_at=_utc(10),
        ),
    ]
    return TalentStream(
        stream_id=STREAM_ID,
        version=2,
        recruiting_actor_context=RecruitingActorContext(
            recruiter_user_id=RECRUITER_ID,
            requesting_organization_id="org-r-1",
            hiring_company_id="org-h-1",
            mandate_id=None,
        ),
        requirement_snapshot=StreamRequirementSnapshot(
            role_dna=RoleDNARef(role_dna_id="role-dna-other", version=ROLE_DNA_VERSION + 1),
            opportunity_spec=OpportunitySpecificationRef(
                opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                version=OPPORTUNITY_VERSION,
            ),
            requirement_version=REQUIREMENT_VERSION + 1,
            captured_at=created_at,
        ),
        state=TalentStreamState.ACTIVE,
        created_at=created_at,
        updated_at=entries[-1].occurred_at,
        history=tuple(entries),
    )


def _opportunity_source() -> OpportunitySpecificationSource:
    return OpportunitySpecificationSource(
        opportunity_spec_id=OPPORTUNITY_SPEC_ID,
        version=OPPORTUNITY_VERSION,
        source_job_id=JOB_ID,
        source_ref=SOURCE_REF,
        version_provenance_ref=SOURCE_REF,
    )


def _application(app_id: str, candidate_id: str, *, ms: int = 30,
                 job_id: str = JOB_ID,
                 status: ApplicationStatus = ApplicationStatus.PENDING) -> ApplicationSource:
    return ApplicationSource(
        application_id=app_id,
        candidate_id=candidate_id,
        job_id=job_id,
        status=status,
        applied_at=_utc(ms),
    )


def _application_position(source) -> tuple[datetime, str]:
    return (source.applied_at, str(source.application_id))


def _match(candidate_id: str) -> ProfessionalMatchResult:
    return ProfessionalMatchResult(
        candidate_id=candidate_id,
        candidate_profile_version=3,
        role_dna_id=ROLE_DNA_ID,
        role_dna_version=ROLE_DNA_VERSION,
        match_engine_version="match-engine-v1",
        professional_match_score=80,
        evidence_coverage=70,
        components=(),
        computed_at=_utc(400),
    )


def _fit(candidate_id: str) -> OpportunityFitResult:
    return OpportunityFitResult(
        candidate_id=candidate_id,
        candidate_preferences_version=5,
        opportunity_spec_id=OPPORTUNITY_SPEC_ID,
        opportunity_spec_version=OPPORTUNITY_VERSION,
        engine_version="opportunity-fit-engine-v1",
        hard_eligibility_state=HardEligibilityState.ELIGIBLE,
        opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        evidence_coverage=60,
        components=(),
        computed_at=_utc(401),
    )


def _discovery_item(candidate_id: str) -> DiscoveryPoolCandidate:
    return DiscoveryPoolCandidate(
        candidate_id=candidate_id,
        discovery_state=DiscoveryState(
            candidate_id=candidate_id,
            enabled=True,
            allow_compatible_opportunities=False,
            ask_before_reveal=False,
            anonymous_only=False,
            preferences_version=5,
            updated_at=_utc(402),
        ),
        professional_match=_match(candidate_id),
        opportunity_fit=_fit(candidate_id),
    )


def _discovery_cursor(after_candidate_id: str) -> DiscoveryPoolCursor:
    return DiscoveryPoolCursor(
        stream_id=STREAM_ID,
        stream_version=STREAM_VERSION,
        requirement_version=REQUIREMENT_VERSION,
        role_dna_id=ROLE_DNA_ID,
        role_dna_version=ROLE_DNA_VERSION,
        opportunity_spec_id=OPPORTUNITY_SPEC_ID,
        opportunity_spec_version=OPPORTUNITY_VERSION,
        after_candidate_id=after_candidate_id,
    )


def _discovery_page(*items: DiscoveryPoolCandidate,
                    next_after: str | None = None) -> DiscoveryPoolPage:
    return DiscoveryPoolPage(
        items=tuple(items),
        next_cursor=None if next_after is None else _discovery_cursor(next_after),
        scanned_count=len(items),
    )


def _command(command_id: str = CMD_ID, *, stream_id: str = STREAM_ID,
             refresh_at: datetime = REFRESH_AT) -> StreamCandidateRefreshCommand:
    return StreamCandidateRefreshCommand(stream_id, command_id, refresh_at)


def _generation_id(command_id: str = CMD_ID) -> str:
    return generation_identifier(
        stream_id=STREAM_ID,
        stream_version=STREAM_VERSION,
        requirement_version=REQUIREMENT_VERSION,
        role_dna_id=ROLE_DNA_ID,
        role_dna_version=ROLE_DNA_VERSION,
        opportunity_spec_id=OPPORTUNITY_SPEC_ID,
        opportunity_spec_version=OPPORTUNITY_VERSION,
        command_id=command_id,
    )


async def _begin_and_seal(repo, *, generation_id, candidate_count,
                          stream_id=STREAM_ID):
    await repo.begin_generation(
        stream_id=stream_id,
        generation_id=generation_id,
        stream_version=STREAM_VERSION,
        requirement_version=REQUIREMENT_VERSION,
        role_dna_id=ROLE_DNA_ID,
        role_dna_version=ROLE_DNA_VERSION,
        opportunity_spec_id=OPPORTUNITY_SPEC_ID,
        opportunity_spec_version=OPPORTUNITY_VERSION,
    )
    await repo.seal_generation(
        stream_id=stream_id,
        generation_id=generation_id,
        stream_version=STREAM_VERSION,
        requirement_version=REQUIREMENT_VERSION,
        role_dna_id=ROLE_DNA_ID,
        role_dna_version=ROLE_DNA_VERSION,
        opportunity_spec_id=OPPORTUNITY_SPEC_ID,
        opportunity_spec_version=OPPORTUNITY_VERSION,
        candidate_count=candidate_count,
    )


class _FakeStreams:
    def __init__(self, primary, *, changed_after=None, changed_stream=None):
        self._primary = primary
        self._changed_after = changed_after
        self._changed_stream = (
            changed_stream if changed_stream is not None else primary
        )
        self.get_calls = 0
        self.changed = False
        self.readiness_error = False
        self.stored_data_error = False

    async def readiness(self):
        if self.readiness_error:
            raise TalentStreamReadinessError("stream storage not ready")
        if self.stored_data_error:
            raise TalentStreamStoredDataError("stored stream data")

    async def get(self, stream_id):
        self.get_calls += 1
        if self.stored_data_error:
            raise TalentStreamStoredDataError("stored stream data")
        if self.changed or (
            self._changed_after is not None and self.get_calls > self._changed_after
        ):
            return self._changed_stream
        return self._primary

    def force_changed(self):
        self.changed = True


class _FakeSources:
    def __init__(self, opportunity):
        self.opportunity = opportunity
        self.opportunity_sequence = []
        self.events = {}
        self.raise_readiness = False
        self.raise_stored_data = False
        self.raise_repository_error = False

    async def readiness_intent(self):
        if self.raise_readiness:
            raise StreamCandidateSourceReadinessError("intent storage not ready")
        if self.raise_repository_error:
            raise StreamCandidateSourceRepositoryError("intent storage unreachable")

    async def get_opportunity(self, opportunity_spec_id, version):
        if self.raise_stored_data:
            raise StreamCandidateSourceStoredDataError("invalid stored spec")
        if self.raise_repository_error:
            raise StreamCandidateSourceRepositoryError("spec read failed")
        if self.opportunity_sequence:
            return self.opportunity_sequence.pop(0)
        return self.opportunity

    async def list_intent_events(self, job_id, event_type, *, after_event=None,
                                 limit=INTENT_EVENT_PAGE_LIMIT):
        if self.raise_stored_data:
            raise StreamCandidateSourceStoredDataError("invalid stored b7 intent event")
        if self.raise_repository_error:
            raise StreamCandidateSourceRepositoryError("b7 intent event read failed")
        docs = sorted(
            self.events.get((job_id, event_type), []),
            key=lambda doc: (doc["occurred_at"], str(doc["_id"])),
        )
        return tuple(docs[:limit]), None


class _FakeApplications:
    def __init__(self, sources=(), *, authorized=True):
        self.sources = tuple(sorted(sources, key=_application_position))
        self.authorized = authorized
        self.calls = []
        self.scope_calls = 0
        self._scope_fail_on = None
        self.raise_access = False
        self.raise_stored = False

    async def list_page(self, recruiter_id, stream_id, *, after=None, limit=100):
        self.calls.append((recruiter_id, stream_id, after, limit))
        if self.raise_access:
            raise ApplicationSourceAccessError("application source not authorized")
        if self.raise_stored:
            raise ApplicationSourceStoredDataError("invalid stored application source")
        boundary = None
        if after is not None:
            boundary = (after.applied_at, str(after.application_id))
        page = []
        for source in self.sources:
            position = _application_position(source)
            if boundary is None or position > boundary:
                page.append(source)
        return tuple(page[:limit])

    async def _scope(self, recruiter_id, stream_id):
        self.scope_calls += 1
        if self.raise_access:
            raise ApplicationSourceAccessError("application source not authorized")
        if self.raise_stored:
            raise ApplicationSourceStoredDataError("invalid stored application source")
        if self._scope_fail_on is not None and self.scope_calls >= self._scope_fail_on:
            raise ApplicationSourceAccessError("application source not authorized")
        if not self.authorized:
            raise ApplicationSourceAccessError("application source not authorized")
        return _SecuredScope(
            stream_id=str(stream_id),
            job_id=JOB_ID,
            fingerprint=(),
        )

    def fail_scope_on_call(self, call_number):
        self._scope_fail_on = call_number


class _FakeSavedFavorites:
    def __init__(self, mapping=None):
        self.mapping = dict(mapping or {})

    async def saved_jobs_readiness(self):
        pass

    async def get_saved_job(self, candidate_id, job_id, saved_job_id):
        return self.mapping.get((str(candidate_id), str(job_id), str(saved_job_id)))


class _FakeDiscovery:
    def __init__(self, pages=()):
        self.pages = list(pages)
        self.raise_access = False
        self.raise_stored = False

    async def list_page(self, stream_id, *, after=None, limit=100):
        if self.raise_access:
            raise DiscoveryPoolAccessError("discovery pool not authorized")
        if self.raise_stored:
            raise DiscoveryPoolStoredDataError("invalid stored discovery pool")
        if self.pages:
            return self.pages.pop(0)
        return _discovery_page()


class _CollectionStub:
    def with_options(self, **kwargs):
        return self


class _FakeDB(dict):
    def __missing__(self, key):
        stub = _CollectionStub()
        self[key] = stub
        return stub

    def __getattr__(self, name):
        return self[name]


class _FakeCandidateRepository:
    """Faithful in-memory port of the B7 staging/publication CAS contract."""

    def __init__(self, *, ready=True, state=None, documents=(),
                 fail_stage_batch=0, barrier_reads=0,
                 flip_streams=None, fail_state_read=False):
        self.ready = ready
        self.state = state
        self.documents = dict(documents)
        self.generations = {}
        self.fail_stage_batch = fail_stage_batch
        self.barrier_reads = barrier_reads
        self.flip_streams = flip_streams
        self.fail_state_read = fail_state_read
        self.stage_calls = 0
        self._reads = 0
        self._event = None

    async def get_projection_state(self, stream_id):
        if not self.ready:
            raise StreamCandidateReadinessError(
                "b7 candidate projection storage is not ready"
            )
        if self.fail_state_read:
            raise StreamCandidateRepositoryError("b7 projection state is malformed")
        snapshot = self.state
        self._reads += 1
        if self._event is None:
            self._event = asyncio.Event()
        if self.barrier_reads and self._reads >= self.barrier_reads:
            self._event.set()
        if self.barrier_reads:
            await asyncio.wait_for(self._event.wait(), timeout=10)
            await asyncio.sleep(0)
        return snapshot

    @staticmethod
    def _same_publication(state, *, target_state_version, generation_id,
                          stream_version, requirement_version, role_dna_id,
                          role_dna_version, opportunity_spec_id,
                          opportunity_spec_version, candidate_count,
                          published_at):
        return (
            state.active_generation_id == generation_id
            and state.state_version == target_state_version
            and state.stream_version == stream_version
            and state.requirement_version == requirement_version
            and state.role_dna_id == role_dna_id
            and state.role_dna_version == role_dna_version
            and state.opportunity_spec_id == opportunity_spec_id
            and state.opportunity_spec_version == opportunity_spec_version
            and state.candidate_count == candidate_count
            and state.published_at == published_at
        )

    def _generation_scope_matches(self, record, *, stream_id, generation_id,
                                  stream_version, requirement_version,
                                  role_dna_id, role_dna_version,
                                  opportunity_spec_id, opportunity_spec_version):
        return (
            str(record.stream_id) == str(stream_id)
            and str(record.generation_id) == str(generation_id)
            and int(record.stream_version) == int(stream_version)
            and int(record.requirement_version) == int(requirement_version)
            and str(record.role_dna_id) == str(role_dna_id)
            and int(record.role_dna_version) == int(role_dna_version)
            and str(record.opportunity_spec_id) == str(opportunity_spec_id)
            and int(record.opportunity_spec_version) == int(opportunity_spec_version)
        )

    def _generation(self, stream_id, generation_id):
        document = self.generations.get(
            generation_record_document_id(stream_id, generation_id)
        )
        if document is None:
            return None
        return generation_record_from_document(document)

    async def begin_generation(
        self, stream_id, *, generation_id, stream_version,
        requirement_version, role_dna_id, role_dna_version,
        opportunity_spec_id, opportunity_spec_version,
    ):
        if not self.ready:
            raise StreamCandidateReadinessError(
                "b7 candidate projection storage is not ready"
            )
        document = generation_record_to_document(StreamCandidateGenerationRecord(
            stream_id=stream_id,
            generation_id=generation_id,
            stream_version=stream_version,
            requirement_version=requirement_version,
            role_dna_id=role_dna_id,
            role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
            state=GenerationState.BUILDING,
            candidate_count=None,
        ))
        record_id = generation_record_document_id(stream_id, generation_id)
        if record_id in self.generations:
            existing = generation_record_from_document(self.generations[record_id])
            if self._generation_scope_matches(
                existing, stream_id=stream_id, generation_id=generation_id,
                stream_version=stream_version, requirement_version=requirement_version,
                role_dna_id=role_dna_id, role_dna_version=role_dna_version,
                opportunity_spec_id=opportunity_spec_id,
                opportunity_spec_version=opportunity_spec_version,
            ):
                return existing
            raise StreamCandidateConflictError("b7 generation scope mismatch")
        self.generations[record_id] = document
        return generation_record_from_document(document)

    async def seal_generation(
        self, stream_id, *, generation_id, stream_version,
        requirement_version, role_dna_id, role_dna_version,
        opportunity_spec_id, opportunity_spec_version,
        candidate_count,
    ):
        if not self.ready:
            raise StreamCandidateReadinessError(
                "b7 candidate projection storage is not ready"
            )
        record = self._generation(stream_id, generation_id)
        if record is None:
            raise StreamCandidateConflictError("b7 generation is not registered")
        if not self._generation_scope_matches(
            record, stream_id=stream_id, generation_id=generation_id,
            stream_version=stream_version, requirement_version=requirement_version,
            role_dna_id=role_dna_id, role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
        ):
            raise StreamCandidateConflictError("b7 generation scope mismatch")
        if record.state is GenerationState.SEALED:
            if record.candidate_count != candidate_count:
                raise StreamCandidateConflictError(
                    "b7 sealed generation candidate count mismatch"
                )
            return record
        if record.state is GenerationState.BUILDING:
            if record.staging_batch_id is not None:
                raise StreamCandidateConflictError("b7 generation seal conflict")
            pending_record = StreamCandidateGenerationRecord(
                stream_id=record.stream_id,
                generation_id=record.generation_id,
                stream_version=record.stream_version,
                requirement_version=record.requirement_version,
                role_dna_id=record.role_dna_id,
                role_dna_version=record.role_dna_version,
                opportunity_spec_id=record.opportunity_spec_id,
                opportunity_spec_version=record.opportunity_spec_version,
                state=GenerationState.SEALING,
                candidate_count=candidate_count,
            )
            self.generations[generation_record_document_id(
                stream_id, generation_id
            )] = generation_record_to_document(pending_record)
        elif record.candidate_count != candidate_count:
            raise StreamCandidateConflictError(
                "b7 interrupted seal retry count mismatch"
            )
        staged = [
            document
            for document in self.documents.values()
            if document.get("stream_id") == stream_id
            and document.get("generation_id") == generation_id
        ]
        if len(staged) != candidate_count:
            raise StreamCandidateConflictError("b7 generation candidate count mismatch")
        sealed_record = StreamCandidateGenerationRecord(
            stream_id=record.stream_id,
            generation_id=record.generation_id,
            stream_version=record.stream_version,
            requirement_version=record.requirement_version,
            role_dna_id=record.role_dna_id,
            role_dna_version=record.role_dna_version,
            opportunity_spec_id=record.opportunity_spec_id,
            opportunity_spec_version=record.opportunity_spec_version,
            state=GenerationState.SEALED,
            candidate_count=candidate_count,
        )
        sealed_document = generation_record_to_document(sealed_record)
        self.generations[generation_record_document_id(stream_id, generation_id)] = (
            sealed_document
        )
        return generation_record_from_document(sealed_document)

    async def stage_candidates(self, candidates):
        if not self.ready:
            raise StreamCandidateReadinessError(
                "b7 candidate projection storage is not ready"
            )
        if type(candidates) not in (list, tuple) or not candidates:
            raise StreamCandidateRepositoryError(
                "b7 staging requires a non-empty batch"
            )
        first = candidates[0]
        scope = (
            str(first.stream_id),
            int(first.stream_version),
            int(first.requirement_version),
            str(first.generation_id),
            str(first.role_dna_id),
            int(first.role_dna_version),
            str(first.opportunity_spec_id),
            int(first.opportunity_spec_version),
        )
        for candidate in candidates[1:]:
            candidate_scope = (
                str(candidate.stream_id),
                int(candidate.stream_version),
                int(candidate.requirement_version),
                str(candidate.generation_id),
                str(candidate.role_dna_id),
                int(candidate.role_dna_version),
                str(candidate.opportunity_spec_id),
                int(candidate.opportunity_spec_version),
            )
            if candidate_scope != scope:
                raise StreamCandidateRepositoryError(
                    "b7 batch must share one exact generation scope"
                )
        documents = [stream_candidate_to_document(candidate) for candidate in candidates]
        ids = [document["_id"] for document in documents]
        if len(set(ids)) != len(ids):
            raise StreamCandidateRepositoryError("b7 batch has duplicate candidate ids")
        self.stage_calls += 1
        if self.fail_stage_batch and self.stage_calls == self.fail_stage_batch:
            raise StreamCandidateRepositoryError("b7 staging write failed")
        record = self._generation(first.stream_id, first.generation_id)
        if record is None:
            raise StreamCandidateConflictError("b7 generation is not registered")
        if not self._generation_scope_matches(
            record,
            stream_id=first.stream_id,
            generation_id=first.generation_id,
            stream_version=first.stream_version,
            requirement_version=first.requirement_version,
            role_dna_id=first.role_dna_id,
            role_dna_version=first.role_dna_version,
            opportunity_spec_id=first.opportunity_spec_id,
            opportunity_spec_version=first.opportunity_spec_version,
        ):
            raise StreamCandidateConflictError("b7 generation scope mismatch")
        if record.state is not GenerationState.BUILDING:
            return await self._stage_validation_only(
                first, documents, candidates, record
            )
        try:
            fingerprint = staging_batch_fingerprint(candidates)
        except ValueError:
            raise StreamCandidateRepositoryError(
                "b7 staging received an invalid batch"
            ) from None
        if (
            record.staging_batch_id is not None
            and record.staging_batch_id != fingerprint
        ):
            raise StreamCandidateConflictError("b7 staging batch is already reserved")
        if record.staging_batch_id is None:
            self._set_staging_batch(
                first.stream_id, first.generation_id, fingerprint
            )
        for candidate, document in zip(candidates, documents):
            stored = self.documents.get(document["_id"])
            if stored is not None:
                if stream_candidate_from_document(stored) != candidate:
                    raise StreamCandidateConflictError(
                        "b7 staging conflicts with an existing candidate document"
                    )
                continue
            self.documents[document["_id"]] = document
        if self.flip_streams is not None:
            self.flip_streams.force_changed()
        self._set_staging_batch(first.stream_id, first.generation_id, None)
        return {
            "stream_id": first.stream_id,
            "generation_id": first.generation_id,
            "staged": len(documents),
        }

    async def _stage_validation_only(self, first, documents, candidates, record):
        message = (
            "b7 generation is sealing"
            if record.state is GenerationState.SEALING
            else "b7 generation is sealed"
        )
        for candidate, document in zip(candidates, documents):
            stored = self.documents.get(document["_id"])
            if stored is None or stream_candidate_from_document(stored) != candidate:
                raise StreamCandidateConflictError(message)
        return {
            "stream_id": first.stream_id,
            "generation_id": first.generation_id,
            "staged": 0,
        }

    def _set_staging_batch(self, stream_id, generation_id, fingerprint):
        record_id = generation_record_document_id(stream_id, generation_id)
        document = self.generations.get(record_id)
        if document is None:
            return
        document = dict(document)
        if fingerprint is None:
            document.pop("staging_batch_id", None)
        else:
            document["staging_batch_id"] = fingerprint
        self.generations[record_id] = document

    async def publish_generation(
        self,
        stream_id,
        *,
        generation_id,
        stream_version,
        requirement_version,
        role_dna_id,
        role_dna_version,
        opportunity_spec_id,
        opportunity_spec_version,
        expected_candidate_count,
        expected_state,
        published_at=None,
    ):
        if not self.ready:
            raise StreamCandidateReadinessError(
                "b7 candidate projection storage is not ready"
            )
        if published_at is None:
            raise ValueError("invalid stream candidate publication timestamp")
        published_at = utc_millisecond(published_at, "published_at")
        if expected_state is not None and expected_state.stream_id != stream_id:
            raise StreamCandidateConflictError("b7 expected projection state mismatch")
        record = self._generation(stream_id, generation_id)
        if record is None:
            raise StreamCandidateConflictError("b7 generation is not registered")
        if not self._generation_scope_matches(
            record,
            stream_id=stream_id,
            generation_id=generation_id,
            stream_version=stream_version,
            requirement_version=requirement_version,
            role_dna_id=role_dna_id,
            role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
        ):
            raise StreamCandidateConflictError("b7 generation scope mismatch")
        if record.state is not GenerationState.SEALED:
            raise StreamCandidateConflictError("b7 generation is not sealed")
        if record.candidate_count != expected_candidate_count:
            raise StreamCandidateConflictError(
                "b7 sealed generation candidate count mismatch"
            )
        staged = [
            document
            for document in self.documents.values()
            if document.get("stream_id") == stream_id
            and document.get("generation_id") == generation_id
        ]
        if len(staged) != expected_candidate_count:
            raise StreamCandidateConflictError("b7 generation candidate count mismatch")
        metadata = {
            "generation_id": generation_id,
            "stream_version": stream_version,
            "requirement_version": requirement_version,
            "role_dna_id": role_dna_id,
            "role_dna_version": role_dna_version,
            "opportunity_spec_id": opportunity_spec_id,
            "opportunity_spec_version": opportunity_spec_version,
            "candidate_count": expected_candidate_count,
        }
        current = self.state
        if current is None and expected_state is not None:
            raise StreamCandidateConflictError(
                "b7 expected projection state mismatch"
            )
        if current is None:
            target = ProjectionState(
                stream_id=stream_id,
                state_version=1,
                active_generation_id=generation_id,
                stream_version=stream_version,
                requirement_version=requirement_version,
                role_dna_id=role_dna_id,
                role_dna_version=role_dna_version,
                opportunity_spec_id=opportunity_spec_id,
                opportunity_spec_version=opportunity_spec_version,
                candidate_count=expected_candidate_count,
                published_at=published_at,
            )
            if self.state is None:
                self.state = target
                return target
            if self._same_publication(
                self.state, target_state_version=1, **metadata,
                published_at=published_at,
            ):
                return self.state
            raise StreamCandidateConflictError("b7 projection publish conflict")
        if current.active_generation_id == generation_id:
            if self._same_publication(
                current, target_state_version=current.state_version, **metadata,
                published_at=published_at,
            ):
                return current
            raise StreamCandidateConflictError("b7 projection publish conflict")
        if expected_state is None or expected_state != current:
            raise StreamCandidateConflictError("b7 expected projection state mismatch")
        target = ProjectionState(
            stream_id=stream_id,
            state_version=current.state_version + 1,
            active_generation_id=generation_id,
            stream_version=stream_version,
            requirement_version=requirement_version,
            role_dna_id=role_dna_id,
            role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
            candidate_count=expected_candidate_count,
            published_at=published_at,
        )
        self.state = target
        return target


def _build_aggregation(streams=None, sources=None, apps=None, saved=None,
                       discovery=None):
    aggregation = StreamCandidateAggregationService(_FakeDB())
    aggregation.streams = streams if streams is not None else _FakeStreams(_make_stream())
    aggregation.sources = sources if sources is not None else _FakeSources(
        _opportunity_source()
    )
    aggregation.applications = apps if apps is not None else _FakeApplications()
    aggregation.saved_favorites = saved if saved is not None else _FakeSavedFavorites()
    aggregation.discovery = discovery if discovery is not None else _FakeDiscovery()
    return aggregation


def _build_refresh(*, streams=None, sources=None, apps=None, saved=None,
                   discovery=None, repo=None):
    aggregation = _build_aggregation(streams, sources, apps, saved, discovery)
    repository = repo if repo is not None else _FakeCandidateRepository()
    service = StreamCandidateRefreshService(
        _FakeDB(), aggregation=aggregation, repository=repository
    )
    return service, aggregation, repository


class TestRefreshCommandContract:
    def test_command_is_frozen_and_validated(self):
        command = _command()
        assert command.stream_id == STREAM_ID
        assert command.command_id == CMD_ID
        assert command.refresh_at == REFRESH_AT
        assert command.refresh_at.tzinfo is not None
        with pytest.raises(Exception):
            command.command_id = "unfrozen"

    def test_command_rejects_invalid_identity(self):
        with pytest.raises(ValueError, match="invalid stream candidate refresh command"):
            StreamCandidateRefreshCommand("", CMD_ID, REFRESH_AT)
        with pytest.raises(ValueError, match="invalid stream candidate refresh command"):
            StreamCandidateRefreshCommand(STREAM_ID, "", REFRESH_AT)

    def test_command_rejects_invalid_refresh_at(self):
        naive = _utc(900).replace(tzinfo=None)
        with pytest.raises(ValueError, match="invalid stream candidate refresh command"):
            _command(refresh_at=naive)
        micros = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="invalid stream candidate refresh command"):
            _command(refresh_at=micros)


class TestGenerationIdentity:
    def test_deterministic_versioned_digest(self):
        first = _generation_id()
        assert GENERATION_PATTERN.match(first)
        assert first == _generation_id()
        assert first == generation_identifier(
            stream_id=STREAM_ID, stream_version=STREAM_VERSION,
            requirement_version=REQUIREMENT_VERSION, role_dna_id=ROLE_DNA_ID,
            role_dna_version=ROLE_DNA_VERSION, opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            opportunity_spec_version=OPPORTUNITY_VERSION, command_id=CMD_ID,
        )

    def test_command_change_drives_identity(self):
        assert _generation_id() != _generation_id("cmd-other")

    def test_scope_change_drives_identity(self):
        assert generation_identifier(
            stream_id=STREAM_ID, stream_version=STREAM_VERSION + 1,
            requirement_version=REQUIREMENT_VERSION, role_dna_id=ROLE_DNA_ID,
            role_dna_version=ROLE_DNA_VERSION, opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            opportunity_spec_version=OPPORTUNITY_VERSION, command_id=CMD_ID,
        ) != _generation_id()

    def test_invalid_scope_is_rejected(self):
        with pytest.raises(ValueError, match="invalid stream candidate refresh generation identity"):
            generation_identifier(
                stream_id="", stream_version=STREAM_VERSION,
                requirement_version=REQUIREMENT_VERSION, role_dna_id=ROLE_DNA_ID,
                role_dna_version=ROLE_DNA_VERSION, opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                opportunity_spec_version=OPPORTUNITY_VERSION, command_id=CMD_ID,
            )
        with pytest.raises(ValueError, match="invalid stream candidate refresh generation identity"):
            generation_identifier(
                stream_id=STREAM_ID, stream_version=0,
                requirement_version=REQUIREMENT_VERSION, role_dna_id=ROLE_DNA_ID,
                role_dna_version=ROLE_DNA_VERSION, opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                opportunity_spec_version=OPPORTUNITY_VERSION, command_id=CMD_ID,
            )


class TestInitialRefresh:
    def test_refresh_requires_the_exact_command(self):
        service, _, _ = _build_refresh()
        with pytest.raises(ValueError, match="invalid stream candidate refresh command"):
            _run(service.refresh(None))

    def test_initial_refresh_publishes_one_generation(self):
        apps = _FakeApplications([
            _application("app-1", "cand-1", ms=20),
            _application("app-2", "cand-2", ms=30),
        ])
        service, aggregation, repo = _build_refresh(apps=apps)
        result = _run(service.refresh(_command()))
        assert type(result) is StreamCandidateRefreshResult
        assert result.stream_id == STREAM_ID
        assert result.generation_id == _generation_id()
        assert result.candidate_count == 2
        assert result.state_version == 1
        assert result.published_at == REFRESH_AT
        assert len(repo.documents) == 2
        state = _run(repo.get_projection_state(STREAM_ID))
        assert state is not None
        assert state.active_generation_id == _generation_id()
        assert state.candidate_count == 2
        assert state.published_at == REFRESH_AT

    def test_result_is_minimal(self):
        apps = _FakeApplications([_application("app-1", "cand-1")])
        service, _, _ = _build_refresh(apps=apps)
        result = _run(service.refresh(_command()))
        fields = {field.name for field in dataclasses.fields(result)}
        assert fields == {
            "stream_id", "generation_id", "candidate_count",
            "state_version", "published_at",
        }

    def test_empty_generation_skips_staging(self):
        service, aggregation, repo = _build_refresh(apps=_FakeApplications())
        result = _run(service.refresh(_command()))
        assert result.candidate_count == 0
        assert repo.documents == {}
        state = _run(repo.get_projection_state(STREAM_ID))
        assert state.active_generation_id == _generation_id()
        assert state.candidate_count == 0

    def test_follow_up_refresh_advances_pointer_and_keeps_old_generation(self):
        apps = _FakeApplications([
            _application("app-1", "cand-1", ms=20),
            _application("app-2", "cand-2", ms=30),
        ])
        service, _, repo = _build_refresh(apps=apps)
        first = _run(service.refresh(_command("cmd-a")))
        second = _run(service.refresh(_command("cmd-b")))
        assert first.state_version == 1
        assert second.generation_id == _generation_id("cmd-b")
        assert second.state_version == 2
        assert second.candidate_count == 2
        state = _run(repo.get_projection_state(STREAM_ID))
        assert state.active_generation_id == _generation_id("cmd-b")
        assert len(repo.documents) == 4
        old_docs = [
            doc for doc in repo.documents.values()
            if doc.get("generation_id") == _generation_id("cmd-a")
        ]
        assert len(old_docs) == 2

    def test_empty_follow_up_keeps_previous_generation_readable(self):
        apps = _FakeApplications([
            _application("app-1", "cand-1", ms=20),
            _application("app-2", "cand-2", ms=30),
        ])
        service, aggregation, repo = _build_refresh(apps=apps)
        _run(service.refresh(_command("cmd-a")))
        aggregation.applications.sources = ()
        result = _run(service.refresh(_command("cmd-b")))
        assert result.candidate_count == 0
        state = _run(repo.get_projection_state(STREAM_ID))
        assert state.active_generation_id == _generation_id("cmd-b")
        assert state.candidate_count == 0
        assert len(repo.documents) == 2
        assert all(
            doc.get("generation_id") == _generation_id("cmd-a")
            for doc in repo.documents.values()
        )


class TestRetryIdempotency:
    def test_retry_after_success_is_idempotent(self):
        apps = _FakeApplications([
            _application("app-1", "cand-1", ms=20),
            _application("app-2", "cand-2", ms=30),
        ])
        service, _, repo = _build_refresh(apps=apps)
        first = _run(service.refresh(_command()))
        second = _run(service.refresh(_command()))
        assert second.generation_id == first.generation_id == _generation_id()
        assert second.state_version == 1
        assert second.published_at == first.published_at == REFRESH_AT
        assert len(repo.documents) == 2

    def test_partial_staging_retry_completes(self, monkeypatch):
        monkeypatch.setattr(
            "domains.talent_stream.stream_candidate_refresh.STAGING_BATCH_SIZE", 2
        )
        apps = _FakeApplications([
            _application(f"app-{i}", f"cand-{i}", ms=20 + i) for i in range(1, 6)
        ])
        repo = _FakeCandidateRepository(fail_stage_batch=2)
        service, _, repository = _build_refresh(apps=apps, repo=repo)
        with pytest.raises(StreamCandidateRefreshStoredDataError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == STORED_MSG
        assert len(repo.documents) == 2
        repo.fail_stage_batch = 0
        result = _run(service.refresh(_command()))
        assert result.generation_id == _generation_id()
        assert result.candidate_count == 5
        assert len(repo.documents) == 5
        assert repo.stage_calls == 5

    def test_same_command_changed_sources_payload_conflict(self):
        apps = _FakeApplications([
            _application("app-1", "cand-1", ms=20),
            _application("app-2", "cand-2", ms=30),
        ])
        service, aggregation, repo = _build_refresh(apps=apps)
        _run(service.refresh(_command()))
        aggregation.applications = _FakeApplications([
            _application("app-1", "cand-1", ms=70),
            _application("app-2", "cand-2", ms=30),
        ])
        with pytest.raises(StreamCandidateRefreshConflictError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == SCOPE_CHANGED_MSG
        state = _run(repo.get_projection_state(STREAM_ID))
        assert state.active_generation_id == _generation_id()


class TestSameCommandDifferentRefreshAt:
    def test_non_empty_same_command_different_refresh_at_conflicts(self):
        apps = _FakeApplications([
            _application("app-1", "cand-1", ms=20),
            _application("app-2", "cand-2", ms=30),
        ])
        service, _, repo = _build_refresh(apps=apps)
        first = _run(service.refresh(_command()))
        assert first.generation_id == _generation_id()
        assert first.state_version == 1
        assert first.published_at == REFRESH_AT
        with pytest.raises(StreamCandidateRefreshConflictError) as exc:
            _run(service.refresh(_command(refresh_at=_utc(950))))
        assert str(exc.value) == SCOPE_CHANGED_MSG
        state = _run(repo.get_projection_state(STREAM_ID))
        assert state.active_generation_id == _generation_id()
        assert state.state_version == 1
        assert state.published_at == REFRESH_AT
        assert len(repo.documents) == 2

    def test_empty_same_command_different_refresh_at_conflicts(self):
        service, _, repo = _build_refresh(apps=_FakeApplications())
        first = _run(service.refresh(_command()))
        assert first.candidate_count == 0
        assert first.published_at == REFRESH_AT
        with pytest.raises(StreamCandidateRefreshConflictError) as exc:
            _run(service.refresh(_command(refresh_at=_utc(950))))
        assert str(exc.value) == SCOPE_CHANGED_MSG
        state = _run(repo.get_projection_state(STREAM_ID))
        assert state.active_generation_id == _generation_id()
        assert state.state_version == 1
        assert state.published_at == REFRESH_AT
        assert repo.documents == {}

    def test_empty_same_command_same_refresh_at_stays_idempotent(self):
        service, _, repo = _build_refresh(apps=_FakeApplications())
        first = _run(service.refresh(_command()))
        second = _run(service.refresh(_command()))
        assert second.generation_id == first.generation_id
        assert second.state_version == 1
        assert second.published_at == first.published_at == REFRESH_AT


class TestCasExpectedStateGone:
    def test_publish_with_expected_state_but_no_current_state_conflicts(self):
        expected = ProjectionState(
            stream_id=STREAM_ID,
            state_version=4,
            active_generation_id="previous-gen",
            stream_version=STREAM_VERSION,
            requirement_version=REQUIREMENT_VERSION,
            role_dna_id=ROLE_DNA_ID,
            role_dna_version=ROLE_DNA_VERSION,
            opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            opportunity_spec_version=OPPORTUNITY_VERSION,
            candidate_count=0,
            published_at=_utc(800),
        )
        repo = _FakeCandidateRepository(state=None)
        _run(_begin_and_seal(repo, generation_id="previous-gen", candidate_count=0))
        with pytest.raises(StreamCandidateConflictError) as exc:
            _run(repo.publish_generation(
                STREAM_ID,
                generation_id="previous-gen",
                stream_version=STREAM_VERSION,
                requirement_version=REQUIREMENT_VERSION,
                role_dna_id=ROLE_DNA_ID,
                role_dna_version=ROLE_DNA_VERSION,
                opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                opportunity_spec_version=OPPORTUNITY_VERSION,
                expected_candidate_count=0,
                expected_state=expected,
                published_at=_utc(800),
            ))
        assert str(exc.value) == "b7 expected projection state mismatch"
        assert repo.state is None

    def test_publish_with_no_expected_state_but_current_exists_conflicts(self):
        current = ProjectionState(
            stream_id=STREAM_ID,
            state_version=1,
            active_generation_id="published-gen",
            stream_version=STREAM_VERSION,
            requirement_version=REQUIREMENT_VERSION,
            role_dna_id=ROLE_DNA_ID,
            role_dna_version=ROLE_DNA_VERSION,
            opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            opportunity_spec_version=OPPORTUNITY_VERSION,
            candidate_count=0,
            published_at=_utc(700),
        )
        repo = _FakeCandidateRepository(state=current)
        _run(_begin_and_seal(repo, generation_id="other-gen", candidate_count=0))
        with pytest.raises(StreamCandidateConflictError) as exc:
            _run(repo.publish_generation(
                STREAM_ID,
                generation_id="other-gen",
                stream_version=STREAM_VERSION,
                requirement_version=REQUIREMENT_VERSION,
                role_dna_id=ROLE_DNA_ID,
                role_dna_version=ROLE_DNA_VERSION,
                opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                opportunity_spec_version=OPPORTUNITY_VERSION,
                expected_candidate_count=0,
                expected_state=None,
                published_at=_utc(800),
            ))
        assert str(exc.value) == "b7 expected projection state mismatch"
        state = _run(repo.get_projection_state(STREAM_ID))
        assert state.state_version == 1
        assert state.published_at == _utc(700)

    def test_publish_same_generation_retry_requires_matching_published_at(self):
        repo = _FakeCandidateRepository(
            state=ProjectionState(
                stream_id=STREAM_ID,
                state_version=1,
                active_generation_id="published-gen",
                stream_version=STREAM_VERSION,
                requirement_version=REQUIREMENT_VERSION,
                role_dna_id=ROLE_DNA_ID,
                role_dna_version=ROLE_DNA_VERSION,
                opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                opportunity_spec_version=OPPORTUNITY_VERSION,
                candidate_count=0,
                published_at=_utc(700),
            )
        )
        _run(_begin_and_seal(repo, generation_id="published-gen", candidate_count=0))
        with pytest.raises(StreamCandidateConflictError) as exc:
            _run(repo.publish_generation(
                STREAM_ID,
                generation_id="published-gen",
                stream_version=STREAM_VERSION,
                requirement_version=REQUIREMENT_VERSION,
                role_dna_id=ROLE_DNA_ID,
                role_dna_version=ROLE_DNA_VERSION,
                opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                opportunity_spec_version=OPPORTUNITY_VERSION,
                expected_candidate_count=0,
                expected_state=None,
                published_at=_utc(800),
            ))
        assert str(exc.value) == "b7 projection publish conflict"
        state = _run(repo.get_projection_state(STREAM_ID))
        assert state.published_at == _utc(700)


class TestConcurrency:
    def test_concurrent_refresh_has_exactly_one_winner(self):
        apps = _FakeApplications([
            _application("app-a-1", "cand-a-1", ms=21),
            _application("app-a-2", "cand-a-2", ms=22),
        ])
        repo = _FakeCandidateRepository(barrier_reads=2)
        service, _, repository = _build_refresh(apps=apps, repo=repo)
        cmd_a = _command("cmd-a")
        cmd_b = _command("cmd-b")

        async def run_both():
            return await asyncio.gather(
                service.refresh(cmd_a),
                service.refresh(cmd_b),
                return_exceptions=True,
            )

        results = _run(run_both())
        successes = [r for r in results if type(r) is StreamCandidateRefreshResult]
        errors = [r for r in results if isinstance(r, Exception)]
        assert len(successes) == 1, results
        assert len(errors) == 1, results
        assert type(errors[0]) is StreamCandidateRefreshConflictError
        assert str(errors[0]) == SCOPE_CHANGED_MSG
        winner = successes[0]
        state = _run(repo.get_projection_state(STREAM_ID))
        assert state.active_generation_id == winner.generation_id
        assert state.state_version == 1
        loser_command = "cmd-b" if winner.generation_id == _generation_id("cmd-a") else "cmd-a"
        loser_generation = _generation_id(loser_command)
        loser_docs = {
            doc["_id"] for doc in repo.documents.values()
            if doc.get("generation_id") == loser_generation
        }
        assert len(loser_docs) == 2


class TestScopeRevalidation:
    def test_scope_change_before_publish_is_refused(self):
        closed = _make_stream(TalentStreamState.CLOSED, version=STREAM_VERSION + 1)
        streams = _FakeStreams(_make_stream(), changed_after=3, changed_stream=closed)
        service, _, repo = _build_refresh(streams=streams)
        with pytest.raises(StreamCandidateRefreshConflictError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == SCOPE_CHANGED_MSG
        assert _run(repo.get_projection_state(STREAM_ID)) is None

    def test_snapshot_refs_change_before_publish_is_refused(self):
        streams = _FakeStreams(
            _make_stream(), changed_after=3, changed_stream=_make_stream_changed_refs()
        )
        service, _, repo = _build_refresh(streams=streams)
        with pytest.raises(StreamCandidateRefreshConflictError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == SCOPE_CHANGED_MSG
        assert _run(repo.get_projection_state(STREAM_ID)) is None

    def test_scope_change_during_staging_is_revalidated_after_stage(self):
        closed = _make_stream(TalentStreamState.CLOSED, version=STREAM_VERSION + 1)
        streams = _FakeStreams(_make_stream(), changed_stream=closed)
        repo = _FakeCandidateRepository(flip_streams=streams)
        apps = _FakeApplications([_application("app-1", "cand-1")])
        service, _, repository = _build_refresh(streams=streams, apps=apps, repo=repo)
        with pytest.raises(StreamCandidateRefreshConflictError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == SCOPE_CHANGED_MSG
        assert _run(repo.get_projection_state(STREAM_ID)) is None
        assert len(repo.documents) == 1

    def test_actor_mutation_after_build_blocks_stage_and_publish(self):
        changed = dataclasses.replace(
            _make_stream(),
            recruiting_actor_context=RecruitingActorContext(
                recruiter_user_id=RECRUITER_ID,
                requesting_organization_id="org-r-other",
                hiring_company_id="org-h-1",
                mandate_id=None,
            ),
        )
        streams = _FakeStreams(_make_stream(), changed_after=3, changed_stream=changed)
        apps = _FakeApplications([_application("app-1", "cand-1")])
        service, _, repo = _build_refresh(streams=streams, apps=apps)
        with pytest.raises(StreamCandidateRefreshConflictError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == SCOPE_CHANGED_MSG
        assert _run(repo.get_projection_state(STREAM_ID)) is None
        assert len(repo.documents) == 0

    def test_source_job_mutation_after_build_blocks_stage_and_publish(self):
        sources = _FakeSources(_opportunity_source())
        changed = OpportunitySpecificationSource(
            opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            version=OPPORTUNITY_VERSION,
            source_job_id="job-other",
            source_ref=SOURCE_REF,
            version_provenance_ref=SOURCE_REF,
        )
        sources.opportunity_sequence = [
            _opportunity_source(), _opportunity_source(), changed,
        ]
        apps = _FakeApplications([_application("app-1", "cand-1")])
        service, _, repo = _build_refresh(sources=sources, apps=apps)
        with pytest.raises(StreamCandidateRefreshConflictError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == SCOPE_CHANGED_MSG
        assert _run(repo.get_projection_state(STREAM_ID)) is None
        assert len(repo.documents) == 0

    def test_provenance_mutation_after_staging_blocks_publish(self):
        sources = _FakeSources(_opportunity_source())
        changed = OpportunitySpecificationSource(
            opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            version=OPPORTUNITY_VERSION,
            source_job_id=JOB_ID,
            source_ref="source-ref-other",
            version_provenance_ref="source-ref-other",
        )
        sources.opportunity_sequence = [
            _opportunity_source(), _opportunity_source(),
            _opportunity_source(), changed,
        ]
        apps = _FakeApplications([_application("app-1", "cand-1")])
        service, _, repo = _build_refresh(sources=sources, apps=apps)
        with pytest.raises(StreamCandidateRefreshConflictError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == SCOPE_CHANGED_MSG
        assert _run(repo.get_projection_state(STREAM_ID)) is None
        assert len(repo.documents) == 1

    def test_unchanged_scope_passes_both_revalidations(self):
        service, _, repo = _build_refresh(
            apps=_FakeApplications([_application("app-1", "cand-1")])
        )
        result = _run(service.refresh(_command()))
        assert result.state_version == 1


class TestAuthorizationReadinessStored:
    def test_missing_or_inactive_stream_is_not_authorized(self):
        service, _, _ = _build_refresh(streams=_FakeStreams(None))
        with pytest.raises(StreamCandidateRefreshNotAuthorizedError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == NOT_AUTHORIZED_MSG

    def test_revoked_recruiter_is_not_authorized(self):
        apps = _FakeApplications(authorized=False)
        service, _, _ = _build_refresh(apps=apps)
        with pytest.raises(StreamCandidateRefreshNotAuthorizedError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == NOT_AUTHORIZED_MSG

    def test_revoked_recruiter_during_processing_is_a_scope_conflict(self):
        apps = _FakeApplications()
        apps.fail_scope_on_call(2)
        service, _, repo = _build_refresh(apps=apps)
        with pytest.raises(StreamCandidateRefreshConflictError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == SCOPE_CHANGED_MSG
        assert _run(repo.get_projection_state(STREAM_ID)) is None

    def test_repository_unavailable_is_storage_not_ready(self):
        repo = _FakeCandidateRepository(ready=False)
        service, _, _ = _build_refresh(repo=repo)
        with pytest.raises(StreamCandidateRefreshStorageNotReadyError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == STORAGE_NOT_READY_MSG

    def test_stream_collection_unavailable_is_storage_not_ready(self):
        streams = _FakeStreams(_make_stream())
        streams.readiness_error = True
        service, _, _ = _build_refresh(streams=streams)
        with pytest.raises(StreamCandidateRefreshStorageNotReadyError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == STORAGE_NOT_READY_MSG

    def test_malformed_stored_state_is_stored_data(self):
        repo = _FakeCandidateRepository(fail_state_read=True)
        service, _, _ = _build_refresh(repo=repo)
        with pytest.raises(StreamCandidateRefreshStoredDataError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == STORED_MSG

    def test_source_storage_unavailable_is_storage_not_ready(self):
        sources = _FakeSources(_opportunity_source())
        sources.raise_readiness = True
        service, _, _ = _build_refresh(sources=sources)
        with pytest.raises(StreamCandidateRefreshStorageNotReadyError) as exc:
            _run(service.refresh(_command()))
        assert str(exc.value) == STORAGE_NOT_READY_MSG


class TestAggregationScopeCurrentPrimitive:
    def _built(self, service):
        return _run(service.build_generation(
            STREAM_ID, generation_id=_generation_id(), computed_at=REFRESH_AT
        ))

    def test_valid_generation_passes(self):
        service = _build_aggregation(
            apps=_FakeApplications([_application("app-1", "cand-1")])
        )
        built = self._built(service)
        _run(service.assert_generation_scope_current(built))

    def test_missing_stream_is_conflict(self):
        service = _build_aggregation(streams=_FakeStreams(_make_stream()))
        built = self._built(service)
        service.streams = _FakeStreams(None)
        with pytest.raises(StreamCandidateAggregationConflictError):
            _run(service.assert_generation_scope_current(built))

    def test_changed_scope_refs_is_conflict(self):
        service = _build_aggregation(streams=_FakeStreams(_make_stream()))
        built = self._built(service)
        service.streams = _FakeStreams(_make_stream_changed_refs())
        with pytest.raises(StreamCandidateAggregationConflictError):
            _run(service.assert_generation_scope_current(built))

    def test_closed_stream_is_conflict(self):
        service = _build_aggregation(streams=_FakeStreams(_make_stream()))
        built = self._built(service)
        service.streams = _FakeStreams(
            _make_stream(TalentStreamState.CLOSED, version=STREAM_VERSION + 1)
        )
        with pytest.raises(StreamCandidateAggregationConflictError):
            _run(service.assert_generation_scope_current(built))

    def test_revoked_recruiter_is_conflict(self):
        apps = _FakeApplications()
        service = _build_aggregation(apps=apps)
        built = self._built(service)
        apps.authorized = False
        with pytest.raises(StreamCandidateAggregationConflictError):
            _run(service.assert_generation_scope_current(built))

    def test_non_generation_argument_is_stored_data(self):
        service = _build_aggregation()
        with pytest.raises(StreamCandidateAggregationStoredDataError):
            _run(service.assert_generation_scope_current(object()))

    def test_stream_storage_unavailable_is_conflict(self):
        streams = _FakeStreams(_make_stream())
        service = _build_aggregation(streams=streams)
        built = self._built(service)
        streams.stored_data_error = True
        with pytest.raises(StreamCandidateAggregationConflictError):
            _run(service.assert_generation_scope_current(built))