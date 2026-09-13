"""TS-B6 G1 against an explicit disposable standalone MongoDB only."""
from copy import deepcopy
from datetime import datetime, timezone
import os
from urllib.parse import urlsplit
import uuid

from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient
import pytest
import pytest_asyncio

from domains.matching.opportunity_fit_models import HardEligibilityState
from domains.shared.ids import (
    HiringCompanyId, OpportunitySpecId, OrganizationId, RecruiterUserId,
    RoleDNAId, TalentStreamId,
)
from domains.shared.versioning import EntityVersion
from domains.talent_stream.contracts import (
    OpportunitySpecificationRef, RecruitingActorContext, RoleDNARef,
    StreamRequirementSnapshot,
)
from domains.talent_stream.discovery_pool_repository import DiscoveryPoolReadinessError
from domains.talent_stream.discovery_pool_service import (
    DiscoveryPoolConflictError, DiscoveryPoolService,
)
from domains.talent_stream.stream_models import (
    StreamCommandHistoryEntry, StreamCommandKind, TalentStream, TalentStreamState,
)
from domains.talent_stream.stream_repository import stream_to_document
from scripts.migrate_ts_b6_discovery_pool_index import migrate, preflight


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
A2_INDEX = "ts_a2_candidate_preferences_candidate_unique"
B6_INDEX = "ts_b6_discovery_pool_scan"
B6_KEYS = [
    ("discovery.enabled", 1),
    ("discovery.allow_compatible_opportunities", 1),
    ("candidate_id", 1),
]
B6_PARTIAL = {
    "discovery.enabled": True,
    "discovery.allow_compatible_opportunities": True,
}


@pytest_asyncio.fixture
async def db():
    url = os.environ.get("B6_MONGO_URL")
    if not url:
        pytest.skip("B6_MONGO_URL must designate disposable standalone Mongo")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "mongodb"
            and parsed.hostname == "127.0.0.1"
            and parsed.port is not None and parsed.port > 0
            and parsed.netloc == f"127.0.0.1:{parsed.port}"
            and parsed.path in ("", "/")
            and not parsed.query and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        pytest.fail("B6 requires an explicit loopback port without credentials/database/options")
    client = AsyncIOMotorClient(
        url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
        socketTimeoutMS=5000,
    )
    name = "test_ts_b6_" + uuid.uuid4().hex
    standalone = False
    try:
        hello = await client.admin.command("hello")
        assert "setName" not in hello and hello.get("msg") != "isdbgrid"
        standalone = True
        yield client[name]
    finally:
        try:
            if standalone:
                assert name.startswith("test_ts_b6_") and len(name) == 43
                await client.drop_database(name)
        finally:
            client.close()


def stream(*, state=TalentStreamState.ACTIVE):
    create = StreamCommandHistoryEntry(
        "create", "fp-create", StreamCommandKind.CREATE, None,
        TalentStreamState.DRAFT, EntityVersion(1), NOW,
    )
    history = (create,)
    if state is TalentStreamState.ACTIVE:
        history += (StreamCommandHistoryEntry(
            "activate", "fp-activate", StreamCommandKind.ACTIVATE,
            TalentStreamState.DRAFT, TalentStreamState.ACTIVE, EntityVersion(2), NOW,
        ),)
    elif state is TalentStreamState.CLOSED:
        history += (StreamCommandHistoryEntry(
            "close", "fp-close", StreamCommandKind.CLOSE,
            TalentStreamState.DRAFT, TalentStreamState.CLOSED, EntityVersion(2), NOW,
        ),)
    return TalentStream(
        TalentStreamId("stream-1"), EntityVersion(len(history)),
        RecruitingActorContext(
            RecruiterUserId("recruiter-1"), OrganizationId("org-1"),
            HiringCompanyId("company-1"), None,
        ),
        StreamRequirementSnapshot(
            RoleDNARef(RoleDNAId("role-1"), EntityVersion(1)),
            OpportunitySpecificationRef(OpportunitySpecId("spec-1"), EntityVersion(1)),
            EntityVersion(1), NOW,
        ),
        state, NOW, NOW, history,
    )


def preference(candidate="candidate-1", *, search_state="passive", version=1,
               enabled=True, allow=True, work_mode="any"):
    return {
        "_id": f"candidate_preferences:{candidate}", "candidate_id": candidate,
        "version": version, "created_at": NOW, "updated_at": NOW,
        "search_state": search_state,
        "discovery": {
            "enabled": enabled, "allow_compatible_opportunities": allow,
            "ask_before_reveal": True, "anonymous_only": True,
        },
        "target_roles": [], "work_mode": work_mode, "contract_types": [],
        "excluded_company_ids": [],
    }


def profile(candidate="candidate-1"):
    return {
        "_id": f"candidate_profile:{candidate}", "candidate_id": candidate,
        "version": 1, "created_at": NOW, "updated_at": NOW,
        "occupations": [], "experiences": [], "skills": [], "certifications": [],
        "languages": [], "industries": [], "education": [], "portfolio": [],
    }


