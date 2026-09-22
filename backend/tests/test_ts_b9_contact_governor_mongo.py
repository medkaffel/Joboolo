"""B9.2 G1 against an explicitly supplied disposable replica-set Mongo only."""
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
from domains.talent_stream.contracts import RecruitingActorContext
from domains.trust.contact_governor_models import (
    ActiveReservationLimitPolicy,
    CompanyCoolingPolicy,
    ContactGovernorPolicyV1,
    ContactGovernorRequest,
    DuplicateProtectionPolicy,
    FrequencyCapPolicy,
    GovernorCompanyCoolingScope,
    GovernorDuplicateScope,
    GovernorFrequencyCap,
    GovernorFrequencyScope,
    GovernorReservationCommand,
    GovernorReservationOutcome,
    GovernorReservationState,
    derive_request_fingerprint,
    derive_reservation_id,
)
from domains.trust.contact_governor_persistence import (
    ContactGovernorCandidateGuard,
    guard_from_document,
    guard_to_document,
    reservation_from_document,
    reservation_record_from_command,
    reservation_to_document,
)
from domains.trust.contact_governor_repository import (
    ContactGovernorConflictError,
    ContactGovernorReadinessError,
    ContactGovernorRepository,
    ContactGovernorRepositoryError,
)
from scripts.migrate_ts_b9_contact_governor import (
    B9MigrationError,
    migrate,
    preflight,
)


