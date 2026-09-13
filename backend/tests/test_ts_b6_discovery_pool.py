"""TS-B6 G0: hermetic Discovery Pool contracts and orchestration."""
import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from domains.matching.models import ProfessionalMatchResult
from domains.matching.opportunity_fit_models import (
    HardEligibilityState,
    OpportunityFitResult,
    OpportunityFitState,
)
from domains.matching.service import MatchInputNotFoundError
from domains.shared.ids import (
    CandidateId,
    HiringCompanyId,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import EngineVersion, EntityVersion
from domains.talent_stream.contracts import (
    OpportunitySpecificationRef,
    RecruitingActorContext,
    RoleDNARef,
    StreamRequirementSnapshot,
)
from domains.talent_stream.discovery_pool_models import DiscoveryPoolCursor
from domains.talent_stream.discovery_pool_repository import (
    DiscoveryPoolReadinessError,
    DiscoveryPoolRepository,
)
from domains.talent_stream.discovery_pool_service import (
    DiscoveryPoolAccessError,
    DiscoveryPoolConflictError,
    DiscoveryPoolService,
    DiscoveryPoolStoredDataError,
    MAX_DISCOVERY_POOL_SCAN_PAGE_SIZE,
)
from domains.talent_stream.stream_models import (
    StreamCommandHistoryEntry,
    StreamCommandKind,
    TalentStream,
    TalentStreamState,
)
from domains.talent_stream.stream_repository import TalentStreamStoredDataError


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 14, 10, 0, tzinfo=timezone.utc)


def make_stream(*, state=TalentStreamState.ACTIVE, version=None, role_version=3, spec_version=4):
    create = StreamCommandHistoryEntry(
        "create", "fingerprint-create", StreamCommandKind.CREATE, None,
        TalentStreamState.DRAFT, EntityVersion(1), NOW,
    )
    history = (create,)
    updated = NOW
    if state is TalentStreamState.ACTIVE:
        history += (StreamCommandHistoryEntry(
            "activate", "fingerprint-activate", StreamCommandKind.ACTIVATE,
            TalentStreamState.DRAFT, TalentStreamState.ACTIVE, EntityVersion(2), NOW,
        ),)
    elif state is TalentStreamState.CLOSED:
        history += (StreamCommandHistoryEntry(
            "close", "fingerprint-close", StreamCommandKind.CLOSE,
            TalentStreamState.DRAFT, TalentStreamState.CLOSED, EntityVersion(2), NOW,
        ),)
    if version is None:
        version = len(history)
    return TalentStream(
        stream_id=TalentStreamId("stream-1"),
        version=EntityVersion(version),
        recruiting_actor_context=RecruitingActorContext(
            RecruiterUserId("recruiter-1"), OrganizationId("org-1"),
            HiringCompanyId("company-1"), None,
        ),
        requirement_snapshot=StreamRequirementSnapshot(
            RoleDNARef(RoleDNAId("role-1"), EntityVersion(role_version)),
            OpportunitySpecificationRef(OpportunitySpecId("spec-1"), EntityVersion(spec_version)),
            EntityVersion(5), NOW,
        ),
        state=state,
        created_at=NOW,
        updated_at=updated,
        history=history,
    )


def preference(candidate="candidate-1", *, version=1, search_state="passive", enabled=True, allow=True):
    return {
        "_id": f"candidate_preferences:{candidate}",
        "candidate_id": candidate,
        "version": version,
        "search_state": search_state,
        "discovery": {
            "enabled": enabled,
            "allow_compatible_opportunities": allow,
            "ask_before_reveal": True,
            "anonymous_only": True,
        },
        "excluded_company_ids": [],
        "updated_at": NOW.replace(tzinfo=None),
    }


def user(candidate="candidate-1", *, user_type="candidate", active=True):
    return {"_id": candidate, "user_type": user_type, "is_active": active}


def match(candidate="candidate-1", *, score=7, coverage=3):
    return ProfessionalMatchResult(
        CandidateId(candidate), EntityVersion(9), RoleDNAId("role-1"), EntityVersion(3),
        EngineVersion("match-v1"), score, coverage, (), NOW,
    )


def fit(candidate="candidate-1", *, hard=HardEligibilityState.ELIGIBLE,
        state=OpportunityFitState.UNRESOLVED, version=1):
    return OpportunityFitResult(
        CandidateId(candidate), EntityVersion(version), OpportunitySpecId("spec-1"),
        EntityVersion(4), EngineVersion("fit-v1"), hard, state, 0, (), NOW,
    )


