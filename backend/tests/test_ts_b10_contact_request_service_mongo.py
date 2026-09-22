"""B10.3 atomic orchestration G1 on an explicit disposable rs0 MongoDB."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

from bson import BSON
from motor.motor_asyncio import AsyncIOMotorClient
import pytest
import pytest_asyncio

from async_outbox.models import RetryPolicy
from async_outbox.repository import OutboxRepository
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
from domains.shared.versioning import PolicyVersion
from domains.talent_stream.anonymous_talent_adapter import (
    derive_anonymous_talent_card_ref,
)
from domains.talent_stream.contact_request_models import (
    CONTACT_REQUEST_HANDOFF_JOB_TYPE,
    ContactRequestCreateOutcome,
    CreateContactRequestCommand,
    derive_contact_request_id,
)
from domains.talent_stream.contact_request_repository import (
    ContactRequestRepository,
)
from domains.talent_stream.contact_request_service import (
    ContactRequestService,
    ContactRequestServiceConflictError,
    ContactRequestServiceUnavailableError,
)
from domains.talent_stream.contracts import RecruitingActorContext
from domains.trust.contact_governor_models import (
    ActiveReservationLimitPolicy,
    CompanyCoolingPolicy,
    ContactGovernorPolicyV1,
    ContactGovernorRequest,
    DuplicateProtectionPolicy,
    FrequencyCapPolicy,
    GovernorReservationCommand,
    GovernorReservationOutcome,
    GovernorReservationState,
    derive_request_fingerprint,
    derive_reservation_id,
)
from domains.trust.contact_governor_repository import ContactGovernorRepository
from scripts.migrate_async_outbox_indexes import migrate as migrate_a14
from scripts.migrate_ts_b10_contact_requests import migrate as migrate_b10
from scripts.migrate_ts_b9_contact_governor import migrate as migrate_b9


NOW = datetime(2026, 9, 22, 14, 0, tzinfo=timezone.utc)
CARD_KEY = b"b10-service-mongo-card-key-32-bytes"


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
    name = "test_ts_b10_service_" + uuid.uuid4().hex
    verified = False
    try:
        hello = await client.admin.command("hello")
        assert hello.get("msg") != "isdbgrid" and hello.get("setName") == "rs0"
        verified = True
        yield SimpleNamespace(db=client[name], client=client)
    finally:
        try:
            if verified:
                assert name.startswith("test_ts_b10_service_")
                await client.drop_database(name)
        finally:
            client.close()


def actor():
    return RecruitingActorContext(
        recruiter_user_id=RecruiterUserId("recruiter-1"),
        requesting_organization_id=OrganizationId("organization-1"),
        hiring_company_id=HiringCompanyId("company-1"),
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


def policy(*, lease=timedelta(minutes=5)):
    return ContactGovernorPolicyV1(
        policy_version=PolicyVersion("contact-governor-v1-test"),
        minimum_professional_match_score=70,
        frequency_cap_policy=FrequencyCapPolicy(enabled=False, caps=None),
        duplicate_protection_policy=DuplicateProtectionPolicy(
            enabled=False,
            scope=None,
            window=None,
        ),
        company_cooling_policy=CompanyCoolingPolicy(
            enabled=False,
            scope=None,
            period=None,
        ),
        active_reservation_limit_policy=ActiveReservationLimitPolicy(
            enabled=False,
            maximum_active_reservations=None,
        ),
        reservation_lease=lease,
    )


def reservation_command(*, key="request-1", candidate="candidate-1", lease=None):
    request = governor_request(key=key, candidate=candidate)
    selected_policy = policy(lease=lease or timedelta(minutes=5))
    return GovernorReservationCommand(
        request=request,
        policy=selected_policy,
        evaluated_at=NOW,
        reservation_id=derive_reservation_id(request),
        request_fingerprint=derive_request_fingerprint(request),
        reservation_expires_at=NOW + selected_policy.reservation_lease,
    )


def create_command(reservation):
    request = reservation.request
    return CreateContactRequestCommand(
        idempotency_key=request.idempotency_key,
        reservation_id=reservation.reservation_id,
        governor_request_fingerprint=reservation.request_fingerprint,
        anonymous_card_ref=derive_anonymous_talent_card_ref(
            key=CARD_KEY,
            stream_id=str(request.stream_id),
            generation_id=request.generation_id,
            candidate_id=str(request.candidate_id),
        ),
        recruiting_actor=request.recruiting_actor,
    )


async def ready(database):
    assert (await migrate_b9(database.db, apply=True))["ready"]
    assert (await migrate_b10(database.db, apply=True))["ready"]
    assert (await migrate_a14(database.db, apply=True))["ready"]
    return (
        ContactGovernorRepository(database.db),
        ContactRequestRepository(database.db),
        OutboxRepository(database.db),
    )


def service(repositories, *, clock, retry=RetryPolicy(3, 2, 60)):
    governor, requests, outbox = repositories
    return ContactRequestService(
        governor_repository=governor,
        contact_request_repository=requests,
        outbox_repository=outbox,
        card_ref_key=CARD_KEY,
        retry_policy=retry,
        clock=clock,
    )


async def snapshot(db):
    result = {}
    for name in (
        "contact_governor_reservations",
        "contact_governor_candidate_guards",
        "talent_stream_contact_requests",
        "async_outbox",
    ):
        documents = await db[name].find({}).sort("_id", 1).to_list(None)
        result[name] = tuple(BSON.encode(document) for document in documents)
    return result


async def reserve(governor, reservation):
    result = await governor.reserve(reservation)
    assert result.outcome is GovernorReservationOutcome.RESERVED


@pytest.mark.asyncio
async def test_atomic_create_and_exact_replay_after_expiry_and_policy_change(database):
    repositories = await ready(database)
    governor, requests, outbox = repositories
    reservation = reservation_command()
    await reserve(governor, reservation)
    command = create_command(reservation)
    created = await service(
        repositories,
        clock=lambda: NOW + timedelta(milliseconds=1),
    ).create(command)
    assert created.outcome is ContactRequestCreateOutcome.CREATED

    request = await requests.get(str(created.contact_request_id))
    binding = None
    async with await database.client.start_session() as session:
        session.start_transaction()
        binding = await governor.read_contact_request_binding(
            reservation.reservation_id,
            session=session,
        )
        await session.abort_transaction()
    publication = await outbox.read_publication(
        request.handoff_job_id,
        CONTACT_REQUEST_HANDOFF_JOB_TYPE,
        str(request.contact_request_id),
    )
    assert binding.status is GovernorReservationState.CONSUMED
    assert binding.contact_request_id == str(request.contact_request_id)
    assert publication.envelope.retry_policy == RetryPolicy(3, 2, 60)

    before = await snapshot(database.db)
    replayed = await service(
        repositories,
        clock=lambda: NOW + timedelta(hours=1),
        retry=RetryPolicy(9, 7, 180),
    ).create(command)
    assert replayed.outcome is ContactRequestCreateOutcome.IDEMPOTENT_REPLAY
    assert await snapshot(database.db) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["governor", "request", "outbox"])
async def test_failure_at_each_write_stage_rolls_back_all_three(
    database,
    monkeypatch,
    failure_stage,
):
    repositories = await ready(database)
    governor, requests, outbox = repositories
    reservation = reservation_command(key=f"rollback-{failure_stage}")
    await reserve(governor, reservation)
    before = await snapshot(database.db)
    target, method_name = {
        "governor": (governor, "consume"),
        "request": (requests, "insert"),
        "outbox": (outbox, "publish_in_transaction"),
    }[failure_stage]
    original = getattr(target, method_name)

    async def fail_after_write(*args, **kwargs):
        await original(*args, **kwargs)
        raise RuntimeError("candidate-secret@example.test")

    monkeypatch.setattr(target, method_name, fail_after_write)
    with pytest.raises(ContactRequestServiceUnavailableError) as raised:
        await service(
            repositories,
            clock=lambda: NOW + timedelta(milliseconds=1),
        ).create(create_command(reservation))
    assert str(raised.value) == "contact request service unavailable"
    assert "candidate-secret" not in str(raised.value)
    assert await snapshot(database.db) == before


@pytest.mark.asyncio
async def test_expired_reservation_fails_without_any_new_write(database):
    repositories = await ready(database)
    governor, _, _ = repositories
    reservation = reservation_command(lease=timedelta(milliseconds=1))
    await reserve(governor, reservation)
    before = await snapshot(database.db)
    with pytest.raises(ContactRequestServiceConflictError):
        await service(
            repositories,
            clock=lambda: NOW + timedelta(milliseconds=1),
        ).create(create_command(reservation))
    assert await snapshot(database.db) == before


@pytest.mark.asyncio
async def test_reservation_activity_boundary_is_inclusive(database):
    repositories = await ready(database)
    governor, _, _ = repositories
    reservation = reservation_command(key="activity-boundary")
    await reserve(governor, reservation)

    created = await service(repositories, clock=lambda: NOW).create(
        create_command(reservation)
    )

    assert created.outcome is ContactRequestCreateOutcome.CREATED


@pytest.mark.asyncio
async def test_concurrent_identical_create_has_one_create_and_one_replay(database):
    repositories = await ready(database)
    governor, _, _ = repositories
    reservation = reservation_command(key="concurrent")
    await reserve(governor, reservation)
    command = create_command(reservation)
    results = await asyncio.gather(
        *(
            service(
                repositories,
                clock=lambda: NOW + timedelta(milliseconds=1),
            ).create(command)
            for _ in range(2)
        )
    )
    assert sorted(result.outcome.value for result in results) == [
        "created",
        "idempotent_replay",
    ]
    assert await database.db.talent_stream_contact_requests.count_documents({}) == 1
    assert await database.db.async_outbox.count_documents({}) == 1
    assert await database.db.contact_governor_reservations.count_documents(
        {"status": "consumed"}
    ) == 1


@pytest.mark.asyncio
async def test_same_key_recovers_after_competing_failed_transaction(
    database,
    monkeypatch,
):
    repositories = await ready(database)
    governor, _, outbox = repositories
    reservation = reservation_command(key="failed-transaction-race")
    await reserve(governor, reservation)
    command = create_command(reservation)
    first_failed = asyncio.Event()
    winner_done = asyncio.Event()
    original_publish = outbox.publish_in_transaction
    publish_calls = 0

    async def fail_first_publish(*args, **kwargs):
        nonlocal publish_calls
        publish_calls += 1
        result = await original_publish(*args, **kwargs)
        if publish_calls == 1:
            first_failed.set()
            raise RuntimeError("fictional post-write transaction failure")
        return result

    monkeypatch.setattr(outbox, "publish_in_transaction", fail_first_publish)
    first_service = service(
        repositories,
        clock=lambda: NOW + timedelta(milliseconds=1),
    )
    original_recover = first_service._recover_committed

    async def recover_after_winner(*args, **kwargs):
        await winner_done.wait()
        return await original_recover(*args, **kwargs)

    monkeypatch.setattr(first_service, "_recover_committed", recover_after_winner)

    async def create_winner():
        await first_failed.wait()
        try:
            return await service(
                repositories,
                clock=lambda: NOW + timedelta(milliseconds=2),
            ).create(command)
        finally:
            winner_done.set()

    failed_then_recovered, winner = await asyncio.gather(
        first_service.create(command),
        create_winner(),
    )

    assert failed_then_recovered.outcome is ContactRequestCreateOutcome.IDEMPOTENT_REPLAY
    assert winner.outcome is ContactRequestCreateOutcome.CREATED
    assert await database.db.talent_stream_contact_requests.count_documents({}) == 1
    assert await database.db.async_outbox.count_documents({}) == 1
    assert await database.db.contact_governor_reservations.count_documents(
        {"status": "consumed"}
    ) == 1


@pytest.mark.asyncio
async def test_same_scoped_key_with_different_fingerprint_conflicts_without_writes(
    database,
):
    repositories = await ready(database)
    governor, _, _ = repositories
    reservation = reservation_command(key="fingerprint-conflict")
    await reserve(governor, reservation)
    original = create_command(reservation)
    await service(
        repositories,
        clock=lambda: NOW + timedelta(milliseconds=1),
    ).create(original)
    conflicting = replace(
        original,
        anonymous_card_ref=derive_anonymous_talent_card_ref(
            key=CARD_KEY,
            stream_id=str(reservation.request.stream_id),
            generation_id=reservation.request.generation_id,
            candidate_id="different-candidate",
        ),
    )
    before = await snapshot(database.db)

    with pytest.raises(ContactRequestServiceConflictError):
        await service(
            repositories,
            clock=lambda: NOW + timedelta(milliseconds=2),
        ).create(conflicting)

    assert await snapshot(database.db) == before


@pytest.mark.asyncio
async def test_competing_keys_cannot_consume_one_reservation_twice(database):
    repositories = await ready(database)
    governor, _, _ = repositories
    reservation = reservation_command(key="two-key-race")
    await reserve(governor, reservation)
    valid = create_command(reservation)
    foreign = replace(
        valid,
        idempotency_key=IdempotencyKey("foreign-scoped-key"),
    )

    results = await asyncio.gather(
        service(
            repositories,
            clock=lambda: NOW + timedelta(milliseconds=1),
        ).create(valid),
        service(
            repositories,
            clock=lambda: NOW + timedelta(milliseconds=1),
        ).create(foreign),
        return_exceptions=True,
    )

    assert sum(
        isinstance(result, ContactRequestServiceConflictError)
        for result in results
    ) == 1
    created = [
        result
        for result in results
        if not isinstance(result, BaseException)
    ]
    assert len(created) == 1
    assert created[0].outcome is ContactRequestCreateOutcome.CREATED
    assert await database.db.talent_stream_contact_requests.count_documents({}) == 1
    assert await database.db.async_outbox.count_documents({}) == 1
    assert await database.db.contact_governor_reservations.count_documents(
        {"status": "consumed", "contact_request_id": str(created[0].contact_request_id)}
    ) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("corruption", "error_type"),
    [
        ("b9_mismatch", ContactRequestServiceConflictError),
        ("b9_malformed", ContactRequestServiceUnavailableError),
        ("b10_missing", ContactRequestServiceConflictError),
        ("a14_missing", ContactRequestServiceConflictError),
        ("a14_mismatch", ContactRequestServiceConflictError),
        ("a14_malformed", ContactRequestServiceConflictError),
    ],
)
async def test_committed_replay_requires_healthy_three_part_state(
    database,
    corruption,
    error_type,
):
    repositories = await ready(database)
    governor, requests, _ = repositories
    reservation = reservation_command(key=f"corrupt-{corruption}")
    await reserve(governor, reservation)
    command = create_command(reservation)
    created = await service(
        repositories,
        clock=lambda: NOW + timedelta(milliseconds=1),
    ).create(command)
    request_id = str(created.contact_request_id)
    if corruption == "b9_mismatch":
        await database.db.contact_governor_reservations.update_one(
            {"_id": reservation.reservation_id},
            {"$set": {"contact_request_id": "different-request"}},
        )
    elif corruption == "b9_malformed":
        await database.db.contact_governor_reservations.update_one(
            {"_id": reservation.reservation_id},
            {"$set": {"unexpected_sensitive_field": "must-not-be-repaired"}},
        )
    elif corruption == "b10_missing":
        await database.db.talent_stream_contact_requests.delete_one(
            {"_id": request_id}
        )
    elif corruption == "a14_missing":
        await database.db.async_outbox.delete_one({})
    elif corruption == "a14_mismatch":
        await database.db.async_outbox.update_one(
            {},
            {"$set": {"reference.reference_id": "different-request"}},
        )
    else:
        await database.db.async_outbox.update_one(
            {},
            {"$set": {"unexpected_sensitive_field": "must-not-be-repaired"}},
        )
    before = await snapshot(database.db)
    with pytest.raises(error_type):
        await service(
            repositories,
            clock=lambda: NOW + timedelta(hours=1),
            retry=RetryPolicy(8, 4, 120),
        ).create(command)
    assert await snapshot(database.db) == before
    if corruption != "b10_missing":
        assert await requests.get(request_id) is not None


@pytest.mark.asyncio
async def test_replay_accepts_progressed_a14_operational_state(database):
    repositories = await ready(database)
    governor, _, outbox = repositories
    reservation = reservation_command(key="progressed-outbox")
    await reserve(governor, reservation)
    command = create_command(reservation)
    await service(
        repositories,
        clock=lambda: NOW + timedelta(milliseconds=1),
    ).create(command)
    claimed = await outbox.claim("b10-test-worker", lease_seconds=60)
    assert claimed is not None
    before = await snapshot(database.db)

    replayed = await service(
        repositories,
        clock=lambda: NOW + timedelta(hours=1),
        retry=RetryPolicy(8, 4, 120),
    ).create(command)

    assert replayed.outcome is ContactRequestCreateOutcome.IDEMPOTENT_REPLAY
    assert await snapshot(database.db) == before