NOW = datetime(2026, 9, 22, 10, 0, 0, 123000, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def database():
    url = os.environ.get("B9_REPLICA_SET_URL")
    if not url:
        pytest.skip("explicit B9 disposable replica-set Mongo URL required")
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
        pytest.fail("B9 requires loopback rs0 with an explicit port and no other options")
    client = AsyncIOMotorClient(
        url,
        serverSelectionTimeoutMS=5000,
        socketTimeoutMS=5000,
    )
    name = "test_ts_b9_" + uuid.uuid4().hex
    verified = False
    try:
        hello = await client.admin.command("hello")
        assert hello.get("msg") != "isdbgrid" and hello.get("setName") == "rs0"
        verified = True
        yield SimpleNamespace(db=client[name], client=client)
    finally:
        try:
            if verified:
                assert name.startswith("test_ts_b9_")
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


def request(*, key="attempt-1", candidate="candidate-1", actor_value=None, **changes):
    values = {
        "idempotency_key": IdempotencyKey(key),
        "candidate_id": CandidateId(candidate),
        "stream_id": TalentStreamId("stream-1"),
        "generation_id": "generation-1",
        "projection_state_version": 1,
        "stream_version": 1,
        "requirement_version": 1,
        "role_dna_id": RoleDNAId("role-1"),
        "role_dna_version": 1,
        "opportunity_spec_id": OpportunitySpecId("opportunity-1"),
        "opportunity_spec_version": 1,
        "recruiting_actor": actor_value or actor(),
    }
    values.update(changes)
    return ContactGovernorRequest(**values)


def policy(
    *,
    frequency=None,
    duplicate=None,
    cooling=None,
    active=None,
    lease=timedelta(minutes=10),
):
    return ContactGovernorPolicyV1(
        policy_version=PolicyVersion("contact-governor-v1-test"),
        minimum_professional_match_score=70,
        frequency_cap_policy=frequency or FrequencyCapPolicy(enabled=False, caps=None),
        duplicate_protection_policy=duplicate
        or DuplicateProtectionPolicy(enabled=False, scope=None, window=None),
        company_cooling_policy=cooling
        or CompanyCoolingPolicy(enabled=False, scope=None, period=None),
        active_reservation_limit_policy=active
        or ActiveReservationLimitPolicy(
            enabled=False, maximum_active_reservations=None
        ),
        reservation_lease=lease,
    )


def command(*, at=NOW, request_value=None, policy_value=None):
    request_value = request_value or request()
    policy_value = policy_value or policy()
    return GovernorReservationCommand(
        request=request_value,
        policy=policy_value,
        evaluated_at=at,
        reservation_id=derive_reservation_id(request_value),
        request_fingerprint=derive_request_fingerprint(request_value),
        reservation_expires_at=at + policy_value.reservation_lease,
    )


async def ready(database):
    result = await migrate(database.db, apply=True)
    assert result["ready"]
    return ContactGovernorRepository(database.db)


async def documents(db, collection):
    return tuple(
        BSON.encode(document)
        for document in await db[collection].find({}).sort("_id", 1).to_list(None)
    )


async def insert_record(db, value):
    await db.contact_governor_reservations.insert_one(reservation_to_document(value))


def prior_record(
    *,
    at,
    key="prior",
    actor_value=None,
    policy_value=None,
    state=GovernorReservationState.RESERVED,
    expires_at=None,
    contact_request_id=None,
):
    created = command(
        at=at,
        request_value=request(key=key, actor_value=actor_value),
        policy_value=policy_value or policy(),
    )
    return replace(
        reservation_record_from_command(created),
        status=state,
        expires_at=expires_at or created.reservation_expires_at,
        contact_request_id=contact_request_id,
    )


def test_strict_persistence_roundtrip_and_naive_bson_boundary():
    record = reservation_record_from_command(command())
    document = reservation_to_document(record)
    document["activity_at"] = document["activity_at"].replace(tzinfo=None)
    document["expires_at"] = document["expires_at"].replace(tzinfo=None)
    restored = reservation_from_document(document)
    assert restored == record
    guard = ContactGovernorCandidateGuard("candidate-1", 1, NOW)
    guard_document = guard_to_document(guard)
    guard_document["updated_at"] = NOW.replace(tzinfo=None)
    assert guard_from_document(guard_document) == guard


@pytest.mark.parametrize(
    "mutation",
    [
        lambda doc: doc.update(extra="secret"),
        lambda doc: doc.pop("policy_version"),
        lambda doc: doc.update(status="unknown"),
        lambda doc: doc.update(activity_at="not-a-date"),
        lambda doc: doc.update(contact_request_id="request-without-consumed-state"),
    ],
)
def test_strict_reservation_rehydration_rejects_malformed_documents(mutation):
    document = reservation_to_document(reservation_record_from_command(command()))
    mutation(document)
    with pytest.raises(ValueError):
        reservation_from_document(document)


@pytest.mark.asyncio
async def test_migration_dry_run_apply_repeat_and_exact_metadata(database):
    db = database.db
    before = await db.list_collection_names()
    dry = await migrate(db)
    assert not dry["ready"] and dry == await migrate(db)
    assert await db.list_collection_names() == before == []
    applied = await migrate(db, apply=True)
    assert applied["ready"] and applied == await migrate(db, apply=True)
    assert set(await db.list_collection_names()) == {
        "contact_governor_reservations",
        "contact_governor_candidate_guards",
    }
    reservations = await db.contact_governor_reservations.index_information()
    assert set(reservations) == {
        "_id_",
        "ts_b9_candidate_activity",
        "ts_b9_requesting_org_activity",
        "ts_b9_hiring_company_activity",
        "ts_b9_dedup_activity",
        "ts_b9_contact_request_unique",
    }
    assert all("expireAfterSeconds" not in spec for spec in reservations.values())
    assert set(await db.contact_governor_candidate_guards.index_information()) == {"_id_"}


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", ["wrong_index", "unexpected", "ttl"])
async def test_migration_rejects_index_corruption_without_repair(database, corruption):
    db = database.db
    if corruption == "wrong_index":
        await db.create_collection("contact_governor_reservations", collation={"locale": "simple"})
        await db.contact_governor_reservations.create_index(
            [("wrong", 1)], name="ts_b9_candidate_activity"
        )
    else:
        await migrate(db, apply=True)
        if corruption == "unexpected":
            await db.contact_governor_reservations.create_index(
                [("unexpected", 1)], name="unexpected"
            )
        else:
            await db.contact_governor_reservations.create_index(
                [("expires_at", 1)], name="forbidden_ttl", expireAfterSeconds=1
            )
    before = await db.list_collection_names(), await db.contact_governor_reservations.index_information()
    with pytest.raises(B9MigrationError):
        await migrate(db, apply=True)
    assert (await db.list_collection_names(), await db.contact_governor_reservations.index_information()) == before


@pytest.mark.asyncio
async def test_migration_rejects_wrong_collation_and_malformed_documents(database):
    db = database.db
    await db.create_collection(
        "contact_governor_reservations", collation={"locale": "en"}
    )
    with pytest.raises(B9MigrationError):
        await migrate(db, apply=True)
    await db.drop_collection("contact_governor_reservations")
    await migrate(db, apply=True)
    await db.contact_governor_reservations.insert_one({"_id": "malformed"})
    with pytest.raises(B9MigrationError):
        await preflight(db)


@pytest.mark.asyncio
async def test_migration_preflight_rejects_malformed_guard_and_duplicate_binding(database):
    db = database.db
    await db.create_collection(
        "contact_governor_reservations", collation={"locale": "simple"}
    )
    await db.create_collection(
        "contact_governor_candidate_guards", collation={"locale": "simple"}
    )
    await db.contact_governor_candidate_guards.insert_one(
        {"_id": "candidate-1", "schema_version": "wrong", "revision": 1, "updated_at": NOW}
    )
    with pytest.raises(B9MigrationError):
        await preflight(db)
    await db.contact_governor_candidate_guards.delete_many({})
    for key in ("first", "second"):
        value = reservation_record_from_command(
            command(request_value=request(key=key))
        )
        await insert_record(
            db,
            replace(
                value,
                status=GovernorReservationState.CONSUMED,
                contact_request_id="same-contact-request",
            ),
        )
    with pytest.raises(B9MigrationError):
        await preflight(db)


@pytest.mark.asyncio
async def test_repository_readiness_requires_all_b9_metadata(database):
    repository = ContactGovernorRepository(database.db)
    with pytest.raises(ContactGovernorReadinessError):
        await repository.readiness()
    await migrate(database.db, apply=True)
    assert (await repository.readiness()).diagnostics == ()
    await database.db.contact_governor_reservations.drop_index(
        "ts_b9_candidate_activity"
    )
    with pytest.raises(ContactGovernorReadinessError):
        await repository.reserve(command())


@pytest.mark.asyncio
async def test_reserve_create_replay_conflict_and_terminal_key_reuse(database):
    repository = await ready(database)
    first = command()
    created = await repository.reserve(first)
    replay = await repository.reserve(first)
    assert created.outcome is GovernorReservationOutcome.RESERVED
    assert replay.outcome is GovernorReservationOutcome.IDEMPOTENT_REPLAY
    conflict = await repository.reserve(
        command(request_value=request(candidate="candidate-2"))
    )
    assert conflict.outcome is GovernorReservationOutcome.IDEMPOTENCY_CONFLICT
    await repository.release(first.reservation_id)
    denied = await repository.reserve(first)
    assert denied.outcome is GovernorReservationOutcome.DUPLICATE
    assert await database.db.contact_governor_reservations.count_documents({}) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,same_actor,different_actor",
    [
        (GovernorFrequencyScope.CANDIDATE_GLOBAL, actor(), actor(recruiter="other")),
        (GovernorFrequencyScope.RECRUITER_CANDIDATE, actor(), actor(recruiter="other")),
        (
            GovernorFrequencyScope.REQUESTING_ORGANIZATION_CANDIDATE,
            actor(),
            actor(requesting="other"),
        ),
        (
            GovernorFrequencyScope.HIRING_COMPANY_CANDIDATE,
            actor(),
            actor(hiring="other"),
        ),
    ],
)
async def test_frequency_scope_and_half_open_boundaries(
    database, scope, same_actor, different_actor
):
    repository = await ready(database)
    configured = policy(
        frequency=FrequencyCapPolicy(
            enabled=True,
            caps=(GovernorFrequencyCap(scope, 1, timedelta(hours=1)),),
        )
    )
    await insert_record(
        database.db,
        prior_record(
            at=NOW - timedelta(hours=1),
            actor_value=same_actor,
            policy_value=configured,
            expires_at=NOW + timedelta(minutes=1),
        ),
    )
    same = await repository.reserve(
        command(
            request_value=request(key="same", actor_value=same_actor),
            policy_value=configured,
        )
    )
    assert same.outcome is GovernorReservationOutcome.FREQUENCY_CAP_REACHED
    different = await repository.reserve(
        command(
            request_value=request(key="different", actor_value=different_actor),
            policy_value=configured,
        )
    )
    expected = (
        GovernorReservationOutcome.FREQUENCY_CAP_REACHED
        if scope is GovernorFrequencyScope.CANDIDATE_GLOBAL
        else GovernorReservationOutcome.RESERVED
    )
    assert different.outcome is expected


