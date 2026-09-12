"""A14 G1: disposable Mongo only; state idempotency is not external exactly-once.

Every test gets its own generated database. No application environment fallback,
startup, worker, email or external effect is exercised.
"""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import os
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import OperationFailure
import pytest
import pytest_asyncio

from async_outbox.models import JobEnvelope, JobReference, RetryPolicy, JobState, FailureCode
from async_outbox.repository import (
    OutboxRepository, OutboxConflictError, OutboxLeaseLostError,
    OutboxReadinessError, OutboxTransactionRequiredError,
)
from async_outbox.index_requirements import OUTBOX_REQUIREMENT
from scripts.migrate_async_outbox_indexes import migrate, preflight, OutboxMigrationError


@pytest_asyncio.fixture(params=["standalone", "replica"])
async def database(request):
    topology = request.param
    variable = "A14_REPLICA_SET_URL" if topology == "replica" else "A14_STANDALONE_URL"
    url = os.environ.get(variable)
    if not url:
        pytest.skip("explicit A14 disposable Mongo URL required")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "mongodb" and parsed.hostname in ("localhost", "127.0.0.1")
            and parsed.port is not None and parsed.port > 0
            and parsed.netloc == f"{parsed.hostname}:{parsed.port}"
            and parsed.path in ("", "/") and not parsed.fragment
            and parsed.query == ("replicaSet=rs0" if topology == "replica" else "")
        )
    except ValueError:
        valid = False
    if not valid:
        pytest.fail("A14 requires loopback with explicit port and approved topology options only")
    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000, socketTimeoutMS=5000)
    name = "test_ts_a14_" + uuid.uuid4().hex
    verified = False
    try:
        hello = await client.admin.command("hello")
        assert hello.get("msg") != "isdbgrid"
        assert (hello.get("setName") == "rs0") if topology == "replica" else ("setName" not in hello)
        verified = True
        yield SimpleNamespace(db=client[name], client=client, topology=topology)
    finally:
        try:
            if verified:
                assert name.startswith("test_ts_a14_") and len(name) == 44
                await client.drop_database(name)
        finally:
            client.close()


def envelope(**changes):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return replace(JobEnvelope("job1", "fixture", "key1", "fixture-v1",
                               JobReference("fixture", "reference1", 1), RetryPolicy(3, 2, 60),
                               now, now), **changes)


async def ready(database):
    assert (await migrate(database.db, apply=True))["ready"]
    return OutboxRepository(database.db)


async def stored(db):
    return tuple(BSON.encode(doc) for doc in await db.async_outbox.find({}).sort("_id", 1).to_list(None))


async def expire_fixture_lease(db):
    # Test arrangement uses Mongo time; no sleep or client-clock race.
    await db.async_outbox.update_one({"_id": "job1", "state": "leased"}, [{"$set": {
        "updated_at": {"$subtract": ["$$NOW", 2000]},
        "lease_until": {"$subtract": ["$$NOW", 1000]},
    }}])


async def owned(repo, method, token):
    if method == "renew": return await repo.renew("job1", token, lease_seconds=60)
    if method == "fail": return await repo.fail("job1", token, reason=FailureCode.PERMANENT)
    return await getattr(repo, method)("job1", token)


@pytest.mark.asyncio
async def test_migration_empty_repeatable_apply_only_expected_indexes(database):
    db = database.db
    first = await migrate(db)
    assert first == await migrate(db) and not first["ready"]
    assert await db.list_collection_names() == []
    repo = await ready(database)
    assert await db.list_collection_names() == ["async_outbox"]
    indexes = await db.async_outbox.index_information()
    assert set(indexes) == {"_id_", *(i.name for i in OUTBOX_REQUIREMENT.indexes)}
    assert all("expireAfterSeconds" not in spec for spec in indexes.values())
    await repo.publish(envelope())
    before = await stored(db)
    assert (await migrate(db, apply=True))["ready"]
    assert await stored(db) == before
    assert await db.async_outbox.index_information() == indexes


