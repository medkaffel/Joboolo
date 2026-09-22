#!/usr/bin/env python3
"""Explicit B10 Contact Request migration; read-only without --apply.

Writers must remain stopped while applying.  This migration creates only the
approved ordinary simple-collation collection and its one unique reservation
index.  It never drops, renames, repairs, rewrites or backfills data.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from motor.motor_asyncio import AsyncIOMotorClient

from domains.talent_stream.contact_request_persistence import (
    contact_request_from_document,
)
from domains.talent_stream.index_requirements import (
    TALENT_STREAM_CONTACT_REQUESTS_REQUIREMENT,
)
from mongo_index_safety import compare_index


COLLECTION = "talent_stream_contact_requests"
RESERVATION_UNIQUE_NAME = "ts_b10_contact_request_reservation_unique"
RESERVATION_UNIQUE_KEY = [("reservation_id", 1)]


class B10MigrationError(RuntimeError):
    pass


def _validate_collection(record):
    if record.get("type") != "collection":
        raise B10MigrationError("B10 storage must be an ordinary collection")
    options = record.get("options", {})
    if (
        type(options) is not dict
        or options.get("capped", False) is not False
        or "timeseries" in options
        or "viewOn" in options
    ):
        raise B10MigrationError("B10 storage must be an ordinary collection")
    if options.get("collation", {}).get("locale", "simple") != "simple":
        raise B10MigrationError("B10 storage must use simple collation")
    if "expireAfterSeconds" in options:
        raise B10MigrationError("TTL is forbidden on B10 storage")
    return options


def _validate_indexes(indexes, options):
    expected = {
        index.name: index
        for index in TALENT_STREAM_CONTACT_REQUESTS_REQUIREMENT.indexes
    }
    for name, metadata in indexes.items():
        if type(metadata) is not dict:
            raise B10MigrationError("invalid B10 index metadata")
        if "expireAfterSeconds" in metadata:
            raise B10MigrationError("TTL is forbidden on B10 indexes")
        if name == "_id_":
            if list(metadata.get("key", [])) != [("_id", 1)]:
                raise B10MigrationError("incompatible B10 native identity index")
            continue
        requirement = expected.get(name)
        if requirement is None:
            raise B10MigrationError("unexpected B10 index")
        if compare_index(requirement, metadata, options.get("collation")):
            raise B10MigrationError("incompatible B10 index")


async def preflight(db):
    try:
        collections = {}
        cursor = await db.list_collections(filter={"name": COLLECTION})
        async for record in cursor:
            collections[record["name"]] = record

        indexes = {}
        if COLLECTION in collections:
            options = _validate_collection(collections[COLLECTION])
            indexes = await db[COLLECTION].index_information()
            _validate_indexes(indexes, options)

        documents_checked = 0
        reservation_ids = set()
        if COLLECTION in collections:
            async for document in db[COLLECTION].find({}):
                raw_reservation_id = (
                    document.get("reservation_id")
                    if type(document) is dict
                    else None
                )
                if (
                    type(raw_reservation_id) is str
                    and raw_reservation_id in reservation_ids
                ):
                    raise B10MigrationError(
                        "duplicate B10 reservation binding; no migration applied"
                    )
                try:
                    request = contact_request_from_document(document)
                except (ValueError, TypeError, KeyError, OverflowError) as exc:
                    raise B10MigrationError(
                        "malformed B10 contact request; no migration applied"
                    ) from exc
                reservation_ids.add(request.reservation_id)
                documents_checked += 1
    except B10MigrationError:
        raise
    except Exception as exc:
        raise B10MigrationError("B10 migration preflight failed") from exc

    expected_names = {
        index.name for index in TALENT_STREAM_CONTACT_REQUESTS_REQUIREMENT.indexes
    }
    present_names = expected_names & set(indexes)
    collection_ready = COLLECTION in collections
    return {
        "collection": collection_ready,
        "indexes_ready": sorted(present_names),
        "documents_checked": documents_checked,
        "ready": collection_ready and present_names == expected_names,
    }


async def migrate(db, *, apply=False):
    if type(apply) is not bool:
        raise ValueError("explicit boolean apply required")
    result = await preflight(db)
    if not apply:
        return result
    try:
        if not result["collection"]:
            await db.create_collection(COLLECTION, collation={"locale": "simple"})
        result = await preflight(db)
        if RESERVATION_UNIQUE_NAME not in set(result["indexes_ready"]):
            await db.talent_stream_contact_requests.create_index(
                RESERVATION_UNIQUE_KEY,
                name=RESERVATION_UNIQUE_NAME,
                unique=True,
            )
        result = await preflight(db)
    except B10MigrationError:
        raise
    except Exception as exc:
        raise B10MigrationError("B10 migration failed") from exc
    if not result["ready"]:
        raise B10MigrationError("B10 storage is not ready")
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
        print('{"error":"b10_migration_failed"}')
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    raise SystemExit(asyncio.run(main(apply=parser.parse_args().apply)))