def role():
    return {
        "_id": "role-1:v1", "role_dna_id": "role-1", "version": 1,
        "status": "active", "canonical_title": "Backend Engineer",
        "created_at": NOW, "updated_at": NOW, "aliases": [], "skills": [],
        "capabilities": [], "certifications": [], "languages": [],
        "transferable_role_refs": [], "adjacent_role_refs": [], "provenance": "manual",
    }


def spec(*, work_arrangement=None):
    doc = {
        "_id": "spec-1:v1", "opportunity_spec_id": "spec-1", "version": 1,
        "status": "active", "created_at": NOW, "updated_at": NOW,
        "contract_types": [], "industry_constraints": [], "company_constraints": [],
        "must_have_requirements": [], "nice_to_have_requirements": [],
        "provenance": "manual",
    }
    if work_arrangement is not None:
        doc["work_arrangement"] = work_arrangement
    return doc


async def storage(db, *, b6=True):
    await db.create_collection("talent_streams")
    await db.create_collection("candidate_preferences")
    await db.candidate_preferences.create_index(
        [("candidate_id", 1)], unique=True, name=A2_INDEX,
    )
    if b6:
        assert (await migrate(db, apply=True))["ready"]


async def seed(db, *, candidates=("candidate-1",), search_state="passive",
               work_mode="any", opportunity_mode=None, b6=True):
    await storage(db, b6=b6)
    await db.talent_streams.insert_one(stream_to_document(stream()))
    await db.role_dnas.insert_one(role())
    await db.opportunity_specs.insert_one(spec(work_arrangement=opportunity_mode))
    await db.users.insert_many([
        {"_id": candidate, "user_type": "candidate", "is_active": True}
        for candidate in candidates
    ])
    await db.candidate_profiles.insert_many([profile(candidate) for candidate in candidates])
    await db.candidate_preferences.insert_many([
        preference(candidate, search_state=search_state, work_mode=work_mode)
        for candidate in candidates
    ])
    return DiscoveryPoolService(db)


async def snapshot(db, names):
    result = {}
    for name in names:
        docs = await db[name].find({}).sort("_id", 1).to_list(length=None)
        result[name] = tuple(BSON.encode(doc) for doc in docs)
    return result


@pytest.mark.asyncio
async def test_readiness_missing_b6_index_refuses_without_runtime_creation(db):
    current = await seed(db, b6=False)
    before = await db.candidate_preferences.index_information()
    with pytest.raises(DiscoveryPoolReadinessError):
        await current.list_page("stream-1")
    assert await db.candidate_preferences.index_information() == before


@pytest.mark.asyncio
async def test_migration_preflight_is_non_mutating(db):
    await storage(db, b6=False)
    before = await db.candidate_preferences.index_information()
    assert await preflight(db) == {"ready": False, "diagnostics": 1}
    assert await db.candidate_preferences.index_information() == before


@pytest.mark.asyncio
async def test_migration_apply_creates_exact_nonunique_non_ttl_partial_index(db):
    await storage(db, b6=False)
    assert (await migrate(db, apply=True))["ready"]
    indexes = await db.candidate_preferences.index_information()
    actual = indexes[B6_INDEX]
    assert actual["key"] == B6_KEYS
    assert actual.get("unique", False) is False
    assert "expireAfterSeconds" not in actual
    assert actual["partialFilterExpression"] == B6_PARTIAL
    assert indexes[A2_INDEX]["unique"] is True


@pytest.mark.asyncio
async def test_migration_is_repeatable(db):
    await storage(db, b6=False)
    first = await migrate(db, apply=True)
    metadata = await db.candidate_preferences.index_information()
    second = await migrate(db, apply=True)
    assert first == second == {"ready": True, "diagnostics": 0}
    assert await db.candidate_preferences.index_information() == metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong", ["keys", "partial"])
async def test_wrong_b6_index_fails_closed(db, wrong):
    await storage(db, b6=False)
    keys = list(reversed(B6_KEYS)) if wrong == "keys" else B6_KEYS
    partial = {"discovery.enabled": True} if wrong == "partial" else B6_PARTIAL
    await db.candidate_preferences.create_index(
        keys, name=B6_INDEX, partialFilterExpression=partial,
    )
    with pytest.raises(DiscoveryPoolReadinessError):
        await DiscoveryPoolService(db).list_page("stream-1")


@pytest.mark.asyncio
async def test_real_mongo_scan_order_is_candidate_id_ascending(db):
    current = await seed(db, candidates=("candidate-c", "candidate-a", "candidate-b"))
    page = await current.list_page("stream-1")
    assert [str(item.candidate_id) for item in page.items] == [
        "candidate-a", "candidate-b", "candidate-c",
    ]


