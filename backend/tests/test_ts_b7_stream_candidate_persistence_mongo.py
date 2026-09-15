"""B7.2 G1: Mongo persistence and repository integration suite.

Run only when an explicit B7_MONGO_URL targets a standalone local Mongo
(127.0.0.1, no auth, no db, no options) AND the pytest-asyncio plugin is
installed. Each test uses an isolated random database test_ts_b7_<uuid> and
drops only that database. No MONGO_URL/DB_NAME/admins/grants are touched.
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import pytest_asyncio  # noqa: F401
    HAVE_PYTEST_ASYNCIO = True
except ModuleNotFoundError:
    HAVE_PYTEST_ASYNCIO = False

from domains.matching.opportunity_fit_models import HardEligibilityState, OpportunityFitState
from domains.talent_stream.stream_candidate_models import (
    ApplicationEvidence,
    DeclaredInterestEvidence,
    DiscoveryEvidence,
    OpportunityFitSummary,
    ProfessionalMatchSummary,
    SharedFavoriteEvidence,
    StreamCandidate,
)
from domains.talent_stream.stream_candidate_persistence import (
    TALENT_STREAM_CANDIDATE_GENERATIONS_SCHEMA_VERSION,
    TALENT_STREAM_CANDIDATE_PROJECTION_STATE_SCHEMA_VERSION,
    TALENT_STREAM_CANDIDATE_SCHEMA_VERSION,
    GenerationState,
    StreamCandidateGenerationRecord,
    candidate_document_id,
    generation_record_document_id,
    generation_record_from_document,
    generation_record_to_document,
    stream_candidate_from_document,
)
from domains.talent_stream.stream_candidate_repository import (
    StreamCandidateConflictError,
    StreamCandidateReadinessError,
    StreamCandidateRepository,
    StreamCandidateRepositoryError,
)
from scripts.migrate_ts_b7_stream_candidate_projection import (
    B7MigrationError,
    migrate,
    preflight,
)

B7_MONGO_URL = os.environ.get("B7_MONGO_URL")

pytestmark = pytest.mark.skipif(
    not HAVE_PYTEST_ASYNCIO or not B7_MONGO_URL,
    reason="G1 NOT RUN LOCALLY — no explicit B7_MONGO_URL (and/or pytest_asyncio missing)",
)


def _utc(ms=0):
    return datetime(2026, 1, 1, 12, 0, 0, ms * 1000, tzinfo=timezone.utc)


def _candidate(**overrides):
    values = dict(
        stream_id="stream-123",
        stream_version=3,
        requirement_version=2,
        generation_id="generation-abc",
        candidate_id="candidate-1",
        role_dna_id="role-dna-1",
        role_dna_version=4,
        opportunity_spec_id="spec-1",
        opportunity_spec_version=2,
        application_evidence=ApplicationEvidence("app-1", "active", _utc(1)),
        declared_interest_evidence=DeclaredInterestEvidence("declared-1", _utc(2)),
        shared_favorite_evidence=SharedFavoriteEvidence("shared-1", "corr-1", _utc(3)),
        discovery_evidence=DiscoveryEvidence(5, _utc(4)),
        professional_match_summary=ProfessionalMatchSummary(
            1, 4, "match-engine-v1", 80, 70, _utc(5)
        ),
        opportunity_fit_summary=OpportunityFitSummary(
            5, 2, "fit-engine-v1",
            HardEligibilityState.ELIGIBLE, OpportunityFitState.COMPATIBLE, 75, _utc(6),
        ),
        computed_at=_utc(7),
    )
    values.update(overrides)
    return StreamCandidate(**values)


def _candidate_set(stream_id, generation_id, count, **overrides):
    candidates = []
    for index in range(count):
        candidate_id = f"candidate-{index}"
        if index % 2 == 0:
            kwargs = {key: None for key in (
                "declared_interest_evidence", "shared_favorite_evidence",
                "discovery_evidence", "professional_match_summary",
                "opportunity_fit_summary")}
            kwargs["application_evidence"] = ApplicationEvidence(f"app-{index}", "active", _utc(index + 1))
        else:
            kwargs = {key: None for key in (
                "application_evidence", "shared_favorite_evidence",
                "discovery_evidence", "professional_match_summary",
                "opportunity_fit_summary")}
            kwargs["declared_interest_evidence"] = DeclaredInterestEvidence(f"declared-{index}", _utc(index + 1))
        candidates.append(_candidate(
            application_evidence=kwargs.get("application_evidence"),
            declared_interest_evidence=kwargs.get("declared_interest_evidence"),
            shared_favorite_evidence=kwargs.get("shared_favorite_evidence"),
            discovery_evidence=kwargs.get("discovery_evidence"),
            professional_match_summary=kwargs.get("professional_match_summary"),
            opportunity_fit_summary=kwargs.get("opportunity_fit_summary"),
            computed_at=_utc(7),
            stream_id=stream_id,
            generation_id=generation_id,
            candidate_id=candidate_id,
            **overrides,
        ))
    return candidates


async def _bundle(database):
    collection_names = sorted(await database.list_collection_names())

    async def dump(name):
        return list(await database[name].find({}).to_list(length=None))

    indexes = {}
    for name in collection_names:
        index_infos = []
        async for info in database[name].list_indexes():
            index_infos.append((info["name"], list(info["key"])))
        indexes[name] = sorted(index_infos)
    return {
        "collections": collection_names,
        "indexes": indexes,
        "candidates": await dump("talent_stream_candidates") if "talent_stream_candidates" in collection_names else [],
        "states": await dump("talent_stream_candidate_projection_states") if "talent_stream_candidate_projection_states" in collection_names else [],
        "generations": await dump("talent_stream_candidate_generations") if "talent_stream_candidate_generations" in collection_names else [],
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


def _publish(repository, *, stream_id, generation_id, expected_candidate_count,
             observed=None, published_at=_utc(900)):
    return repository.publish_generation(
        stream_id=stream_id, stream_version=3, requirement_version=2,
        generation_id=generation_id, expected_candidate_count=expected_candidate_count,
        role_dna_id="role-dna-1", role_dna_version=4,
        opportunity_spec_id="spec-1", opportunity_spec_version=2,
        expected_state=observed,
        published_at=published_at,
    )


async def _begin(repository, *, stream_id, generation_id):
    return await repository.begin_generation(
        stream_id=stream_id, generation_id=generation_id,
        stream_version=3, requirement_version=2,
        role_dna_id="role-dna-1", role_dna_version=4,
        opportunity_spec_id="spec-1", opportunity_spec_version=2,
    )


async def _seal(repository, *, stream_id, generation_id, candidate_count):
    return await repository.seal_generation(
        stream_id=stream_id, generation_id=generation_id,
        stream_version=3, requirement_version=2,
        role_dna_id="role-dna-1", role_dna_version=4,
        opportunity_spec_id="spec-1", opportunity_spec_version=2,
        candidate_count=candidate_count,
    )


async def _provision_a11_baseline(database):
    existing = set(await database.list_collection_names())
    if "talent_intent_events" not in existing:
        await database.create_collection("talent_intent_events", collation={"locale": "simple"})
    await database["talent_intent_events"].create_index(
        [("idempotency_key", 1)],
        name="ts_a11_idempotency_key_unique",
        unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
        collation={"locale": "simple"},
    )


async def _migrate_b7_ready(database):
    await _provision_a11_baseline(database)
    return await migrate(database, apply=True)


@pytest.mark.asyncio
async def test_1_migration_preflight_without_apply_is_immutable(b7_db):
    result = await preflight(b7_db)
    assert result["index_ready"] is False
    assert result["candidates_collection"] is False
    assert result["projection_states_collection"] is False
    assert result["generations_collection"] is False
    assert result["generations_ready"] is False
    assert result["generation_records_checked"] == 0
    unchanged = await migrate(b7_db, apply=False)
    assert unchanged == result
    assert await b7_db.list_collection_names() == []


@pytest.mark.asyncio
async def test_1b_apply_requires_a11_baseline_and_mutates_nothing(b7_db):
    with pytest.raises(B7MigrationError):
        await migrate(b7_db, apply=True)
    assert await b7_db.list_collection_names() == []


@pytest.mark.asyncio
async def test_1c_apply_refuses_intent_collection_without_canonical_index(b7_db):
    await b7_db.create_collection("talent_intent_events", collation={"locale": "simple"})
    with pytest.raises(B7MigrationError):
        await migrate(b7_db, apply=True)
    collections = set(await b7_db.list_collection_names())
    assert collections == {"talent_intent_events"}
    indexes = set(await b7_db["talent_intent_events"].index_information())
    assert indexes == {"_id_"}
    assert "ts_a11_idempotency_key_unique" not in indexes
    assert "ts_b7_intent_job_event_scan" not in indexes


@pytest.mark.asyncio
async def test_2_migration_apply_creates_collections_and_unique_index(b7_db):
    await _migrate_b7_ready(b7_db)
    collections = await b7_db.list_collection_names()
    assert "talent_stream_candidates" in collections
    assert "talent_stream_candidate_projection_states" in collections
    assert "talent_stream_candidate_generations" in collections
    candidate_infos = await b7_db["talent_stream_candidates"].index_information()
    assert candidate_infos["_id_"]["key"] == [("_id", 1)]
    index = candidate_infos["ts_b7_stream_generation_candidate_unique"]
    assert index["key"] == [("stream_id", 1), ("generation_id", 1), ("candidate_id", 1)]
    assert index["unique"] is True
    assert "expireAfterSeconds" not in index
    generation_infos = await b7_db["talent_stream_candidate_generations"].index_information()
    assert set(generation_infos) == {"_id_"}
    assert generation_infos["_id_"]["key"] == [("_id", 1)]
    await preflight(b7_db)


@pytest.mark.asyncio
async def test_3_migration_is_repeatable_and_does_not_mutate_state(b7_db):
    await _migrate_b7_ready(b7_db)
    before = await _bundle(b7_db)
    await _migrate_b7_ready(b7_db)
    after = await _bundle(b7_db)
    assert before == after


@pytest.mark.asyncio
async def test_4_preflight_fails_closed_on_unexpected_extra_index(b7_db):
    await _migrate_b7_ready(b7_db)
    await b7_db["talent_stream_candidates"].create_index([("candidate_id", 1)], name="rogue_index")
    with pytest.raises(B7MigrationError):
        await preflight(b7_db)


@pytest.mark.asyncio
async def test_5_preflight_detects_existing_candidate_index_without_apply(b7_db):
    collection = b7_db["talent_stream_candidates"]
    await collection.create_index(
        [("stream_id", 1), ("generation_id", 1), ("candidate_id", 1)],
        name="ts_b7_stream_generation_candidate_unique",
        unique=True,
    )
    result = await preflight(b7_db)
    assert result["index_ready"] is True


@pytest.mark.asyncio
async def test_5b_preflight_fails_closed_on_malformed_candidate_document(b7_db):
    collection = b7_db["talent_stream_candidates"]
    await collection.create_index(
        [("stream_id", 1), ("generation_id", 1), ("candidate_id", 1)],
        name="ts_b7_stream_generation_candidate_unique",
        unique=True,
    )
    await collection.insert_one({
        "_id": candidate_document_id("stream-1", "generation-1", "candidate-0"),
        "schema_version": "talent-stream-candidate-v9",
        "stream_id": "stream-1",
    })
    with pytest.raises(B7MigrationError):
        await preflight(b7_db)


@pytest.mark.asyncio
async def test_6_readiness_fails_fast_before_any_write_when_collections_missing(b7_db):
    repository = StreamCandidateRepository(b7_db)
    with pytest.raises(StreamCandidateReadinessError):
        await repository.readiness()
    assert await b7_db["talent_stream_candidates"].count_documents({}) == 0
    assert await b7_db["talent_stream_candidate_projection_states"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_7_readiness_succeeds_only_after_migration(b7_db):
    with pytest.raises(StreamCandidateReadinessError):
        await StreamCandidateRepository(b7_db).readiness()
    await _migrate_b7_ready(b7_db)
    await StreamCandidateRepository(b7_db).readiness()


@pytest.mark.asyncio
@pytest.mark.parametrize("try_idempotent", [True, False])
async def test_8_publish_initial_generation_and_idempotent_retry(b7_db, try_idempotent):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    candidates = _candidate_set("stream-1", "generation-1", 2)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(candidates)
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=2)

    state = await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=2, observed=None,
    )
    assert state.state_version == 1
    assert state.active_generation_id == "generation-1"
    assert state.candidate_count == 2
    assert await b7_db["talent_stream_candidate_projection_states"].count_documents({"_id": "stream-1"}) == 1

    stored = await b7_db["talent_stream_candidate_projection_states"].find_one({"_id": "stream-1"})
    assert stored["schema_version"] == TALENT_STREAM_CANDIDATE_PROJECTION_STATE_SCHEMA_VERSION
    assert stored["state_version"] == 1
    assert isinstance(stored["published_at"], datetime)
    assert stored["published_at"].tzinfo is None
    assert state.published_at.tzinfo is not None
    assert state.published_at == stored["published_at"].replace(tzinfo=timezone.utc)

    candidates_docs = list(await b7_db["talent_stream_candidates"].find({}).to_list(length=None))
    assert len(candidates_docs) == 2
    ordered = sorted(zip(sorted(candidates, key=lambda c: c.candidate_id),
                         sorted(candidates_docs, key=lambda d: d["candidate_id"])),
                     key=lambda pair: pair[0].candidate_id)
    for candidate, document in ordered:
        assert document["_id"] == candidate_document_id(
            "stream-1", "generation-1", candidate.candidate_id
        )
        assert document["schema_version"] == TALENT_STREAM_CANDIDATE_SCHEMA_VERSION
        assert document["stream_id"] == "stream-1"
        assert document["generation_id"] == "generation-1"

    stored_record = await b7_db["talent_stream_candidate_generations"].find_one(
        {"_id": generation_record_document_id("stream-1", "generation-1")}
    )
    record = generation_record_from_document(stored_record)
    assert record.state is GenerationState.SEALED
    assert record.candidate_count == 2
    assert stored_record["schema_version"] == TALENT_STREAM_CANDIDATE_GENERATIONS_SCHEMA_VERSION

    if try_idempotent:
        again = await _publish(
            repository, stream_id="stream-1", generation_id="generation-1",
            expected_candidate_count=2, observed=None,
        )
        assert again.state_version == 1
        assert await b7_db["talent_stream_candidate_projection_states"].count_documents({}) == 1


@pytest.mark.asyncio
async def test_9_second_generation_cas_publication_increments_state_version(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    first = _candidate_set("stream-1", "generation-1", 1)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(first)
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=None,
    )
    second = _candidate_set("stream-1", "generation-2", 1)
    await _begin(repository, stream_id="stream-1", generation_id="generation-2")
    await repository.stage_candidates(second)
    await _seal(repository, stream_id="stream-1", generation_id="generation-2",
                candidate_count=1)
    observed = await repository.get_projection_state("stream-1")
    state = await _publish(
        repository, stream_id="stream-1", generation_id="generation-2",
        expected_candidate_count=1, observed=observed,
    )
    assert state.state_version == 2
    assert state.active_generation_id == "generation-2"
    assert await b7_db["talent_stream_candidate_projection_states"].count_documents({}) == 1
    assert await b7_db["talent_stream_candidates"].count_documents({"generation_id": "generation-2"}) == 1
    assert await b7_db["talent_stream_candidates"].count_documents({"generation_id": "generation-1"}) == 1


@pytest.mark.asyncio
async def test_10_two_initial_publications_race_one_wins_loser_conflicts(b7_db):
    await _migrate_b7_ready(b7_db)
    repository_a = StreamCandidateRepository(b7_db)
    repository_b = StreamCandidateRepository(b7_db)
    await _begin(repository_a, stream_id="stream-1", generation_id="generation-a")
    await repository_a.stage_candidates(_candidate_set("stream-1", "generation-a", 1))
    await _seal(repository_a, stream_id="stream-1", generation_id="generation-a",
                candidate_count=1)
    await _begin(repository_b, stream_id="stream-1", generation_id="generation-b")
    await repository_b.stage_candidates(_candidate_set("stream-1", "generation-b", 1))
    await _seal(repository_b, stream_id="stream-1", generation_id="generation-b",
                candidate_count=1)
    state_a = await _publish(
        repository_a, stream_id="stream-1", generation_id="generation-a",
        expected_candidate_count=1, observed=None,
    )
    assert state_a.state_version == 1
    with pytest.raises(StreamCandidateConflictError):
        await _publish(
            repository_b, stream_id="stream-1", generation_id="generation-b",
            expected_candidate_count=1, observed=None,
        )
    final = await repository_a.get_projection_state("stream-1")
    assert final.active_generation_id == "generation-a"
    assert final.state_version == 1


@pytest.mark.asyncio
async def test_11_optimistic_concurrency_effectively_serializes_publications(b7_db):
    await _migrate_b7_ready(b7_db)
    repository_a = StreamCandidateRepository(b7_db)
    repository_b = StreamCandidateRepository(b7_db)
    await _begin(repository_a, stream_id="stream-1", generation_id="generation-1")
    await repository_a.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await _seal(repository_a, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    await _begin(repository_a, stream_id="stream-1", generation_id="generation-2")
    await repository_a.stage_candidates(_candidate_set("stream-1", "generation-2", 1))
    await _seal(repository_a, stream_id="stream-1", generation_id="generation-2",
                candidate_count=1)
    await _begin(repository_b, stream_id="stream-1", generation_id="generation-3")
    await repository_b.stage_candidates(_candidate_set("stream-1", "generation-3", 1))
    await _seal(repository_b, stream_id="stream-1", generation_id="generation-3",
                candidate_count=1)
    await _publish(
        repository_a, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=None,
    )
    stale_observed = await repository_b.get_projection_state("stream-1")
    assert stale_observed.state_version == 1 and stale_observed.active_generation_id == "generation-1"
    winning = await _publish(
        repository_a, stream_id="stream-1", generation_id="generation-2",
        expected_candidate_count=1, observed=stale_observed,
    )
    assert winning.state_version == 2 and winning.active_generation_id == "generation-2"
    with pytest.raises(StreamCandidateConflictError):
        await _publish(
            repository_b, stream_id="stream-1", generation_id="generation-3",
            expected_candidate_count=1, observed=stale_observed,
        )
    final = await repository_a.get_projection_state("stream-1")
    assert final.active_generation_id == "generation-2" and final.state_version == 2


@pytest.mark.asyncio
async def test_12_exact_publication_retry_is_idempotent(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    first = await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=None,
    )
    current = await repository.get_projection_state("stream-1")
    retry = await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=current,
    )
    assert retry == current == first
    assert (await repository.get_projection_state("stream-1")).state_version == 1


@pytest.mark.asyncio
async def test_publish_records_exact_provided_timestamp(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    state = await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=None, published_at=_utc(901),
    )
    assert state.published_at == _utc(901)
    stored = await b7_db["talent_stream_candidate_projection_states"].find_one(
        {"_id": "stream-1"}
    )
    assert stored["published_at"] == _utc(901).replace(tzinfo=None)
    assert await b7_db["talent_stream_candidate_projection_states"].count_documents({}) == 1


@pytest.mark.asyncio
async def test_publish_retry_with_same_timestamp_is_idempotent(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    first = await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=None, published_at=_utc(901),
    )
    current = await repository.get_projection_state("stream-1")
    retry = await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=current, published_at=_utc(901),
    )
    assert retry == current == first
    assert (await repository.get_projection_state("stream-1")).state_version == 1
    again = await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=current, published_at=_utc(901),
    )
    assert await repository.get_projection_state("stream-1") == again


@pytest.mark.asyncio
async def test_publish_same_generation_different_timestamp_conflicts(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=None, published_at=_utc(901),
    )
    current = await repository.get_projection_state("stream-1")
    with pytest.raises(StreamCandidateConflictError):
        await _publish(
            repository, stream_id="stream-1", generation_id="generation-1",
            expected_candidate_count=1, observed=current, published_at=_utc(902),
        )
    state = await repository.get_projection_state("stream-1")
    assert state.published_at == _utc(901)
    assert state.state_version == 1


@pytest.mark.asyncio
async def test_13_zero_candidate_generation_is_valid(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-empty")
    await _seal(repository, stream_id="stream-1", generation_id="generation-empty",
                candidate_count=0)
    state = await _publish(
        repository, stream_id="stream-1", generation_id="generation-empty",
        expected_candidate_count=0, observed=None,
    )
    assert state.candidate_count == 0
    assert state.active_generation_id == "generation-empty"
    assert await repository.get_projection_state("stream-1") == state
    assert await repository.find_generation("stream-1", "generation-empty", limit=100) == []


@pytest.mark.asyncio
async def test_14_staging_duplicate_conflicts_and_identical_retry_is_idempotent(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    candidates = _candidate_set("stream-1", "generation-1", 2)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(candidates)
    with pytest.raises(StreamCandidateRepositoryError):
        await repository.stage_candidates(candidates + [_candidate(
            stream_id="stream-1", generation_id="generation-1", candidate_id="candidate-1",
        )])
    conflicting = [_candidate(
        stream_id="stream-1", generation_id="generation-1", candidate_id="candidate-0",
        application_evidence=ApplicationEvidence("app-other", "active", _utc(50)),
    )]
    with pytest.raises(StreamCandidateConflictError):
        await repository.stage_candidates(conflicting)
    result = await repository.stage_candidates(candidates)
    assert result["staged"] == 0 and result["idempotent_retries"] == 2
    assert len(await repository.find_generation("stream-1", "generation-1", limit=100)) == 2


@pytest.mark.asyncio
async def test_15_staging_exact_retry_is_idempotent(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    same = _candidate_set("stream-1", "generation-1", 1)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(same)
    await repository.stage_candidates(same)
    read_back = await repository.find_generation("stream-1", "generation-1", limit=100)
    assert read_back == same == [
        stream_candidate_from_document(document)
        for document in await b7_db["talent_stream_candidates"].find(
            {"_id": candidate_document_id("stream-1", "generation-1", "candidate-0")}
        ).to_list(length=1)
    ]


@pytest.mark.asyncio
async def test_16_publication_rejects_candidate_count_mismatch(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    with pytest.raises(StreamCandidateConflictError):
        await _publish(
            repository, stream_id="stream-1", generation_id="generation-1",
            expected_candidate_count=2, observed=None,
        )
    assert await b7_db["talent_stream_candidate_projection_states"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_17_old_generations_remain_readable_after_swap(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=None,
    )
    await _begin(repository, stream_id="stream-1", generation_id="generation-2")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-2", 1))
    await _seal(repository, stream_id="stream-1", generation_id="generation-2",
                candidate_count=1)
    observed = await repository.get_projection_state("stream-1")
    await _publish(
        repository, stream_id="stream-1", generation_id="generation-2",
        expected_candidate_count=1, observed=observed,
    )
    old = await repository.find_generation("stream-1", "generation-1", limit=100)
    assert len(old) == 1
    assert await b7_db["talent_stream_candidates"].count_documents({}) == 2
    state = await repository.get_projection_state("stream-1")
    assert state.active_generation_id == "generation-2" and state.state_version == 2


@pytest.mark.asyncio
async def test_18_pagination_ascending_and_strict_limit(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    candidates = _candidate_set("stream-1", "generation-1", 5)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(candidates)
    reference = sorted(candidates, key=lambda item: item.candidate_id)
    page = await repository.find_generation("stream-1", "generation-1", limit=2)
    assert [item.candidate_id for item in page] == ["candidate-0", "candidate-1"]
    page = await repository.find_generation(
        "stream-1", "generation-1", limit=2, after_candidate_id="candidate-1"
    )
    assert [item.candidate_id for item in page] == ["candidate-2", "candidate-3"]
    page = await repository.find_generation(
        "stream-1", "generation-1", limit=2, after_candidate_id="candidate-3"
    )
    assert [item.candidate_id for item in page] == ["candidate-4"]
    assert await repository.find_generation("stream-1", "generation-1", limit=5) == reference
    with pytest.raises(StreamCandidateRepositoryError):
        await repository.find_generation("stream-1", "generation-1", limit=0)
    with pytest.raises(StreamCandidateRepositoryError):
        await repository.find_generation("stream-1", "generation-1", limit=501)


@pytest.mark.asyncio
async def test_19_publication_never_touches_other_collections(b7_db):
    await _migrate_b7_ready(b7_db)
    await b7_db["talent_streams"].insert_one({"_id": "stream-1", "kind": "intruder"})
    await b7_db["candidate_preferences"].insert_one({"_id": "pref-1"})
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=None,
    )
    bundle = await _bundle(b7_db)
    assert await b7_db["talent_streams"].count_documents({}) == 1
    assert await b7_db["candidate_preferences"].count_documents({}) == 1
    assert bundle["states"][0]["schema_version"] == TALENT_STREAM_CANDIDATE_PROJECTION_STATE_SCHEMA_VERSION
    assert len(bundle["candidates"]) == 1
    assert bundle["generations"][0]["schema_version"] == (
        TALENT_STREAM_CANDIDATE_GENERATIONS_SCHEMA_VERSION)
    assert bundle["generations"][0]["state"] == "sealed"
    for name in ("idempotency_key", "raw_saved_job", "raw_candidate_profile",
                 "recruiter_notes", "name", "email"):
        for document in bundle["candidates"] + bundle["states"] + bundle["generations"]:
            assert name not in document


async def test_begin_writes_a_building_record_without_count(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    stored = await b7_db["talent_stream_candidate_generations"].find_one(
        {"_id": generation_record_document_id("stream-1", "generation-1")}
    )
    assert stored["schema_version"] == TALENT_STREAM_CANDIDATE_GENERATIONS_SCHEMA_VERSION
    assert stored["state"] == "building"
    assert "candidate_count" not in stored
    record = generation_record_from_document(stored)
    assert record.state is GenerationState.BUILDING and record.candidate_count is None


@pytest.mark.asyncio
async def test_building_generation_cannot_be_published(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    with pytest.raises(StreamCandidateConflictError) as exc:
        await _publish(
            repository, stream_id="stream-1", generation_id="generation-1",
            expected_candidate_count=1, observed=None,
        )
    assert str(exc.value) == "b7 generation is not sealed"
    assert await b7_db["talent_stream_candidate_projection_states"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_sealed_generation_is_permanently_immutable(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=None,
    )
    with pytest.raises(StreamCandidateConflictError) as exc:
        await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 2))
    assert str(exc.value) == "b7 generation is sealed"
    with pytest.raises(StreamCandidateConflictError) as exc:
        await repository.begin_generation(
            stream_id="stream-1", generation_id="generation-1",
            stream_version=3, requirement_version=2,
            role_dna_id="role-dna-1", role_dna_version=5,
            opportunity_spec_id="spec-1", opportunity_spec_version=2,
        )
    assert str(exc.value) == "b7 generation scope mismatch"
    assert await b7_db["talent_stream_candidates"].count_documents({}) == 1
    record = await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    assert record.state is GenerationState.SEALED and record.candidate_count == 1


@pytest.mark.asyncio
async def test_sealed_exact_seal_retry_is_idempotent(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    first = await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                        candidate_count=1)
    retry = await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                        candidate_count=1)
    assert retry == first and retry.state is GenerationState.SEALED
    assert retry.candidate_count == 1


@pytest.mark.asyncio
async def test_seal_after_publish_count_mismatch_conflicts(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                candidate_count=1)
    await _publish(
        repository, stream_id="stream-1", generation_id="generation-1",
        expected_candidate_count=1, observed=None,
    )
    with pytest.raises(StreamCandidateConflictError) as exc:
        await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                    candidate_count=2)
    assert str(exc.value) == "b7 sealed generation candidate count mismatch"


@pytest.mark.asyncio
async def test_seal_count_mismatch_with_staged_documents_conflicts(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    with pytest.raises(StreamCandidateConflictError) as exc:
        await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                    candidate_count=2)
    assert str(exc.value) == "b7 generation candidate count mismatch"
    record = await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                         candidate_count=1)
    assert record.state is GenerationState.SEALED


@pytest.mark.asyncio
async def test_seal_scope_mismatch_conflicts(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    with pytest.raises(StreamCandidateConflictError) as exc:
        await repository.seal_generation(
            stream_id="stream-1", generation_id="generation-1",
            stream_version=3, requirement_version=2,
            role_dna_id="role-dna-1", role_dna_version=5,
            opportunity_spec_id="spec-1", opportunity_spec_version=2,
            candidate_count=1,
        )
    assert str(exc.value) == "b7 generation scope mismatch"
    assert await b7_db["talent_stream_candidate_projection_states"].count_documents({}) == 0


@pytest.mark.asyncio
async def test_interrupted_seal_resumes_only_by_exact_retry(b7_db):
    await _migrate_b7_ready(b7_db)
    repository = StreamCandidateRepository(b7_db)
    await _begin(repository, stream_id="stream-1", generation_id="generation-1")
    await repository.stage_candidates(_candidate_set("stream-1", "generation-1", 1))
    await b7_db["talent_stream_candidate_generations"].update_one(
        {"_id": generation_record_document_id("stream-1", "generation-1")},
        {"$set": {"state": "sealing", "candidate_count": 1}},
    )
    pending = await repository._read_generation_record("stream-1", "generation-1")
    assert pending.state is GenerationState.SEALING and pending.candidate_count == 1
    with pytest.raises(StreamCandidateConflictError) as exc:
        await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                    candidate_count=2)
    assert str(exc.value) == "b7 interrupted seal retry count mismatch"
    sealed = await _seal(repository, stream_id="stream-1", generation_id="generation-1",
                         candidate_count=1)
    assert sealed.state is GenerationState.SEALED and sealed.candidate_count == 1


async def _ready_without_intent_scan(database):
    await _migrate_b7_ready(database)
    await database["talent_intent_events"].drop_index("ts_b7_intent_job_event_scan")


@pytest.mark.asyncio
async def test_20_a11_conform_without_scan_index_is_acceptable_preflight(b7_db):
    await _ready_without_intent_scan(b7_db)
    result = await preflight(b7_db)
    assert result["intent_index_ready"] is False
    assert result["index_ready"] is True
    assert result["candidates_collection"] is True
    assert result["projection_states_collection"] is True


@pytest.mark.asyncio
async def test_21_apply_false_never_provisions_the_intent_index(b7_db):
    await _ready_without_intent_scan(b7_db)
    result = await migrate(b7_db, apply=False)
    assert result["intent_index_ready"] is False
    intent_infos = await b7_db["talent_intent_events"].index_information()
    assert set(intent_infos) == {"_id_", "ts_a11_idempotency_key_unique"}
    candidates_infos = await b7_db["talent_stream_candidates"].index_information()
    assert set(candidates_infos) == {"_id_", "ts_b7_stream_generation_candidate_unique"}


@pytest.mark.asyncio
async def test_22_apply_true_provisions_exactly_the_intent_scan_index(b7_db):
    await _ready_without_intent_scan(b7_db)
    result = await _migrate_b7_ready(b7_db)
    assert result["intent_index_ready"] is True
    assert result["index_ready"] is True
    intent_infos = await b7_db["talent_intent_events"].index_information()
    assert set(intent_infos) == {
        "_id_", "ts_a11_idempotency_key_unique", "ts_b7_intent_job_event_scan",
    }
    scan = intent_infos["ts_b7_intent_job_event_scan"]
    assert scan["key"] == [("job_id", 1), ("event_type", 1), ("occurred_at", 1), ("_id", 1)]
    assert scan.get("unique", False) is False
    assert "expireAfterSeconds" not in scan
    assert "partialFilterExpression" not in scan
    assert scan.get("collation", {}).get("locale", "simple") == "simple"
    assert not scan.get("sparse", False) and not scan.get("hidden", False)


@pytest.mark.asyncio
async def test_23_repeatable_migration_remains_identical_with_intent_provisioned(b7_db):
    await _migrate_b7_ready(b7_db)
    before = await _bundle(b7_db)
    await _migrate_b7_ready(b7_db)
    after = await _bundle(b7_db)
    assert before == after
    intent_infos = await b7_db["talent_intent_events"].index_information()
    assert set(intent_infos) == {
        "_id_", "ts_a11_idempotency_key_unique", "ts_b7_intent_job_event_scan",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [
    {"unique": True},
    {"collation": {"locale": "fr"}},
    {"partialFilterExpression": {"job_id": {"$type": "string"}}},
])
async def test_24_preflight_fails_closed_on_incompatible_scan_index(b7_db, kwargs):
    await _ready_without_intent_scan(b7_db)
    await b7_db["talent_intent_events"].create_index(
        [("job_id", 1), ("event_type", 1), ("occurred_at", 1), ("_id", 1)],
        name="ts_b7_intent_job_event_scan", **kwargs,
    )
    with pytest.raises(B7MigrationError):
        await preflight(b7_db)


@pytest.mark.asyncio
async def test_25_preflight_fails_closed_on_wrong_scan_key_order(b7_db):
    await _ready_without_intent_scan(b7_db)
    await b7_db["talent_intent_events"].create_index(
        [("event_type", 1), ("job_id", 1), ("occurred_at", 1), ("_id", 1)],
        name="ts_b7_intent_job_event_scan",
    )
    with pytest.raises(B7MigrationError):
        await preflight(b7_db)


@pytest.mark.asyncio
async def test_26_preflight_fails_closed_on_unexpected_a11_index(b7_db):
    await _ready_without_intent_scan(b7_db)
    await b7_db["talent_intent_events"].create_index([("occurred_at", 1)], name="ts_rogue_scan")
    with pytest.raises(B7MigrationError):
        await preflight(b7_db)
    assert set(await b7_db["talent_intent_events"].index_information()) == {
        "_id_", "ts_a11_idempotency_key_unique", "ts_rogue_scan",
    }


@pytest.mark.asyncio
async def test_27_preflight_fails_closed_on_incompatible_a11_idempotency_index(b7_db):
    await _ready_without_intent_scan(b7_db)
    intent_collection = b7_db["talent_intent_events"]
    await intent_collection.drop_index("ts_a11_idempotency_key_unique")
    await intent_collection.create_index(
        [("event_id", 1)], name="ts_a11_idempotency_key_unique", unique=True,
        partialFilterExpression={"event_id": {"$type": "string"}},
        collation={"locale": "simple"},
    )
    with pytest.raises(B7MigrationError):
        await preflight(b7_db)


@pytest.mark.asyncio
async def test_28_preflight_fails_closed_on_non_simple_intent_collection(b7_db):
    await _ready_without_intent_scan(b7_db)
    await b7_db["talent_intent_events"].drop()
    await b7_db.create_collection("talent_intent_events", collation={"locale": "fr"})
    await b7_db["talent_intent_events"].create_index(
        [("idempotency_key", 1)], name="ts_a11_idempotency_key_unique", unique=True,
        partialFilterExpression={"idempotency_key": {"$type": "string"}},
        collation={"locale": "simple"},
    )
    with pytest.raises(B7MigrationError):
        await preflight(b7_db)


@pytest.mark.asyncio
async def test_29_preflight_fails_closed_on_ttl_intent_index(b7_db):
    await _ready_without_intent_scan(b7_db)
    await b7_db["talent_intent_events"].create_index(
        [("occurred_at", 1)], name="ts_rogue_expiry_ttl", expireAfterSeconds=3600
    )
    with pytest.raises(B7MigrationError):
        await preflight(b7_db)