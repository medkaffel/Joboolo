"""G0 hermetic tests for TS-B7 STEP 3 Stream Candidate aggregation.

Everything here is in-memory only: no Mongo, no network, no external clock.
The aggregation service is wired with scripted fakes for the five read-only
dependencies (B1 Streams, B3 Opportunity/Intent sources, B3 Applications,
B5 SavedJob cycle, B6 Discovery Pool). Determinism, concurrency safety,
fail-closed behavior, redacted errors and the PEP-8 read-only surface of the
two new STEP 3 modules are all enforced without a database.
"""
import asyncio
import ast
import dataclasses
from datetime import datetime, timezone
from pathlib import Path

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
from domains.talent_stream.discovery_pool_repository import DiscoveryPoolReadinessError
from domains.talent_stream.discovery_pool_service import (
    DiscoveryPoolAccessError,
    DiscoveryPoolConflictError,
    DiscoveryPoolStoredDataError,
)
from domains.talent_stream.shared_favorite_repository import (
    SharedFavoriteReadinessError,
    SharedFavoriteRepositoryError,
)
from domains.talent_stream.stream_candidate_aggregation import (
    BuiltStreamCandidateGeneration,
    StreamCandidateAggregationAccessError,
    StreamCandidateAggregationConflictError,
    StreamCandidateAggregationReadinessError,
    StreamCandidateAggregationService,
    StreamCandidateAggregationStoredDataError,
    StreamCandidateGenerationScopeGuard,
)
from domains.talent_stream.stream_candidate_intent_source import B4_EVENT_TYPE
from domains.talent_stream.stream_candidate_models import (
    ApplicationEvidence,
    DiscoveryEvidence,
    OpportunityFitSummary,
    ProfessionalMatchSummary,
    StreamCandidate,
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
)
from domains.talent_stream.stream_repository import (
    TalentStreamReadinessError,
    TalentStreamStoredDataError,
)

from test_ts_b7_stream_candidate_contracts import (
    _make_b4_event,
    _make_b5_share_event,
    _make_b5_withdraw_event,
)
from domains.intent.serialization import event_to_document

ACCESS_MSG = "stream candidate aggregation not authorized"
READINESS_MSG = "stream candidate aggregation storage is not ready"
STORED_MSG = "invalid stored stream candidate source"
CONFLICT_MSG = "stream candidate aggregation scope changed"

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
GENERATION_ID = "generation-abc"


def _utc(ms: int = 0) -> datetime:
    return datetime(2026, 1, 1, 12, 0, 0, ms * 1000, tzinfo=timezone.utc)


SAVED_JOB_TEMPLATE = {
    "_id": "corr-y",
    "user_id": "cand-y",
    "job_id": JOB_ID,
    "created_at": _utc(50),
    "updated_at": _utc(60),
}


