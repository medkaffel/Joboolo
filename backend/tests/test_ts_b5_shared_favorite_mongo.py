"""TS-B5 G1 against an explicit disposable standalone MongoDB only."""
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
from domains.talent_stream.shared_favorite_repository import (
    SharedFavoriteReadinessError,
    SharedFavoriteRepositoryError,
)
from domains.talent_stream.shared_favorite_service import (
    SharedFavoriteConflictError,
    SharedFavoriteNotEligibleError,
    SharedFavoriteService,
)
from scripts.migrate_ts_a11_intent_event_indexes import migrate


NOW = datetime(2026, 9, 13, 17, 0, 0, 1000, tzinfo=timezone.utc)


class TickingClock:
    def __init__(self):
        self.current = NOW

    def __call__(self):
        value = self.current
        self.current += timedelta(milliseconds=1)
        return value


@pytest_asyncio.fixture
async def db():
    url = os.environ.get("B5_MONGO_URL")
    if not url:
        pytest.skip("B5_MONGO_URL must designate disposable standalone Mongo")
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
            "B5 requires an explicit loopback port without credentials/database/options"
        )

    client = AsyncIOMotorClient(
        url,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=5000,
    )
    name = "test_ts_b5_" + uuid.uuid4().hex
    standalone = False
    try:
        hello = await client.admin.command("hello")
        assert "setName" not in hello and hello.get("msg") != "isdbgrid"
        standalone = True
        yield client[name]
    finally:
        try:
            if standalone:
                assert name.startswith("test_ts_b5_") and len(name) == 43
                await client.drop_database(name)
        finally:
            client.close()


def saved(saved_id="saved-1", candidate="candidate-1", job="job-1", **changes):
    document = {
        "_id": saved_id,
        "user_id": candidate,
        "job_id": job,
        "created_at": NOW.replace(tzinfo=None),
        "updated_at": NOW.replace(tzinfo=None),
    }
    document.update(changes)
    return document


async def seed(db, *, migrate_a11=True, saved_index=True):
    if migrate_a11:
        await migrate(db, apply=True)
    if saved_index:
        await db.saved_jobs.create_index(
            [("user_id", 1), ("job_id", 1)],
            unique=True,
            name="arbitrary_historical_name",
        )
    await db.users.insert_many([
        {"_id": "candidate-1", "user_type": "candidate", "is_active": True},
        {"_id": "candidate-2", "user_type": "candidate", "is_active": True},
    ])
    await db.jobs.insert_many([
        {"_id": "job-1", "is_active": True},
        {"_id": "job-2", "is_active": True},
    ])
    await db.saved_jobs.insert_one(saved())
    return SharedFavoriteService(db, clock=TickingClock())


async def snapshot(db, names):
    result = {}
    for name in names:
        documents = await db[name].find({}).sort("_id", 1).to_list(length=None)
        result[name] = tuple(BSON.encode(document) for document in documents)
    return result


async def share(current, *, candidate="candidate-1", job="job-1", saved_id="saved-1", key="share-1"):
    return await current.share(
        candidate, job, saved_id, caller_idempotency_key=key,
    )


