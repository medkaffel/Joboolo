"""B10.2 strict persistence G1 on an explicit disposable rs0 MongoDB."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError
import pytest
import pytest_asyncio

from domains.shared.ids import (
    CandidateId,
    HiringCompanyId,
    IdempotencyKey,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.talent_stream.anonymous_talent_adapter import (
    derive_anonymous_talent_card_ref,
)
from domains.talent_stream.contact_request_models import (
    CreateContactRequestCommand,
    create_contact_request,
)
from domains.talent_stream.contact_request_persistence import (
    CONTACT_REQUEST_OPTIONAL_FIELDS,
    CONTACT_REQUEST_REQUIRED_FIELDS,
    contact_request_from_document,
    contact_request_to_document,
)
from domains.talent_stream.contact_request_repository import (
    ContactRequestConflictError,
    ContactRequestReadinessError,
    ContactRequestRepository,
    ContactRequestRepositoryError,
    ContactRequestTransactionRequiredError,
)
from domains.talent_stream.contracts import RecruitingActorContext
from domains.trust.contact_governor_models import (
    ContactGovernorRequest,
    GovernorReservationState,
    derive_request_fingerprint,
    derive_reservation_id,
)
from scripts.migrate_ts_b10_contact_requests import (
    B10MigrationError,
    COLLECTION,
    RESERVATION_UNIQUE_KEY,
    RESERVATION_UNIQUE_NAME,
    migrate,
    preflight,
)


NOW = datetime(2026, 9, 22, 14, 0, 0, 123000, tzinfo=timezone.utc)
CARD_KEY = b"b10-persistence-card-key-32-bytes-minimum"


@pytest_asyncio.fixture
async def database():
    url = os.environ.get("B10_REPLICA_SET_URL")
    if not url:
        pytest.skip("explicit B10 disposable replica-set Mongo URL required")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "mongodb"
            and parsed.hostname in ("localhost", "127.0.0.1")
            and parsed.port is not None
            and parsed.port > 0
            and parsed.netloc == f"{parsed.hostname}:{parsed.port}"
            and parsed.path in ("", "/")
            and parsed.query == "replicaSet=rs0"
            and not parsed.fragment
        )
    except ValueError:
        valid = False
    if not valid:
        pytest.fail("B10 requires loopback rs0 with an explicit port and no other options")
    client = AsyncIOMotorClient(
        url,
        serverSelectionTimeoutMS=5000,
        socketTimeoutMS=5000,
    )
    name = "test_ts_b10_" + uuid.uuid4().hex
    verified = False
    try:
        hello = await client.admin.command("hello")
        assert hello.get("msg") != "isdbgrid" and hello.get("setName") == "rs0"
        verified = True
        yield SimpleNamespace(db=client[name], client=client)
    finally:
        try:
            if verified:
                assert name.startswith("test_ts_b10_") and len(name) == 44
                await client.drop_database(name)
        finally:
            client.close()


def actor(*, recruiter="recruiter-1", requesting="org-1", hiring="company-1"):
    return RecruitingActorContext(
        recruiter_user_id=RecruiterUserId(recruiter),
        requesting_organization_id=OrganizationId(requesting),
        hiring_company_id=HiringCompanyId(hiring),
        mandate_id=None,
    )


def governor_request(*, key="request-1", candidate="candidate-1"):
    return ContactGovernorRequest(
        idempotency_key=IdempotencyKey(key),
        candidate_id=CandidateId(candidate),
        stream_id=TalentStreamId("stream-1"),
        generation_id="generation-1",
        projection_state_version=2,
        stream_version=3,
        requirement_version=4,
        role_dna_id=RoleDNAId("role-1"),
        role_dna_version=5,
        opportunity_spec_id=OpportunitySpecId("opportunity-1"),
        opportunity_spec_version=6,
        recruiting_actor=actor(),
    )


def binding(*, key="request-1", candidate="candidate-1"):
    request = governor_request(key=key, candidate=candidate)
    return SimpleNamespace(
        reservation_id=derive_reservation_id(request),
        request_fingerprint=derive_request_fingerprint(request),
        idempotency_key=str(request.idempotency_key),
        candidate_id=str(request.candidate_id),
        stream_id=str(request.stream_id),
        generation_id=request.generation_id,
        projection_state_version=request.projection_state_version,
        stream_version=request.stream_version,
        requirement_version=request.requirement_version,
        role_dna_id=str(request.role_dna_id),
        role_dna_version=request.role_dna_version,
        opportunity_spec_id=str(request.opportunity_spec_id),
        opportunity_spec_version=request.opportunity_spec_version,
        recruiter_user_id=str(request.recruiting_actor.recruiter_user_id),
        requesting_organization_id=str(
            request.recruiting_actor.requesting_organization_id
        ),
        hiring_company_id=str(request.recruiting_actor.hiring_company_id),
        mandate_id=None,
        policy_version="contact-governor-v1-test",
        activity_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        status=GovernorReservationState.RESERVED,
        contact_request_id=None,
    )


def aggregate(*, key="request-1", candidate="candidate-1"):
    reservation = binding(key=key, candidate=candidate)
    card_ref = derive_anonymous_talent_card_ref(
        key=CARD_KEY,
        stream_id=reservation.stream_id,
        generation_id=reservation.generation_id,
        candidate_id=reservation.candidate_id,
    )
    command = CreateContactRequestCommand(
        idempotency_key=IdempotencyKey(reservation.idempotency_key),
        reservation_id=reservation.reservation_id,
        governor_request_fingerprint=reservation.request_fingerprint,
        anonymous_card_ref=card_ref,
        recruiting_actor=actor(),
    )
    return create_contact_request(
        command,
        reservation,
        card_ref_key=CARD_KEY,
        created_at=NOW + timedelta(milliseconds=1),
    )


async def snapshot(db):
    result = {}
    cursor = await db.list_collections()
    async for record in cursor:
        name = record["name"]
        documents = await db[name].find({}).sort("_id", 1).to_list(None)
        indexes = await db[name].index_information()
        result[name] = (
            record,
            indexes,
            tuple(BSON.encode(document) for document in documents),
        )
    return result


def test_strict_bson_roundtrip_and_naive_utc_boundary():
    request = aggregate()
    document = contact_request_to_document(request)
    assert set(document) == CONTACT_REQUEST_REQUIRED_FIELDS
    assert set(document).isdisjoint(CONTACT_REQUEST_OPTIONAL_FIELDS)
    decoded = BSON.encode(document).decode()
    assert decoded["created_at"].tzinfo is None
    assert contact_request_from_document(decoded) == request


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("contact_request_id", "ts-b10-request-v1-" + "0" * 64),
        ("command_fingerprint", "ts-b10-command-v1:" + "0" * 64),
        ("state", "created"),
        ("reservation_activity_at", NOW.replace(tzinfo=None)),
        ("reservation_expires_at", (NOW + timedelta(minutes=5)).replace(tzinfo=None)),
        ("created_at", (NOW + timedelta(milliseconds=1)).replace(tzinfo=None)),
        ("created_at", NOW + timedelta(microseconds=1)),
    ],
)
def test_serializer_rejects_corrupted_frozen_aggregate(field, value):
    request = aggregate()
    object.__setattr__(request, field, value)
    with pytest.raises(ValueError, match="request must be a valid ContactRequest"):
        contact_request_to_document(request)


def test_serializer_rejects_corrupted_nested_actor():
    request = aggregate()
    object.__setattr__(
        request.recruiting_actor,
        "recruiter_user_id",
        RecruiterUserId("different-recruiter"),
    )
    with pytest.raises(ValueError, match="request must be a valid ContactRequest"):
        contact_request_to_document(request)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda document: document.update(extra="candidate-secret@example.test"),
        lambda document: document.pop("reservation_id"),
        lambda document: document.update(version=True),
        lambda document: document.update(version=2),
        lambda document: document.update(state="accepted"),
        lambda document: document.update(created_at="not-a-date"),
        lambda document: document.update(
            created_at=NOW.replace(tzinfo=None, microsecond=123001)
        ),
        lambda document: document.update(candidate_id="different-candidate"),
        lambda document: document.update(_id="ts-b10-request-v1-" + "0" * 64),
        lambda document: document.update(handoff_job_id="not-canonical"),
        lambda document: document.update(mandate_id=None),
    ],
)
def test_strict_rehydration_rejects_malformed_or_contradictory_documents(mutation):
    document = contact_request_to_document(aggregate())
    mutation(document)
    with pytest.raises((ValueError, TypeError, KeyError, OverflowError)):
        contact_request_from_document(document)


def test_persistence_contains_no_unnecessary_sensitive_payload():
    document = contact_request_to_document(aggregate())
    forbidden = {
        "profile",
        "email",
        "phone",
        "cv",
        "message",
        "match",
        "fit",
        "permission_evidence",
        "trust_evidence",
        "provenance",
        "anonymous_card",
        "invitation",
        "decision",
    }
    assert set(document).isdisjoint(forbidden)
    assert type(document["anonymous_card_ref"]) is str


@pytest.mark.asyncio
async def test_migration_dry_run_apply_repeat_and_exact_metadata(database):
    before = await snapshot(database.db)
    dry = await migrate(database.db, apply=False)
    assert dry == {
        "collection": False,
        "indexes_ready": [],
        "documents_checked": 0,
        "ready": False,
    }
    assert await snapshot(database.db) == before == {}

    applied = await migrate(database.db, apply=True)
    assert applied == {
        "collection": True,
        "indexes_ready": [RESERVATION_UNIQUE_NAME],
        "documents_checked": 0,
        "ready": True,
    }
    metadata = await database.db[COLLECTION].index_information()
    assert set(metadata) == {"_id_", RESERVATION_UNIQUE_NAME}
    assert metadata[RESERVATION_UNIQUE_NAME]["key"] == RESERVATION_UNIQUE_KEY
    assert metadata[RESERVATION_UNIQUE_NAME]["unique"] is True
    stable = await snapshot(database.db)
    assert await migrate(database.db, apply=True) == applied
    assert await snapshot(database.db) == stable


@pytest.mark.asyncio
async def test_migration_rejects_wrong_collection_collation(database):
    await database.db.create_collection(
        COLLECTION,
        collation={"locale": "en", "strength": 2},
    )
    before = await snapshot(database.db)
    with pytest.raises(B10MigrationError):
        await preflight(database.db)
    assert await snapshot(database.db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["wrong_key", "nonunique", "extra", "ttl"])
async def test_migration_rejects_incompatible_extra_and_ttl_indexes(
    database, corruption
):
    await database.db.create_collection(COLLECTION, collation={"locale": "simple"})
    collection = database.db[COLLECTION]
    if corruption == "wrong_key":
        await collection.create_index(
            [("candidate_id", 1)],
            name=RESERVATION_UNIQUE_NAME,
            unique=True,
        )
    elif corruption == "nonunique":
        await collection.create_index(
            RESERVATION_UNIQUE_KEY,
            name=RESERVATION_UNIQUE_NAME,
            unique=False,
        )
    elif corruption == "extra":
        await collection.create_index([("candidate_id", 1)], name="unexpected")
    else:
        await collection.create_index(
            [("created_at", 1)],
            name="forbidden_ttl",
            expireAfterSeconds=60,
        )
    before = await snapshot(database.db)
    with pytest.raises(B10MigrationError):
        await migrate(database.db, apply=True)
    assert await snapshot(database.db) == before


@pytest.mark.asyncio
async def test_migration_rejects_malformed_existing_document(database):
    await database.db.create_collection(COLLECTION, collation={"locale": "simple"})
    await database.db[COLLECTION].insert_one(
        {"_id": "malformed", "secret": "candidate-secret@example.test"}
    )
    before = await snapshot(database.db)
    with pytest.raises(B10MigrationError) as raised:
        await preflight(database.db)
    assert "candidate-secret" not in str(raised.value)
    assert await snapshot(database.db) == before


@pytest.mark.asyncio
async def test_migration_rejects_duplicate_reservation_bindings(database):
    await database.db.create_collection(COLLECTION, collation={"locale": "simple"})
    first = contact_request_to_document(aggregate())
    second = deepcopy(first)
    second["_id"] = "ts-b10-request-v1-" + "f" * 64
    await database.db[COLLECTION].insert_many([first, second])
    before = await snapshot(database.db)
    with pytest.raises(B10MigrationError, match="duplicate B10 reservation binding"):
        await preflight(database.db)
    assert await snapshot(database.db) == before


@pytest.mark.asyncio
async def test_repository_readiness_and_exact_get_hit_miss(database):
    repository = ContactRequestRepository(database.db)
    with pytest.raises(ContactRequestReadinessError):
        await repository.readiness()
    await migrate(database.db, apply=True)
    assert (await repository.readiness()).ok
    request = aggregate()
    await database.db[COLLECTION].insert_one(contact_request_to_document(request))
    assert await repository.get(str(request.contact_request_id)) == request
    missing = str(aggregate(key="missing").contact_request_id)
    assert await repository.get(missing) is None


@pytest.mark.asyncio
async def test_repository_get_uses_optional_caller_session(database):
    await migrate(database.db, apply=True)
    repository = ContactRequestRepository(database.db)
    request = aggregate()
    await database.db[COLLECTION].insert_one(contact_request_to_document(request))
    async with await database.client.start_session() as session:
        session.start_transaction()
        assert await repository.get(
            str(request.contact_request_id), session=session
        ) == request
        await session.abort_transaction()


@pytest.mark.asyncio
async def test_transaction_only_insert_rejects_missing_and_inactive_session(database):
    await migrate(database.db, apply=True)
    repository = ContactRequestRepository(database.db)
    before = await snapshot(database.db)
    with pytest.raises(ContactRequestTransactionRequiredError):
        await repository.insert(aggregate(), session=None)
    with pytest.raises(ContactRequestTransactionRequiredError):
        await repository.insert(
            aggregate(), session=SimpleNamespace(in_transaction=False)
        )
    assert await snapshot(database.db) == before


@pytest.mark.asyncio
async def test_transaction_insert_commit_and_rollback(database):
    await migrate(database.db, apply=True)
    repository = ContactRequestRepository(database.db)
    committed = aggregate(key="committed", candidate="candidate-commit")
    rolled_back = aggregate(key="rolled-back", candidate="candidate-rollback")
    async with await database.client.start_session() as session:
        session.start_transaction()
        await repository.insert(committed, session=session)
        await session.commit_transaction()
    async with await database.client.start_session() as session:
        session.start_transaction()
        await repository.insert(rolled_back, session=session)
        await session.abort_transaction()
    assert await repository.get(str(committed.contact_request_id)) == committed
    assert await repository.get(str(rolled_back.contact_request_id)) is None
    assert "async_outbox" not in await database.db.list_collection_names()


@pytest.mark.asyncio
async def test_repository_duplicate_is_fixed_redacted_conflict(database):
    await migrate(database.db, apply=True)
    repository = ContactRequestRepository(database.db)
    request = aggregate()
    async with await database.client.start_session() as session:
        session.start_transaction()
        await repository.insert(request, session=session)
        await session.commit_transaction()
    async with await database.client.start_session() as session:
        session.start_transaction()
        with pytest.raises(ContactRequestConflictError) as raised:
            await repository.insert(request, session=session)
        await session.abort_transaction()
    assert str(raised.value) == "contact request persistence conflict"
    assert str(request.candidate_id) not in str(raised.value)


@pytest.mark.asyncio
async def test_concurrent_transaction_inserts_admit_exactly_one_request(database):
    await migrate(database.db, apply=True)
    repository = ContactRequestRepository(database.db)
    request = aggregate(key="concurrent")

    async def attempt():
        async with await database.client.start_session() as session:
            session.start_transaction()
            try:
                await repository.insert(request, session=session)
                await session.commit_transaction()
                return "committed"
            except ContactRequestRepositoryError:
                if session.in_transaction:
                    await session.abort_transaction()
                return "denied"

    outcomes = await asyncio.gather(attempt(), attempt())
    assert outcomes.count("committed") == 1
    assert outcomes.count("denied") == 1
    documents = await database.db[COLLECTION].find({}).to_list(None)
    assert len(documents) == 1
    assert contact_request_from_document(documents[0]) == request


@pytest.mark.asyncio
async def test_unique_reservation_index_is_enforced(database):
    await migrate(database.db, apply=True)
    first = contact_request_to_document(aggregate())
    conflicting = deepcopy(first)
    conflicting["_id"] = "ts-b10-request-v1-" + "e" * 64
    await database.db[COLLECTION].insert_one(first)
    with pytest.raises(DuplicateKeyError):
        await database.db[COLLECTION].insert_one(conflicting)


@pytest.mark.asyncio
async def test_malformed_runtime_record_fails_closed_and_redacts(database):
    await migrate(database.db, apply=True)
    repository = ContactRequestRepository(database.db)
    request = aggregate()
    await database.db[COLLECTION].insert_one(
        {
            "_id": str(request.contact_request_id),
            "candidate_id": str(request.candidate_id),
            "secret": "candidate-secret@example.test",
        }
    )
    with pytest.raises(ContactRequestRepositoryError) as raised:
        await repository.get(str(request.contact_request_id))
    assert str(raised.value) == "contact request record is malformed"
    assert "candidate-secret" not in str(raised.value)
