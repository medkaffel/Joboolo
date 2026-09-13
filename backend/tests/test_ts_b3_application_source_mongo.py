"""TS-B3 G1 against an explicitly configured disposable standalone MongoDB."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from urllib.parse import urlsplit
import uuid

from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient
import pytest
import pytest_asyncio

from domains.shared.ids import (
    HiringCompanyId,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import EntityVersion
from domains.talent_stream.application_source_models import ApplicationSourceCursor
from domains.talent_stream.application_source_repository import (
    ApplicationSourceReadinessError,
)
from domains.talent_stream.application_source_service import (
    ApplicationSourceAccessError,
    ApplicationSourceConflictError,
    ApplicationSourceService,
    ApplicationSourceStoredDataError,
)
from domains.talent_stream.contracts import (
    OpportunitySpecificationRef,
    RecruitingActorContext,
    RoleDNARef,
    StreamRequirementSnapshot,
)
from domains.talent_stream.index_requirements import TS_INDEX_REQUIREMENTS
from domains.talent_stream.stream_models import (
    StreamCommandHistoryEntry,
    StreamCommandKind,
    TalentStream,
    TalentStreamState,
)
from domains.talent_stream.stream_repository import stream_to_document
from models import ApplicationStatus


NOW = datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc)
REQUIRED_TS_COLLECTIONS = {"talent_streams", "opportunity_specs", "organizations"}


@pytest_asyncio.fixture
async def db():
    url = os.environ.get("B3_MONGO_URL")
    if not url:
        pytest.skip("B3_MONGO_URL must designate disposable standalone Mongo")
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
        pytest.fail("B3 requires explicit loopback port without credentials/database/options")

    client = AsyncIOMotorClient(
        url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
        socketTimeoutMS=5000,
    )
    name = "test_ts_b3_" + uuid.uuid4().hex
    standalone = False
    try:
        hello = await client.admin.command("hello")
        assert "setName" not in hello and hello.get("msg") != "isdbgrid"
        standalone = True
        yield client[name]
    finally:
        try:
            if standalone:
                assert name.startswith("test_ts_b3_") and len(name) == 43
                await client.drop_database(name)
        finally:
            client.close()


def talent_stream():
    actor = RecruitingActorContext(
        recruiter_user_id=RecruiterUserId("recruiter-1"),
        requesting_organization_id=OrganizationId("requesting-org-1"),
        hiring_company_id=HiringCompanyId("hiring-org-1"),
        mandate_id=None,
    )
    requirement = StreamRequirementSnapshot(
        role_dna=RoleDNARef(RoleDNAId("role-1"), EntityVersion(1)),
        opportunity_spec=OpportunitySpecificationRef(
            OpportunitySpecId("opportunity-1"), EntityVersion(1),
        ),
        requirement_version=EntityVersion(1),
        captured_at=NOW,
    )
    created = StreamCommandHistoryEntry(
        command_id="create-1",
        command_fingerprint="fingerprint-1",
        command_kind=StreamCommandKind.CREATE,
        from_state=None,
        to_state=TalentStreamState.DRAFT,
        resulting_version=EntityVersion(1),
        occurred_at=NOW,
    )
    return TalentStream(
        stream_id=TalentStreamId("stream-1"),
        version=EntityVersion(1),
        recruiting_actor_context=actor,
        requirement_snapshot=requirement,
        state=TalentStreamState.DRAFT,
        created_at=NOW,
        updated_at=NOW,
        history=(created,),
    )


def source_job(**changes):
    value = {
        "_id": "job-1",
        "employer_id": "recruiter-1",
        "company_id": "company-1",
        "title": "Backend Engineer",
        "is_active": False,
        "expires_at": NOW - timedelta(days=1),
    }
    value.update(changes)
    return value


def application(application_id="application-1", **changes):
    value = {
        "_id": application_id,
        "candidate_id": "candidate-1",
        "job_id": "job-1",
        "status": "pending",
        "created_at": NOW + timedelta(minutes=1),
        # Forbidden data exists in storage to prove the strict projection.
        "cv_url": "private/cv.pdf",
        "cover_letter": "private letter",
        "employer_notes": "private notes",
    }
    value.update(changes)
    return value


async def provision(db, *, job=None, applications=None, application_index=True):
    for requirement in TS_INDEX_REQUIREMENTS:
        if requirement.name not in REQUIRED_TS_COLLECTIONS:
            continue
        await db.create_collection(requirement.name)
        for index in requirement.indexes:
            kwargs = {"name": index.name, "unique": index.unique}
            if index.partial_filter is not None:
                kwargs["partialFilterExpression"] = dict(index.partial_filter)
            if index.collation is not None:
                kwargs["collation"] = dict(index.collation)
            await db[requirement.name].create_index(list(index.keys), **kwargs)

    await db.create_collection("applications")
    if application_index:
        await db.applications.create_index(
            [("job_id", 1), ("candidate_id", 1)],
            unique=True,
            name="job_id_1_candidate_id_1",
        )
    await db.users.insert_one({
        "_id": "recruiter-1", "user_type": "employer", "is_active": True,
        "email": "must-not-be-read@example.invalid",
    })
    await db.companies.insert_one({
        "_id": "company-1", "owner_id": "recruiter-1", "name": "Fictional",
    })
    await db.organizations.insert_one({
        "_id": "hiring-org-1",
        "organization_id": "hiring-org-1",
        "legacy_company_id": "company-1",
        "version": 1,
        "legal_name": "Fictional SAS",
        "verification_state": "unverified",
        "created_at": NOW,
        "updated_at": NOW,
    })
    await db.jobs.insert_one(job or source_job())
    await db.opportunity_specs.insert_one({
        "_id": "opportunity-1:v1",
        "opportunity_spec_id": "opportunity-1",
        "version": 1,
        "provenance": "internal_job",
        "source_job_id": "job-1",
        "source_ref": "ts-b2-own-job-v2:future-compatible",
        "version_provenance": "internal_job",
        "version_provenance_ref": "ts-b2-own-job-v2:future-compatible",
    })
    await db.talent_streams.insert_one(stream_to_document(talent_stream()))
    if applications:
        await db.applications.insert_many(deepcopy(applications))
    return ApplicationSourceService(db)


async def snapshot(db):
    result = {}
    for name in sorted(await db.list_collection_names()):
        documents = await db[name].find({}).sort("_id", 1).to_list(length=None)
        result[name] = tuple(BSON.encode(document) for document in documents)
    return result


@pytest.mark.asyncio
async def test_nominal_projection_future_mapping_and_no_writes_without_job_id_single_index(db):
    service = await provision(db, applications=[
        application("application-2", candidate_id="candidate-2", status="accepted", created_at=NOW + timedelta(minutes=2)),
        application("application-1", status="reviewed"),
    ])
    assert set(await db.applications.index_information()) == {"_id_", "job_id_1_candidate_id_1"}
    before = await snapshot(db)
    result = await service.list_page("recruiter-1", "stream-1")
    assert await snapshot(db) == before
    assert tuple(item.application_id for item in result) == ("application-1", "application-2")
    assert tuple(item.status for item in result) == (
        ApplicationStatus.REVIEWED, ApplicationStatus.ACCEPTED,
    )
    assert all(set(item.__dataclass_fields__) == {
        "application_id", "candidate_id", "job_id", "status", "applied_at",
    } for item in result)


@pytest.mark.asyncio
async def test_empty_and_exact_job_filter(db):
    service = await provision(db, applications=[
        application("other", candidate_id="candidate-2", job_id="job-2"),
    ])
    assert await service.list_page("recruiter-1", "stream-1") == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "reviewed", "accepted", "rejected"])
async def test_all_canonical_statuses_and_bson_dates(db, status):
    service = await provision(db, applications=[application(status=status)])
    result = await service.list_page("recruiter-1", "stream-1")
    assert result[0].status.value == status
    assert result[0].applied_at.tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_pagination_and_deterministic_tie_breaker(db):
    documents = [
        application(
            f"application-{index:03}",
            candidate_id=f"candidate-{index:03}",
            created_at=NOW + timedelta(milliseconds=index // 2),
        )
        for index in reversed(range(101))
    ]
    service = await provision(db, applications=documents)
    first = await service.list_page("recruiter-1", "stream-1")
    second = await service.list_page(
        "recruiter-1", "stream-1",
        after=ApplicationSourceCursor(first[-1].applied_at, first[-1].application_id),
    )
    identifiers = [item.application_id for item in first + second]
    assert len(first) == 100 and len(second) == 1
    assert identifiers == sorted(identifiers)


@pytest.mark.asyncio
@pytest.mark.parametrize("marker,value", [
    ("source", "monster.fr"),
    ("is_partner", True),
    ("partner_id", "partner-1"),
    ("campaign_id", "campaign-1"),
    ("external_url", "https://example.test/job"),
    ("external_ref", "external-1"),
])
async def test_non_native_job_markers_are_denied(db, marker, value):
    service = await provision(db, job=source_job(**{marker: value}), applications=[application()])
    with pytest.raises(ApplicationSourceAccessError):
        await service.list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("target,change", [
    ("users", {"is_active": False}),
    ("users", {"user_type": "candidate"}),
    ("jobs", {"employer_id": "other-recruiter"}),
    ("companies", {"owner_id": "other-recruiter"}),
    ("organizations", {"legacy_company_id": "company-2"}),
])
async def test_current_user_job_company_and_organization_scope_is_required(db, target, change):
    service = await provision(db, applications=[application()])
    await db[target].update_one({}, {"$set": change})
    with pytest.raises(ApplicationSourceAccessError):
        await service.list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"provenance": "imported"},
    {"version_provenance": "imported"},
    {"source_job_id": "job-2"},
    {"source_ref": "one", "version_provenance_ref": "two"},
])
async def test_invalid_a4_fails_closed(db, changes):
    service = await provision(db, applications=[application()])
    await db.opportunity_specs.update_one({}, {"$set": changes})
    with pytest.raises((ApplicationSourceAccessError, ApplicationSourceStoredDataError)):
        await service.list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
async def test_inactive_expired_job_is_allowed_but_deleted_job_is_denied(db):
    service = await provision(db, applications=[application()])
    assert len(await service.list_page("recruiter-1", "stream-1")) == 1
    await db.jobs.delete_one({"_id": "job-1"})
    with pytest.raises(ApplicationSourceAccessError):
        await service.list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"status": "unknown"},
    {"candidate_id": None},
    {"created_at": "2026-09-13"},
])
async def test_malformed_matching_application_fails_closed(db, changes):
    service = await provision(db, applications=[application(**changes)])
    with pytest.raises(ApplicationSourceStoredDataError):
        await service.list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
async def test_missing_unique_index_and_historical_duplicate_fail_readiness(db):
    service = await provision(
        db,
        application_index=False,
        applications=[application(), application("application-2")],
    )
    with pytest.raises(ApplicationSourceReadinessError):
        await service.list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
async def test_concurrent_ownership_transfer_is_a_conflict(db):
    service = await provision(db, applications=[application()])
    original = service.repository.list_applications

    async def transfer(*args, **kwargs):
        result = await original(*args, **kwargs)
        await db.jobs.update_one({"_id": "job-1"}, {"$set": {"employer_id": "other-recruiter"}})
        return result

    service.repository.list_applications = transfer
    with pytest.raises(ApplicationSourceConflictError):
        await service.list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
async def test_concurrent_application_change_is_a_point_in_time_fact(db):
    service = await provision(db, applications=[application()])
    original = service.repository.list_applications

    async def change_status(*args, **kwargs):
        result = await original(*args, **kwargs)
        await db.applications.update_one(
            {"_id": "application-1"}, {"$set": {"status": "accepted"}},
        )
        return result

    service.repository.list_applications = change_status
    result = await service.list_page("recruiter-1", "stream-1")
    assert result[0].status is ApplicationStatus.PENDING
    service.repository.list_applications = original
    assert (await service.list_page("recruiter-1", "stream-1"))[0].status is ApplicationStatus.ACCEPTED
