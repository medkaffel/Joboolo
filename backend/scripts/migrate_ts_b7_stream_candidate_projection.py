#!/usr/bin/env python3
"""Explicit TS-B7 Stream Candidate projection migration; read-only without --apply.

Creates ONLY: the two B7 collections, the B7 candidate unique index, and the B7
Intent job event scan index used exclusively by the future B7 Intent reader.
Never drops collections/indexes, mutates documents, backfills, repairs, adds TTL
or touches TalentStream. Preflight strictly inspects existing metadata and B7
documents and fails closed on any incompatibility, including any non-ordinary,
non-simple or TTL A11 events collection.
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


def _validate_intent_indexes(indexes, options):
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
    names = {CANDIDATES_COLLECTION, STATES_COLLECTION, INTENT_COLLECTION}
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
        if INTENT_COLLECTION in collections:
            _validate_collection_options(collections[INTENT_COLLECTION].get("options", {}))
            _validate_intent_indexes(indexes.get(INTENT_COLLECTION, {}),
                                     collections[INTENT_COLLECTION].get("options", {}))
        candidate_count = 0
        identities = set()
        if CANDIDATES_COLLECTION in collections:
            async for document in db[CANDIDATES_COLLECTION].find({}):
                try:
                    candidate = stream_candidate_from_document(document)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise B7MigrationError(
                        "Malformed B7 candidate document; no indexes created"
                    ) from exc
                identity = (
                    candidate.stream_id,
                    candidate.generation_id,
                    candidate.candidate_id,
                )
                if identity in identities:
                    raise B7MigrationError("Duplicate B7 candidate logical identity")
                identities.add(identity)
                candidate_count += 1
        state_count = 0
        if STATES_COLLECTION in collections:
            async for document in db[STATES_COLLECTION].find({}):
                try:
                    projection_state_from_document(document)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise B7MigrationError(
                        "Malformed B7 projection state; no indexes created"
                    ) from exc
                state_count += 1
    except B7MigrationError:
        raise
    except Exception as exc:
        raise B7MigrationError("B7 migration preflight failed") from exc
    return {
        "candidates_collection": CANDIDATES_COLLECTION in collections,
        "projection_states_collection": STATES_COLLECTION in collections,
        "index_ready": INDEX_NAME in indexes.get(CANDIDATES_COLLECTION, {}),
        "intent_index_ready": INTENT_INDEX_NAME in indexes.get(INTENT_COLLECTION, {}),
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
        if not result["candidates_collection"]:
            await db.create_collection(CANDIDATES_COLLECTION, collation={"locale": "simple"})
        if not result["projection_states_collection"]:
            await db.create_collection(STATES_COLLECTION, collation={"locale": "simple"})
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
    if not (result["index_ready"] and result["intent_index_ready"]):
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
        return 0 if result["index_ready"] and result["intent_index_ready"] else 1
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