@pytest.mark.asyncio
async def test_same_timestamp_committed_activity_counts_for_frequency(database):
    repository = await ready(database)
    configured = policy(
        frequency=FrequencyCapPolicy(
            enabled=True,
            caps=(
                GovernorFrequencyCap(
                    GovernorFrequencyScope.CANDIDATE_GLOBAL,
                    1,
                    timedelta(hours=1),
                ),
            ),
        )
    )
    await insert_record(
        database.db,
        prior_record(
            at=NOW,
            key="future-peer",
            policy_value=configured,
            expires_at=NOW + timedelta(minutes=10),
        ),
    )
    result = await repository.reserve(
        command(request_value=request(key="new"), policy_value=configured)
    )
    assert result.outcome is GovernorReservationOutcome.FREQUENCY_CAP_REACHED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "offset,expected",
    [
        (timedelta(hours=-1), GovernorReservationOutcome.RESERVED),
        (
            timedelta(hours=-1, milliseconds=1),
            GovernorReservationOutcome.COMPANY_COOLING_ACTIVE,
        ),
    ],
)
async def test_company_cooling_strict_boundary(database, offset, expected):
    repository = await ready(database)
    configured = policy(
        cooling=CompanyCoolingPolicy(
            enabled=True,
            scope=GovernorCompanyCoolingScope.HIRING_COMPANY_CANDIDATE,
            period=timedelta(hours=1),
        )
    )
    await insert_record(
        database.db,
        prior_record(
            at=NOW + offset,
            policy_value=configured,
            expires_at=NOW + timedelta(minutes=1),
        ),
    )
    result = await repository.reserve(
        command(request_value=request(key="new"), policy_value=configured)
    )
    assert result.outcome is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "offset,expected",
    [
        (timedelta(hours=-1), GovernorReservationOutcome.DUPLICATE),
        (
            timedelta(hours=-1, milliseconds=-1),
            GovernorReservationOutcome.RESERVED,
        ),
    ],
)
async def test_duplicate_window_boundary(database, offset, expected):
    repository = await ready(database)
    configured = policy(
        duplicate=DuplicateProtectionPolicy(
            enabled=True,
            scope=GovernorDuplicateScope.STREAM_CANDIDATE_RECRUITER,
            window=timedelta(hours=1),
        )
    )
    await insert_record(
        database.db,
        prior_record(
            at=NOW + offset,
            policy_value=configured,
            expires_at=NOW + timedelta(minutes=1),
        ),
    )
    result = await repository.reserve(
        command(request_value=request(key="new"), policy_value=configured)
    )
    assert result.outcome is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,different_actor",
    [
        (
            GovernorDuplicateScope.STREAM_CANDIDATE_RECRUITER,
            actor(recruiter="other"),
        ),
        (
            GovernorDuplicateScope.STREAM_CANDIDATE_REQUESTING_ORGANIZATION,
            actor(requesting="other"),
        ),
        (
            GovernorDuplicateScope.STREAM_CANDIDATE_HIRING_COMPANY,
            actor(hiring="other"),
        ),
    ],
)
async def test_duplicate_scope_isolation(database, scope, different_actor):
    repository = await ready(database)
    configured = policy(
        duplicate=DuplicateProtectionPolicy(
            enabled=True,
            scope=scope,
            window=timedelta(hours=1),
        )
    )
    await insert_record(
        database.db,
        prior_record(
            at=NOW - timedelta(minutes=1),
            policy_value=configured,
            expires_at=NOW + timedelta(minutes=1),
        ),
    )
    same = await repository.reserve(
        command(request_value=request(key="same"), policy_value=configured)
    )
    different = await repository.reserve(
        command(
            request_value=request(key="different", actor_value=different_actor),
            policy_value=configured,
        )
    )
    assert same.outcome is GovernorReservationOutcome.DUPLICATE
    assert different.outcome is GovernorReservationOutcome.RESERVED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope,different_actor",
    [
        (
            GovernorCompanyCoolingScope.REQUESTING_ORGANIZATION_CANDIDATE,
            actor(requesting="other"),
        ),
        (
            GovernorCompanyCoolingScope.HIRING_COMPANY_CANDIDATE,
            actor(hiring="other"),
        ),
    ],
)
async def test_company_cooling_scope_isolation(database, scope, different_actor):
    repository = await ready(database)
    configured = policy(
        cooling=CompanyCoolingPolicy(
            enabled=True,
            scope=scope,
            period=timedelta(hours=1),
        )
    )
    await insert_record(
        database.db,
        prior_record(
            at=NOW - timedelta(minutes=1),
            policy_value=configured,
            expires_at=NOW + timedelta(minutes=1),
        ),
    )
    same = await repository.reserve(
        command(request_value=request(key="same"), policy_value=configured)
    )
    different = await repository.reserve(
        command(
            request_value=request(key="different", actor_value=different_actor),
            policy_value=configured,
        )
    )
    assert same.outcome is GovernorReservationOutcome.COMPANY_COOLING_ACTIVE
    assert different.outcome is GovernorReservationOutcome.RESERVED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state,expires_delta,counts",
    [
        (GovernorReservationState.RESERVED, timedelta(milliseconds=1), True),
        (GovernorReservationState.RESERVED, timedelta(0), False),
        (GovernorReservationState.RESERVED, timedelta(milliseconds=-1), False),
        (GovernorReservationState.CONSUMED, timedelta(seconds=-1), True),
        (GovernorReservationState.RELEASED, timedelta(hours=1), False),
    ],
)
async def test_frozen_lifecycle_counting_for_frequency(
    database, state, expires_delta, counts
):
    repository = await ready(database)
    configured = policy(
        frequency=FrequencyCapPolicy(
            enabled=True,
            caps=(
                GovernorFrequencyCap(
                    GovernorFrequencyScope.CANDIDATE_GLOBAL,
                    1,
                    timedelta(hours=1),
                ),
            ),
        ),
        lease=timedelta(hours=2),
    )
    await insert_record(
        database.db,
        prior_record(
            at=NOW - timedelta(minutes=1),
            policy_value=configured,
            state=state,
            expires_at=NOW + expires_delta,
            contact_request_id="contact-prior"
            if state is GovernorReservationState.CONSUMED
            else None,
        ),
    )
    result = await repository.reserve(
        command(request_value=request(key="new"), policy_value=configured)
    )
    assert result.outcome is (
        GovernorReservationOutcome.FREQUENCY_CAP_REACHED
        if counts
        else GovernorReservationOutcome.RESERVED
    )


