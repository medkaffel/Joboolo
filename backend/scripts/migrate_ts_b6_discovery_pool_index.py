#!/usr/bin/env python3
"""Explicit TS-B6 Discovery Pool index migration; preflight is read-only."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.motor_asyncio import AsyncIOMotorClient

from domains.talent_stream.index_requirements import CANDIDATE_PREFERENCES_REQUIREMENT
from mongo_index_safety import verify_metadata


INDEX_KEYS = [
    ("discovery.enabled", 1),
    ("discovery.allow_compatible_opportunities", 1),
    ("candidate_id", 1),
]
INDEX_NAME = "ts_b6_discovery_pool_scan"
PARTIAL_FILTER = {
    "discovery.enabled": True,
    "discovery.allow_compatible_opportunities": True,
}


class DiscoveryPoolMigrationError(RuntimeError):
    pass


async def preflight(db):
    name = CANDIDATE_PREFERENCES_REQUIREMENT.name
    try:
        collections = {}
        cursor = await db.list_collections(filter={"name": name})
        async for record in cursor:
            collections[record["name"]] = record
        indexes = {}
        if collections.get(name, {}).get("type") == "collection":
            indexes[name] = await db[name].index_information()
        report = verify_metadata((CANDIDATE_PREFERENCES_REQUIREMENT,), collections, indexes)
    except Exception:
        raise DiscoveryPoolMigrationError("Discovery Pool preflight failed") from None
    if not report.ok:
        raise DiscoveryPoolMigrationError("incompatible Candidate Preferences metadata")
    b6_diagnostics = tuple(
        diagnostic for diagnostic in report.diagnostics
        if diagnostic.index_position == 2
    )
    b6_missing = (
        len(b6_diagnostics) == 1 and b6_diagnostics[0].code == "missing_index"
    )
    if b6_diagnostics and not b6_missing:
        raise DiscoveryPoolMigrationError("incompatible Discovery Pool metadata")
    return {"ready": not b6_missing, "diagnostics": 1 if b6_missing else 0}


async def migrate(db, *, apply=False):
    if type(apply) is not bool:
        raise ValueError("explicit boolean apply required")
    result = await preflight(db)
    if not apply or result["ready"]:
        return result
    try:
        await db.candidate_preferences.create_index(
            INDEX_KEYS,
            name=INDEX_NAME,
            partialFilterExpression=PARTIAL_FILTER,
        )
    except Exception:
        raise DiscoveryPoolMigrationError("Discovery Pool index creation failed") from None
    result = await preflight(db)
    if not result["ready"]:
        raise DiscoveryPoolMigrationError("Discovery Pool storage is not ready")
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
        return 0 if result["ready"] else 1
    except Exception:
        print('{"error":"discovery_pool_migration_failed"}')
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    raise SystemExit(asyncio.run(main(apply=parser.parse_args().apply)))
