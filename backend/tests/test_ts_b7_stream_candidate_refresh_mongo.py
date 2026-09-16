"""B7 STEP 4 G1: refresh orchestration over a real disposable standalone MongoDB.

Run only when an explicit B7_MONGO_URL targets a standalone local Mongo
(127.0.0.1, no auth, no db, no options) AND the pytest-asyncio plugin is
installed. Each test uses an isolated random database test_ts_b7_<uuid> and
drops only that database. Seeding is performed by direct document insertion
through the exact canonical serializers; the only application write path used
is the refresh service itself against the three B7 collections. No
MONGO_URL/DB_NAME/admins/grants/trust are touched.
"""
import asyncio
import os
import re
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
from domains.talent_stream.stream_candidate_persistence import (
    generation_record_document_id,
)
from domains.talent_stream.stream_candidate_refresh import (
    StreamCandidateRefreshCommand,
    StreamCandidateRefreshConflictError,
    StreamCandidateRefreshNotAuthorizedError,
    StreamCandidateRefreshService,
    StreamCandidateRefreshStorageNotReadyError,
    generation_identifier,
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
from scripts.migrate_ts_b7_stream_candidate_projection import migrate

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

NOT_AUTHORIZED_MSG = "stream candidate refresh not authorized"
STORAGE_NOT_READY_MSG = "stream candidate refresh storage is not ready"
STORED_MSG = "invalid stored stream candidate projection"
SCOPE_CHANGED_MSG = "stream candidate refresh scope changed"

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
    return datetime(
        2026, 1, 1, 12, 0, 0,
        tzinfo=timezone.utc,
    ) + timedelta(milliseconds=ms)


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
            captured_at=_utc(1),
        ),
        state=TalentStreamState.ACTIVE,
        created_at=_utc(1),
        updated_at=_utc(2),
        history=(create, activate),
    )


def _closed_stream():
    create = StreamCommandHistoryEntry(
        "create-1", "fp-create", StreamCommandKind.CREATE, None,
        TalentStreamState.DRAFT, EntityVersion(1), _utc(1),
    )
    activate = StreamCommandHistoryEntry(
        "activate-1", "fp-activate", StreamCommandKind.ACTIVATE,
        TalentStreamState.DRAFT, TalentStreamState.ACTIVE, EntityVersion(2), _utc(2),
    )
    close = StreamCommandHistoryEntry(
        "close-1", "fp-close", StreamCommandKind.CLOSE,
        TalentStreamState.ACTIVE, TalentStreamState.CLOSED, EntityVersion(3), _utc(4),
    )
    return TalentStream(
        stream_id=TalentStreamId(STREAM_ID),
        version=EntityVersion(3),
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
            captured_at=_utc(1),
        ),
        state=TalentStreamState.CLOSED,
        created_at=_utc(1),
        updated_at=_utc(4),
        history=(create, activate, close),
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
        "created_at": _utc(5),
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


def _command(command_id="cmd-1", *, refresh_ms=500):
    return StreamCandidateRefreshCommand(STREAM_ID, command_id, _utc(refresh_ms))


def _expected_generation_id(command_id, *, stream_version=STREAM_VERSION):
    return generation_identifier(
        stream_id=STREAM_ID,
        stream_version=stream_version,
        requirement_version=REQUIREMENT_VERSION,
        role_dna_id=ROLE_DNA_ID,
        role_dna_version=ROLE_DNA_VERSION,
        opportunity_spec_id=OPPORTUNITY_SPEC_ID,
        opportunity_spec_version=OPPORTUNITY_VERSION,
        command_id=command_id,
    )