@pytest.mark.asyncio
async def test_active_reservation_expiry_boundary(database):
    repository = await ready(database)
    configured = policy(
        active=ActiveReservationLimitPolicy(
            enabled=True, maximum_active_reservations=1
        )
    )
    await insert_record(
        database.db,
        prior_record(
            at=NOW - timedelta(minutes=1),
            policy_value=configured,
            expires_at=NOW,
        ),
    )
    result = await repository.reserve(
        command(request_value=request(key="new"), policy_value=configured)
    )
    assert result.outcome is GovernorReservationOutcome.RESERVED


@pytest.mark.asyncio
async def test_concurrent_same_identity_and_candidate_limit_are_serialized(database):
    repository = await ready(database)
    same = command()
    same_results = await asyncio.gather(*(repository.reserve(same) for _ in range(8)))
    assert sum(item.outcome is GovernorReservationOutcome.RESERVED for item in same_results) == 1
    assert all(
        item.outcome
        in {GovernorReservationOutcome.RESERVED, GovernorReservationOutcome.IDEMPOTENT_REPLAY}
        for item in same_results
    )
    assert await database.db.contact_governor_reservations.count_documents({}) == 1

    await database.db.contact_governor_reservations.delete_many({})
    configured = policy(
        active=ActiveReservationLimitPolicy(
            enabled=True, maximum_active_reservations=1
        )
    )
    commands = [
        command(request_value=request(key=f"key-{i}"), policy_value=configured)
        for i in range(8)
    ]
    results = await asyncio.gather(*(repository.reserve(item) for item in commands))
    assert sum(item.outcome is GovernorReservationOutcome.RESERVED for item in results) == 1
    assert sum(
        item.outcome is GovernorReservationOutcome.ACTIVE_RESERVATION_LIMIT_REACHED
        for item in results
    ) == 7
    guard = await database.db.contact_governor_candidate_guards.find_one(
        {"_id": "candidate-1"}
    )
    assert guard["revision"] == 16


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dimension,blocked_outcome",
    [
        ("frequency", GovernorReservationOutcome.FREQUENCY_CAP_REACHED),
        ("duplicate", GovernorReservationOutcome.DUPLICATE),
        ("cooling", GovernorReservationOutcome.COMPANY_COOLING_ACTIVE),
    ],
)
async def test_same_timestamp_concurrency_admits_only_one_without_active_limit(
    database, dimension, blocked_outcome
):
    repository = await ready(database)
    overrides = {}
    if dimension == "frequency":
        overrides["frequency"] = FrequencyCapPolicy(
            enabled=True,
            caps=(
                GovernorFrequencyCap(
                    GovernorFrequencyScope.CANDIDATE_GLOBAL,
                    1,
                    timedelta(hours=1),
                ),
            ),
        )
    elif dimension == "duplicate":
        overrides["duplicate"] = DuplicateProtectionPolicy(
            enabled=True,
            scope=GovernorDuplicateScope.STREAM_CANDIDATE_RECRUITER,
            window=timedelta(hours=1),
        )
    else:
        overrides["cooling"] = CompanyCoolingPolicy(
            enabled=True,
            scope=GovernorCompanyCoolingScope.HIRING_COMPANY_CANDIDATE,
            period=timedelta(hours=1),
        )
    configured = policy(**overrides)
    assert not configured.active_reservation_limit_policy.enabled
    attempts = [
        command(
            at=NOW,
            request_value=request(key=f"{dimension}-{index}"),
            policy_value=configured,
        )
        for index in range(8)
    ]
    results = await asyncio.gather(*(repository.reserve(item) for item in attempts))
    assert sum(
        result.outcome is GovernorReservationOutcome.RESERVED for result in results
    ) == 1
    assert sum(result.outcome is blocked_outcome for result in results) == 7
    assert await database.db.contact_governor_reservations.count_documents({}) == 1


