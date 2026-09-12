"""A13 G1: generated databases on explicitly configured loopback standalone.

Only fixtures provision data/indexes. The checker uses metadata reads alone.
No application configuration or shared database fallback is used.
"""
from datetime import datetime, timezone
import os
from urllib.parse import urlsplit
import uuid

from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient
import pytest
import pytest_asyncio

from domains.talent_stream.index_requirements import TS_INDEX_REQUIREMENTS
from scripts.check_ts_mongo_invariants import check_database, main


@pytest_asyncio.fixture
async def db():
    url = os.environ.get("A13_MONGO_URL")
    if not url:
        pytest.skip("A13_MONGO_URL must designate disposable standalone Mongo")
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme == "mongodb" and parsed.hostname == "127.0.0.1"
                 and parsed.port is not None and parsed.port > 0
                 and parsed.netloc == f"127.0.0.1:{parsed.port}"
                 and parsed.path in ("", "/") and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        pytest.fail("A13 requires explicit loopback port without credentials/database/options")
    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000, socketTimeoutMS=5000)
    name = "test_ts_a13_" + uuid.uuid4().hex
    standalone = False
    try:
        hello = await client.admin.command("hello")
        assert "setName" not in hello and hello.get("msg") != "isdbgrid"
        standalone = True
        yield client[name]
    finally:
        try:
            if standalone:
                assert name.startswith("test_ts_a13_") and len(name) == 44
                await client.drop_database(name)
        finally:
            client.close()


async def provision(db, *, omit=None, override=None, shape=None):
    """Test-only setup; no migration or application startup is invoked."""
    for collection in TS_INDEX_REQUIREMENTS:
        options = shape if collection.name == "talent_intent_events" and shape else {}
        await db.create_collection(collection.name, **options)
        if options.get("viewOn") or options.get("timeseries"):
            continue
        for index in collection.indexes:
            if index.name == omit:
                continue
            kwargs = {"name": index.name, "unique": index.unique}
            if index.partial_filter is not None:
                kwargs["partialFilterExpression"] = dict(index.partial_filter)
            if index.collation is not None:
                kwargs["collation"] = dict(index.collation)
            keys = list(index.keys)
            if override and index.name == override[0]:
                changes = dict(override[1])
                keys = changes.pop("key", keys)
                kwargs.update(changes)
            await db[collection.name].create_index(keys, **kwargs)


async def snapshot(db):
    result = {}
    cursor = await db.list_collections()
    async for record in cursor:
        name = record["name"]
        docs = await db[name].find({}).sort("_id", 1).to_list(length=None)
        indexes = await db[name].index_information() if record["type"] == "collection" else {}
        result[name] = (record, indexes, tuple(BSON.encode(doc) for doc in docs))
    return result


@pytest.mark.asyncio
async def test_empty_db_remains_empty(db):
    before = await snapshot(db)
    report = await check_database(db)
    assert not report.ok
    assert len(report.diagnostics) == 13
    assert {d.code for d in report.diagnostics} == {"missing_collection"}
    assert await snapshot(db) == before == {}


@pytest.mark.asyncio
async def test_conforming_repeatable_and_bson_documents_unchanged(db):
    await provision(db)
    await db.candidate_profiles.insert_one({
        "_id": "fictional-1", "candidate_id": "fictional-1", "version": 1,
        "profile": {"display_name": "Fictional Candidate", "skills": ["Python"]},
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    })
    before = await snapshot(db)
    first = await check_database(db)
    assert first.ok and first.diagnostics == ()
    assert await check_database(db) == first
    assert await snapshot(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,code", [
    ({"key": [("wrong_key", 1)]}, "keys"),
    ({"unique": False}, "unique"),
    ({"hidden": True}, "hidden"),
    ({"partialFilterExpression": {"candidate_id": {"$type": "string"}}}, "partial_filter"),
])
async def test_expected_name_wrong_definition(db, changes, code):
    await provision(db, override=("ts_a1_candidate_id_unique", changes))
    before = await snapshot(db)
    report = await check_database(db)
    assert not report.ok and code in {d.code for d in report.diagnostics}
    assert await snapshot(db) == before


@pytest.mark.asyncio
async def test_missing_performance_index_is_warning(db):
    await provision(db, omit="ts_a8_recruiter_verification_state")
    report = await check_database(db)
    assert report.ok
    assert len(report.diagnostics) == 1
    assert report.diagnostics[0].severity == "warning"


@pytest.mark.asyncio
@pytest.mark.parametrize("changes,code", [
    ({"expireAfterSeconds": 3600}, "forbidden_ttl"),
    ({"collation": {"locale": "en", "strength": 2}}, "collation"),
])
async def test_a11_incompatible_index_options(db, changes, code):
    await provision(db, override=("ts_a11_idempotency_key_unique", changes))
    before = await snapshot(db)
    report = await check_database(db)
    assert not report.ok and code in {d.code for d in report.diagnostics}
    assert await snapshot(db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("shape,code", [
    ({"capped": True, "size": 1048576}, "collection_shape"),
    ({"timeseries": {"timeField": "at"}}, "collection_shape"),
    ({"viewOn": "candidate_profiles", "pipeline": []}, "collection_shape"),
    ({"collation": {"locale": "en", "strength": 2}}, "collection_collation"),
])
async def test_a11_collection_contract(db, shape, code):
    await provision(db, shape=shape)
    before = await snapshot(db)
    report = await check_database(db)
    assert not report.ok and code in {d.code for d in report.diagnostics}
    assert await snapshot(db) == before


@pytest.mark.asyncio
async def test_cli_exit_status_with_disposable_database(db, monkeypatch, capsys):
    monkeypatch.setenv("MONGO_URL", os.environ["A13_MONGO_URL"])
    monkeypatch.setenv("DB_NAME", db.name)
    assert await main() == 1
    assert await db.list_collection_names() == []
    await provision(db)
    assert await main() == 0
    output = capsys.readouterr().out
    assert db.name not in output and os.environ["A13_MONGO_URL"] not in output
