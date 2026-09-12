"""A14 hermetic contracts and Mongo call boundaries; no network or server."""
import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bson import BSON
from pymongo.errors import DuplicateKeyError
import pytest

from async_outbox.models import (
    JobEnvelope, JobReference, RetryPolicy, OperationalState, OutboxRecord,
    JobState, FailureCode,
)
from async_outbox.serialization import record_to_document, record_from_document
from async_outbox.repository import (
    OutboxRepository, OutboxConflictError, OutboxReadinessError,
    OutboxTransactionRequiredError, OutboxLeaseLostError,
)
from async_outbox.index_requirements import OUTBOX_REQUIREMENT
from scripts import migrate_async_outbox_indexes as migration

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def envelope(**changes):
    return replace(JobEnvelope("job1", "example", "key1", "handler-v1",
                               JobReference("example", "opaque1", 1), RetryPolicy(3, 2, 60), NOW, NOW), **changes)


def record(state=JobState.PENDING):
    if state is JobState.PENDING:
        op = OperationalState(state, 0, NOW, NOW)
    elif state is JobState.COMPLETED:
        op = OperationalState(state, 1, NOW, NOW, completion_token="token1", completed_at=NOW)
    elif state is JobState.FAILED:
        op = OperationalState(state, 3, NOW, NOW, failed_at=NOW, failure_code=FailureCode.ATTEMPTS_EXHAUSTED)
    else:
        op = OperationalState(state, 1, NOW, NOW, lease_owner="worker1", lease_token="token1",
                              lease_until=NOW + timedelta(seconds=30))
    return OutboxRecord(envelope(), op)


def indexes():
    return {"_id_": {"key": [("_id", 1)]}, **{
        i.name: {"key": list(i.keys), "unique": i.unique} for i in OUTBOX_REQUIREMENT.indexes
    }}


class Cursor:
    def __init__(self, values):
        self.values = deepcopy(values)
    def __aiter__(self):
        async def iterate():
            for value in self.values:
                yield value
        return iterate()


class Database:
    """Deliberately exposes no connection/startup/document-mutation API."""
    def __init__(self, *, exists=True, specs=None, docs=()):
        self.exists, self.docs = exists, list(docs)
        self.specs = indexes() if specs is None else specs
        self.insert_one = AsyncMock()
        self.find_one = AsyncMock(return_value=None)
        self.find_one_and_update = AsyncMock(return_value=None)
        self.create_index = AsyncMock(side_effect=self._create_index)
    def __getitem__(self, name):
        assert name == "async_outbox"
        return self
    def with_options(self, **kwargs):
        return self
    async def list_collections(self, **kwargs):
        return Cursor([{"name": "async_outbox", "type": "collection", "options": {}}] if self.exists else [])
    async def index_information(self):
        return deepcopy(self.specs) if self.exists else {}
    def find(self, query):
        assert query == {}
        return Cursor(self.docs)
    async def _create_index(self, keys, **kwargs):
        self.exists = True
        self.specs.setdefault("_id_", {"key": [("_id", 1)]})
        self.specs[kwargs["name"]] = {"key": keys, "unique": kwargs["unique"]}


@pytest.mark.parametrize("state", list(JobState))
def test_strict_roundtrip_all_states(state):
    obj = record(state)
    assert record_from_document(BSON.encode(record_to_document(obj)).decode()) == obj


@pytest.mark.parametrize("version", [2**31, 2**40, 2**63 - 1])
def test_bson_roundtrip_supported_large_reference_version(version):
    obj = replace(record(), envelope=envelope(reference=JobReference("example", "opaque1", version)))
    assert record_from_document(BSON.encode(record_to_document(obj)).decode()) == obj


@pytest.mark.parametrize("key,value", [
    ("unknown", "private"), ("schema_version", "future-v9"), ("attempt_count", True),
    ("created_at", "2026-01-01"), ("created_at", NOW.replace(microsecond=1)),
    ("state", "unknown"), ("correlation_id", None),
])
def test_invalid_document_rejected(key, value):
    doc = record_to_document(record())
    doc[key] = value
    with pytest.raises(ValueError):
        record_from_document(doc)


@pytest.mark.parametrize("changes", [{"max_attempts": True}, {"max_attempts": 0},
                                    {"max_attempts": 101}, {"initial_delay_seconds": 0},
                                    {"max_delay_seconds": 604801}])
def test_retry_bounds(changes):
    with pytest.raises(ValueError):
        replace(RetryPolicy(3, 2, 60), **changes)


def test_utc_precision_and_no_naive_input():
    with pytest.raises(ValueError):
        envelope(created_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValueError):
        JobReference("example", "opaque1", True)
    assert envelope(created_at=NOW.astimezone(timezone(timedelta(hours=2)))).created_at == NOW
    assert RetryPolicy(10, 2, 5).delay_seconds(10) == 5