@pytest.mark.asyncio
async def test_guard_time_regression_fails_closed_without_mutation(database):
    repository = await ready(database)
    initial = command(request_value=request(key="initial"))
    assert (await repository.reserve(initial)).outcome is GovernorReservationOutcome.RESERVED
    before = guard_from_document(
        await database.db.contact_governor_candidate_guards.find_one(
            {"_id": "candidate-1"}
        )
    )

    backdated = command(
        at=NOW - timedelta(milliseconds=1),
        request_value=request(key="backdated"),
    )
    with pytest.raises(ContactGovernorRepositoryError) as raised:
        await repository.reserve(backdated)
    assert str(raised.value) == "contact governor repository unavailable"
    after = guard_from_document(
        await database.db.contact_governor_candidate_guards.find_one(
            {"_id": "candidate-1"}
        )
    )
    assert after == before
    assert await database.db.contact_governor_reservations.count_documents({}) == 1

    valid = command(
        at=NOW + timedelta(milliseconds=1),
        request_value=request(key="valid"),
    )
    assert (await repository.reserve(valid)).outcome is GovernorReservationOutcome.RESERVED
    advanced = guard_from_document(
        await database.db.contact_governor_candidate_guards.find_one(
            {"_id": "candidate-1"}
        )
    )
    assert advanced.revision == before.revision + 1
    assert advanced.updated_at == NOW + timedelta(milliseconds=1)
    assert await database.db.contact_governor_reservations.count_documents({}) == 2


