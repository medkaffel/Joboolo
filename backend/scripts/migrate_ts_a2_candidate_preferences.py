#!/usr/bin/env python3
"""TS-A2 index-only migration. Never infers preferences or Discovery opt-in."""
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

INDEX = "ts_a2_candidate_preferences_candidate_unique"


async def main():
    url = os.environ.get("MONGO_URL")
    if not url:
        raise SystemExit("MONGO_URL is required")
    db_name = os.environ.get("DB_NAME", "indeed_clone")
    client = AsyncIOMotorClient(url)
    db = client[db_name]
    try:
        duplicates = await db.candidate_preferences.aggregate([
            {"$group": {"_id": "$candidate_id", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 1},
        ]).to_list(length=1)
        if duplicates:
            raise SystemExit("duplicate candidate_preferences detected; index not created")
        await db.candidate_preferences.create_index([("candidate_id", 1)], unique=True, name=INDEX)
        print(f"TS-A2 index ready: {INDEX}; no preference/discovery backfill performed")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