def test_separate_immutable_envelope_and_operational_snapshot():
    original = record()
    with pytest.raises(FrozenInstanceError):
        original.envelope.job_type = "changed"
    completed = replace(original, operational=record(JobState.COMPLETED).operational)
    assert completed.envelope == original.envelope
    assert original.operational.state is JobState.PENDING
    assert completed.operational.completion_token == "token1"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", list(JobState))
async def test_publication_recovers_both_identities_in_any_state(state):
    db = Database()
    db.insert_one.side_effect = DuplicateKeyError("fictional duplicate")
    doc = record_to_document(record(state))
    db.find_one.side_effect = [doc, deepcopy(doc)]
    result = await OutboxRepository(db).publish(envelope())
    assert result == record(state)
    assert db.find_one.await_args_list[0].args[0] == {"_id": "job1"}
    assert db.find_one.await_args_list[1].args[0] == {"job_type": "example", "idempotency_key": "key1"}
    assert all("session" not in call.kwargs for call in db.find_one.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("collision", ["missing_id", "missing_key", "crossed", "different", "malformed"])
async def test_publication_collision_fails_closed(collision):
    db = Database()
    db.insert_one.side_effect = DuplicateKeyError("fictional duplicate")
    first, second = record_to_document(record()), record_to_document(record())
    if collision == "missing_id": first = None
    if collision == "missing_key": second = None
    if collision == "crossed": second["_id"] = "job2"
    if collision == "different": first["payload_schema_version"] = "handler-v2"
    if collision == "malformed": second["extra"] = "forbidden"
    db.find_one.side_effect = [first, second]
    with pytest.raises(OutboxConflictError):
        await OutboxRepository(db).publish(envelope())


@pytest.mark.asyncio
async def test_claim_single_atomic_call_server_clock_and_fresh_tokens():
    db = Database()
    db.find_one_and_update.return_value = record_to_document(record(JobState.LEASED))
    repo = OutboxRepository(db)
    await repo.claim("worker1", lease_seconds=30)
    first = db.find_one_and_update.await_args
    query, pipeline = first.args
    assert first.kwargs["sort"][-1] == ("_id", 1)
    assert {"$lt": ["$attempt_count", "$retry_policy.max_attempts"]} in query["$expr"]["$and"]
    assert "$$NOW" in repr(query) and "pending" in repr(query) and "leased" in repr(query)
    assert pipeline[0]["$set"]["attempt_count"] == {"$add": ["$attempt_count", 1]}
    assert pipeline[0]["$set"]["lease_until"] == {"$add": ["$$NOW", 30000]}
    assert db.find_one_and_update.await_count == 1
    await repo.claim("worker1", lease_seconds=30)
    assert pipeline[0]["$set"]["lease_token"] != db.find_one_and_update.await_args.args[1][0]["$set"]["lease_token"]
    db.find_one.assert_not_awaited()


async def invoke(repo, method, token="foreign"):
    if method == "publish": return await repo.publish(envelope())
    if method == "coupled": return await repo.publish_in_transaction(envelope(), session=SimpleNamespace(in_transaction=True))
    if method == "claim": return await repo.claim("worker1", lease_seconds=30)
    if method == "terminalize": return await repo.terminalize_expired()
    if method == "renew": return await repo.renew("job1", token, lease_seconds=30)
    if method == "fail": return await repo.fail("job1", token, reason=FailureCode.PERMANENT)
    return await getattr(repo, method)("job1", token)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["renew", "retry", "fail", "complete"])
async def test_stale_token_refused_with_live_lease_predicate(method):
    db = Database()
    with pytest.raises(OutboxLeaseLostError):
        await invoke(OutboxRepository(db), method)
    query = db.find_one_and_update.await_args.args[0]
    assert query["_id"] == "job1" and query["state"] == "leased" and query["lease_token"] == "foreign"
    assert query["$expr"] == {"$gt": ["$lease_until", "$$NOW"]}


@pytest.mark.asyncio
async def test_completion_same_terminal_token_is_read_only():
    db = Database()
    db.find_one.return_value = record_to_document(record(JobState.COMPLETED))
    assert await OutboxRepository(db).complete("job1", "token1") == record(JobState.COMPLETED)
    assert db.find_one.await_args.args[0]["completion_token"] == "token1"
    db.find_one_and_update.assert_not_awaited()


@pytest.mark.asyncio
async def test_terminalization_bounded_atomic_and_repeatable():
    db = Database()
    db.find_one_and_update.side_effect = [record_to_document(record(JobState.FAILED)), None]
    repo = OutboxRepository(db)
    assert (await repo.terminalize_expired()).operational.failure_code is FailureCode.ATTEMPTS_EXHAUSTED
    query, pipeline = db.find_one_and_update.await_args.args
    assert query["state"] == "leased"
    assert {"$gte": ["$attempt_count", "$retry_policy.max_attempts"]} in query["$expr"]["$and"]
    assert {"$lte": ["$lease_until", "$$NOW"]} in query["$expr"]["$and"]
    assert pipeline[0]["$set"]["failure_code"] == "attempts_exhausted"
    assert await repo.terminalize_expired() is None
    assert db.find_one_and_update.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("active", [None, False, 1])