@pytest.mark.asyncio
async def test_concurrent_identical_publication_one_record(database):
    repo = await ready(database)
    obj = envelope()
    results = await asyncio.gather(*(repo.publish(obj) for _ in range(12)))
    assert all(result.envelope == obj for result in results)
    assert await database.db.async_outbox.count_documents({}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", ["id", "dedup", "crossed", "payload"])
async def test_publication_identity_conflicts(database, collision):
    repo = await ready(database)
    first = envelope()
    await repo.publish(first)
    if collision == "id": attempted = replace(first, idempotency_key="other")
    elif collision == "dedup": attempted = replace(first, job_id="other")
    elif collision == "payload": attempted = replace(first, payload_schema_version="fixture-v2")
    else:
        await repo.publish(replace(first, job_id="job2", idempotency_key="key2"))
        attempted = replace(first, idempotency_key="key2")
    before = await stored(database.db)
    with pytest.raises(OutboxConflictError):
        await repo.publish(attempted)
    assert await stored(database.db) == before


@pytest.mark.asyncio
async def test_concurrent_claim_one_current_owner_and_one_increment(database):
    repo = await ready(database)
    await repo.publish(envelope())
    results = await asyncio.gather(*(repo.claim(f"worker{i}", lease_seconds=60) for i in range(12)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1 and winners[0].operational.attempt_count == 1
    doc = await database.db.async_outbox.find_one({"_id": "job1"})
    assert doc["lease_token"] == winners[0].operational.lease_token
    renewed = await repo.renew("job1", doc["lease_token"], lease_seconds=60)
    assert renewed.operational.attempt_count == 1


@pytest.mark.asyncio
async def test_expiry_reclaim_new_token_and_stale_owner_refused(database):
    repo = await ready(database)
    await repo.publish(envelope())
    first = await repo.claim("worker1", lease_seconds=60)
    await expire_fixture_lease(database.db)
    second = await repo.claim("worker2", lease_seconds=60)
    assert second.operational.attempt_count == 2
    assert second.operational.lease_token != first.operational.lease_token
    before = await stored(database.db)
    for method in ("renew", "retry", "fail", "complete"):
        with pytest.raises(OutboxLeaseLostError):
            await owned(repo, method, first.operational.lease_token)
    assert await stored(database.db) == before


@pytest.mark.asyncio
async def test_expired_final_attempt_terminalized_once(database):
    repo = await ready(database)
    await repo.publish(envelope(retry_policy=RetryPolicy(1, 2, 60)))
    await repo.claim("worker1", lease_seconds=60)
    await expire_fixture_lease(database.db)
    assert await repo.claim("worker2", lease_seconds=60) is None
    results = await asyncio.gather(*(repo.terminalize_expired() for _ in range(4)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert winners[0].operational.state is JobState.FAILED
    assert winners[0].operational.failure_code is FailureCode.ATTEMPTS_EXHAUSTED
    assert await repo.terminalize_expired() is None
    assert await database.db.async_outbox.count_documents({"state": "leased"}) == 0


@pytest.mark.asyncio
async def test_retry_server_backoff_and_clear_lease(database):
    repo = await ready(database)
    await repo.publish(envelope())
    claimed = await repo.claim("worker1", lease_seconds=60)
    retried = await repo.retry("job1", claimed.operational.lease_token)
    op = retried.operational
    assert op.state is JobState.PENDING and op.attempt_count == 1
    assert (op.available_at - op.updated_at).total_seconds() == 2
    assert op.lease_owner is None and op.lease_token is None and op.lease_until is None
    assert op.failure_code is FailureCode.TRANSIENT
    with pytest.raises(OutboxLeaseLostError):
        await repo.retry("job1", claimed.operational.lease_token)


@pytest.mark.asyncio
async def test_completion_terminal_token_idempotent(database):
    repo = await ready(database)
    await repo.publish(envelope())
    claimed = await repo.claim("worker1", lease_seconds=60)
    token = claimed.operational.lease_token
    result = await repo.complete("job1", token)
    assert result.operational.state is JobState.COMPLETED
    assert result.operational.completion_token == token
    before = await stored(database.db)
    assert await repo.complete("job1", token) == result
    with pytest.raises(OutboxLeaseLostError):
        await repo.complete("job1", "foreign")
    assert await stored(database.db) == before


@pytest.mark.asyncio
async def test_coupled_requires_active_session(database):
    repo = await ready(database)
    async with await database.client.start_session() as session:
        with pytest.raises(OutboxTransactionRequiredError):
            await repo.publish_in_transaction(envelope(), session=session)
    assert await database.db.async_outbox.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("abort", [False, True])
async def test_transaction_commit_abort_or_standalone_refusal(database, abort):
    repo = await ready(database)
    db = database.db
    await db.create_collection("domain_fixture")

    class AbortFixture(Exception):
        pass

    async def transaction():
        async with await database.client.start_session() as session:
            async with session.start_transaction():
                # Outbox first also proves its coupled path itself refuses a
                # standalone topology before any domain fixture is written.
                await repo.publish_in_transaction(envelope(), session=session)
                await db.domain_fixture.insert_one({"_id": "fixture1"}, session=session)
                assert await db.async_outbox.count_documents({}) == 0
                if abort:
                    raise AbortFixture()

    if database.topology == "standalone":
        with pytest.raises(OperationFailure):
            await transaction()
        expected = 0
    elif abort:
        with pytest.raises(AbortFixture):
            await transaction()
        expected = 0
    else:
        await transaction()
        expected = 1
    assert await db.async_outbox.count_documents({}) == expected
    assert await db.domain_fixture.count_documents({}) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["missing", "wrong"])
async def test_critical_readiness_blocks_mutations(database, broken):
    repo = await ready(database)
    await repo.publish(envelope())
    claimed = await repo.claim("worker1", lease_seconds=60)
    await database.db.async_outbox.drop_index("a14_outbox_dedup_unique")
    if broken == "wrong":
        await database.db.async_outbox.create_index("wrong", name="a14_outbox_dedup_unique", unique=True)
    before = await stored(database.db)
    for method in ("renew", "retry", "fail", "complete"):
        with pytest.raises(OutboxReadinessError):
            await owned(repo, method, claimed.operational.lease_token)
    with pytest.raises(OutboxReadinessError): await repo.publish(envelope(job_id="new", idempotency_key="new"))
    with pytest.raises(OutboxReadinessError): await repo.claim("worker2", lease_seconds=60)
    with pytest.raises(OutboxReadinessError): await repo.terminalize_expired()
    assert await stored(database.db) == before


@pytest.mark.asyncio
async def test_missing_performance_index_is_diagnostic(database):
    repo = await ready(database)
    await database.db.async_outbox.drop_index("a14_outbox_pending_lookup")
    report = await repo.readiness()
    assert report.ok and len(report.diagnostics) == 1
    assert report.diagnostics[0].severity == "warning"
    assert (await repo.publish(envelope())).envelope == envelope()


@pytest.mark.asyncio
async def test_migration_bad_documents_never_repaired(database):
    db = database.db
    await db.async_outbox.insert_one({"_id": "malformed", "schema_version": "future"})
    before = await stored(db)
    with pytest.raises(OutboxMigrationError): await migrate(db, apply=True)
    assert await stored(db) == before
    assert set(await db.async_outbox.index_information()) == {"_id_"}
