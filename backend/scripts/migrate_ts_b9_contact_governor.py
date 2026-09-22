#!/usr/bin/env python3
"""Explicit B9 Contact Governor storage migration; read-only without --apply.

Creates only the two B9 collections and five declared reservation indexes.
Preflight rejects malformed documents, non-simple/non-ordinary collections,
TTL, unexpected indexes and incompatible definitions. It never drops, renames,
repairs or backfills anything.
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
    CONTACT_GOVERNOR_CANDIDATE_GUARDS_REQUIREMENT,
    CONTACT_GOVERNOR_RESERVATIONS_REQUIREMENT,
)
from domains.trust.contact_governor_persistence import (
    guard_from_document,
    reservation_from_document,
)
from mongo_index_safety import compare_index


RESERVATIONS_COLLECTION = "contact_governor_reservations"
GUARDS_COLLECTION = "contact_governor_candidate_guards"

CANDIDATE_ACTIVITY_NAME = "ts_b9_candidate_activity"
CANDIDATE_ACTIVITY_KEY = [("candidate_id", 1), ("status", 1), ("activity_at", 1)]
REQUESTING_ORG_ACTIVITY_NAME = "ts_b9_requesting_org_activity"
REQUESTING_ORG_ACTIVITY_KEY = [
    ("candidate_id", 1),
    ("requesting_organization_id", 1),
    ("status", 1),
    ("activity_at", 1),
]
HIRING_COMPANY_ACTIVITY_NAME = "ts_b9_hiring_company_activity"
HIRING_COMPANY_ACTIVITY_KEY = [
    ("candidate_id", 1),
    ("hiring_company_id", 1),
    ("status", 1),
    ("activity_at", 1),
]
DEDUP_ACTIVITY_NAME = "ts_b9_dedup_activity"
DEDUP_ACTIVITY_KEY = [
    ("candidate_id", 1),
    ("dedup_key", 1),
    ("status", 1),
    ("activity_at", 1),
]
CONTACT_REQUEST_UNIQUE_NAME = "ts_b9_contact_request_unique"
CONTACT_REQUEST_UNIQUE_KEY = [("contact_request_id", 1)]
CONTACT_REQUEST_PARTIAL = {"contact_request_id": {"$type": "string"}}


class B9MigrationError(RuntimeError):
    pass


def _validate_collection(record, label):
    if record.get("type") != "collection":
        raise B9MigrationError(f"{label} must be an ordinary collection")
    options = record.get("options", {})
    if (
        type(options) is not dict
        or options.get("capped", False) is not False
        or "timeseries" in options
        or "viewOn" in options
    ):
        raise B9MigrationError(f"{label} must be an ordinary collection")
    if options.get("collation", {}).get("locale", "simple") != "simple":
        raise B9MigrationError(f"{label} must use simple collation")
    if "expireAfterSeconds" in options:
        raise B9MigrationError("TTL is forbidden on B9 collections")
    return options


def _validate_indexes(indexes, requirement, options, label):
    expected = {index.name: index for index in requirement.indexes}
    for name, metadata in indexes.items():
        if type(metadata) is not dict:
            raise B9MigrationError(f"invalid {label} index metadata")
        if "expireAfterSeconds" in metadata:
            raise B9MigrationError("TTL is forbidden on B9 indexes")
        if name == "_id_":
            if list(metadata.get("key", [])) != [("_id", 1)]:
                raise B9MigrationError(f"incompatible native identity index on {label}")
            continue
        requirement_index = expected.get(name)
        if requirement_index is None:
            raise B9MigrationError(f"unexpected index on {label}")
        if compare_index(requirement_index, metadata, options.get("collation")):
            raise B9MigrationError(f"incompatible index on {label}")


async def preflight(db):
    names = {RESERVATIONS_COLLECTION, GUARDS_COLLECTION}
    try:
        collections = {}
        cursor = await db.list_collections(filter={"name": {"$in": sorted(names)}})
        async for record in cursor:
            collections[record["name"]] = record
        indexes = {}
        for name in names:
            if collections.get(name, {}).get("type") == "collection":
                indexes[name] = await db[name].index_information()

        if RESERVATIONS_COLLECTION in collections:
            options = _validate_collection(
                collections[RESERVATIONS_COLLECTION], "B9 reservations"
            )
            _validate_indexes(
                indexes.get(RESERVATIONS_COLLECTION, {}),
                CONTACT_GOVERNOR_RESERVATIONS_REQUIREMENT,
                options,
                "B9 reservations",
            )
        if GUARDS_COLLECTION in collections:
            options = _validate_collection(collections[GUARDS_COLLECTION], "B9 guards")
            _validate_indexes(
                indexes.get(GUARDS_COLLECTION, {}),
                CONTACT_GOVERNOR_CANDIDATE_GUARDS_REQUIREMENT,
                options,
                "B9 guards",
            )

        reservation_count = 0
        contact_request_ids = set()
        if RESERVATIONS_COLLECTION in collections:
            async for document in db[RESERVATIONS_COLLECTION].find({}):
                try:
                    reservation = reservation_from_document(document)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise B9MigrationError(
                        "malformed B9 reservation document; no migration applied"
                    ) from exc
                if reservation.contact_request_id is not None:
                    if reservation.contact_request_id in contact_request_ids:
                        raise B9MigrationError(
                            "duplicate B9 contact request binding; no migration applied"
                        )
                    contact_request_ids.add(reservation.contact_request_id)
                reservation_count += 1

        guard_count = 0
        if GUARDS_COLLECTION in collections:
            async for document in db[GUARDS_COLLECTION].find({}):
                try:
                    guard_from_document(document)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise B9MigrationError(
                        "malformed B9 guard document; no migration applied"
                    ) from exc
                guard_count += 1
    except B9MigrationError:
        raise
    except Exception as exc:
        raise B9MigrationError("B9 migration preflight failed") from exc

    reservation_indexes = indexes.get(RESERVATIONS_COLLECTION, {})
    expected_names = {
        index.name for index in CONTACT_GOVERNOR_RESERVATIONS_REQUIREMENT.indexes
    }
    present_names = expected_names & set(reservation_indexes)
    ready = (
        RESERVATIONS_COLLECTION in collections
        and GUARDS_COLLECTION in collections
        and present_names == expected_names
    )
    return {
        "reservations_collection": RESERVATIONS_COLLECTION in collections,
        "candidate_guards_collection": GUARDS_COLLECTION in collections,
        "reservation_indexes_ready": sorted(present_names),
        "reservation_documents_checked": reservation_count,
        "candidate_guard_documents_checked": guard_count,
        "ready": ready,
    }


async def migrate(db, *, apply=False):
    if type(apply) is not bool:
        raise ValueError("explicit boolean apply required")
    result = await preflight(db)
    if not apply:
        return result
    try:
        if not result["reservations_collection"]:
            await db.create_collection(
                RESERVATIONS_COLLECTION,
                collation={"locale": "simple"},
            )
        if not result["candidate_guards_collection"]:
            await db.create_collection(
                GUARDS_COLLECTION,
                collation={"locale": "simple"},
            )
        result = await preflight(db)
        present = set(result["reservation_indexes_ready"])
        if CANDIDATE_ACTIVITY_NAME not in present:
            await db.contact_governor_reservations.create_index(
                CANDIDATE_ACTIVITY_KEY,
                name=CANDIDATE_ACTIVITY_NAME,
            )
        if REQUESTING_ORG_ACTIVITY_NAME not in present:
            await db.contact_governor_reservations.create_index(
                REQUESTING_ORG_ACTIVITY_KEY,
                name=REQUESTING_ORG_ACTIVITY_NAME,
            )
        if HIRING_COMPANY_ACTIVITY_NAME not in present:
            await db.contact_governor_reservations.create_index(
                HIRING_COMPANY_ACTIVITY_KEY,
                name=HIRING_COMPANY_ACTIVITY_NAME,
            )
        if DEDUP_ACTIVITY_NAME not in present:
            await db.contact_governor_reservations.create_index(
                DEDUP_ACTIVITY_KEY,
                name=DEDUP_ACTIVITY_NAME,
            )
        if CONTACT_REQUEST_UNIQUE_NAME not in present:
            await db.contact_governor_reservations.create_index(
                CONTACT_REQUEST_UNIQUE_KEY,
                name=CONTACT_REQUEST_UNIQUE_NAME,
                unique=True,
                partialFilterExpression=CONTACT_REQUEST_PARTIAL,
            )
        result = await preflight(db)
    except B9MigrationError:
        raise
    except Exception as exc:
        raise B9MigrationError("B9 migration failed") from exc
    if not result["ready"]:
        raise B9MigrationError("B9 storage is not ready")
    return result


async def main(*, apply=False):
    url = os.environ.get("MONGO_URL")
    name = os.environ.get("DB_NAME")
    if not url or not url.strip() or not name or not name.strip():
        print('{"error":"explicit_configuration_required"}')
        return 2
    client = None
    try:
        client = AsyncIOMotorClient(
            url,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000,
        )
        result = await migrate(client[name], apply=apply)
        print(json.dumps(result, separators=(",", ":")))
        return 0 if result["ready"] else 1
    except Exception:
        print('{"error":"b9_migration_failed"}')
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    raise SystemExit(asyncio.run(main(apply=parser.parse_args().apply)))