class FakeRepository:
    def __init__(self, documents=(), *, stream=None):
        self.documents = list(documents)
        self.current = {doc.get("candidate_id"): deepcopy(doc) for doc in documents}
        self.users = {cid: user(cid) for cid in self.current if isinstance(cid, str)}
        self.streams = [stream or make_stream()]
        self.calls = []

    async def readiness(self):
        self.calls.append(("readiness",))

    async def get_stream(self, stream_id):
        self.calls.append(("get_stream", stream_id))
        value = self.streams.pop(0) if len(self.streams) > 1 else self.streams[0]
        if isinstance(value, Exception):
            raise value
        return value

    async def list_preferences(self, *, after_candidate_id, limit):
        self.calls.append(("list_preferences", after_candidate_id, limit))
        docs = sorted(self.documents, key=lambda item: str(item.get("candidate_id")))
        if after_candidate_id is not None:
            docs = [doc for doc in docs if doc.get("candidate_id") > after_candidate_id]
        return deepcopy(docs[:limit])

    async def get_preferences(self, candidate_id):
        self.calls.append(("get_preferences", candidate_id))
        value = self.current.get(candidate_id)
        return deepcopy(value)

    async def get_user(self, candidate_id):
        self.calls.append(("get_user", candidate_id))
        return deepcopy(self.users.get(candidate_id))


class FakeMatch:
    def __init__(self):
        self.calls = []
        self.results = {}

    async def compute(self, candidate_id, role_id, role_version):
        candidate = str(candidate_id)
        self.calls.append((candidate, str(role_id), int(role_version)))
        value = self.results.get(candidate, match(candidate))
        if isinstance(value, Exception):
            raise value
        return value


class FakeFit:
    def __init__(self):
        self.calls = []
        self.results = {}

    async def compute(self, candidate_id, spec_id, spec_version, *, candidate_preferences_version):
        candidate = str(candidate_id)
        self.calls.append((candidate, str(spec_id), int(spec_version), int(candidate_preferences_version)))
        value = self.results.get(candidate, fit(candidate, version=int(candidate_preferences_version)))
        if isinstance(value, Exception):
            raise value
        return value


def service(repository):
    instance = DiscoveryPoolService.__new__(DiscoveryPoolService)
    instance.repository = repository
    instance.match_service = FakeMatch()
    instance.fit_service = FakeFit()
    return instance


@pytest.mark.asyncio
@pytest.mark.parametrize("search_state", ["active", "passive", "paused"])
async def test_nominal_discovery_keeps_search_state_orthogonal_and_preserves_results(search_state):
    repo = FakeRepository([preference(search_state=search_state)])
    subject = service(repo)
    page = await subject.list_page("stream-1")
    assert page.scanned_count == 1 and page.next_cursor is None
    assert [str(item.candidate_id) for item in page.items] == ["candidate-1"]
    assert page.items[0].professional_match.professional_match_score == 7
    assert page.items[0].professional_match.evidence_coverage == 3
    assert page.items[0].opportunity_fit.opportunity_fit_state is OpportunityFitState.UNRESOLVED
    assert subject.match_service.calls == [("candidate-1", "role-1", 3)]
    assert subject.fit_service.calls == [("candidate-1", "spec-1", 4, 1)]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,allow", [(False, False), (True, False)])
async def test_discovery_requires_both_explicit_controls(enabled, allow):
    doc = preference(enabled=enabled, allow=allow)
    if not enabled:
        doc["discovery"]["ask_before_reveal"] = False
        doc["discovery"]["anonymous_only"] = False
    subject = service(FakeRepository([doc]))
    assert (await subject.list_page("stream-1")).items == ()
    assert subject.match_service.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [TalentStreamState.DRAFT, TalentStreamState.CLOSED])
async def test_non_active_stream_is_refused(state):
    with pytest.raises(DiscoveryPoolAccessError):
        await service(FakeRepository([], stream=make_stream(state=state))).list_page("stream-1")