async def withdraw(current, positive, *, candidate="candidate-1", job="job-1", key="withdraw-1"):
    return await current.withdraw(
        candidate, job, str(positive.event_id), caller_idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_readiness_requires_a11_and_saved_job_unique_pair(db):
    current = await seed(db, migrate_a11=False, saved_index=False)
    with pytest.raises(SharedFavoriteReadinessError):
        await share(current)
    assert await db.talent_intent_events.count_documents({}) == 0
    await migrate(db, apply=True)
    with pytest.raises(SharedFavoriteReadinessError):
        await share(current)
    await db.saved_jobs.create_index(
        [("user_id", 1), ("job_id", 1)], unique=True, name="different-name",
    )
    assert (await share(current)).correlation_id == "saved-1"


@pytest.mark.asyncio
async def test_private_saved_job_alone_creates_no_intent_event(db):
    await seed(db)
    assert await db.saved_jobs.count_documents({}) == 1
    assert await db.talent_intent_events.count_documents({}) == 0


@pytest.mark.asyncio
async def test_real_share_retry_and_no_secondary_collection_writes(db):
    current = await seed(db)
    protected = ("users", "jobs", "saved_jobs")
    before = await snapshot(db, protected)
    first = await share(current)
    second = await share(current)
    assert second == first
    assert first.correlation_id == "saved-1"
    assert await db.talent_intent_events.count_documents({}) == 1
    assert await snapshot(db, protected) == before


@pytest.mark.asyncio
async def test_real_concurrent_share_has_one_winner(db):
    current = await seed(db)
    results = await asyncio.gather(*(share(current) for _ in range(20)))
    assert len({result.event_id for result in results}) == 1
    assert len({result.occurred_at for result in results}) == 1
    assert await db.talent_intent_events.count_documents({}) == 1


@pytest.mark.asyncio
async def test_foreign_and_malformed_saved_jobs_fail_closed(db):
    current = await seed(db)
    await db.saved_jobs.delete_one({"_id": "saved-1"})
    await db.saved_jobs.insert_many([
        saved("foreign", candidate="candidate-2"),
        saved("malformed", created_at="2026-09-13"),
    ])
    with pytest.raises(SharedFavoriteNotEligibleError):
        await share(current, saved_id="foreign")
    with pytest.raises(SharedFavoriteNotEligibleError):
        await share(current, saved_id="malformed", key="share-2")
    assert await db.talent_intent_events.count_documents({}) == 0


@pytest.mark.asyncio
async def test_saved_job_deleted_between_validation_reads_prevents_insert(db, monkeypatch):
    current = await seed(db)
    original = current.repository.get_saved_job
    calls = 0

    async def delete_before_second(candidate_id, job_id, saved_job_id):
        nonlocal calls
        calls += 1
        if calls == 2:
            await db.saved_jobs.delete_one({"_id": saved_job_id})
        return await original(candidate_id, job_id, saved_job_id)

    monkeypatch.setattr(current.repository, "get_saved_job", delete_before_second)
    with pytest.raises(SharedFavoriteNotEligibleError):
        await share(current)
    assert await db.talent_intent_events.count_documents({}) == 0


@pytest.mark.asyncio
async def test_unsave_after_final_read_may_leave_history_but_resave_does_not_reactivate_it(db, monkeypatch):
    current = await seed(db)
    original_record = current.repository.record

    async def unsave_then_record(event):
        await db.saved_jobs.delete_one({"_id": "saved-1"})
        return await original_record(event)

    monkeypatch.setattr(current.repository, "record", unsave_then_record)
    old = await share(current)
    assert old.correlation_id == "saved-1"
    assert await db.saved_jobs.count_documents({}) == 0
    await db.saved_jobs.insert_one(saved("saved-2"))
    assert await db.talent_intent_events.count_documents({}) == 1
    monkeypatch.setattr(current.repository, "record", original_record)
    new = await share(current, saved_id="saved-2", key="share-2")
    assert new.correlation_id == "saved-2"
    assert old.event_id != new.event_id


@pytest.mark.asyncio
async def test_withdrawal_is_append_only_after_job_and_saved_job_deletion(db):
    current = await seed(db)
    positive = await share(current)
    stored_positive = await db.talent_intent_events.find_one({"_id": positive.event_id})
    await db.saved_jobs.delete_many({})
    await db.jobs.delete_many({})
    negative = await withdraw(current, positive)
    assert negative.correlation_id == "saved-1"
    assert negative.causation_id == positive.event_id
    assert await db.talent_intent_events.count_documents({}) == 2
    assert await db.talent_intent_events.find_one({"_id": positive.event_id}) == stored_positive


@pytest.mark.asyncio
async def test_real_concurrent_withdrawal_has_one_winner(db):
    current = await seed(db)
    positive = await share(current)
    results = await asyncio.gather(*(withdraw(current, positive) for _ in range(20)))
    assert len({result.event_id for result in results}) == 1
    assert len({result.occurred_at for result in results}) == 1
    assert await db.talent_intent_events.count_documents({}) == 2


@pytest.mark.asyncio
async def test_wrong_candidate_cannot_withdraw_another_candidates_share(db):
    current = await seed(db)
    positive = await share(current)
    with pytest.raises(SharedFavoriteConflictError):
        await withdraw(current, positive, candidate="candidate-2")
    assert await db.talent_intent_events.count_documents({}) == 1


@pytest.mark.asyncio
async def test_network_retry_recovers_committed_share_and_withdrawal(db, monkeypatch):
    current = await seed(db)
    original = current.repository.event_service.repo.insert

    async def insert_then_disconnect(document):
        await original(document)
        raise AutoReconnect("synthetic lost response")

    monkeypatch.setattr(
        current.repository.event_service.repo, "insert", insert_then_disconnect,
    )
    with pytest.raises(SharedFavoriteRepositoryError):
        await share(current)
    monkeypatch.setattr(current.repository.event_service.repo, "insert", original)
    positive = await share(current)

    monkeypatch.setattr(
        current.repository.event_service.repo, "insert", insert_then_disconnect,
    )
    with pytest.raises(SharedFavoriteRepositoryError):
        await withdraw(current, positive)
    monkeypatch.setattr(current.repository.event_service.repo, "insert", original)
    negative = await withdraw(current, positive)
    stored = await db.talent_intent_events.find_one({"_id": negative.event_id})
    assert event_from_document(stored) == negative
    assert await db.talent_intent_events.count_documents({}) == 2
