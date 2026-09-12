"""TS-B1 G1 against an explicitly configured disposable standalone MongoDB."""
import asyncio
from datetime import datetime, timedelta, timezone
import os
from urllib.parse import urlsplit
import uuid

from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient
import pytest
import pytest_asyncio

from domains.shared.ids import (
    HiringCompanyId, MandateId, OpportunitySpecId, OrganizationId,
    RecruiterUserId, RoleDNAId,
)
from domains.shared.versioning import EntityVersion
from domains.talent_stream.contracts import (
    OpportunitySpecificationRef, RecruitingActorContext, RoleDNARef,
    StreamRequirementSnapshot,
)
from domains.talent_stream.stream_models import TalentStream, TalentStreamState
from domains.talent_stream.stream_repository import (
    TalentStreamConflictError, TalentStreamReadinessError, TalentStreamRepository,
    TalentStreamStoredDataError,
)
from domains.talent_stream.stream_service import TalentStreamService
from scripts.migrate_ts_b1_talent_streams import migrate, preflight


NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def db():
    url = os.environ.get("B1_MONGO_URL")
    if not url:
        pytest.skip("B1_MONGO_URL must designate disposable standalone Mongo")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "mongodb"
            and parsed.hostname in ("127.0.0.1", "localhost")
            and parsed.port is not None
            and parsed.port > 0
            and parsed.netloc == f"{parsed.hostname}:{parsed.port}"
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        pytest.fail("B1 requires explicit loopback port without credentials/database/options")
    client = AsyncIOMotorClient(
        url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, socketTimeoutMS=5000,
    )
    name = "test_ts_b1_" + uuid.uuid4().hex
    standalone = False
    try:
        hello = await client.admin.command("hello")
        assert "setName" not in hello and hello.get("msg") != "isdbgrid"
        standalone = True
        yield client[name]
    finally:
        try:
            if standalone:
                assert name.startswith("test_ts_b1_") and len(name) == 43
                await client.drop_database(name)
        finally:
            client.close()


def actor(*, recruiter="recruiter-1"):
    return RecruitingActorContext(
        recruiter_user_id=RecruiterUserId(recruiter),
        requesting_organization_id=OrganizationId("requesting-org-1"),
        hiring_company_id=HiringCompanyId("hiring-company-1"),
        mandate_id=MandateId("mandate-1"),
    )


def requirement(*, role_version=1):
    return StreamRequirementSnapshot(
        role_dna=RoleDNARef(RoleDNAId("role-1"), EntityVersion(role_version)),
        opportunity_spec=OpportunitySpecificationRef(
            OpportunitySpecId("opportunity-1"), EntityVersion(2),
        ),
        requirement_version=EntityVersion(3),
        captured_at=NOW,
    )


async def prepare(db):
    result = await migrate(db, apply=True)
    assert result["ready"]
    return TalentStreamService(db)


async def bson_documents(db):
    documents = await db.talent_streams.find({}).sort("_id", 1).to_list(length=None)
    return tuple(BSON.encode(document) for document in documents)


async def create(app, stream_id="stream-1", command_id="create-1", **changes):
    return await app.create(
        stream_id,
        changes.get("actor", actor()),
        changes.get("requirement", requirement()),
        command_id=command_id,
        occurred_at=changes.get("occurred_at", NOW),
    )


@pytest.mark.asyncio
async def test_empty_preflight_is_read_only_and_apply_is_exact_and_repeatable(db):
    assert await db.list_collection_names() == []
    assert await preflight(db) == {
        "ready": False, "documents_checked": 0, "diagnostics": 1,
    }
    assert await db.list_collection_names() == []
    first = await migrate(db, apply=True)
    assert first == {"ready": True, "documents_checked": 0, "diagnostics": 0}
    assert await db.list_collection_names() == ["talent_streams"]
    options = await db.talent_streams.options()
    assert options.get("collation", {}).get("locale", "simple") == "simple"
    indexes = await db.talent_streams.index_information()
    assert set(indexes) == {"_id_"}
    assert list(indexes["_id_"]["key"]) == [("_id", 1)]
    before = (options, indexes, await bson_documents(db))
    assert await migrate(db, apply=True) == first
    assert (await db.talent_streams.options(),
            await db.talent_streams.index_information(),
            await bson_documents(db)) == before
    assert (await TalentStreamRepository(db).readiness()).ok


@pytest.mark.asyncio
async def test_exact_create_and_read_round_trip_preserves_a0_snapshots(db):
    app = await prepare(db)
    created = await create(app)
    restored = await app.get("stream-1")
    assert restored == created
    assert restored.recruiting_actor_context == actor()
    assert restored.requirement_snapshot == requirement()
    assert restored.state is TalentStreamState.DRAFT and restored.version == 1
    assert await db.talent_streams.count_documents({}) == 1


@pytest.mark.asyncio
async def test_concurrent_identical_creates_converge_to_one_document(db):
    app = await prepare(db)
    results = await asyncio.gather(*(
        create(app) for _ in range(8)
    ))
    assert all(result == results[0] for result in results)
    assert await db.talent_streams.count_documents({}) == 1
    assert len(results[0].history) == 1 and results[0].version == 1