@pytest.mark.asyncio
async def test_concurrent_actor_key_collision_across_candidates_is_protocol_conflict(database):
    repository = await ready(database)
    attempts = [
        command(request_value=request(candidate="candidate-1")),
        command(request_value=request(candidate="candidate-2")),
    ]
    results = await asyncio.gather(*(repository.reserve(item) for item in attempts))
    assert sorted(result.outcome.value for result in results) == [
        GovernorReservationOutcome.IDEMPOTENCY_CONFLICT.value,
        GovernorReservationOutcome.RESERVED.value,
    ]
    assert await database.db.contact_governor_reservations.count_documents({}) == 1


@pytest.mark.asyncio
async def test_reserve_transaction_rolls_back_guard_on_internal_failure(database, monkeypatch):
    repository = await ready(database)

    def fail(*args, **kwargs):
        raise RuntimeError("sensitive internal failure")

    monkeypatch.setattr(ContactGovernorRepository, "_apply_policy", fail)
    with pytest.raises(ContactGovernorRepositoryError) as raised:
        await repository.reserve(command())
    assert str(raised.value) == "contact governor repository unavailable"
    assert await database.db.contact_governor_reservations.count_documents({}) == 0
    assert await database.db.contact_governor_candidate_guards.count_documents({}) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "offset,allowed",
    [
        (timedelta(milliseconds=-1), True),
        (timedelta(0), False),
        (timedelta(milliseconds=1), False),
    ],
)
async def test_consume_expiry_boundaries(database, offset, allowed):
    repository = await ready(database)
    created = command()
    await repository.reserve(created)
    evaluated_at = created.reservation_expires_at + offset
    if allowed:
        await repository.consume(
            created.reservation_id,
            "contact-1",
            evaluated_at=evaluated_at,
        )
        stored = reservation_from_document(
            await database.db.contact_governor_reservations.find_one(
                {"_id": created.reservation_id}
            )
        )
        assert stored.status is GovernorReservationState.CONSUMED
        assert stored.activity_at == created.evaluated_at
    else:
        with pytest.raises(ContactGovernorConflictError):
            await repository.consume(
                created.reservation_id,
                "contact-1",
                evaluated_at=evaluated_at,
            )


