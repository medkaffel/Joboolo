"""B7 STEP 3 G1: aggregation over a real disposable standalone MongoDB.

Run only when an explicit B7_MONGO_URL targets a standalone local Mongo
(127.0.0.1, no auth, no db, no options) AND the pytest-asyncio plugin is
installed. Each test uses an isolated random database test_ts_b7_<uuid> and
drops only that database. Seeding is performed by direct document insertion
through the exact canonical serializers; no application write path is used.
No MONGO_URL/DB_NAME/admins/grants are touched.
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pytest_asyncio  # noqa: F401
    HAVE_PYTEST_ASYNCIO = True
except ModuleNotFoundError:
    HAVE_PYTEST_ASYNCIO = False

from domains.intent.serialization import event_to_document
from domains.matching.opportunity_fit_models import (
    HardEligibilityState,
    OpportunityFitState,
)
from domains.talent_stream.application_source_service import ApplicationSourceConflictError
from domains.talent_stream.contracts import (
    OpportunitySpecificationRef,
    RecruitingActorContext,
    RoleDNARef,
    StreamRequirementSnapshot,
)
from domains.talent_stream.events import (
    IntentKind,
    IntentOrigin,
    IntentSourceType,
    IntentSubject,
    TalentIntentEvent,
)
from domains.talent_stream.index_requirements import TS_INDEX_REQUIREMENTS
from domains.talent_stream.stream_candidate_aggregation import (
    BuiltStreamCandidateGeneration,
    StreamCandidateAggregationAccessError,
    StreamCandidateAggregationConflictError,
    StreamCandidateAggregationReadinessError,
    StreamCandidateAggregationService,
    StreamCandidateAggregationStoredDataError,
)
from domains.talent_stream.stream_candidate_intent_source import (
    B4_EVENT_ID_PREFIX,
    B4_EVENT_TYPE,
    B4_IDEMPOTENCY_PREFIX,
    B5_SHARE_EVENT_ID_PREFIX,
    B5_SHARE_EVENT_TYPE,
    B5_SHARE_IDEMPOTENCY_PREFIX,
    B5_WITHDRAW_EVENT_ID_PREFIX,
    B5_WITHDRAW_EVENT_TYPE,
    B5_WITHDRAW_IDEMPOTENCY_PREFIX,
)
from domains.talent_stream.stream_models import (
    StreamCommandHistoryEntry,
    StreamCommandKind,
    TalentStream,
    TalentStreamState,
)
from domains.talent_stream.stream_repository import stream_to_document
from domains.shared.ids import (
    CandidateId,
    HiringCompanyId,
    IdempotencyKey,
    IntentEventId,
    JobId,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import EntityVersion, SchemaVersion
from models import ApplicationStatus

B7_MONGO_URL = os.environ.get("B7_MONGO_URL")

pytestmark = pytest.mark.skipif(
    not HAVE_PYTEST_ASYNCIO or not B7_MONGO_URL,
    reason="G1 NOT RUN LOCALLY — no explicit B7_MONGO_URL (and/or pytest_asyncio missing)",
)

STREAM_ID = "stream-1"
STREAM_VERSION = 2
REQUIREMENT_VERSION = 1
ROLE_DNA_ID = "role-1"
ROLE_DNA_VERSION = 1
OPPORTUNITY_SPEC_ID = "spec-1"
OPPORTUNITY_VERSION = 1
SOURCE_JOB_ID = "job-1"
RECRUITER_ID = "recruiter-1"
GENERATION_ID = "generation-abc"

ACCESS_MSG = "stream candidate aggregation not authorized"
READINESS_MSG = "stream candidate aggregation storage is not ready"
STORED_MSG = "invalid stored stream candidate source"
CONFLICT_MSG = "stream candidate aggregation scope changed"

_REQUIRED_TS_COLLECTIONS = {
    "talent_streams",
    "opportunity_specs",
    "organizations",
    "candidate_preferences",
    "role_dnas",
    "candidate_profiles",
    "talent_intent_events",
}


def _utc(ms=0):
    return datetime(2026, 1, 1, 12, 0, 0, ms * 1000, tzinfo=timezone.utc)


def _canonical_identity(version, candidate_id, caller_key):
    encoded = json.dumps(
        [version, candidate_id, caller_key], ensure_ascii=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _event(
    candidate_id,
    job_id,
    occurred_at,
    event_type,
    version,
    event_prefix,
    key_prefix,
    correlation_id=None,
    causation_id=None,
    caller_key="g1-caller-key",
):
    digest = _canonical_identity(version, candidate_id, caller_key)
    return TalentIntentEvent(
        event_id=IntentEventId(f"{event_prefix}{digest}"),
        schema_version=SchemaVersion("intent-event-v1"),
        subject=IntentSubject(candidate_id=CandidateId(candidate_id)),
        intent_kind=IntentKind.JOB,
        origin=IntentOrigin.DECLARED,
        event_type=event_type,
        occurred_at=occurred_at,
        created_at=occurred_at,
        source_type=IntentSourceType("candidate_declared"),
        idempotency_key=IdempotencyKey(f"{key_prefix}{digest}"),
        job_id=JobId(job_id),
        correlation_id=correlation_id,
        causation_id=causation_id,
    )


def _b4(candidate_id, job_id=SOURCE_JOB_ID, occurred_at=_utc(100),
         caller_key="g1-b4"):
    return _event(
        candidate_id, job_id, occurred_at, B4_EVENT_TYPE,
        "ts-b4-v1", B4_EVENT_ID_PREFIX, B4_IDEMPOTENCY_PREFIX,
        caller_key=caller_key,
    )


def _share(candidate_id, correlation_id, job_id=SOURCE_JOB_ID,
           occurred_at=_utc(120), caller_key="g1-b5-share"):
    return _event(
        candidate_id, job_id, occurred_at, B5_SHARE_EVENT_TYPE,
        "ts-b5-share-v1", B5_SHARE_EVENT_ID_PREFIX, B5_SHARE_IDEMPOTENCY_PREFIX,
        correlation_id=correlation_id, caller_key=caller_key,
    )


def _withdraw(candidate_id, correlation_id, causation_id, job_id=SOURCE_JOB_ID,
              occurred_at=_utc(130), caller_key="g1-b5-withdraw"):
    return _event(
        candidate_id, job_id, occurred_at, B5_WITHDRAW_EVENT_TYPE,
        "ts-b5-withdraw-v1", B5_WITHDRAW_EVENT_ID_PREFIX, B5_WITHDRAW_IDEMPOTENCY_PREFIX,
        correlation_id=correlation_id, causation_id=causation_id,
        caller_key=caller_key,
    )


def _stream():
    create = StreamCommandHistoryEntry(
        "create-1", "fp-create", StreamCommandKind.CREATE, None,
        TalentStreamState.DRAFT, EntityVersion(1), _utc(1),
    )
    activate = StreamCommandHistoryEntry(
        "activate-1", "fp-activate", StreamCommandKind.ACTIVATE,
        TalentStreamState.DRAFT, TalentStreamState.ACTIVE, EntityVersion(2), _utc(2),
    )
    return TalentStream(
        stream_id=TalentStreamId(STREAM_ID),
        version=EntityVersion(STREAM_VERSION),
        recruiting_actor_context=RecruitingActorContext(
            recruiter_user_id=RecruiterUserId(RECRUITER_ID),
            requesting_organization_id=OrganizationId("org-1"),
            hiring_company_id=HiringCompanyId("hiring-org-1"),
            mandate_id=None,
        ),
        requirement_snapshot=StreamRequirementSnapshot(
            role_dna=RoleDNARef(RoleDNAId(ROLE_DNA_ID), EntityVersion(ROLE_DNA_VERSION)),
            opportunity_spec=OpportunitySpecificationRef(
                OpportunitySpecId(OPPORTUNITY_SPEC_ID), EntityVersion(OPPORTUNITY_VERSION),
            ),
            requirement_version=EntityVersion(REQUIREMENT_VERSION),
            captured_at=_utc(3),
        ),
        state=TalentStreamState.ACTIVE,
        created_at=_utc(1),
        updated_at=_utc(2),
        history=(create, activate),
    )


def _job():
    return {
        "_id": SOURCE_JOB_ID,
        "employer_id": RECRUITER_ID,
        "company_id": "company-1",
        "title": "Backend Engineer",
        "is_active": True,
        "expires_at": _utc(0) + timedelta(days=30),
    }


def _opportunity(**overrides):
    doc = {
        "_id": f"{OPPORTUNITY_SPEC_ID}:v{OPPORTUNITY_VERSION}",
        "opportunity_spec_id": OPPORTUNITY_SPEC_ID,
        "version": OPPORTUNITY_VERSION,
        "provenance": "internal_job",
        "source_job_id": SOURCE_JOB_ID,
        "source_ref": "ts-b2-own-job-v2:future-compatible",
        "version_provenance": "internal_job",
        "version_provenance_ref": "ts-b2-own-job-v2:future-compatible",
        "status": "active",
        "created_at": _utc(4),
        "updated_at": _utc(4),
        "contract_types": [],
        "industry_constraints": [],
        "company_constraints": [],
        "must_have_requirements": [],
        "nice_to_have_requirements": [],
    }
    doc.update(overrides)
    return doc


def _application(application_id, candidate_id, *, ms, status="pending"):
    return {
        "_id": application_id,
        "candidate_id": candidate_id,
        "job_id": SOURCE_JOB_ID,
        "status": status,
        "created_at": _utc(ms),
    }


def _saved_job(candidate_id, correlation_id, *, created_ms=50,
               updated_ms=60, user_id=None, job_id=SOURCE_JOB_ID,
               doc_id=None):
    return {
        "_id": doc_id or correlation_id,
        "user_id": user_id or candidate_id,
        "job_id": job_id,
        "created_at": _utc(created_ms),
        "updated_at": _utc(updated_ms),
    }


def _preference(candidate_id):
    return {
        "_id": f"candidate_preferences:{candidate_id}",
        "candidate_id": candidate_id,
        "version": 1,
        "updated_at": _utc(5),
        "search_state": "passive",
        "discovery": {
            "enabled": True,
            "allow_compatible_opportunities": True,
            "ask_before_reveal": True,
            "anonymous_only": True,
        },
        "excluded_company_ids": [],
    }


def _profile(candidate_id):
    return {
        "_id": f"candidate_profile:{candidate_id}",
        "candidate_id": candidate_id,
        "version": 1,
        "created_at": _utc(4),
        "updated_at": _utc(5),
        "occupations": [],
        "experiences": [],
        "skills": [],
        "certifications": [],
        "languages": [],
        "industries": [],
        "education": [],
        "portfolio": [],
    }


def _role_dna():
    return {
        "_id": f"{ROLE_DNA_ID}:v{ROLE_DNA_VERSION}",
        "role_dna_id": ROLE_DNA_ID,
        "version": ROLE_DNA_VERSION,
        "status": "active",
        "canonical_title": "Backend Engineer",
        "created_at": _utc(4),
        "updated_at": _utc(4),
        "aliases": [],
        "skills": [],
        "capabilities": [],
        "certifications": [],
        "languages": [],
        "transferable_role_refs": [],
        "adjacent_role_refs": [],
        "provenance": "manual",
    }


if HAVE_PYTEST_ASYNCIO:

    @pytest_asyncio.fixture
    async def b7_db():
        if not B7_MONGO_URL:
            pytest.skip("G1 NOT RUN LOCALLY — no explicit B7_MONGO_URL")
        parsed = urlsplit(B7_MONGO_URL)
        if parsed.scheme != "mongodb":
            pytest.fail("B7_MONGO_URL must use scheme mongodb")
        if parsed.hostname != "127.0.0.1" or parsed.port is None:
            pytest.fail("B7_MONGO_URL must target loopback 127.0.0.1 with an explicit port")
        if parsed.netloc != f"127.0.0.1:{parsed.port}":
            pytest.fail("B7_MONGO_URL must contain only host and port (no credentials)")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            pytest.fail("B7_MONGO_URL must not carry a database, options, or fragment")

        import motor.motor_asyncio

        client = motor.motor_asyncio.AsyncIOMotorClient(
            f"mongodb://127.0.0.1:{parsed.port}/", serverSelectionTimeoutMS=1000
        )
        hello = await client.admin.command("hello")
        if "setName" in hello:
            client.close()
            pytest.fail("G1 requires a standalone local Mongo, not a replica set")
        database_name = f"test_ts_b7_{uuid.uuid4().hex}"
        database = client[database_name]
        try:
            yield database
        finally:
            await client.drop_database(database_name)
            client.close()

else:

    @pytest.fixture
    def b7_db():
        pytest.skip("G1 NOT RUN LOCALLY — no explicit B7_MONGO_URL")


async def provision(
    db,
    *,
    applications=(),
    intent_events=(),
    saved_jobs=(),
    discovery_candidates=(),
    opportunity=None,
    include_b7_scan_index=True,
    include_saved_jobs_unique_index=True,
):
    existing = set(await db.list_collection_names())
    for requirement in TS_INDEX_REQUIREMENTS:
        if requirement.name not in _REQUIRED_TS_COLLECTIONS:
            continue
        if requirement.name not in existing:
            await db.create_collection(requirement.name)
        for index in requirement.indexes:
            kwargs = {"name": index.name, "unique": index.unique}
            if index.partial_filter is not None:
                kwargs["partialFilterExpression"] = dict(index.partial_filter)
            if index.collation is not None:
                kwargs["collation"] = dict(index.collation)
            await db[requirement.name].create_index(list(index.keys), **kwargs)

    await db.create_collection("applications")
    await db.applications.create_index(
        [("job_id", 1), ("candidate_id", 1)],
        unique=True,
        name="job_id_1_candidate_id_1",
    )
    await db.create_collection("saved_jobs")
    if include_saved_jobs_unique_index:
        await db.saved_jobs.create_index(
            [("user_id", 1), ("job_id", 1)],
            unique=True,
            name="ts_b5_saved_job_candidate_job_unique",
        )
    if not include_b7_scan_index:
        await db.talent_intent_events.drop_index("ts_b7_intent_job_event_scan")

    await db.users.insert_many(
        [{"_id": RECRUITER_ID, "user_type": "employer", "is_active": True}]
        + [
            {"_id": candidate_id, "user_type": "candidate", "is_active": True}
            for candidate_id in discovery_candidates
        ]
    )
    await db.companies.insert_one({
        "_id": "company-1", "owner_id": RECRUITER_ID, "name": "Fictional",
    })
    await db.organizations.insert_one({
        "_id": "hiring-org-1",
        "organization_id": "hiring-org-1",
        "legacy_company_id": "company-1",
        "version": 1,
        "legal_name": "Fictional SAS",
        "verification_state": "unverified",
        "created_at": _utc(1),
        "updated_at": _utc(1),
    })
    await db.jobs.insert_one(_job())
    await db.opportunity_specs.insert_one(
        _opportunity() if opportunity is None else opportunity
    )
    await db.talent_streams.insert_one(stream_to_document(_stream()))
    await db.role_dnas.insert_one(_role_dna())
    if discovery_candidates:
        await db.candidate_profiles.insert_many(
            [_profile(candidate_id) for candidate_id in discovery_candidates]
        )
        await db.candidate_preferences.insert_many(
            [_preference(candidate_id) for candidate_id in discovery_candidates]
        )
    if applications:
        await db.applications.insert_many(applications)
    if intent_events:
        docs = [event_to_document(event) for event in intent_events]
        await db.talent_intent_events.insert_many(docs)
    if saved_jobs:
        await db.saved_jobs.insert_many(saved_jobs)
    return StreamCandidateAggregationService(db)


class _ConflictAppsSource:
    def __init__(self, wrapped, on_call):
        self.wrapped = wrapped
        self.on_call = on_call
        self.calls = 0

    async def list_page(self, recruiter_id, stream_id, *, after=None, limit=100):
        self.calls += 1
        if self.calls == self.on_call:
            raise ApplicationSourceConflictError("application source changed")
        return await self.wrapped.list_page(
            recruiter_id, stream_id, after=after, limit=limit,
        )


@pytest.mark.asyncio
async def test_1_four_source_aggregation_and_identity(b7_db):
    service = await provision(
        b7_db,
        applications=[
            _application("app-1", "cand-a", ms=30, status="reviewed"),
            _application("app-2", "cand-b", ms=31, status="rejected"),
        ],
        intent_events=[
            _b4("cand-c", occurred_at=_utc(100)),
            _share("cand-d", "corr-1", occurred_at=_utc(120)),
        ],
        saved_jobs=[_saved_job("cand-d", "corr-1")],
        discovery_candidates=("cand-e",),
    )
    result = await service.build_generation(
        STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
    )
    assert isinstance(result, BuiltStreamCandidateGeneration)
    assert result.candidate_count == 5
    assert [str(c.candidate_id) for c in result.candidates] == [
        "cand-a", "cand-b", "cand-c", "cand-d", "cand-e",
    ]
    cand = result.candidates[0]
    assert cand.application_evidence is not None
    assert cand.application_evidence.status == ApplicationStatus.REVIEWED.value
    declared = next(c for c in result.candidates if str(c.candidate_id) == "cand-c")
    assert str(declared.declared_interest_evidence.event_id).startswith(
        "ts-b4-event-v1:sha256:"
    )
    shared = next(c for c in result.candidates if str(c.candidate_id) == "cand-d")
    assert shared.shared_favorite_evidence.correlation_id == "corr-1"
    discovered = next(c for c in result.candidates if str(c.candidate_id) == "cand-e")
    assert discovered.discovery_evidence is not None
    assert discovered.professional_match_summary is not None
    assert discovered.opportunity_fit_summary is not None
    assert discovered.opportunity_fit_summary.hard_eligibility_state == (
        HardEligibilityState.ELIGIBLE
    )
    assert discovered.computed_at == _utc(500)
    with pytest.raises(AttributeError):
        result.candidates[0].candidate_id = "changed"


@pytest.mark.asyncio
async def test_2_application_pagination_and_final_revalidation_check(b7_db):
    many = [
        _application(f"app-{i:03d}", f"cand-{i:03d}", ms=i)
        for i in range(107)
    ]
    service = await provision(b7_db, applications=many)
    result = await service.build_generation(
        STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
    )
    assert result.candidate_count == 107
    ids = [str(c.candidate_id) for c in result.candidates]
    assert ids == sorted(ids)


@pytest.mark.asyncio
async def test_3_intent_pagination_over_500_events(b7_db):
    events = [
        _b4(f"cand-{i:03d}", occurred_at=_utc(i), caller_key=f"key-{i:03d}")
        for i in range(505)
    ]
    service = await provision(b7_db, intent_events=events)
    result = await service.build_generation(
        STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
    )
    assert result.candidate_count == 505


@pytest.mark.asyncio
async def test_4_shared_favorite_keeps_latest_validated_representative(b7_db):
    service = await provision(
        b7_db,
        intent_events=[
            _share("cand-d", "corr-1", occurred_at=_utc(120), caller_key="k-share-1"),
            _share("cand-d", "corr-2", occurred_at=_utc(125), caller_key="k-share-2"),
        ],
        saved_jobs=[
            _saved_job("cand-d", "corr-1"),
            _saved_job("cand-d", "corr-2"),
        ],
    )
    result = await service.build_generation(
        STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
    )
    assert result.candidate_count == 1
    cand = result.candidates[0]
    assert cand.shared_favorite_evidence.correlation_id == "corr-2"
    assert cand.shared_favorite_evidence.occurred_at == _utc(125)
    assert cand.declared_interest_evidence is None


@pytest.mark.asyncio
async def test_5_valid_withdrawal_excludes_share(b7_db):
    share = _share("cand-d", "corr-1", occurred_at=_utc(120))
    withdraw = _withdraw(
        "cand-d", "corr-1", str(share.event_id), occurred_at=_utc(130),
    )
    service = await provision(
        b7_db,
        intent_events=[share, withdraw],
        saved_jobs=[_saved_job("cand-d", "corr-1")],
    )
    result = await service.build_generation(
        STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
    )
    assert result.candidate_count == 0


@pytest.mark.asyncio
async def test_6_foreign_job_intent_document_fails_closed(b7_db):
    service = await provision(
        b7_db,
        intent_events=[_b4("cand-a", job_id="job-other", occurred_at=_utc(100))],
    )
    with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
        await service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        )
    assert str(exc.value) == STORED_MSG


@pytest.mark.asyncio
async def test_7_malformed_opportunity_spec_fails_closed(b7_db):
    service = await provision(
        b7_db,
        opportunity=_opportunity(provenance="manual"),
    )
    with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
        await service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        )
    assert str(exc.value) == STORED_MSG
    assert "spec-" not in str(exc.value) and "stream-" not in str(exc.value)


@pytest.mark.asyncio
async def test_8_missing_opportunity_spec_fails_closed(b7_db):
    service = await provision(b7_db)
    await b7_db.opportunity_specs.drop()
    with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
        await service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        )
    assert str(exc.value) == STORED_MSG


@pytest.mark.asyncio
async def test_9_inconsistent_saved_job_fails_closed(b7_db):
    service = await provision(
        b7_db,
        intent_events=[_share("cand-d", "corr-1", occurred_at=_utc(120))],
        saved_jobs=[_saved_job("cand-d", "corr-1", user_id="other-user")],
    )
    with pytest.raises(StreamCandidateAggregationStoredDataError) as exc:
        await service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        )
    assert str(exc.value) == STORED_MSG


@pytest.mark.asyncio
async def test_10_share_without_saved_job_is_dropped(b7_db):
    service = await provision(
        b7_db,
        intent_events=[_share("cand-d", "corr-1", occurred_at=_utc(120))],
    )
    result = await service.build_generation(
        STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
    )
    assert result.candidate_count == 0


@pytest.mark.asyncio
async def test_11_missing_b7_scan_index_blocks_readiness_without_repair(b7_db):
    service = await provision(b7_db, include_b7_scan_index=False)
    indexes_before = await b7_db.talent_intent_events.index_information()
    with pytest.raises(StreamCandidateAggregationReadinessError) as exc:
        await service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        )
    assert str(exc.value) == READINESS_MSG
    assert await b7_db.talent_intent_events.index_information() == indexes_before


@pytest.mark.asyncio
async def test_12_missing_saved_jobs_unique_index_blocks_readiness(b7_db):
    service = await provision(
        b7_db,
        include_saved_jobs_unique_index=False,
        intent_events=[_share("cand-d", "corr-1", occurred_at=_utc(120))],
    )
    with pytest.raises(StreamCandidateAggregationReadinessError) as exc:
        await service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        )
    assert str(exc.value) == READINESS_MSG


@pytest.mark.asyncio
async def test_13_application_conflict_maps_to_conflict(b7_db):
    many = [
        _application(f"app-{i:03d}", f"cand-{i:03d}", ms=i)
        for i in range(110)
    ]
    service = await provision(b7_db, applications=many)
    service.applications = _ConflictAppsSource(service.applications, on_call=2)
    with pytest.raises(StreamCandidateAggregationConflictError) as exc:
        await service.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        )
    assert str(exc.value) == CONFLICT_MSG
    assert service.applications.calls == 2


@pytest.mark.asyncio
async def test_14_deterministic_rebuild_and_missing_stream_access(b7_db):
    service1 = await provision(b7_db)
    result1 = await service1.build_generation(
        STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
    )
    service2 = await provision(b7_db)
    result2 = await service2.build_generation(
        STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
    )
    assert result1 == result2
    await b7_db.talent_streams.delete_one({"_id": STREAM_ID})
    with pytest.raises(StreamCandidateAggregationAccessError) as exc:
        await service2.build_generation(
            STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
        )
    assert str(exc.value) == ACCESS_MSG


@pytest.mark.asyncio
async def test_15_inactive_discovery_candidate_is_excluded(b7_db):
    service = await provision(
        b7_db,
        intent_events=[_b4("cand-c", occurred_at=_utc(100))],
        discovery_candidates=("cand-e",),
    )
    await b7_db.users.update_one(
        {"_id": "cand-e"}, {"$set": {"is_active": False}}
    )
    result = await service.build_generation(
        STREAM_ID, generation_id=GENERATION_ID, computed_at=_utc(500),
    )
    assert [str(c.candidate_id) for c in result.candidates] == ["cand-c"]


@pytest.mark.asyncio
async def test_16_errors_are_redacted_fixed_messages(b7_db):
    service = await provision(b7_db)
    forbidden = ["cand-", "recruiter-", "job-", "spec-", "stream-", "@", GENERATION_ID]
    for message in (ACCESS_MSG, READINESS_MSG, STORED_MSG, CONFLICT_MSG):
        for token in forbidden:
            assert token not in message