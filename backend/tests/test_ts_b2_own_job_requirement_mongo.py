"""TS-B2 G1 against an explicitly configured disposable standalone MongoDB."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from urllib.parse import urlsplit
import uuid

from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient
import pytest
import pytest_asyncio

from domains.talent_stream.index_requirements import TS_INDEX_REQUIREMENTS
from domains.talent_stream.own_job_mapping import (
    OwnJobMappingError,
    OwnJobSourceConflictError,
)
from domains.talent_stream.own_job_repository import (
    OwnJobAccessError,
    OwnJobReadinessError,
)
from domains.talent_stream.own_job_service import OwnJobRequirementService


NOW = datetime(2026, 9, 12, 22, 0, tzinfo=timezone.utc)
TARGET_COLLECTIONS = {"role_dnas", "opportunity_specs"}


@pytest_asyncio.fixture
async def db():
    url = os.environ.get("B2_MONGO_URL")
    if not url:
        pytest.skip("B2_MONGO_URL must designate disposable standalone Mongo")
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
        pytest.fail("B2 requires explicit loopback port without credentials/database/options")

    client = AsyncIOMotorClient(
        url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
        socketTimeoutMS=5000,
    )
    name = "test_ts_b2_" + uuid.uuid4().hex
    standalone = False
    try:
        hello = await client.admin.command("hello")
        assert "setName" not in hello and hello.get("msg") != "isdbgrid"
        standalone = True
        yield client[name]
    finally:
        try:
            if standalone:
                assert name.startswith("test_ts_b2_") and len(name) == 43
                await client.drop_database(name)
        finally:
            client.close()


def source_job(**changes):
    value = {
        "_id": "job-1",
        "employer_id": "recruiter-1",
        "company_id": "company-1",
        "title": "Backend Engineer",
        "description": "Build APIs",
        "location": "Paris",
        "salary_min": 50000,
        "salary_max": 70000,
        "salary_currency": "EUR",
        "job_type": "CDI",
        "is_remote": True,
        "requirements": ["Python"],
        "benefits": ["Transport"],
        "tags": ["backend"],
        "is_active": False,
        "expires_at": NOW - timedelta(days=1),
    }
    value.update(changes)
    return value


async def provision(db, *, job=None):
    for requirement in TS_INDEX_REQUIREMENTS:
        if requirement.name not in TARGET_COLLECTIONS:
            continue
        await db.create_collection(requirement.name)
        for index in requirement.indexes:
            kwargs = {"name": index.name, "unique": index.unique}
            if index.partial_filter is not None:
                kwargs["partialFilterExpression"] = dict(index.partial_filter)
            if index.collation is not None:
                kwargs["collation"] = dict(index.collation)
            await db[requirement.name].create_index(list(index.keys), **kwargs)
    await db.users.insert_one({
        "_id": "recruiter-1", "user_type": "employer", "is_active": True,
    })
    await db.companies.insert_one({
        "_id": "company-1", "owner_id": "recruiter-1",
    })
    await db.jobs.insert_one(job or source_job())
    return OwnJobRequirementService(db)


async def target_bson(db):
    result = {}
    for name in sorted(TARGET_COLLECTIONS):
        documents = await db[name].find({}).sort("_id", 1).to_list(length=None)
        result[name] = tuple(BSON.encode(document) for document in documents)
    return result


@pytest.mark.asyncio
async def test_exact_mapping_retry_and_concurrency_converge_without_source_mutation(db):
    service = await provision(db)
    source_before = BSON.encode(await db.jobs.find_one({"_id": "job-1"}))

    results = await asyncio.gather(*(
        service.prepare(
            "recruiter-1", "job-1", command_id="command-1", captured_at=NOW,
        )
        for _ in range(8)
    ))

    assert all(result == results[0] for result in results)
    assert await db.role_dnas.count_documents({}) == 1
    assert await db.opportunity_specs.count_documents({}) == 1
    assert BSON.encode(await db.jobs.find_one({"_id": "job-1"})) == source_before

    role = await db.role_dnas.find_one({})
    opportunity = await db.opportunity_specs.find_one({})
    assert role["version"] == 1 and role["status"] == "draft"
    assert role["canonical_title"] == "Backend Engineer"
    assert role["skills"] == role["capabilities"] == []
    assert opportunity["version"] == 1 and opportunity["status"] == "draft"
    assert opportunity["compensation"] == {
        "minimum": 50000, "maximum": 70000, "currency": "EUR", "basis": None,
    }
    assert opportunity["location"] == {"locations": ["Paris"], "radius_km": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("change,error", [
    ({"employer_id": "other-recruiter"}, OwnJobAccessError),
    ({"is_partner": True}, OwnJobMappingError),
    ({"external_url": "https://example.test/job"}, OwnJobMappingError),
])
async def test_unowned_partner_and_external_sources_leave_targets_empty(db, change, error):
    service = await provision(db, job=source_job(**change))
    with pytest.raises(error):
        await service.prepare(
            "recruiter-1", "job-1", command_id="command-1", captured_at=NOW,
        )
    assert await target_bson(db) == {"opportunity_specs": (), "role_dnas": ()}


@pytest.mark.asyncio
async def test_current_company_ownership_is_required_for_every_preparation(db):
    service = await provision(db)
    await service.prepare(
        "recruiter-1", "job-1", command_id="command-1", captured_at=NOW,
    )
    before = await target_bson(db)
    await db.companies.update_one(
        {"_id": "company-1"}, {"$set": {"owner_id": "other-recruiter"}},
    )
    with pytest.raises(OwnJobAccessError):
        await service.prepare("recruiter-1", "job-1", command_id="command-2")
    assert await target_bson(db) == before


@pytest.mark.asyncio
async def test_same_command_changed_source_conflicts_but_new_command_creates_new_pair(db):
    service = await provision(db)
    first = await service.prepare(
        "recruiter-1", "job-1", command_id="command-1", captured_at=NOW,
    )
    await db.jobs.update_one(
        {"_id": "job-1"}, {"$set": {"title": "Platform Engineer"}},
    )
    before = await target_bson(db)
    with pytest.raises(OwnJobSourceConflictError):
        await service.prepare("recruiter-1", "job-1", command_id="command-1")
    assert await target_bson(db) == before

    second = await service.prepare(
        "recruiter-1", "job-1", command_id="command-2",
        captured_at=NOW + timedelta(seconds=1),
    )
    assert second.requirement_snapshot.role_dna != first.requirement_snapshot.role_dna
    assert await db.role_dnas.count_documents({}) == 2
    assert await db.opportunity_specs.count_documents({}) == 2


@pytest.mark.asyncio
async def test_b2_does_not_create_or_mutate_talent_stream_documents(db):
    service = await provision(db)
    sentinel = {
        "_id": "existing-stream", "state": "draft", "private": "unchanged",
    }
    await db.talent_streams.insert_one(deepcopy(sentinel))
    before = BSON.encode(await db.talent_streams.find_one({"_id": "existing-stream"}))
    await service.prepare(
        "recruiter-1", "job-1", command_id="command-1", captured_at=NOW,
    )
    after = BSON.encode(await db.talent_streams.find_one({"_id": "existing-stream"}))
    assert after == before
    assert await db.talent_streams.count_documents({}) == 1


@pytest.mark.asyncio
async def test_incompatible_target_metadata_fails_before_any_write(db):
    service = await provision(db)
    await db.opportunity_specs.create_index(
        [("expires_at", 1)], name="unexpected_ttl", expireAfterSeconds=60,
    )
    with pytest.raises(OwnJobReadinessError):
        await service.prepare(
            "recruiter-1", "job-1", command_id="command-1", captured_at=NOW,
        )
    assert await target_bson(db) == {"opportunity_specs": (), "role_dnas": ()}
