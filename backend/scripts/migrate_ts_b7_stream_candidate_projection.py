#!/usr/bin/env python3
"""Explicit TS-B7 Stream Candidate projection migration; read-only without --apply.

Creates ONLY: the three B7 collections, the B7 candidate unique index, and the
B7 Intent job event scan index used exclusively by the future B7 Intent reader.
Never drops collections/indexes, mutates documents, backfills, repairs, adds TTL
or touches TalentStream. Preflight strictly inspects existing metadata and B7
documents and fails closed on any incompatibility, including any non-ordinary,
non-simple or TTL A11 events collection. When B7 candidates or projection
states already exist, the generation registry must already hold an exact
SEALED record for every referenced generation; missing, unsealed or
mismatched-scope/count records fail closed without repair (the migration never
fabricates a registry for pre-existing data), and every ProjectionState must
match its generation record and its candidate document set exactly. --apply
requires the A11 Intent events collection and its canonical idempotency index
to already exist and conform; the migration never creates the Intent events
collection (A11 owns it).
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.motor_asyncio import AsyncIOMotorClient

from domains.talent_stream.index_requirements import (
    TALENT_INTENT_EVENTS_REQUIREMENT,
    TALENT_STREAM_CANDIDATES_REQUIREMENT,
)
from domains.talent_stream.stream_candidate_persistence import (
    GenerationState,
    generation_record_from_document,
    projection_state_from_document,
    stream_candidate_from_document,
)
from mongo_index_safety import compare_index

INDEX_NAME = "ts_b7_stream_generation_candidate_unique"
INDEX_KEY = [
    ("stream_id", 1),
    ("generation_id", 1),
    ("candidate_id", 1),
]
CANDIDATES_COLLECTION = "talent_stream_candidates"
STATES_COLLECTION = "talent_stream_candidate_projection_states"
GENERATIONS_COLLECTION = "talent_stream_candidate_generations"
INTENT_INDEX_NAME = "ts_b7_intent_job_event_scan"
INTENT_INDEX_KEY = [
    ("job_id", 1),
    ("event_type", 1),
    ("occurred_at", 1),
    ("_id", 1),
]
INTENT_COLLECTION = "talent_intent_events"
A11_REQUIREMENT = TALENT_INTENT_EVENTS_REQUIREMENT
A11_IDEMPOTENCY_INDEX = A11_REQUIREMENT.indexes[0]
INTENT_SCAN_INDEX = A11_REQUIREMENT.indexes[1]


class B7MigrationError(RuntimeError):
    pass


def _validate_collection_options(options):
    if options.get("capped"):
        raise B7MigrationError("B7 collections must be ordinary")
    if "timeseries" in options or "viewOn" in options:
        raise B7MigrationError("B7 collections must be ordinary non-view collections")
    if options.get("collation", {}).get("locale", "simple") != "simple":
        raise B7MigrationError("B7 collections must use simple collation")
    if "expireAfterSeconds" in options:
        raise B7MigrationError("TTL is forbidden on B7 collections")


def _validate_candidate_indexes(indexes, options):
    requirement = TALENT_STREAM_CANDIDATES_REQUIREMENT.indexes[0]
    for name, spec in indexes.items():
        if "expireAfterSeconds" in spec:
            raise B7MigrationError("TTL is forbidden on B7 candidate indexes")
        if name == "_id_":
            if list(spec.get("key", [])) != [("_id", 1)]:
                raise B7MigrationError("Incompatible native identity index on B7 candidates")
        elif name == INDEX_NAME:
            if compare_index(requirement, spec, options.get("collation")):
                raise B7MigrationError("Incompatible B7 candidate unique index")
        else:
            raise B7MigrationError("Unexpected index on B7 candidates collection")


def _validate_state_indexes(indexes, options):
    for name, spec in indexes.items():
        if "expireAfterSeconds" in spec:
            raise B7MigrationError("TTL is forbidden on B7 projection state indexes")
        if name == "_id_":
            if list(spec.get("key", [])) != [("_id", 1)]:
                raise B7MigrationError("Incompatible native identity index on B7 projection states")
        else:
            raise B7MigrationError("Unexpected index on B7 projection states collection")


def _validate_generation_indexes(indexes, options):
    for name, spec in indexes.items():
        if "expireAfterSeconds" in spec:
            raise B7MigrationError("TTL is forbidden on B7 generation registry indexes")
        if name == "_id_":
            if list(spec.get("key", [])) != [("_id", 1)]:
                raise B7MigrationError("Incompatible native identity index on B7 generation registry")
        else:
            raise B7MigrationError("Unexpected index on B7 generation registry collection")


def _validate_intent_indexes(indexes, options):
    if A11_IDEMPOTENCY_INDEX.name not in indexes:
        raise B7MigrationError("Missing canonical A11 idempotency index on Intent events")
    for name, spec in indexes.items():
        if "expireAfterSeconds" in spec:
            raise B7MigrationError("TTL is forbidden on Intent event indexes")
        if name == "_id_":
            if list(spec.get("key", [])) != [("_id", 1)]:
                raise B7MigrationError("Incompatible native identity index on Intent events")
        elif name == A11_IDEMPOTENCY_INDEX.name:
            if compare_index(A11_IDEMPOTENCY_INDEX, spec, options.get("collation")):
                raise B7MigrationError("Incompatible A11 idempotency index on Intent events")
        elif name == INTENT_INDEX_NAME:
            if compare_index(INTENT_SCAN_INDEX, spec, options.get("collation")):
                raise B7MigrationError("Incompatible B7 Intent job event scan index")
        else:
            raise B7MigrationError("Unexpected index on Intent events collection")


async def preflight(db):
    names = {
        CANDIDATES_COLLECTION, STATES_COLLECTION, GENERATIONS_COLLECTION,
        INTENT_COLLECTION,
    }
    try:
        collections = {}
        cursor = await db.list_collections(filter={"name": {"$in": sorted(names)}})
        async for record in cursor:
            collections[record["name"]] = record
        indexes = {}
        for name in names:
            if collections.get(name, {}).get("type") == "collection":
                indexes[name] = await db[name].index_information()
        if CANDIDATES_COLLECTION in collections:
            _validate_collection_options(collections[CANDIDATES_COLLECTION].get("options", {}))
            _validate_candidate_indexes(indexes.get(CANDIDATES_COLLECTION, {}),
                                        collections[CANDIDATES_COLLECTION].get("options", {}))
        if STATES_COLLECTION in collections:
            _validate_collection_options(collections[STATES_COLLECTION].get("options", {}))
            _validate_state_indexes(indexes.get(STATES_COLLECTION, {}),
                                    collections[STATES_COLLECTION].get("options", {}))
        if GENERATIONS_COLLECTION in collections:
            _validate_collection_options(collections[GENERATIONS_COLLECTION].get("options", {}))
            _validate_generation_indexes(indexes.get(GENERATIONS_COLLECTION, {}),
                                         collections[GENERATIONS_COLLECTION].get("options", {}))
        if INTENT_COLLECTION in collections:
            _validate_collection_options(collections[INTENT_COLLECTION].get("options", {}))
            _validate_intent_indexes(indexes.get(INTENT_COLLECTION, {}),
                                     collections[INTENT_COLLECTION].get("options", {}))
        candidate_count = 0
        identities = set()
        generation_scopes = {}
        generation_counts = {}
        if CANDIDATES_COLLECTION in collections:
            async for document in db[CANDIDATES_COLLECTION].find({}):
                try:
                    candidate = stream_candidate_from_document(document)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise B7MigrationError(
                        "Malformed B7 candidate document; no indexes created"
                    ) from exc
                identity = (
                    str(candidate.stream_id),
                    str(candidate.generation_id),
                    str(candidate.candidate_id),
                )
                if identity in identities:
                    raise B7MigrationError("Duplicate B7 candidate logical identity")
                identities.add(identity)
                generation_key = (
                    str(candidate.stream_id),
                    str(candidate.generation_id),
                )
                scope = (
                    int(candidate.stream_version),
                    int(candidate.requirement_version),
                    str(candidate.role_dna_id),
                    int(candidate.role_dna_version),
                    str(candidate.opportunity_spec_id),
                    int(candidate.opportunity_spec_version),
                )
                if (
                    generation_key in generation_scopes
                    and generation_scopes[generation_key] != scope
                ):
                    raise B7MigrationError(
                        "B7 candidate scope is inconsistent within one generation"
                    )
                generation_scopes[generation_key] = scope
                generation_counts[generation_key] = (
                    generation_counts.get(generation_key, 0) + 1
                )
                candidate_count += 1
        state_count = 0
        published_counts = {}
        states_by_generation = {}
        if STATES_COLLECTION in collections:
            async for document in db[STATES_COLLECTION].find({}):
                try:
                    state = projection_state_from_document(document)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise B7MigrationError(
                        "Malformed B7 projection state; no indexes created"
                    ) from exc
                state_key = (str(state.stream_id), str(state.active_generation_id))
                published_counts[state_key] = int(state.candidate_count)
                states_by_generation[state_key] = state
                state_count += 1
        referenced = set(generation_scopes) | set(published_counts)
        generations_ready = False
        generation_records_checked = 0
        if GENERATIONS_COLLECTION in collections:
            records = {}
            async for document in db[GENERATIONS_COLLECTION].find({}):
                try:
                    record = generation_record_from_document(document)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise B7MigrationError(
                        "Malformed B7 generation registry record; no indexes created"
                    ) from exc
                record_key = (str(record.stream_id), str(record.generation_id))
                if record_key in records:
                    raise B7MigrationError(
                        "Duplicate B7 generation registry identity"
                    )
                records[record_key] = record
                generation_records_checked += 1
            for generation_key in sorted(referenced):
                record = records.get(generation_key)
                if record is None:
                    raise B7MigrationError(
                        "B7 data references a generation absent from the registry"
                    )
                if record.state is not GenerationState.SEALED:
                    raise B7MigrationError(
                        "B7 data references a generation that was never sealed"
                    )
                expected_scope = generation_scopes.get(generation_key)
                if (
                    expected_scope is not None
                    and (
                        int(record.stream_version),
                        int(record.requirement_version),
                        str(record.role_dna_id),
                        int(record.role_dna_version),
                        str(record.opportunity_spec_id),
                        int(record.opportunity_spec_version),
                    )
                    != expected_scope
                ):
                    raise B7MigrationError("B7 generation registry scope mismatch")
                state = states_by_generation.get(generation_key)
                doc_count = generation_counts.get(generation_key)
                if state is not None:
                    doc_count = generation_counts.get(generation_key, 0)
                    record_scope = (
                        str(record.stream_id),
                        str(record.generation_id),
                        int(record.stream_version),
                        int(record.requirement_version),
                        str(record.role_dna_id),
                        int(record.role_dna_version),
                        str(record.opportunity_spec_id),
                        int(record.opportunity_spec_version),
                    )
                    state_scope = (
                        str(state.stream_id),
                        str(state.active_generation_id),
                        int(state.stream_version),
                        int(state.requirement_version),
                        str(state.role_dna_id),
                        int(state.role_dna_version),
                        str(state.opportunity_spec_id),
                        int(state.opportunity_spec_version),
                    )
                    if record_scope != state_scope or (
                        record.candidate_count is None
                        or int(record.candidate_count) != int(state.candidate_count)
                    ):
                        raise B7MigrationError(
                            "B7 generation registry differs from ProjectionState scope/candidate count"
                        )
                    if int(state.candidate_count) != doc_count:
                        raise B7MigrationError(
                            "B7 candidate documents count differs from ProjectionState"
                        )
                if (
                    doc_count is not None
                    and (
                        record.candidate_count is None
                        or int(record.candidate_count) != doc_count
                    )
                ):
                    raise B7MigrationError(
                        "B7 generation registry candidate count mismatch"
                    )
            generations_ready = True
        elif referenced:
            raise B7MigrationError(
                "B7 data exists without a generation registry; no indexes created"
            )
    except B7MigrationError:
        raise
    except Exception as exc:
        raise B7MigrationError("B7 migration preflight failed") from exc
    return {
        "candidates_collection": CANDIDATES_COLLECTION in collections,
        "projection_states_collection": STATES_COLLECTION in collections,
        "generations_collection": GENERATIONS_COLLECTION in collections,
        "generations_ready": generations_ready,
        "generation_records_checked": generation_records_checked,
        "intent_collection": INTENT_COLLECTION in collections,
        "index_ready": INDEX_NAME in indexes.get(CANDIDATES_COLLECTION, {}),
        "intent_index_ready": INTENT_INDEX_NAME in indexes.get(INTENT_COLLECTION, {}),
        "a11_idempotency_index_ready": (
            A11_IDEMPOTENCY_INDEX.name in indexes.get(INTENT_COLLECTION, {})
        ),
        "candidate_documents_checked": candidate_count,
        "projection_state_documents_checked": state_count,
    }


async def migrate(db, *, apply=False):
    if type(apply) is not bool:
        raise ValueError("explicit boolean apply required")
    result = await preflight(db)
    if not apply:
        return result
    try:
        if not (result["intent_collection"] and result["a11_idempotency_index_ready"]):
            raise B7MigrationError(
                "A11 Intent events baseline is required before B7 migration"
            )
        if not result["candidates_collection"]:
            await db.create_collection(CANDIDATES_COLLECTION, collation={"locale": "simple"})
        if not result["projection_states_collection"]:
            await db.create_collection(STATES_COLLECTION, collation={"locale": "simple"})
        if not result["generations_collection"]:
            await db.create_collection(GENERATIONS_COLLECTION, collation={"locale": "simple"})
        result = await preflight(db)
        if not result["index_ready"]:
            await db.talent_stream_candidates.create_index(INDEX_KEY, name=INDEX_NAME, unique=True)
            result = await preflight(db)
        if not result["intent_index_ready"]:
            await db.talent_intent_events.create_index(INTENT_INDEX_KEY, name=INTENT_INDEX_NAME)
            result = await preflight(db)
    except B7MigrationError:
        raise
    except Exception as exc:
        raise B7MigrationError("B7 migration failed") from exc
    if not (result["index_ready"] and result["intent_index_ready"] and result["generations_ready"]):
        raise B7MigrationError("B7 storage is not ready")
    return result


async def main(*, apply=False):
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not url.strip() or not name or not name.strip():
        print('{"error":"explicit_configuration_required"}')
        return 2
    client = None
    try:
        client = AsyncIOMotorClient(
            url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
            socketTimeoutMS=5000,
        )
        result = await migrate(client[name], apply=apply)
        print(json.dumps(result, separators=(",", ":")))
        return 0 if (
            result["index_ready"] and result["intent_index_ready"] and result["generations_ready"]
        ) else 1
    except Exception:
        print('{"error":"b7_migration_failed"}')
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    raise SystemExit(asyncio.run(main(apply=parser.parse_args().apply)))