@pytest.mark.asyncio
async def test_create_collision_does_not_mutate_stored_bson(db):
    app = await prepare(db)
    await create(app)
    before = await bson_documents(db)
    with pytest.raises(TalentStreamConflictError, match="^Talent Stream create conflict$"):
        await create(app, actor=actor(recruiter="recruiter-2"))
    assert await bson_documents(db) == before
    with pytest.raises(TalentStreamConflictError):
        await create(app, command_id="different-command")
    assert await bson_documents(db) == before


@pytest.mark.asyncio
async def test_concurrent_identical_transition_is_one_increment_and_replay(db):
    app = await prepare(db)
    await create(app)
    when = NOW + timedelta(seconds=1)
    results = await asyncio.gather(*(
        app.activate(
            "stream-1", command_id="activate-1", expected_version=1,
            occurred_at=when,
        )
        for _ in range(8)
    ))
    assert all(result.state is TalentStreamState.ACTIVE for result in results)
    current = await app.get("stream-1")
    assert current.version == 2 and len(current.history) == 2


@pytest.mark.asyncio
async def test_concurrent_distinct_commands_have_one_winner(db):
    app = await prepare(db)
    await create(app)
    when = NOW + timedelta(seconds=1)
    results = await asyncio.gather(
        app.activate(
            "stream-1", command_id="activate-1", expected_version=1,
            occurred_at=when,
        ),
        app.close(
            "stream-1", command_id="close-1", expected_version=1,
            occurred_at=when,
        ),
        return_exceptions=True,
    )
    assert sum(type(result) is TalentStream for result in results) == 1
    assert sum(type(result) is TalentStreamConflictError for result in results) == 1
    current = await app.get("stream-1")
    assert current.version == 2 and len(current.history) == 2


@pytest.mark.asyncio
async def test_activate_close_replays_never_increment_twice(db):
    app = await prepare(db)
    await create(app)
    active = await app.activate(
        "stream-1", command_id="activate-1", expected_version=1,
        occurred_at=NOW + timedelta(seconds=1),
    )
    replayed_active = await app.activate(
        "stream-1", command_id="activate-1", expected_version=1,
        occurred_at=NOW + timedelta(minutes=1),
    )
    assert active == replayed_active and len(replayed_active.history) == 2
    closed = await app.close(
        "stream-1", command_id="close-1", expected_version=2,
        occurred_at=NOW + timedelta(seconds=2),
    )
    replayed_closed = await app.close(
        "stream-1", command_id="close-1", expected_version=2,
        occurred_at=NOW + timedelta(minutes=2),
    )
    assert closed == replayed_closed
    assert closed.version == 3 and len(closed.history) == 3


@pytest.mark.asyncio
async def test_stale_or_illegal_commands_do_not_mutate_closed_stream(db):
    app = await prepare(db)
    await create(app)
    await app.close(
        "stream-1", command_id="close-1", expected_version=1,
        occurred_at=NOW + timedelta(seconds=1),
    )
    before = await bson_documents(db)
    with pytest.raises(TalentStreamConflictError):
        await app.activate(
            "stream-1", command_id="activate-1", expected_version=1,
            occurred_at=NOW + timedelta(seconds=2),
        )
    with pytest.raises(TalentStreamConflictError):
        await app.close(
            "stream-1", command_id="close-2", expected_version=2,
            occurred_at=NOW + timedelta(seconds=2),
        )
    assert await bson_documents(db) == before


@pytest.mark.asyncio
async def test_malformed_stored_document_fails_read_and_replay_closed(db):
    await migrate(db, apply=True)
    await db.talent_streams.insert_one({
        "_id": "stream-1", "schema_version": "future-v9", "private": "hidden",
    })
    repository = TalentStreamRepository(db)
    with pytest.raises(TalentStreamStoredDataError, match="^invalid stored Talent Stream$"):
        await repository.get("stream-1")
    with pytest.raises(TalentStreamStoredDataError, match="^invalid stored Talent Stream$"):
        await create(TalentStreamService(db))


@pytest.mark.asyncio
async def test_unexpected_secondary_index_blocks_readiness_and_writes(db):
    app = await prepare(db)
    await db.talent_streams.create_index([("state", 1)], name="unexpected")
    repository = TalentStreamRepository(db)
    with pytest.raises(TalentStreamReadinessError, match="^Talent Stream storage is not ready$"):
        await repository.readiness()
    before = await bson_documents(db)
    with pytest.raises(TalentStreamReadinessError):
        await create(app)
    assert await bson_documents(db) == before


@pytest.mark.asyncio
async def test_non_simple_collection_blocks_readiness_and_writes(db):
    await db.create_collection(
        "talent_streams", collation={"locale": "en", "strength": 2},
    )
    app = TalentStreamService(db)
    with pytest.raises(TalentStreamReadinessError):
        await app.repository.readiness()
    before = await bson_documents(db)
    with pytest.raises(TalentStreamReadinessError):
        await create(app)
    assert await bson_documents(db) == before

