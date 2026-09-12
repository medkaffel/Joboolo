"""Read-only A13 deployment check: explicit MONGO_URL and DB_NAME required.

Reads metadata only. Does not initialize the application or validate business
documents. Run against a stable schema; this is not a transactional snapshot.
Exit codes: 0 conforming, 1 invariant failure, 2 configuration/read failure.
"""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.motor_asyncio import AsyncIOMotorClient
from domains.talent_stream.index_requirements import TS_INDEX_REQUIREMENTS
from mongo_index_safety import verify_metadata


async def check_database(db):
    """Collect only declared namespaces; an absent namespace stays absent."""
    collections, indexes = {}, {}
    cursor = await db.list_collections(filter={
        "name": {"$in": [item.name for item in TS_INDEX_REQUIREMENTS]},
    })
    async for record in cursor:
        collections[record["name"]] = record
    for requirement in TS_INDEX_REQUIREMENTS:
        record = collections.get(requirement.name)
        if record is None:
            continue
        # Views have no indexes. Let the verifier report the shape violation.
        indexes[requirement.name] = (
            await db[requirement.name].index_information()
            if record.get("type") == "collection" else {}
        )
    return verify_metadata(TS_INDEX_REQUIREMENTS, collections, indexes)


async def main():
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not name or not url.strip() or not name.strip():
        print('{"error":"explicit_configuration_required"}')
        return 2
    client = None
    try:
        client = AsyncIOMotorClient(
            url, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000,
            socketTimeoutMS=5000,
        )
        report = await asyncio.wait_for(check_database(client[name]), timeout=30)
        print(json.dumps({"ok": report.ok, **asdict(report)}, separators=(",", ":")))
        return 0 if report.ok else 1
    except Exception:
        # Never render driver exceptions, URIs, namespace names or metadata.
        print('{"error":"metadata_check_failed"}')
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