def _run(coro):
    """Run one async aggregation without relying on any pytest plugin."""
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
            resulting_version=3,
            occurred_at=_utc(20),
        ))
    return TalentStream(
        stream_id=STREAM_ID,
        version=version,
        recruiting_actor_context=RecruitingActorContext(
            recruiter_user_id="recruiter-1",
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


def _opportunity_source() -> OpportunitySpecificationSource:
    return OpportunitySpecificationSource(
        opportunity_spec_id=OPPORTUNITY_SPEC_ID,
        version=OPPORTUNITY_VERSION,
        source_job_id=JOB_ID,
        source_ref=SOURCE_REF,
        version_provenance_ref=SOURCE_REF,
    )


def _make_scope_guard(**overrides) -> StreamCandidateGenerationScopeGuard:
    values = dict(
        recruiting_actor_context=RecruitingActorContext(
            recruiter_user_id=RECRUITER_ID,
            requesting_organization_id="org-r-1",
            hiring_company_id="org-h-1",
            mandate_id=None,
        ),
        opportunity_spec_id=OPPORTUNITY_SPEC_ID,
        opportunity_spec_version=OPPORTUNITY_VERSION,
        source_job_id=JOB_ID,
        source_ref=SOURCE_REF,
        version_provenance_ref=SOURCE_REF,
    )
    values.update(overrides)
    return StreamCandidateGenerationScopeGuard(**values)


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


def _saved_job(candidate_id: str, correlation_id: str, *,
               created_ms: int = 50, updated_ms: int = 60,
               user_id: str | None = None, job_id: str = JOB_ID,
               doc_id: str | None = None) -> dict:
    return {
        "_id": doc_id or correlation_id,
        "user_id": user_id or candidate_id,
        "job_id": job_id,
        "created_at": _utc(created_ms),
        "updated_at": _utc(updated_ms),
    }


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


def _fit(candidate_id: str, *, spec_id: str = OPPORTUNITY_SPEC_ID,
         version: int = OPPORTUNITY_VERSION) -> OpportunityFitResult:
    return OpportunityFitResult(
        candidate_id=candidate_id,
        candidate_preferences_version=5,
        opportunity_spec_id=spec_id,
        opportunity_spec_version=version,
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


class _FakeStreams:
    def __init__(self, *states):
        self._states = list(states)
        self.readiness_error = False
        self.stored_data_error = False
        self.get_calls = 0

    async def readiness(self):
        if self.readiness_error:
            raise TalentStreamReadinessError("stream storage not ready")
        if self.stored_data_error:
            raise TalentStreamStoredDataError("stored stream data")

    async def get(self, stream_id):
        self.get_calls += 1
        if self.stored_data_error:
            raise TalentStreamStoredDataError("stored stream data")
        if not self._states:
            return None
        if len(self._states) > 1:
            return self._states.pop(0)
        return self._states[0]


class _FakeSources:
    def __init__(self, opportunity):
        self.opportunity = opportunity
        self.opportunity_sequence = []
        self.events = {}
        self.raise_readiness = False
        self.raise_repository_error = False
        self.raise_stored_data = False
        self.opportunity_calls = 0

    async def readiness_intent(self):
        if self.raise_readiness:
            raise StreamCandidateSourceReadinessError("intent storage not ready")
        if self.raise_repository_error:
            raise StreamCandidateSourceRepositoryError("intent storage unreachable")

    async def get_opportunity(self, opportunity_spec_id, version):
        self.opportunity_calls += 1
        if self.raise_stored_data:
            raise StreamCandidateSourceStoredDataError("invalid stored spec")
        if self.raise_repository_error:
            raise StreamCandidateSourceRepositoryError("spec read failed")
        if self.opportunity_sequence:
            return self.opportunity_sequence.pop(0)
        return self.opportunity

    @staticmethod
    def _doc_key(doc):
        occurred = doc["occurred_at"]
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=timezone.utc)
        return (occurred.astimezone(timezone.utc), str(doc["_id"]))

    async def list_intent_events(self, job_id, event_type, *, after_event=None,
                                 limit=INTENT_EVENT_PAGE_LIMIT):
        if self.raise_stored_data:
            raise StreamCandidateSourceStoredDataError("invalid stored b7 intent event")
        if self.raise_repository_error:
            raise StreamCandidateSourceRepositoryError("b7 intent event read failed")
        docs = sorted(
            self.events.get((job_id, event_type), self.events.get(event_type, [])),
            key=self._doc_key,
        )
        start = 0
        if after_event is not None:
            key = (after_event.occurred_at, str(after_event.event_id))
            for i, doc in enumerate(docs):
                if self._doc_key(doc) > key:
                    start = i
                    break
            else:
                start = len(docs)
        window = docs[start:start + limit]
        if len(docs) <= start + limit:
            return tuple(window), None
        last = window[-1]
        occurred, _ = self._doc_key(last)
        return tuple(window), IntentEventCursor(
            occurred_at=occurred,
            event_id=str(last["_id"]),
        )


class _FakeApplications:
    def __init__(self, sources=()):
        self.sources = tuple(sorted(sources, key=_application_position))
        self.calls = []
        self.raise_readiness = False
        self.raise_access = False
        self.raise_stored = False
        self.raise_conflict = False
        self.raise_conflict_on = None
        self.secured_job_id = JOB_ID

    async def _scope(self, recruiter_id, stream_id):
        if self.raise_conflict:
            raise ApplicationSourceConflictError("application source changed")
        if self.raise_readiness:
            raise ApplicationSourceReadinessError("application source not ready")
        if self.raise_access:
            raise ApplicationSourceAccessError("application source not authorized")
        if self.raise_stored:
            raise ApplicationSourceStoredDataError("invalid stored application source")
        return _SecuredScope(
            stream_id=str(stream_id),
            job_id=self.secured_job_id,
            fingerprint=(),
        )

    async def list_page(self, recruiter_id, stream_id, *, after=None, limit=100):
        self.calls.append((recruiter_id, stream_id, after, limit))
        if self.raise_conflict_on is not None and len(self.calls) >= self.raise_conflict_on:
            raise ApplicationSourceConflictError("application source changed")
        if self.raise_conflict:
            raise ApplicationSourceConflictError("application source changed")
        if self.raise_readiness:
            raise ApplicationSourceReadinessError("application source not ready")
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


class _FakeSavedFavorites:
    def __init__(self, mapping=None):
        self.mapping = dict(mapping or {})
        self.calls = []
        self.raise_readiness = False
        self.raise_repository_error = False

    async def saved_jobs_readiness(self):
        if self.raise_readiness:
            raise SharedFavoriteReadinessError("saved jobs not ready")
        if self.raise_repository_error:
            raise SharedFavoriteRepositoryError("saved jobs unreachable")

    async def get_saved_job(self, candidate_id, job_id, saved_job_id):
        self.calls.append((str(candidate_id), str(job_id), str(saved_job_id)))
        if self.raise_repository_error:
            raise SharedFavoriteRepositoryError("saved job read failed")
        return self.mapping.get((str(candidate_id), str(job_id), str(saved_job_id)))


class _FakeDiscovery:
    def __init__(self, pages=()):
        self.pages = list(pages)
        self.calls = []
        self.raise_conflict = False
        self.raise_readiness = False
        self.raise_access = False
        self.raise_stored = False

    async def list_page(self, stream_id, *, after=None, limit=100):
        self.calls.append((stream_id, after, limit))
        if self.raise_conflict:
            raise DiscoveryPoolConflictError("discovery pool changed")
        if self.raise_readiness:
            raise DiscoveryPoolReadinessError("discovery pool not ready")
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
    """Minimal subscriptable/attributable Mongo handle so Service wiring
    does not touch IO."""

    def __missing__(self, key):
        stub = _CollectionStub()
        self[key] = stub
        return stub

    def __getattr__(self, name):
        return self[name]


def _build_service(streams=None, sources=None, apps=None, saved=None,
                   discovery=None):
    service = StreamCandidateAggregationService(_FakeDB())
    service.streams = streams if streams is not None else _FakeStreams(_make_stream())
    service.sources = sources if sources is not None else _FakeSources(
        _opportunity_source()
    )
    service.applications = apps if apps is not None else _FakeApplications()
    service.saved_favorites = saved if saved is not None else _FakeSavedFavorites()
    service.discovery = discovery if discovery is not None else _FakeDiscovery()
    return service


class _EmptyScenario:
    """One build of an empty generation, fully isolated per use."""

    def build(self):
        service = _build_service()
        self.streams = service.streams
        self.sources = service.sources
        self.applications = service.applications
        self.saved_favorites = service.saved_favorites
        self.discovery = service.discovery
        return _run(service.build_generation(
            STREAM_ID,
            generation_id=GENERATION_ID,
            computed_at=_utc(500),
        ))


class TestBuiltGenerationIdentity:
    def test_identity_fields_match_scope(self):
        result = _EmptyScenario().build()
        assert result.stream_id == STREAM_ID
        assert int(result.stream_version) == STREAM_VERSION
        assert int(result.requirement_version) == REQUIREMENT_VERSION
        assert result.generation_id == GENERATION_ID
        assert result.role_dna_id == ROLE_DNA_ID
        assert int(result.role_dna_version) == ROLE_DNA_VERSION
        assert result.opportunity_spec_id == OPPORTUNITY_SPEC_ID
        assert int(result.opportunity_spec_version) == OPPORTUNITY_VERSION
        assert result.computed_at == _utc(500)
        assert result.computed_at.tzinfo is not None
        assert result.candidate_count == 0
        assert result.candidates == ()

    def test_invalid_identity_is_rejected(self):
        raw = _build_service()
        cases = (
            {"stream_id": "  ", "generation_id": GENERATION_ID,
             "computed_at": _utc(500)},
            {"stream_id": STREAM_ID, "generation_id": "  ",
             "computed_at": _utc(500)},
            {"stream_id": STREAM_ID, "generation_id": GENERATION_ID,
             "computed_at": datetime(2026, 1, 1, 12, 0, 0)},  # naive
            {"stream_id": STREAM_ID, "generation_id": GENERATION_ID,
             "computed_at": datetime(2026, 1, 1, 12, 0, 0, 1,
                                     tzinfo=timezone.utc)},  # sub-ms
        )
        for kwargs in cases:
            with pytest.raises(ValueError) as exc:
                _run(raw.build_generation(**kwargs))
            assert str(exc.value) == "invalid stream candidate generation identity"

    def test_generation_construction_enforces_unique_ordered_candidates(self):
        cand = StreamCandidate(
            stream_id=STREAM_ID, stream_version=STREAM_VERSION,
            requirement_version=REQUIREMENT_VERSION, generation_id=GENERATION_ID,
            candidate_id="cand-a", role_dna_id=ROLE_DNA_ID,
            role_dna_version=ROLE_DNA_VERSION,
            opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            opportunity_spec_version=OPPORTUNITY_VERSION,
            application_evidence=ApplicationEvidence(
                application_id="app-x", status="submitted", applied_at=_utc(500),
            ),
            computed_at=_utc(500),
        )
        other = StreamCandidate(
            stream_id=STREAM_ID, stream_version=STREAM_VERSION,
            requirement_version=REQUIREMENT_VERSION, generation_id=GENERATION_ID,
            candidate_id="cand-b", role_dna_id=ROLE_DNA_ID,
            role_dna_version=ROLE_DNA_VERSION,
            opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            opportunity_spec_version=OPPORTUNITY_VERSION,
            application_evidence=ApplicationEvidence(
                application_id="app-y", status="submitted", applied_at=_utc(500),
            ),
            computed_at=_utc(500),
        )
        with pytest.raises(ValueError, match="ordered and unique"):
            BuiltStreamCandidateGeneration(
                stream_id=STREAM_ID, stream_version=STREAM_VERSION,
                requirement_version=REQUIREMENT_VERSION, generation_id=GENERATION_ID,
                role_dna_id=ROLE_DNA_ID, role_dna_version=ROLE_DNA_VERSION,
                opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                opportunity_spec_version=OPPORTUNITY_VERSION,
                candidates=(other, cand),
                computed_at=_utc(500),
                scope_guard=_make_scope_guard(),
            )
        with pytest.raises(ValueError, match="ordered and unique"):
            BuiltStreamCandidateGeneration(
                stream_id=STREAM_ID, stream_version=STREAM_VERSION,
                requirement_version=REQUIREMENT_VERSION, generation_id=GENERATION_ID,
                role_dna_id=ROLE_DNA_ID, role_dna_version=ROLE_DNA_VERSION,
                opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                opportunity_spec_version=OPPORTUNITY_VERSION,
                candidates=(cand, cand),
                computed_at=_utc(500),
                scope_guard=_make_scope_guard(),
            )
        with pytest.raises(ValueError, match="scope mismatch"):
            BuiltStreamCandidateGeneration(
                stream_id=STREAM_ID, stream_version=STREAM_VERSION,
                requirement_version=REQUIREMENT_VERSION, generation_id=GENERATION_ID,
                role_dna_id=ROLE_DNA_ID, role_dna_version=ROLE_DNA_VERSION,
                opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                opportunity_spec_version=OPPORTUNITY_VERSION,
                candidates=(
                    StreamCandidate(
                        stream_id=STREAM_ID, stream_version=STREAM_VERSION,
                        requirement_version=REQUIREMENT_VERSION,
                        generation_id="other-generation",
                        candidate_id="cand-a", role_dna_id=ROLE_DNA_ID,
                        role_dna_version=ROLE_DNA_VERSION,
                        opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                        opportunity_spec_version=OPPORTUNITY_VERSION,
                        application_evidence=ApplicationEvidence(
                            application_id="app-x", status="submitted",
                            applied_at=_utc(500),
                        ),
                        computed_at=_utc(500),
                    ),
                ),
                computed_at=_utc(500),
                scope_guard=_make_scope_guard(),
            )

    def test_errors_are_redacted_fixed_messages(self):
        assert ACCESS_MSG == "stream candidate aggregation not authorized"
        assert READINESS_MSG == "stream candidate aggregation storage is not ready"
        assert STORED_MSG == "invalid stored stream candidate source"
        assert CONFLICT_MSG == "stream candidate aggregation scope changed"
        forbidden = ["cand-", "recruiter-", "job-", "spec-", "@", GENERATION_ID]
        for message in (ACCESS_MSG, READINESS_MSG, STORED_MSG, CONFLICT_MSG):
            for token in forbidden:
                assert token not in message


class TestAccessAndReadiness:
    def test_missing_stream_is_not_authorized(self):
        service = _build_service(streams=_FakeStreams())
        with pytest.raises(StreamCandidateAggregationAccessError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == ACCESS_MSG

    def test_inactive_stream_is_not_authorized(self):
        for state, version in (
            (TalentStreamState.DRAFT, 1),
            (TalentStreamState.CLOSED, 3),
        ):
            service = _build_service(
                streams=_FakeStreams(_make_stream(state, version=version))
            )
            with pytest.raises(StreamCandidateAggregationAccessError) as exc:
                _run(service.build_generation(
                    STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
                ))
            assert str(exc.value) == ACCESS_MSG

    def test_stream_readiness_failure_maps_to_readiness(self):
        streams = _FakeStreams(_make_stream())
        streams.readiness_error = True
        service = _build_service(streams=streams)
        with pytest.raises(StreamCandidateAggregationReadinessError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == READINESS_MSG

    def test_stream_stored_data_error_maps_to_stored(self):
        streams = _FakeStreams(_make_stream())
        streams.stored_data_error = True
        service = _build_service(streams=streams)
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_missing_or_inconsistent_opportunity_fails_closed(self):
        sources = _FakeSources(_opportunity_source())
        sources.raise_stored_data = True
        service = _build_service(sources=sources)
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

        wrong = OpportunitySpecificationSource(
            opportunity_spec_id="spec-other",
            version=OPPORTUNITY_VERSION,
            source_job_id=JOB_ID,
            source_ref=SOURCE_REF,
            version_provenance_ref=SOURCE_REF,
        )
        service2 = _build_service(sources=_FakeSources(wrong))
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service2.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_scope_change_during_revalidation_is_conflict(self):
        changed = _make_stream()
        changed = TalentStream(
            stream_id=changed.stream_id,
            version=changed.version,
            recruiting_actor_context=changed.recruiting_actor_context,
            requirement_snapshot=StreamRequirementSnapshot(
                role_dna=RoleDNARef(role_dna_id="role-dna-2",
                                    version=ROLE_DNA_VERSION),
                opportunity_spec=OpportunitySpecificationRef(
                    opportunity_spec_id=OPPORTUNITY_SPEC_ID,
                    version=OPPORTUNITY_VERSION,
                ),
                requirement_version=REQUIREMENT_VERSION,
                captured_at=_utc(0),
            ),
            state=changed.state,
            created_at=changed.created_at,
            updated_at=changed.updated_at,
            history=changed.history,
        )
        service = _build_service(streams=_FakeStreams(_make_stream(), changed))
        with pytest.raises(StreamCandidateAggregationConflictError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == CONFLICT_MSG

    def test_opportunity_change_during_revalidation_is_conflict(self):
        other = OpportunitySpecificationSource(
            opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            version=OPPORTUNITY_VERSION,
            source_job_id="job-other",
            source_ref=SOURCE_REF,
            version_provenance_ref=SOURCE_REF,
        )
        sources = _FakeSources(_opportunity_source())
        sources.opportunity_sequence = [other]
        service = _build_service(sources=sources)
        with pytest.raises(StreamCandidateAggregationConflictError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == CONFLICT_MSG

    def test_final_application_check_conflict_is_conflict(self):
        apps = _FakeApplications([_application("app-1", "cand-a", ms=30)])
        apps.raise_conflict_on = 2  # main read ok, final check fails
        service = _build_service(apps=apps)
        with pytest.raises(StreamCandidateAggregationConflictError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == CONFLICT_MSG


class TestBuildSources:
    def _service(self, apps=(), events=(), saved=None, discovery=()):
        sources = _FakeSources(_opportunity_source())
        sources.events = dict(events)
        return _build_service(
            streams=_FakeStreams(_make_stream()),
            sources=sources,
            apps=_FakeApplications(list(apps)),
            saved=_FakeSavedFavorites(saved or {}),
            discovery=_FakeDiscovery(list(discovery)),
        )

    def _assignment_events(self):
        return {
            "B4": (_make_b4_event("cand-a", JOB_ID, _utc(100)),
                   _make_b4_event("cand-b", JOB_ID, _utc(110))),
            "B5_S": (_make_b5_share_event("cand-c", JOB_ID, "corr-c", _utc(120)),),
            "B5_W": (_make_b5_withdraw_event("cand-d", JOB_ID, "corr-d",
                                             "cause-d", _utc(130))),
        }

    def _events_by_type(self, events):
        mapping = {}
        for event in events:
            key = str(event.event_type)
            mapping.setdefault(key, []).append(event_to_document(event))
        return mapping

    def test_application_evidence(self):
        service = self._service(
            apps=[_application("app-1", "cand-a", ms=30, status=ApplicationStatus.REVIEWED)],
        )
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result.candidate_count == 1
        cand = result.candidates[0]
        assert str(cand.candidate_id) == "cand-a"
        assert cand.application_evidence == ApplicationEvidence(
            application_id="app-1", status="reviewed", applied_at=_utc(30),
        )
        assert cand.declared_interest_evidence is None
        assert cand.shared_favorite_evidence is None
        assert cand.discovery_evidence is None
        assert cand.professional_match_summary is None
        assert cand.opportunity_fit_summary is None
        assert cand.computed_at == _utc(500)

    def test_application_job_mismatch_fails_closed(self):
        service = self._service(
            apps=[_application("app-1", "cand-a", ms=30, job_id="job-other")],
        )
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_application_pagination_merges_pages(self):
        many = [
            _application(f"app-{i:03d}", f"cand-{i:03d}", ms=i)
            for i in range(MAX_APPLICATION_SOURCE_PAGE_SIZE + 7)
        ]
        service = self._service(apps=many)
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result.candidate_count == MAX_APPLICATION_SOURCE_PAGE_SIZE + 7
        ids = [str(c.candidate_id) for c in result.candidates]
        assert ids == sorted(ids)
        assert service.applications.calls[-1][3] == 1  # final revalidation check

    def test_declared_interest_evidence(self):
        events = self._events_by_type(self._assignment_events()["B4"])
        service = self._service(events=events)
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result.candidate_count == 2
        first = result.candidates[0]
        assert str(first.candidate_id) == "cand-a"
        assert first.declared_interest_evidence is not None
        assert first.declared_interest_evidence.occurred_at == _utc(100)
        assert str(first.declared_interest_evidence.event_id).startswith(
            "ts-b4-event-v1:sha256:"
        )

    def test_declared_interest_is_deterministic_regardless_of_doc_order(self):
        b4 = self._assignment_events()["B4"]
        docs = self._events_by_type(b4)
        order_a = self._service(events=docs)
        order_b = self._service(events={k: list(reversed(v)) for k, v in docs.items()})
        result_a = _run(order_a.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        result_b = _run(order_b.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result_a == result_b

    def test_shared_favorite_validated_keeps_representative(self):
        share1 = _make_b5_share_event("cand-c", JOB_ID, "corr-1", _utc(120),
                                      caller_idempotency_key="key-one")
        share2 = _make_b5_share_event("cand-c", JOB_ID, "corr-2", _utc(125),
                                      caller_idempotency_key="key-two")
        events = self._events_by_type((share1, share2))
        saved = {
            ("cand-c", JOB_ID, "corr-1"): _saved_job("cand-c", "corr-1"),
            ("cand-c", JOB_ID, "corr-2"): _saved_job("cand-c", "corr-2"),
        }
        service = self._service(events=events, saved=saved)
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result.candidate_count == 1
        cand = result.candidates[0]
        assert cand.shared_favorite_evidence is not None
        assert cand.shared_favorite_evidence.correlation_id == "corr-2"
        assert cand.shared_favorite_evidence.occurred_at == _utc(125)
        assert cand.declared_interest_evidence is None

    def test_two_active_shares_same_correlation_representative_is_latest(self):
        share1 = _make_b5_share_event("cand-c", JOB_ID, "corr-same", _utc(120),
                                      caller_idempotency_key="key-one")
        share2 = _make_b5_share_event("cand-c", JOB_ID, "corr-same", _utc(125),
                                      caller_idempotency_key="key-two")
        events = self._events_by_type((share1, share2))
        saved = {("cand-c", JOB_ID, "corr-same"): _saved_job("cand-c", "corr-same")}
        service = self._service(events=events, saved=saved)
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result.candidate_count == 1
        cand = result.candidates[0]
        assert cand.shared_favorite_evidence is not None
        assert cand.shared_favorite_evidence.correlation_id == "corr-same"
        assert cand.shared_favorite_evidence.occurred_at == _utc(125)
        assert str(cand.shared_favorite_evidence.event_id) == str(share2.event_id)

    def test_withdrawal_of_first_same_correlation_share_leaves_second_as_representative(self):
        share1 = _make_b5_share_event("cand-c", JOB_ID, "corr-same", _utc(120),
                                      caller_idempotency_key="key-one")
        share2 = _make_b5_share_event("cand-c", JOB_ID, "corr-same", _utc(125),
                                      caller_idempotency_key="key-two")
        withdraw = _make_b5_withdraw_event("cand-c", JOB_ID, "corr-same",
                                           str(share1.event_id), _utc(130))
        events = self._events_by_type((share1, share2, withdraw))
        saved = {("cand-c", JOB_ID, "corr-same"): _saved_job("cand-c", "corr-same")}
        service = self._service(events=events, saved=saved)
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result.candidate_count == 1
        cand = result.candidates[0]
        assert cand.shared_favorite_evidence is not None
        assert cand.shared_favorite_evidence.occurred_at == _utc(125)
        assert str(cand.shared_favorite_evidence.event_id) == str(share2.event_id)

    def test_withdrawal_of_second_same_correlation_share_leaves_first_as_representative(self):
        share1 = _make_b5_share_event("cand-c", JOB_ID, "corr-same", _utc(120),
                                      caller_idempotency_key="key-one")
        share2 = _make_b5_share_event("cand-c", JOB_ID, "corr-same", _utc(125),
                                      caller_idempotency_key="key-two")
        withdraw = _make_b5_withdraw_event("cand-c", JOB_ID, "corr-same",
                                           str(share2.event_id), _utc(130))
        events = self._events_by_type((share1, share2, withdraw))
        saved = {("cand-c", JOB_ID, "corr-same"): _saved_job("cand-c", "corr-same")}
        service = self._service(events=events, saved=saved)
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result.candidate_count == 1
        cand = result.candidates[0]
        assert cand.shared_favorite_evidence is not None
        assert cand.shared_favorite_evidence.occurred_at == _utc(120)
        assert str(cand.shared_favorite_evidence.event_id) == str(share1.event_id)

    def test_withdrawal_wrong_correlation_with_valid_causation_fails_closed(self):
        share = _make_b5_share_event("cand-c", JOB_ID, "corr-same", _utc(120))
        withdraw = _make_b5_withdraw_event("cand-c", JOB_ID, "corr-other",
                                           str(share.event_id), _utc(130))
        events = self._events_by_type((share, withdraw))
        saved = {("cand-c", JOB_ID, "corr-same"): _saved_job("cand-c", "corr-same")}
        service = self._service(events=events, saved=saved)
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_share_with_cancelled_saved_job_is_dropped(self):
        share = _make_b5_share_event("cand-x", JOB_ID, "corr-x", _utc(120))
        events = self._events_by_type((share,))
        service = self._service(events=events)  # no saved job for corr-x
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result.candidate_count == 0

    def test_share_with_stale_or_mismatched_saved_job_fails_closed(self):
        share = _make_b5_share_event("cand-y", JOB_ID, "corr-y", _utc(120))
        events = self._events_by_type((share,))
        bad_cases = (
            _saved_job("cand-y", "corr-y", doc_id="corr-other"),
            _saved_job("cand-y", "corr-y", user_id="other-user"),
            _saved_job("cand-y", "corr-y", updated_ms=40, created_ms=60),
            {**SAVED_JOB_TEMPLATE, "created_at": "not-a-datetime"},
        )
        for saved in bad_cases:
            service = self._service(events=events,
                                    saved={("cand-y", JOB_ID, "corr-y"): saved})
            with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
                _run(service.build_generation(
                    STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
                ))
            assert str(exc.value) == STORED_MSG

    def test_share_with_pending_withdrawal_is_excluded(self):
        share = _make_b5_share_event("cand-e", JOB_ID, "corr-e", _utc(120))
        withdraw = _make_b5_withdraw_event("cand-e", JOB_ID, "corr-e",
                                           str(share.event_id), _utc(130))
        events = self._events_by_type((share, withdraw))
        saved = {("cand-e", JOB_ID, "corr-e"): _saved_job("cand-e", "corr-e")}
        service = self._service(events=events, saved=saved)
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result.candidate_count == 0

    def test_saved_jobs_readiness_failure_maps_to_readiness(self):
        share = _make_b5_share_event("cand-z", JOB_ID, "corr-z", _utc(120))
        events = self._events_by_type((share,))
        service = self._service(events=events)
        service.saved_favorites.raise_readiness = True
        with pytest.raises(StreamCandidateAggregationReadinessError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == READINESS_MSG

    def test_saved_job_read_error_maps_to_stored(self):
        share = _make_b5_share_event("cand-z", JOB_ID, "corr-z", _utc(120))
        events = self._events_by_type((share,))
        service = self._service(events=events)
        service.saved_favorites.raise_repository_error = True
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_discovery_evidence_and_summaries(self):
        service = self._service(discovery=[_discovery_page(_discovery_item("cand-d1"))])
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result.candidate_count == 1
        cand = result.candidates[0]
        assert str(cand.candidate_id) == "cand-d1"
        assert cand.discovery_evidence == DiscoveryEvidence(
            candidate_preferences_version=5, updated_at=_utc(402),
        )
        assert cand.professional_match_summary == ProfessionalMatchSummary(
            candidate_profile_version=3,
            role_dna_version=ROLE_DNA_VERSION,
            match_engine_version="match-engine-v1",
            professional_match_score=80,
            evidence_coverage=70,
            computed_at=_utc(400),
        )
        assert cand.opportunity_fit_summary == OpportunityFitSummary(
            candidate_preferences_version=5,
            opportunity_spec_version=OPPORTUNITY_VERSION,
            fit_engine_version="opportunity-fit-engine-v1",
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
            evidence_coverage=60,
            computed_at=_utc(401),
        )
        assert cand.application_evidence is None

    def test_discovery_fit_mismatch_fails_closed(self):
        item = DiscoveryPoolCandidate(
            candidate_id="cand-d2",
            discovery_state=DiscoveryState(
                candidate_id="cand-d2", enabled=True,
                allow_compatible_opportunities=False, ask_before_reveal=False,
                anonymous_only=False, preferences_version=5, updated_at=_utc(402),
            ),
            professional_match=_match("cand-d2"),
            opportunity_fit=_fit("cand-d2", spec_id="spec-other"),
        )
        service = self._service(discovery=[_discovery_page(item)])
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_discovery_pagination_merges_and_orders(self):
        item_a = _discovery_item("cand-p1")
        item_b = _discovery_item("cand-p2")
        item_c = _discovery_item("cand-p3")
        page1 = _discovery_page(item_a, next_after="cand-p1")
        page2 = _discovery_page(item_b, next_after="cand-p2")
        page3 = _discovery_page(item_c)
        service = self._service(discovery=[page1, page2, page3])
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        ids = [str(c.candidate_id) for c in result.candidates]
        assert ids == ["cand-p1", "cand-p2", "cand-p3"]

    def test_discovery_non_progress_cursor_fails_closed(self):
        item_a = _discovery_item("cand-q1")
        page1 = _discovery_page(item_a, next_after="cand-q1")
        page2 = _discovery_page(item_a, next_after="cand-q1")
        service = self._service(discovery=[page1, page2])
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_discovery_duplicate_candidate_fails_closed(self):
        item = _discovery_item("cand-r1")
        page1 = _discovery_page(item, next_after="cand-r1")
        page2 = _discovery_page(item)
        service = self._service(discovery=[page1, page2])
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_discovery_errors_map_consistent(self):
        service = self._service()
        service.discovery.raise_conflict = True
        with pytest.raises(StreamCandidateAggregationConflictError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == CONFLICT_MSG

        service = self._service()
        service.discovery.raise_readiness = True
        with pytest.raises(StreamCandidateAggregationReadinessError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == READINESS_MSG

        service = self._service()
        service.discovery.raise_stored = True
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_intent_readiness_failure_maps_to_readiness(self):
        service = self._service()
        service.sources.raise_readiness = True
        with pytest.raises(StreamCandidateAggregationReadinessError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == READINESS_MSG

    def test_intent_duplicate_event_fails_closed(self):
        b4 = _make_b4_event("cand-a", JOB_ID, _utc(100),
                            caller_idempotency_key="dup-key")
        doc = event_to_document(b4)
        events = {str(B4_EVENT_TYPE): [doc, dict(doc)]}
        service = self._service(events=events)
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_intent_document_for_other_job_fails_closed(self):
        b4 = _make_b4_event("cand-a", "job-other", _utc(100))
        events = self._events_by_type((b4,))
        service = self._service(events=events)
        with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
            _run(service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            ))
        assert str(exc.value) == STORED_MSG

    def test_fusion_sorts_candidates_and_keeps_all_sources(self):
        apps = [
            _application("app-1", "cand-aaa", ms=30),
            _application("app-2", "cand-ccc", ms=31),
        ]
        b4 = _make_b4_event("cand-bbb", JOB_ID, _utc(100))
        share = _make_b5_share_event("cand-ddd", JOB_ID, "corr-ddd", _utc(120))
        events = self._events_by_type((b4, share))
        saved = {
            ("cand-ddd", JOB_ID, "corr-ddd"): _saved_job("cand-ddd", "corr-ddd"),
        }
        discovery_items = [
            _discovery_item("cand-aaa"),
            _discovery_item("cand-eee"),
        ]
        service = self._service(apps=apps, events=events, saved=saved,
                                discovery=[_discovery_page(*discovery_items)])
        result = _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        ids = [str(c.candidate_id) for c in result.candidates]
        assert ids == sorted(["cand-aaa", "cand-bbb", "cand-ccc", "cand-ddd", "cand-eee"])
        by_id = {str(c.candidate_id): c for c in result.candidates}
        assert by_id["cand-aaa"].application_evidence is not None
        assert by_id["cand-aaa"].discovery_evidence is not None
        assert by_id["cand-bbb"].declared_interest_evidence is not None
        assert by_id["cand-ccc"].application_evidence is not None
        assert by_id["cand-ddd"].shared_favorite_evidence is not None
        assert by_id["cand-eee"].discovery_evidence is not None
        for candidate in result.candidates:
            assert candidate.computed_at == _utc(500)

    def test_build_is_deterministic_and_immutable(self):
        first = self._service()
        second = self._service()
        result_first = _run(first.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        result_second = _run(second.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))
        assert result_first == result_second
        with pytest.raises(AttributeError):
            result_first.candidates = ()

    def test_concurrent_builds_are_consistent(self):
        async def build_once():
            service = self._service()
            return await service.build_generation(
                STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
            )

        async def gather():
            return await asyncio.gather(build_once(), build_once())

        r1, r2 = _run(gather())
        assert r1 == r2


class TestReadOnlySurface:
    _MODULES = ("stream_candidate_aggregation.py", "stream_candidate_source_repository.py")
    _FORBIDDEN = {
        "insert_one", "insert_many", "insert_one_raw", "insert_many_raw",
        "bulk_write", "update_one", "update_many", "replace_one",
        "find_one_and_update", "find_one_and_replace", "find_one_and_delete",
        "delete_one", "delete_many", "create_index", "create_collection",
        "ensure_index", "drop", "drop_index", "drop_indexes", "drop_collection",
        "rename", "aggregate", "distinct", "map_reduce", "start_session",
    }

    def test_step3_modules_never_write(self):
        violations = []
        base = Path(__file__).resolve().parent.parent / "domains" / "talent_stream"
        for module in self._MODULES:
            path = base / module
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in self._FORBIDDEN:
                    violations.append((module, node.lineno, node.attr))
        assert violations == []

    def test_source_repository_has_no_write_api(self):
        from domains.talent_stream import stream_candidate_source_repository as module
        public = [name for name in dir(module) if not name.startswith("_")]
        assert "StreamCandidateSourceRepository" in public
        write_names = [name for name in public if name.startswith(("insert", "update", "delete"))]
        assert write_names == []


class TestGenerationScopeCurrent:
    """STEP 4 revalidation must fail on structural divergences that leave the
    stream/requirement/opportunity versions unchanged."""

    def _built(self, service):
        return _run(service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        ))

    def test_unchanged_scope_is_accepted(self):
        service = _build_service()
        built = self._built(service)
        _run(service.assert_generation_scope_current(built))
        assert built.scope_guard is not None
        assert built.scope_guard.recruiting_actor_context == \
            _make_stream().recruiting_actor_context

    def test_actor_mutation_same_version_is_conflict(self):
        stream = _make_stream()
        service = _build_service(streams=_FakeStreams(stream))
        built = self._built(service)
        changed = dataclasses.replace(
            stream,
            recruiting_actor_context=RecruitingActorContext(
                recruiter_user_id=RECRUITER_ID,
                requesting_organization_id="org-r-other",
                hiring_company_id="org-h-1",
                mandate_id=None,
            ),
        )
        service.streams = _FakeStreams(changed)
        with pytest.raises(StreamCandidateAggregationConflictError) as exc:
            _run(service.assert_generation_scope_current(built))
        assert str(exc.value) == CONFLICT_MSG

    def test_source_job_mutation_same_versions_is_conflict(self):
        service = _build_service()
        built = self._built(service)
        changed = OpportunitySpecificationSource(
            opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            version=OPPORTUNITY_VERSION,
            source_job_id="job-other",
            source_ref=SOURCE_REF,
            version_provenance_ref=SOURCE_REF,
        )
        service.sources = _FakeSources(changed)
        with pytest.raises(StreamCandidateAggregationConflictError) as exc:
            _run(service.assert_generation_scope_current(built))
        assert str(exc.value) == CONFLICT_MSG

    def test_source_ref_mutation_is_conflict(self):
        service = _build_service()
        built = self._built(service)
        changed = OpportunitySpecificationSource(
            opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            version=OPPORTUNITY_VERSION,
            source_job_id=JOB_ID,
            source_ref="source-ref-other",
            version_provenance_ref=SOURCE_REF,
        )
        service.sources = _FakeSources(changed)
        with pytest.raises(StreamCandidateAggregationConflictError) as exc:
            _run(service.assert_generation_scope_current(built))
        assert str(exc.value) == CONFLICT_MSG

    def test_version_provenance_ref_mutation_is_conflict(self):
        service = _build_service()
        built = self._built(service)
        changed = OpportunitySpecificationSource(
            opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            version=OPPORTUNITY_VERSION,
            source_job_id=JOB_ID,
            source_ref=SOURCE_REF,
            version_provenance_ref="source-ref-other",
        )
        service.sources = _FakeSources(changed)
        with pytest.raises(StreamCandidateAggregationConflictError) as exc:
            _run(service.assert_generation_scope_current(built))
        assert str(exc.value) == CONFLICT_MSG

    def test_secured_job_drift_is_conflict(self):
        service = _build_service()
        built = self._built(service)
        service.applications.secured_job_id = "job-other"
        with pytest.raises(StreamCandidateAggregationConflictError) as exc:
            _run(service.assert_generation_scope_current(built))
        assert str(exc.value) == CONFLICT_MSG