@pytest.mark.asyncio
async def test_lifecycle_idempotency_conflicts_and_activity_immutability(database):
    repository = await ready(database)
    consumed = command()
    await repository.reserve(consumed)
    await repository.consume(
        consumed.reservation_id,
        "contact-1",
        evaluated_at=consumed.reservation_expires_at - timedelta(milliseconds=1),
    )
    await repository.consume(
        consumed.reservation_id,
        "contact-1",
        evaluated_at=consumed.reservation_expires_at + timedelta(days=1),
    )
    with pytest.raises(ContactGovernorConflictError):
        await repository.consume(
            consumed.reservation_id,
            "contact-other",
            evaluated_at=NOW,
        )
    with pytest.raises(ContactGovernorConflictError):
        await repository.release(consumed.reservation_id)

    released = command(request_value=request(key="release"))
    await repository.reserve(released)
    await repository.release(released.reservation_id)
    await repository.release(released.reservation_id)
    with pytest.raises(ContactGovernorConflictError):
        await repository.consume(
            released.reservation_id,
            "contact-release",
            evaluated_at=NOW,
        )
    consumed_doc = await database.db.contact_governor_reservations.find_one(
        {"_id": consumed.reservation_id}
    )
    released_doc = await database.db.contact_governor_reservations.find_one(
        {"_id": released.reservation_id}
    )
    assert consumed_doc["activity_at"].replace(tzinfo=timezone.utc) == NOW
    assert released_doc["activity_at"].replace(tzinfo=timezone.utc) == NOW


