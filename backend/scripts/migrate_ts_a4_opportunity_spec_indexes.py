#!/usr/bin/env python3
"""TS-A4 explicit unique index for immutable Opportunity Specification versions."""
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

INDEX = "ts_a4_opportunity_spec_version_unique"


async def main():
    url = os.environ.get("MONGO_URL")
    if not url:
        raise SystemExit("MONGO_URL is required")
    client = AsyncIOMotorClient(url)
    db = client[os.environ.get("DB_NAME", "indeed_clone")]
    try:
        malformed = await db.opportunity_specs.find_one({
            "$or": [
                {"opportunity_spec_id": {"$exists": False}},
                {"opportunity_spec_id": None},
                {"version": {"$exists": False}},
                {"version": None},
            ]
        })
        if malformed:
            raise SystemExit("malformed opportunity_specs detected; index not created")

        duplicates = await db.opportunity_specs.aggregate([
            {
                "$group": {
                    "_id": {
                        "opportunity_spec_id": "$opportunity_spec_id",
                        "version": "$version",
                    },
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
            {"$limit": 1},
        ]).to_list(length=1)
        if duplicates:
            raise SystemExit("duplicate Opportunity Specification versions detected; index not created")

        await db.opportunity_specs.create_index(
            [("opportunity_spec_id", 1), ("version", 1)],
            unique=True,
            name=INDEX,
        )
        print(f"TS-A4 index ready: {INDEX}; no automatic job backfill performed")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
