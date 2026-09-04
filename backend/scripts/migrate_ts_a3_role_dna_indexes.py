#!/usr/bin/env python3
"""TS-A3 explicit indexes for immutable Role DNA versions."""
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

INDEX = "ts_a3_role_dna_version_unique"


async def main():
    url = os.environ.get("MONGO_URL")
    if not url:
        raise SystemExit("MONGO_URL is required")
    db = AsyncIOMotorClient(url)[os.environ.get("DB_NAME", "indeed_clone")]
    duplicates = await db.role_dnas.aggregate([
        {"$group": {"_id": {"role_dna_id": "$role_dna_id", "version": "$version"}, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$limit": 1},
    ]).to_list(length=1)
    if duplicates:
        raise SystemExit("duplicate role_dna versions detected; index not created")
    await db.role_dnas.create_index([("role_dna_id", 1), ("version", 1)], unique=True, name=INDEX)
    print(f"TS-A3 index ready: {INDEX}; no automatic job backfill performed")


if __name__ == "__main__":
    asyncio.run(main())