@pytest.mark.asyncio
async def test_consume_uses_caller_transaction_commit_and_rollback(database):
    repository = await ready(database)
    committed = command(request_value=request(key="commit"))
    rolled_back = command(request_value=request(key="rollback"))
    await repository.reserve(committed)
    await repository.reserve(rolled_back)

    async with await database.client.start_session() as session:
        session.start_transaction()
        await repository.consume(
            committed.reservation_id,
            "contact-commit",
            evaluated_at=NOW + timedelta(milliseconds=1),
            session=session,
        )
        await session.commit_transaction()
    committed_record = reservation_from_document(
        await database.db.contact_governor_reservations.find_one(
            {"_id": committed.reservation_id}
        )
    )
    assert committed_record.status is GovernorReservationState.CONSUMED

    async with await database.client.start_session() as session:
        session.start_transaction()
        await repository.consume(
            rolled_back.reservation_id,
            "contact-rollback",
            evaluated_at=NOW + timedelta(milliseconds=1),
            session=session,
        )
        await session.abort_transaction()
    rolled_back_record = reservation_from_document(
        await database.db.contact_governor_reservations.find_one(
            {"_id": rolled_back.reservation_id}
        )
    )
    assert rolled_back_record.status is GovernorReservationState.RESERVED
    assert "contact_request_id" not in reservation_to_document(rolled_back_record)
    assert "contact_requests" not in await database.db.list_collection_names()


@pytest.mark.asyncio
async def test_contact_request_binding_unique_and_lifecycle_time_is_strict(database):
    repository = await ready(database)
    first = command(request_value=request(key="first"))
    second = command(request_value=request(key="second"))
    await repository.reserve(first)
    await repository.reserve(second)
    await repository.consume(first.reservation_id, "contact-1", evaluated_at=NOW)
    with pytest.raises(ContactGovernorConflictError):
        await repository.consume(second.reservation_id, "contact-1", evaluated_at=NOW)
    for invalid in (NOW.replace(tzinfo=None), NOW + timedelta(microseconds=1)):
        with pytest.raises(ContactGovernorRepositoryError):
            await repository.consume(
                second.reservation_id,
                "contact-2",
                evaluated_at=invalid,
            )


@pytest.mark.asyncio
async def test_malformed_runtime_document_fails_closed_and_redacts(database):
    repository = await ready(database)
    await database.db.contact_governor_reservations.insert_one(
        {
            "_id": derive_reservation_id(request()),
            "candidate_id": "candidate-1",
            "secret": "candidate-secret@example.test",
        }
    )
    with pytest.raises(ContactGovernorRepositoryError) as raised:
        await repository.reserve(command())
    assert "candidate-secret" not in str(raised.value)