@pytest.mark.asyncio
async def test_real_pagination_counts_scanned_candidates_not_results(db):
    current = await seed(db, candidates=("candidate-a", "candidate-b", "candidate-c"))
    await db.users.update_one({"_id": "candidate-a"}, {"$set": {"is_active": False}})
    page = await current.list_page("stream-1", limit=2)
    assert page.scanned_count == 2 and [str(item.candidate_id) for item in page.items] == ["candidate-b"]
    assert str(page.next_cursor.after_candidate_id) == "candidate-b"
    second = await current.list_page("stream-1", after=page.next_cursor, limit=2)
    assert [str(item.candidate_id) for item in second.items] == ["candidate-c"]


@pytest.mark.asyncio
async def test_paused_search_with_discovery_on_is_included(db):
    current = await seed(db, search_state="paused")
    assert [str(item.candidate_id) for item in (await current.list_page("stream-1")).items] == ["candidate-1"]


@pytest.mark.asyncio
async def test_current_inactive_candidate_is_excluded(db):
    current = await seed(db)
    await db.users.update_one({"_id": "candidate-1"}, {"$set": {"is_active": False}})
    assert (await current.list_page("stream-1")).items == ()


@pytest.mark.asyncio
async def test_real_a5_a6_exact_snapshot_integration(db):
    current = await seed(db)
    item = (await current.list_page("stream-1")).items[0]
    assert item.professional_match.role_dna_id == "role-1"
    assert item.professional_match.role_dna_version == 1
    assert item.opportunity_fit.opportunity_spec_id == "spec-1"
    assert item.opportunity_fit.candidate_preferences_version == 1


@pytest.mark.asyncio
async def test_hard_ineligible_is_excluded(db):
    current = await seed(db, work_mode="remote", opportunity_mode="onsite")
    assert (await current.list_page("stream-1")).items == ()


@pytest.mark.asyncio
async def test_hard_unresolved_is_excluded(db):
    current = await seed(db, work_mode="any", opportunity_mode="remote")
    result = await current.fit_service.compute(
        "candidate-1", "spec-1", 1, candidate_preferences_version=EntityVersion(1),
    )
    assert result.hard_eligibility_state is HardEligibilityState.UNRESOLVED
    assert (await current.list_page("stream-1")).items == ()


@pytest.mark.asyncio
async def test_discovery_revocation_between_read_and_revalidation_excludes(db):
    current = await seed(db)
    original = current.match_service.compute
    async def revoke(*args, **kwargs):
        result = await original(*args, **kwargs)
        await db.candidate_preferences.update_one(
            {"candidate_id": "candidate-1"},
            {"$set": {"discovery.enabled": False, "discovery.allow_compatible_opportunities": False}},
        )
        return result
    current.match_service.compute = revoke
    assert (await current.list_page("stream-1")).items == ()


@pytest.mark.asyncio
async def test_preferences_version_change_between_read_and_revalidation_excludes(db):
    current = await seed(db)
    original = current.fit_service.compute
    async def bump(*args, **kwargs):
        result = await original(*args, **kwargs)
        await db.candidate_preferences.update_one(
            {"candidate_id": "candidate-1"}, {"$inc": {"version": 1}},
        )
        return result
    current.fit_service.compute = bump
    assert (await current.list_page("stream-1")).items == ()


@pytest.mark.asyncio
async def test_stream_closure_during_processing_refuses_page(db):
    current = await seed(db)
    original = current.match_service.compute
    async def close(*args, **kwargs):
        result = await original(*args, **kwargs)
        await db.talent_streams.replace_one({"_id": "stream-1"}, stream_to_document(stream(state=TalentStreamState.CLOSED)))
        return result
    current.match_service.compute = close
    with pytest.raises(DiscoveryPoolConflictError):
        await current.list_page("stream-1")


@pytest.mark.asyncio
async def test_zero_item_page_advances_cursor(db):
    current = await seed(db, candidates=("candidate-a", "candidate-b"))
    await db.users.update_one({"_id": "candidate-a"}, {"$set": {"is_active": False}})
    page = await current.list_page("stream-1", limit=1)
    assert page.items == () and str(page.next_cursor.after_candidate_id) == "candidate-a"


@pytest.mark.asyncio
async def test_retrieval_writes_no_business_collection(db):
    current = await seed(db, candidates=("candidate-a", "candidate-b"))
    names = (
        "talent_streams", "candidate_preferences", "users", "candidate_profiles",
        "role_dnas", "opportunity_specs",
    )
    before = await snapshot(db, names)
    await current.list_page("stream-1", limit=1)
    assert await snapshot(db, names) == before
    forbidden = {
        "applications", "saved_jobs", "talent_intent_events", "talent_stream_grants",
        "messages", "talent_stream_candidates", "talent_stream_contact_requests",
    }
    assert not (forbidden & set(await db.list_collection_names()))