async def _state_counts(database):
    names = sorted(await database.list_collection_names())
    return {
        name: await database[name].count_documents({}) for name in names
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
    migrate_b7=True,
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
    if migrate_b7:
        await migrate(db, apply=True)
    return StreamCandidateRefreshService(db)


@pytest.mark.asyncio
async def test_1_initial_refresh_publishes_generation(b7_db):
    service = await provision(
        b7_db,
        applications=[_application("app-1", "cand-a", ms=30)],
        intent_events=[_b4("cand-b", occurred_at=_utc(100))],
    )
    result = await service.refresh(_command("cmd-1", refresh_ms=1234))
    assert result.stream_id == STREAM_ID
    assert result.generation_id == _expected_generation_id("cmd-1")
    assert result.candidate_count == 2
    assert result.state_version == 1
    assert result.published_at == _utc(1234)

    state_doc = await b7_db.talent_stream_candidate_projection_states.find_one(
        {"_id": STREAM_ID}
    )
    assert state_doc["state_version"] == 1
    assert state_doc["active_generation_id"] == result.generation_id
    assert state_doc["published_at"].tzinfo is None
    assert state_doc["published_at"] == _utc(1234).replace(tzinfo=None)
    ids = sorted(
        document["candidate_id"]
        for document in await b7_db.talent_stream_candidates.find({}).to_list(length=None)
    )
    assert ids == ["cand-a", "cand-b"]


@pytest.mark.asyncio
async def test_2_same_command_retry_is_idempotent(b7_db):
    service = await provision(
        b7_db, applications=[_application("app-1", "cand-a", ms=30)],
    )
    first = await service.refresh(_command("cmd-1", refresh_ms=500))
    second = await service.refresh(_command("cmd-1", refresh_ms=500))
    assert first == second
    assert second.state_version == 1
    assert second.generation_id == _expected_generation_id("cmd-1")
    assert await b7_db.talent_stream_candidate_projection_states.count_documents({}) == 1
    assert await b7_db.talent_stream_candidates.count_documents({}) == 1


@pytest.mark.asyncio
async def test_interrupted_seal_resumes_on_exact_command_retry(b7_db):
    service = await provision(
        b7_db, applications=[_application("app-1", "cand-a", ms=30)],
    )
    first = await service.refresh(_command("cmd-1", refresh_ms=500))
    assert first.candidate_count == 1
    record_id = generation_record_document_id(STREAM_ID, first.generation_id)
    await b7_db.talent_stream_candidate_generations.update_one(
        {"_id": record_id},
        {"$set": {"state": "sealing", "candidate_count": 1}},
    )
    second = await service.refresh(_command("cmd-1", refresh_ms=500))
    assert second == first
    assert second.state_version == 1
    stored = await b7_db.talent_stream_candidate_generations.find_one({"_id": record_id})
    assert stored["state"] == "sealed" and stored["candidate_count"] == 1
    assert await b7_db.talent_stream_candidates.count_documents({}) == 1


@pytest.mark.asyncio
async def test_interrupted_seal_wrong_count_conflicts_without_repair(b7_db):
    service = await provision(
        b7_db, applications=[_application("app-1", "cand-a", ms=30)],
    )
    first = await service.refresh(_command("cmd-1", refresh_ms=500))
    record_id = generation_record_document_id(STREAM_ID, first.generation_id)
    await b7_db.talent_stream_candidate_generations.update_one(
        {"_id": record_id},
        {"$set": {"state": "sealing", "candidate_count": 2}},
    )
    with pytest.raises(StreamCandidateRefreshConflictError) as exc:
        await service.refresh(_command("cmd-1", refresh_ms=500))
    assert str(exc.value) == SCOPE_CHANGED_MSG
    stored = await b7_db.talent_stream_candidate_generations.find_one({"_id": record_id})
    assert stored["state"] == "sealing" and stored["candidate_count"] == 2


@pytest.mark.asyncio
async def test_3_concurrent_commands_one_winner_loser_conflicts_and_is_inactive(b7_db):
    await provision(
        b7_db,
        applications=[_application("app-1", "cand-a", ms=30)],
        intent_events=[_b4("cand-b", occurred_at=_utc(100))],
    )
    service_a = StreamCandidateRefreshService(b7_db)
    service_b = StreamCandidateRefreshService(b7_db)
    results = await asyncio.gather(
        service_a.refresh(_command("cmd-a", refresh_ms=500)),
        service_b.refresh(_command("cmd-b", refresh_ms=500)),
        return_exceptions=True,
    )
    successes = [r for r in results if not isinstance(r, Exception)]
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(successes) == 1, results
    assert len(errors) == 1
    assert type(errors[0]) is StreamCandidateRefreshConflictError
    assert str(errors[0]) == SCOPE_CHANGED_MSG
    winner = successes[0]
    assert winner.state_version == 1
    winner_generation = winner.generation_id
    loser_generation = _expected_generation_id("cmd-a") if (
        winner_generation == _expected_generation_id("cmd-b")
    ) else _expected_generation_id("cmd-b")
    assert loser_generation != winner_generation
    state = await b7_db.talent_stream_candidate_projection_states.find_one(
        {"_id": STREAM_ID}
    )
    assert state["state_version"] == 1
    assert state["active_generation_id"] == winner_generation
    assert await b7_db.talent_stream_candidates.count_documents(
        {"generation_id": winner_generation}
    ) == 2


@pytest.mark.asyncio
async def test_4_empty_generation_publishes_zero_candidates(b7_db):
    service = await provision(b7_db)
    result = await service.refresh(_command())
    assert result.candidate_count == 0
    assert result.state_version == 1
    state = await b7_db.talent_stream_candidate_projection_states.find_one(
        {"_id": STREAM_ID}
    )
    assert state["candidate_count"] == 0
    assert await b7_db.talent_stream_candidates.count_documents({}) == 0


@pytest.mark.asyncio
async def test_5_follow_up_command_advances_version_and_preserves_old_generation(b7_db):
    service = await provision(
        b7_db, applications=[_application("app-1", "cand-a", ms=30)],
    )
    first = await service.refresh(_command("cmd-1", refresh_ms=500))
    await b7_db.applications.insert_one(_application("app-2", "cand-b", ms=40))
    second = await service.refresh(_command("cmd-2", refresh_ms=900))
    assert second.state_version == 2
    assert second.candidate_count == 2
    assert first.state_version == 1
    state = await b7_db.talent_stream_candidate_projection_states.find_one(
        {"_id": STREAM_ID}
    )
    assert state["state_version"] == 2
    assert state["active_generation_id"] == second.generation_id
    assert state["candidate_count"] == 2
    old = await b7_db.talent_stream_candidates.count_documents(
        {"generation_id": first.generation_id}
    )
    assert old == 1


@pytest.mark.asyncio
async def test_6_new_declared_interest_appears_in_follow_up_refresh(b7_db):
    service = await provision(
        b7_db, intent_events=[_b4("cand-a", occurred_at=_utc(100), caller_key="g1-b4-a")],
    )
    first = await service.refresh(_command("cmd-1"))
    assert first.candidate_count == 1
    await b7_db.talent_intent_events.insert_one(
        event_to_document(_b4("cand-b", occurred_at=_utc(110), caller_key="g1-b4-b"))
    )
    second = await service.refresh(_command("cmd-2"))
    assert second.candidate_count == 2
    assert second.state_version == 2


@pytest.mark.asyncio
async def test_7_late_withdrawal_removes_candidate_in_follow_up_refresh(b7_db):
    share = _share("cand-d", "corr-1", occurred_at=_utc(120))
    service = await provision(
        b7_db,
        intent_events=[share],
        saved_jobs=[_saved_job("cand-d", "corr-1")],
    )
    first = await service.refresh(_command("cmd-1"))
    assert first.candidate_count == 1
    withdraw = _withdraw(
        "cand-d", "corr-1", str(share.event_id), occurred_at=_utc(130),
    )
    await b7_db.talent_intent_events.insert_one(event_to_document(withdraw))
    second = await service.refresh(_command("cmd-2"))
    assert second.candidate_count == 0
    assert second.state_version == 2


@pytest.mark.asyncio
async def test_8_share_without_saved_job_is_dropped(b7_db):
    service = await provision(
        b7_db, intent_events=[_share("cand-d", "corr-1", occurred_at=_utc(120))],
    )
    result = await service.refresh(_command())
    assert result.candidate_count == 0
    assert result.state_version == 1


@pytest.mark.asyncio
async def test_9_discovery_enable_change_updates_candidates(b7_db):
    service = await provision(
        b7_db, discovery_candidates=("cand-e",),
    )
    first = await service.refresh(_command("cmd-1"))
    assert first.candidate_count == 1
    await b7_db.candidate_preferences.update_one(
        {"_id": "candidate_preferences:cand-e"},
        {"$set": {"discovery.enabled": False}},
    )
    second = await service.refresh(_command("cmd-2"))
    assert second.candidate_count == 0
    assert second.state_version == 2


@pytest.mark.asyncio
async def test_10_closed_stream_is_refused_and_leaves_projection_untouched(b7_db):
    service = await provision(
        b7_db, applications=[_application("app-1", "cand-a", ms=30)],
    )
    await service.refresh(_command("cmd-1"))
    await b7_db.talent_streams.replace_one(
        {"_id": STREAM_ID}, stream_to_document(_closed_stream())
    )
    with pytest.raises(StreamCandidateRefreshNotAuthorizedError) as exc:
        await service.refresh(_command("cmd-2"))
    assert str(exc.value) == NOT_AUTHORIZED_MSG
    state = await b7_db.talent_stream_candidate_projection_states.find_one(
        {"_id": STREAM_ID}
    )
    assert state["state_version"] == 1
    assert state["active_generation_id"] == _expected_generation_id("cmd-1")


@pytest.mark.asyncio
async def test_11_inactive_recruiter_is_not_authorized_and_writes_nothing(b7_db):
    service = await provision(
        b7_db, applications=[_application("app-1", "cand-a", ms=30)],
    )
    await b7_db.users.update_one(
        {"_id": RECRUITER_ID}, {"$set": {"is_active": False}}
    )
    with pytest.raises(StreamCandidateRefreshNotAuthorizedError) as exc:
        await service.refresh(_command())
    assert str(exc.value) == NOT_AUTHORIZED_MSG
    assert await b7_db.talent_stream_candidate_projection_states.count_documents({}) == 0
    assert await b7_db.talent_stream_candidates.count_documents({}) == 0


@pytest.mark.asyncio
async def test_12_refresh_touches_only_b7_collections(b7_db):
    service = await provision(
        b7_db,
        applications=[_application("app-1", "cand-a", ms=30)],
        intent_events=[_b4("cand-b", occurred_at=_utc(100))],
        discovery_candidates=("cand-e",),
    )
    before = await _state_counts(b7_db)
    await service.refresh(_command())
    after = await _state_counts(b7_db)
    changed = {name for name in before if before[name] != after.get(name, -1)}
    changed |= set(after) - set(before)
    assert changed == {
        "talent_stream_candidates", "talent_stream_candidate_projection_states",
        "talent_stream_candidate_generations",
    }
    for name in after:
        token = name.lower()
        assert not any(
            blocked in token for blocked in ("grant", "permission", "trust", "consent")
        )


@pytest.mark.asyncio
async def test_13_old_generations_are_never_deleted(b7_db):
    service = await provision(
        b7_db, applications=[_application("app-1", "cand-a", ms=30)],
    )
    first = await service.refresh(_command("cmd-1"))
    await b7_db.applications.insert_one(_application("app-2", "cand-b", ms=40))
    await service.refresh(_command("cmd-2"))
    assert await b7_db.talent_stream_candidates.count_documents(
        {"generation_id": first.generation_id}
    ) == 1
    assert await b7_db.talent_stream_candidates.count_documents({}) == 3


@pytest.mark.asyncio
async def test_14_generation_identity_is_deterministic_and_command_scoped(b7_db):
    service = await provision(
        b7_db, applications=[_application("app-1", "cand-a", ms=30)],
    )
    first = await service.refresh(_command("cmd-1"))
    retry = await service.refresh(_command("cmd-1"))
    other = await service.refresh(_command("cmd-2"))
    assert first.generation_id == _expected_generation_id("cmd-1")
    assert first.generation_id == retry.generation_id
    assert other.generation_id == _expected_generation_id("cmd-2")
    assert other.generation_id != first.generation_id
    assert re.fullmatch(
        r"ts-b7-generation-v1:sha256:[0-9a-f]{64}", first.generation_id
    )


@pytest.mark.asyncio
async def test_15_published_at_is_command_timestamp_and_stored_naive_utc(b7_db):
    service = await provision(
        b7_db, applications=[_application("app-1", "cand-a", ms=30)],
    )
    result = await service.refresh(_command("cmd-1", refresh_ms=3456))
    assert result.published_at == _utc(3456)
    stored = await b7_db.talent_stream_candidate_projection_states.find_one(
        {"_id": STREAM_ID}
    )
    assert stored["published_at"].tzinfo is None
    assert stored["published_at"] == _utc(3456).replace(tzinfo=None)


@pytest.mark.asyncio
async def test_16_missing_b7_collections_fail_readiness_without_any_write(b7_db):
    service = await provision(
        b7_db,
        applications=[_application("app-1", "cand-a", ms=30)],
        migrate_b7=False,
    )
    with pytest.raises(StreamCandidateRefreshStorageNotReadyError) as exc:
        await service.refresh(_command())
    assert str(exc.value) == STORAGE_NOT_READY_MSG
    assert "talent_stream_candidates" not in await b7_db.list_collection_names()
    assert "talent_stream_candidate_projection_states" not in (
        await b7_db.list_collection_names()
    )


@pytest.mark.asyncio
async def test_17_invalid_refresh_command_and_identity_values_are_value_errors(b7_db):
    await provision(b7_db)
    with pytest.raises(ValueError) as exc:
        StreamCandidateRefreshCommand("", "cmd-1", _utc(500))
    assert str(exc.value) == "invalid stream candidate refresh command"
    with pytest.raises(ValueError) as exc:
        StreamCandidateRefreshCommand(STREAM_ID, "cmd-2", _utc(1).replace(tzinfo=None))
    assert str(exc.value) == "invalid stream candidate refresh command"
    with pytest.raises(ValueError) as exc:
        generation_identifier(
            stream_id="", stream_version=STREAM_VERSION,
            requirement_version=REQUIREMENT_VERSION, role_dna_id=ROLE_DNA_ID,
            role_dna_version=ROLE_DNA_VERSION, opportunity_spec_id=OPPORTUNITY_SPEC_ID,
            opportunity_spec_version=OPPORTUNITY_VERSION, command_id="cmd-1",
        )
    assert str(exc.value) == "invalid stream candidate refresh generation identity"


@pytest.mark.asyncio
async def test_18_error_messages_are_fixed_and_redacted(b7_db):
    await provision(b7_db)
    forbidden = ["cand-", "recruiter-", "job-", "spec-", "stream-", "@"]
    for message in (NOT_AUTHORIZED_MSG, STORAGE_NOT_READY_MSG, STORED_MSG,
                    SCOPE_CHANGED_MSG):
        for token in forbidden:
            assert token not in message