@pytest.mark.asyncio
async def test_absent_and_malformed_stream_fail_closed():
    repo = FakeRepository([])
    repo.streams = [None]
    with pytest.raises(DiscoveryPoolAccessError):
        await service(repo).list_page("stream-1")
    repo.streams = [TalentStreamStoredDataError("bad")]
    with pytest.raises(DiscoveryPoolStoredDataError):
        await service(repo).list_page("stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 101, True, False, 1.0, "1"])
async def test_limit_is_strict_bounded_integer(limit):
    assert MAX_DISCOVERY_POOL_SCAN_PAGE_SIZE == 100
    with pytest.raises(ValueError):
        await service(FakeRepository([])).list_page("stream-1", limit=limit)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,bad", [
    ("enabled", 1), ("enabled", 0), ("enabled", "true"), ("enabled", "false"),
    ("enabled", {}), ("enabled", []), ("enabled", None),
    ("allow_compatible_opportunities", 1), ("allow_compatible_opportunities", 0),
    ("allow_compatible_opportunities", "true"), ("allow_compatible_opportunities", "false"),
    ("allow_compatible_opportunities", {}), ("allow_compatible_opportunities", []),
    ("allow_compatible_opportunities", None),
])
async def test_critical_discovery_boole_are_exact(field, bad):
    doc = preference()
    doc["discovery"][field] = bad
    with pytest.raises(DiscoveryPoolStoredDataError):
        await service(FakeRepository([doc])).list_page("stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda doc: doc.update(_id="wrong"),
    lambda doc: doc.update(version=True),
    lambda doc: doc.update(version=1.0),
    lambda doc: doc.update(updated_at="today"),
    lambda doc: doc.update(excluded_company_ids=[1]),
    lambda doc: doc.update(search_state="unknown"),
    lambda doc: doc.pop("excluded_company_ids"),
])
async def test_malformed_a2_document_refuses_the_page(mutation):
    doc = preference()
    mutation(doc)
    with pytest.raises(DiscoveryPoolStoredDataError):
        await service(FakeRepository([doc])).list_page("stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("replacement", [
    None,
    {"_id": "candidate-1", "user_type": "candidate", "is_active": False},
    {"_id": "candidate-1", "user_type": "employer", "is_active": True},
    {"_id": "candidate-1", "user_type": "admin", "is_active": True},
    {"_id": "candidate-1", "user_type": "partner", "is_active": True},
    {"_id": "other", "user_type": "candidate", "is_active": True},
])
async def test_only_current_active_candidate_users_are_returned(replacement):
    repo = FakeRepository([preference()])
    repo.users["candidate-1"] = replacement
    page = await service(repo).list_page("stream-1")
    assert page.items == () and page.scanned_count == 1


@pytest.mark.asyncio
async def test_missing_or_malformed_profile_is_not_returned_and_no_data_is_invented():
    for failure in (MatchInputNotFoundError("missing"), ValueError("malformed")):
        subject = service(FakeRepository([preference()]))
        subject.match_service.results["candidate-1"] = failure
        page = await subject.list_page("stream-1")
        assert page.items == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("hard", [HardEligibilityState.INELIGIBLE, HardEligibilityState.UNRESOLVED])
async def test_only_hard_eligible_candidates_are_returned(hard):
    subject = service(FakeRepository([preference()]))
    subject.fit_service.results["candidate-1"] = fit(hard=hard)
    assert (await subject.list_page("stream-1")).items == ()


@pytest.mark.asyncio
async def test_low_match_has_no_invented_threshold_when_hard_eligible():
    subject = service(FakeRepository([preference()]))
    subject.match_service.results["candidate-1"] = match(score=0, coverage=0)
    page = await subject.list_page("stream-1")
    assert len(page.items) == 1 and page.items[0].professional_match.professional_match_score == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version", "discovery", "user"])
async def test_final_candidate_revalidation_blocks_concurrent_change(change):
    repo = FakeRepository([preference()])
    if change == "version":
        repo.current["candidate-1"]["version"] = 2
    elif change == "discovery":
        repo.current["candidate-1"]["discovery"]["enabled"] = False
        repo.current["candidate-1"]["discovery"]["allow_compatible_opportunities"] = False
    else:
        repo.users["candidate-1"]["is_active"] = False
    assert (await service(repo).list_page("stream-1")).items == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["closed", "version", "requirement"])
async def test_final_stream_revalidation_blocks_stale_page(change):
    first = make_stream()
    if change == "closed":
        second = make_stream(state=TalentStreamState.CLOSED)
    elif change == "version":
        # A valid later B1 state is CLOSED and therefore also changes version.
        second = make_stream(state=TalentStreamState.CLOSED)
    else:
        second = replace(first, requirement_snapshot=replace(
            first.requirement_snapshot, requirement_version=EntityVersion(6)
        ))
    repo = FakeRepository([preference()], stream=first)
    repo.streams = [first, second]
    with pytest.raises(DiscoveryPoolConflictError):
        await service(repo).list_page("stream-1")


@pytest.mark.asyncio
async def test_pagination_scans_limit_not_return_count_and_extra_is_not_processed():
    docs = [preference(f"candidate-{index:03d}") for index in range(1, 102)]
    repo = FakeRepository(docs)
    for index in range(1, 101, 2):
        repo.users[f"candidate-{index:03d}"]["is_active"] = False
    subject = service(repo)
    page = await subject.list_page("stream-1", limit=100)
    assert page.scanned_count == 100 and len(page.items) == 50
    assert str(page.next_cursor.after_candidate_id) == "candidate-100"
    assert not any(call[0] == "get_user" and call[1] == "candidate-101" for call in repo.calls)


