"""TS-B4 G1 against an explicit disposable standalone MongoDB only."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from urllib.parse import urlsplit
import uuid

from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import AutoReconnect
import pytest
import pytest_asyncio

from domains.intent.serialization import event_from_document
from domains.talent_stream.declared_interest_repository import (
    DeclaredInterestReadinessError,
    DeclaredInterestRepositoryError,
)
from domains.talent_stream.declared_interest_service import (
    DeclaredInterestConflictError,
    DeclaredInterestJobNotEligibleError,
    DeclaredInterestService,
)
from scripts.migrate_ts_a11_intent_event_indexes import migrate


NOW = datetime(2026, 9, 13, 14, 0, 0, 1000, tzinfo=timezone.utc)


class TickingClock:
    def __init__(self):
        self.current = NOW

    def __call__(self):
        value = self.current
        self.current += timedelta(milliseconds=1)
        return value


@pytest_asyncio.fixture
async def db():
    url = os.environ.get("B4_MONGO_URL")
    if not url:
        pytest.skip("B4_MONGO_URL must designate disposable standalone Mongo")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "mongodb"
            and parsed.hostname == "127.0.0.1"
            and parsed.port is not None
            and parsed.port > 0
            and parsed.netloc == f"127.0.0.1:{parsed.port}"
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        pytest.fail(
            "B4 requires an explicit loopback port without credentials/database/options"
        )

    client = AsyncIOMotorClient(
        url,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=5000,
    )
    name = "test_ts_b4_" + uuid.uuid4().hex
    standalone = False
    try:
        hello = await client.admin.command("hello")
        assert "setName" not in hello and hello.get("msg") != "isdbgrid"
        standalone = True
        yield client[name]
    finally:
        try:
            if standalone:
                assert name.startswith("test_ts_b4_") and len(name) == 43
                await client.drop_database(name)
        finally:
            client.close()


async def seed(db, *, migrate_a11=True):
    if migrate_a11:
        await migrate(db, apply=True)
    await db.users.insert_many([
        {"_id": "candidate-1", "user_type": "candidate", "is_active": True},
        {"_id": "candidate-2", "user_type": "candidate", "is_active": True},
    ])
    await db.jobs.insert_many([
        {"_id": "job-1", "is_active": True},
        {"_id": "job-2", "is_active": True},
    ])
    return DeclaredInterestService(db, clock=TickingClock())


async def snapshot(db, names):
    result = {}
    for name in names:
        documents = await db[name].find({}).sort("_id", 1).to_list(length=None)
        result[name] = tuple(BSON.encode(document) for document in documents)
    return result


@pytest.mark.asyncio
async def test_readiness_fails_without_a11_index_then_accepts_test_migration(db):
    current = await seed(db, migrate_a11=False)
    with pytest.raises(DeclaredInterestReadinessError):
        await current.declare(
            "candidate-1", "job-1", caller_idempotency_key="command-1",
        )
    assert await db.talent_intent_events.count_documents({}) == 0
    await migrate(db, apply=True)
    result = await current.declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    assert result.job_id == "job-1"
    assert await db.talent_intent_events.count_documents({}) == 1


@pytest.mark.asyncio
async def test_real_insert_retry_and_no_secondary_collection_writes(db):
    current = await seed(db)
    protected = ("users", "jobs", "campaigns")
    before = await snapshot(db, protected)
    first = await current.declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    second = await current.declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    assert second == first
    assert await db.talent_intent_events.count_documents({}) == 1
    assert await snapshot(db, protected) == before
    assert set(await db.list_collection_names()) == {
        "talent_intent_events", "users", "jobs",
    }


@pytest.mark.asyncio
async def test_real_concurrency_with_different_server_timestamps_has_one_winner(db):
    current = await seed(db)
    results = await asyncio.gather(*(
        current.declare(
            "candidate-1", "job-1", caller_idempotency_key="command-1",
        )
        for _ in range(20)
    ))
    assert len({result.event_id for result in results}) == 1
    assert len({result.occurred_at for result in results}) == 1
    assert await db.talent_intent_events.count_documents({}) == 1


@pytest.mark.asyncio
async def test_same_key_other_job_conflicts_and_other_candidate_is_isolated(db):
    current = await seed(db)
    first = await current.declare(
        "candidate-1", "job-1", caller_idempotency_key="same-command",
    )
    with pytest.raises(DeclaredInterestConflictError):
        await current.declare(
            "candidate-1", "job-2", caller_idempotency_key="same-command",
        )
    second = await current.declare(
        "candidate-2", "job-1", caller_idempotency_key="same-command",
    )
    assert first.event_id != second.event_id
    assert await db.talent_intent_events.count_documents({}) == 2


@pytest.mark.asyncio
async def test_retry_succeeds_after_physical_job_deletion(db):
    current = await seed(db)
    first = await current.declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    await db.jobs.delete_one({"_id": "job-1"})
    second = await current.declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    assert second == first
    with pytest.raises(DeclaredInterestJobNotEligibleError):
        await current.declare(
            "candidate-1", "job-1", caller_idempotency_key="command-2",
        )
    assert await db.talent_intent_events.count_documents({}) == 1


@pytest.mark.asyncio
async def test_non_diffusable_campaign_refuses_only_a_new_command(db):
    current = await seed(db)
    await db.campaigns.insert_one({
        "_id": "campaign-1", "status": "active", "end_date": "2026-09-13",
    })
    await db.jobs.update_one(
        {"_id": "job-1"}, {"$set": {"campaign_id": "campaign-1"}},
    )
    first = await current.declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    await db.campaigns.update_one(
        {"_id": "campaign-1"}, {"$set": {"status": "paused"}},
    )
    assert await current.declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    ) == first
    with pytest.raises(DeclaredInterestJobNotEligibleError):
        await current.declare(
            "candidate-1", "job-1", caller_idempotency_key="command-2",
        )
    assert await db.talent_intent_events.count_documents({}) == 1


@pytest.mark.asyncio
async def test_corrupt_existing_a11_event_fails_closed_without_repair(db):
    current = await seed(db)
    result = await current.declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    await db.talent_intent_events.update_one(
        {"_id": result.event_id}, {"$set": {"permission": True}},
    )
    before = await db.talent_intent_events.find_one({"_id": result.event_id})
    with pytest.raises(DeclaredInterestConflictError):
        await current.declare(
            "candidate-1", "job-1", caller_idempotency_key="command-1",
        )
    after = await db.talent_intent_events.find_one({"_id": result.event_id})
    assert after == before and after["permission"] is True
    assert await db.talent_intent_events.count_documents({}) == 1


@pytest.mark.asyncio
async def test_network_retry_recovers_an_insert_committed_before_disconnect(db, monkeypatch):
    current = await seed(db)
    original = current.repository.event_service.repo.insert

    async def insert_then_disconnect(document):
        await original(document)
        raise AutoReconnect("synthetic lost response")

    monkeypatch.setattr(
        current.repository.event_service.repo, "insert", insert_then_disconnect,
    )
    with pytest.raises(DeclaredInterestRepositoryError):
        await current.declare(
            "candidate-1", "job-1", caller_idempotency_key="command-1",
        )
    monkeypatch.setattr(current.repository.event_service.repo, "insert", original)
    recovered = await current.declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    stored = await db.talent_intent_events.find_one({"_id": recovered.event_id})
    assert event_from_document(stored) == recovered
    assert await db.talent_intent_events.count_documents({}) == 1