async def test_coupled_requires_active_transaction(active):
    db = Database()
    with pytest.raises(OutboxTransactionRequiredError):
        await OutboxRepository(db).publish_in_transaction(envelope(), session=SimpleNamespace(in_transaction=active))
    db.insert_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_coupled_same_session_and_no_recovery_in_failed_transaction():
    db = Database()
    session = SimpleNamespace(in_transaction=True)
    await OutboxRepository(db).publish_in_transaction(envelope(), session=session)
    assert db.insert_one.await_args.kwargs["session"] is session
    db.insert_one.side_effect = DuplicateKeyError("private synthetic error")
    with pytest.raises(OutboxConflictError):
        await OutboxRepository(db).publish_in_transaction(envelope(), session=session)
    db.find_one.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["publish", "coupled", "claim", "renew", "retry", "fail", "complete", "terminalize"])
@pytest.mark.parametrize("broken", ["missing", "wrong"])
async def test_every_mutation_checks_critical_readiness(method, broken):
    specs = indexes()
    if broken == "missing": del specs["a14_outbox_dedup_unique"]
    else: specs["a14_outbox_dedup_unique"]["unique"] = False
    db = Database(specs=specs)
    with pytest.raises(OutboxReadinessError):
        await invoke(OutboxRepository(db), method)
    db.insert_one.assert_not_awaited()
    db.find_one_and_update.assert_not_awaited()


def test_exact_index_manifest():
    requirement = OUTBOX_REQUIREMENT
    assert requirement.name == "async_outbox"
    assert requirement.ordinary and requirement.simple_collation and requirement.forbid_ttl
    assert [(i.name, i.keys, i.critical, i.unique) for i in requirement.indexes] == [
        ("a14_outbox_dedup_unique", (("job_type", 1), ("idempotency_key", 1)), True, True),
        ("a14_outbox_pending_lookup", (("state", 1), ("available_at", 1), ("_id", 1)), False, False),
        ("a14_outbox_lease_lookup", (("state", 1), ("lease_until", 1), ("_id", 1)), False, False),
    ]
    for index in requirement.indexes:
        assert index.collation == {"locale": "simple"} and index.partial_filter is None
        assert not index.hidden and not index.sparse and index.expire_after_seconds is None


@pytest.mark.asyncio
async def test_migration_default_absent_read_only_then_explicit_apply():
    db = Database(exists=False, specs={})
    assert (await migration.migrate(db))["ready"] is False
    assert not db.exists
    db.create_index.assert_not_awaited()
    assert (await migration.migrate(db, apply=True))["ready"] is True
    assert db.create_index.await_count == 3
    assert (await migration.migrate(db, apply=True))["ready"] is True
    assert db.create_index.await_count == 3
    db.insert_one.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["duplicate", "unknown", "index"])
async def test_migration_rejects_before_any_index_creation(bad):
    doc = record_to_document(record())
    db = Database(specs={"_id_": {"key": [("_id", 1)]}}, docs=[doc])
    if bad == "duplicate": db.docs.append({**doc, "_id": "job2"})
    if bad == "unknown": db.docs[0]["schema_version"] = "future"
    if bad == "index": db.specs["a14_outbox_dedup_unique"] = {"key": [("wrong", 1)], "unique": True}
    with pytest.raises(migration.OutboxMigrationError):
        await migration.migrate(db, apply=True)
    db.create_index.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["MONGO_URL", "DB_NAME"])
async def test_cli_requires_both_variables_without_connecting(monkeypatch, capsys, missing):
    monkeypatch.setenv("MONGO_URL", "mongodb://fictional:secret@invalid.test")
    monkeypatch.setenv("DB_NAME", "fictional")
    monkeypatch.delenv(missing)
    monkeypatch.setattr(migration, "AsyncIOMotorClient", lambda *a, **k: pytest.fail("must not connect"))
    assert await migration.main() == 2
    assert capsys.readouterr().out == '{"error":"explicit_configuration_required"}\n'


@pytest.mark.asyncio
async def test_sanitized_operational_errors_and_no_payload_repr():
    secret = "mongodb://fictional:secret@invalid.test/private"
    db = Database()
    db.list_collections = AsyncMock(side_effect=RuntimeError(secret))
    for call, error in ((OutboxRepository(db).readiness, OutboxReadinessError),
                        (lambda: migration.preflight(db), migration.OutboxMigrationError)):
        with pytest.raises(error) as result:
            await call()
        assert secret not in str(result.value)
    assert "opaque1" not in repr(record()) and "key1" not in repr(envelope())


def test_preflight_has_no_mutation_and_apply_is_explicit():
    assert inspect.signature(migration.migrate).parameters["apply"].default is False
    tree = ast.parse(inspect.getsource(migration.preflight))
    calls = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert not calls & {"create_index", "create_collection", "insert_one", "update_one", "delete_many", "drop", "rename"}
    source = Path(migration.__file__).read_text(encoding="utf-8")
    assert 'action="store_true"' in source and "connect_to_mongo" not in source
