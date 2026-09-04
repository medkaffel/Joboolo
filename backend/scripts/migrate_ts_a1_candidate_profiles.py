#!/usr/bin/env python3
"""TS-A1 explicit, idempotent backfill + unique-index migration.

No destructive startup migration. Existing `users` fields are copied conservatively
into authoritative `candidate_profiles`; they are not deleted here.
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from domains.profiles.legacy import profile_from_legacy_user
from domains.profiles.repository import profile_to_document

MARKER = "ts_a1_candidate_profiles_v1"
INDEX = "ts_a1_candidate_id_unique"


async def main() -> None:
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "indeed_clone")
    if not mongo_url:
        raise SystemExit("MONGO_URL is required")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    inserted = 0
    scanned = 0
    try:
        cursor = db.users.find({"user_type": "candidate"})
        async for user_doc in cursor:
            scanned += 1
            profile = profile_from_legacy_user(user_doc, now=datetime.now(timezone.utc))
            result = await db.candidate_profiles.update_one(
                {"_id": str(profile.profile_id)},
                {"$setOnInsert": profile_to_document(profile)},
                upsert=True,
            )
            inserted += int(result.upserted_id is not None)

        duplicates = await db.candidate_profiles.aggregate([
            {"$group": {"_id": "$candidate_id", "count": {"$sum": 1}}},
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 1},
        ]).to_list(length=1)
        if duplicates:
            raise SystemExit("duplicate candidate_profiles detected; unique index not created")

        await db.candidate_profiles.create_index(
            [("candidate_id", 1)], name=INDEX, unique=True
        )
        await db.migration_flags.update_one(
            {"_id": MARKER},
            {"$set": {
                "completed_at": datetime.now(timezone.utc),
                "index": INDEX,
                "scanned_candidates": scanned,
                "inserted_profiles": inserted,
            }},
            upsert=True,
        )
        print(f"TS-A1 complete: scanned={scanned} inserted={inserted} index={INDEX}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
