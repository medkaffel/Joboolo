#!/usr/bin/env python3
"""Explicit TS-B1 collection migration; read-only preflight by default.

Writers must remain stopped while applying. This command never repairs,
rewrites, removes or backfills data and creates no secondary index.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.motor_asyncio import AsyncIOMotorClient

from domains.talent_stream.index_requirements import TALENT_STREAM_REQUIREMENT
from domains.talent_stream.stream_repository import stream_from_document
from mongo_index_safety import verify_metadata


class TalentStreamMigrationError(RuntimeError):
    pass


async def preflight(db):
    try:
        collections = {}
        cursor = await db.list_collections(filter={"name": TALENT_STREAM_REQUIREMENT.name})
        async for record in cursor:
            collections[record["name"]] = record
        if TALENT_STREAM_REQUIREMENT.name not in collections:
            return {"ready": False, "documents_checked": 0, "diagnostics": 1}
        collection = db[TALENT_STREAM_REQUIREMENT.name]
        metadata = {}
        if collections[TALENT_STREAM_REQUIREMENT.name].get("type") == "collection":
            metadata = await collection.index_information()
        report = verify_metadata(
            (TALENT_STREAM_REQUIREMENT,),
            collections,
            {TALENT_STREAM_REQUIREMENT.name: metadata},
        )
        if not report.ok:
            raise TalentStreamMigrationError("incompatible Talent Stream metadata")
        count = 0
        async for document in collection.find({}):
            stream_from_document(document)
            count += 1
        return {"ready": True, "documents_checked": count, "diagnostics": 0}
    except TalentStreamMigrationError:
        raise
    except Exception:
        raise TalentStreamMigrationError("Talent Stream preflight failed") from None


async def migrate(db, *, apply=False):
    if type(apply) is not bool:
        raise ValueError("explicit boolean apply required")
    result = await preflight(db)
    if not apply or result["ready"]:
        return result
    try:
        # An omitted default collation is MongoDB's effective simple collation.
        await db.create_collection(TALENT_STREAM_REQUIREMENT.name)
    except Exception:
        raise TalentStreamMigrationError("Talent Stream collection creation failed") from None
    result = await preflight(db)
    if not result["ready"]:
        raise TalentStreamMigrationError("Talent Stream storage is not ready")
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
        print('{"error":"talent_stream_migration_failed"}')
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create the missing approved collection after successful preflight",
    )
    raise SystemExit(asyncio.run(main(apply=parser.parse_args().apply)))