@pytest.mark.asyncio
async def test_zero_result_page_still_advances_cursor():
    docs = [preference("candidate-1"), preference("candidate-2")]
    repo = FakeRepository(docs)
    repo.users["candidate-1"]["is_active"] = False
    page = await service(repo).list_page("stream-1", limit=1)
    assert page.items == () and page.scanned_count == 1
    assert str(page.next_cursor.after_candidate_id) == "candidate-1"


@pytest.mark.asyncio
async def test_cursor_binds_every_stream_requirement_dimension_and_preserves_opaque_ids():
    repo = FakeRepository([preference(" candidate-1 "), preference("candidate-1")])
    subject = service(repo)
    first = await subject.list_page("stream-1", limit=1)
    cursor = first.next_cursor
    assert str(cursor.after_candidate_id) == " candidate-1 "
    for field, value in (
        ("stream_id", TalentStreamId("other")),
        ("stream_version", EntityVersion(1)),
        ("requirement_version", EntityVersion(6)),
        ("role_dna_id", RoleDNAId("other")),
        ("role_dna_version", EntityVersion(4)),
        ("opportunity_spec_id", OpportunitySpecId("other")),
        ("opportunity_spec_version", EntityVersion(5)),
    ):
        with pytest.raises(ValueError):
            await subject.list_page("stream-1", after=replace(cursor, **{field: value}), limit=1)


def test_models_are_immutable():
    cursor = DiscoveryPoolCursor(
        TalentStreamId("stream-1"), EntityVersion(2), EntityVersion(5),
        RoleDNAId("role-1"), EntityVersion(3), OpportunitySpecId("spec-1"),
        EntityVersion(4), CandidateId("candidate-1"),
    )
    with pytest.raises(FrozenInstanceError):
        cursor.after_candidate_id = CandidateId("other")


def test_runtime_scope_is_read_only_and_does_not_cross_b6_boundaries():
    sources = "\n".join((
        (BACKEND / "domains/talent_stream/discovery_pool_repository.py").read_text(),
        (BACKEND / "domains/talent_stream/discovery_pool_service.py").read_text(),
    ))
    tree = ast.parse(sources)
    forbidden_collections = {
        "applications", "saved_jobs", "talent_intent_events", "talent_stream_grants",
        "messages", "contact_requests", "documents", "cvs",
    }
    forbidden_calls = {
        "insert_one", "insert_many", "update_one", "update_many", "replace_one",
        "delete_one", "delete_many", "bulk_write", "create_index", "create_collection",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden_collections:
            raise AssertionError(f"forbidden collection access: {node.attr}")
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            assert name not in forbidden_calls


class _MetadataCursor:
    def __init__(self, rows): self.rows = rows
    def __aiter__(self): self.iterator = iter(self.rows); return self
    async def __anext__(self):
        try: return next(self.iterator)
        except StopIteration: raise StopAsyncIteration


class _MetadataCollection:
    def __init__(self, indexes): self.indexes = indexes
    def with_options(self, **kwargs): return self
    async def index_information(self): return deepcopy(self.indexes)


class _MetadataDB:
    def __init__(self, indexes):
        self.collections = {
            "candidate_preferences": _MetadataCollection(indexes),
            "talent_streams": _MetadataCollection({"_id_": {"key": [("_id", 1)]}}),
        }
    def __getitem__(self, name): return self.collections[name]
    async def list_collections(self, filter=None, **kwargs):
        wanted = filter["name"]
        names = [wanted] if isinstance(wanted, str) else wanted["$in"]
        return _MetadataCursor([
            {"name": name, "type": "collection", "options": {}}
            for name in names if name in self.collections
        ])


def metadata(*, include_b6=True):
    result = {
        "_id_": {"key": [("_id", 1)]},
        "ts_a2_candidate_preferences_candidate_unique": {
            "key": [("candidate_id", 1)], "unique": True,
        },
    }
    if include_b6:
        result["ts_b6_discovery_pool_scan"] = {
            "key": [("discovery.enabled", 1), ("discovery.allow_compatible_opportunities", 1), ("candidate_id", 1)],
            "partialFilterExpression": {"discovery.enabled": True, "discovery.allow_compatible_opportunities": True},
        }
    return result


@pytest.mark.asyncio
async def test_runtime_readiness_requires_exact_b6_index_without_creating_it():
    repository = DiscoveryPoolRepository(_MetadataDB(metadata(include_b6=False)))
    with pytest.raises(DiscoveryPoolReadinessError):
        await repository.readiness()
    wrong = metadata()
    wrong["ts_b6_discovery_pool_scan"]["key"].reverse()
    with pytest.raises(DiscoveryPoolReadinessError):
        await DiscoveryPoolRepository(_MetadataDB(wrong)).readiness()
    assert (await DiscoveryPoolRepository(_MetadataDB(metadata())).readiness()).ok
