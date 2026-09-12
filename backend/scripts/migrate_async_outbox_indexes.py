"""Explicit A14 index provisioning; read-only by default.

Stop writers during preflight/apply. Metadata and document reads are not a
transactional schema lock. Never repairs data or replaces incompatible indexes.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.motor_asyncio import AsyncIOMotorClient
from async_outbox.index_requirements import OUTBOX_REQUIREMENT
from async_outbox.serialization import record_from_document
from mongo_index_safety import verify_metadata


class OutboxMigrationError(RuntimeError):
    pass


async def preflight(db):
    """Full strict document validation, with metadata-only A13 comparison."""
    try:
        collections = {}
        cursor = await db.list_collections(filter={"name": OUTBOX_REQUIREMENT.name})
        async for record in cursor:
            collections[record["name"]] = record
        if OUTBOX_REQUIREMENT.name not in collections:
            return {"ready": False, "documents_checked": 0, "missing_indexes": 3}
        collection = db[OUTBOX_REQUIREMENT.name]
        metadata = (await collection.index_information()
                    if collections[OUTBOX_REQUIREMENT.name].get("type") == "collection" else {})
        report = verify_metadata((OUTBOX_REQUIREMENT,), collections,
                                 {OUTBOX_REQUIREMENT.name: metadata})
        # A missing secondary index can be provisioned after data validation.
        # Missing native identity and any incompatible existing definition cannot.
        if any(d.code != "missing_index" or d.index_position == 0 for d in report.diagnostics):
            raise OutboxMigrationError("incompatible outbox metadata")
        identities, deduplication = set(), set()
        count = 0
        async for document in collection.find({}):
            try:
                record = record_from_document(document)
            except (ValueError, TypeError, KeyError, OverflowError):
                raise OutboxMigrationError("invalid outbox document") from None
            envelope = record.envelope
            pair = (envelope.job_type, envelope.idempotency_key)
            if envelope.job_id in identities or pair in deduplication:
                raise OutboxMigrationError("duplicate outbox identity")
            identities.add(envelope.job_id)
            deduplication.add(pair)
            count += 1
        missing = sum(index.name not in metadata for index in OUTBOX_REQUIREMENT.indexes)
        return {"ready": report.ok, "documents_checked": count, "missing_indexes": missing}
    except OutboxMigrationError:
        raise
    except Exception:
        raise OutboxMigrationError("outbox preflight unavailable") from None


async def migrate(db, *, apply=False):
    if type(apply) is not bool:
        raise ValueError("explicit boolean apply required")
    result = await preflight(db)
    if not apply:
        return result
    try:
        collection = db[OUTBOX_REQUIREMENT.name]
        existing = await collection.index_information()
        for index in OUTBOX_REQUIREMENT.indexes:
            if index.name not in existing:
                await collection.create_index(list(index.keys), name=index.name,
                                              unique=index.unique, collation=dict(index.collation))
        return await preflight(db)
    except OutboxMigrationError:
        raise
    except Exception:
        raise OutboxMigrationError("outbox index provisioning failed") from None


async def main(*, apply=False):
    url, name = os.environ.get("MONGO_URL"), os.environ.get("DB_NAME")
    if not url or not name or not url.strip() or not name.strip():
        print('{"error":"explicit_configuration_required"}')
        return 2
    client = None
    try:
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000,
                                    connectTimeoutMS=5000, socketTimeoutMS=5000)
        result = await migrate(client[name], apply=apply)
        print(json.dumps(result, separators=(",", ":")))
        return 0 if result["ready"] else 1
    except Exception:
        print('{"error":"outbox_migration_failed"}')
        return 2
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read-only A14 preflight; stop writers before apply")
    parser.add_argument("--apply", action="store_true", help="Provision missing approved indexes")
    raise SystemExit(asyncio.run(main(apply=parser.parse_args().apply)))
