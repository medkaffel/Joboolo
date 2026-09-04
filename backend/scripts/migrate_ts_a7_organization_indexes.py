#!/usr/bin/env python3
"""TS-A7 explicit indexes for canonical organizations and verification audit events."""
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

ORG_ID_INDEX = "ts_a7_organization_id_unique"
LEGACY_COMPANY_INDEX = "ts_a7_legacy_company_unique"
LEGAL_IDENTITY_INDEX = "ts_a7_legal_identity_unique"
VERIFICATION_STATE_INDEX = "ts_a7_verification_state"
EVENT_TIMELINE_INDEX = "ts_a7_verification_event_timeline"
EVENT_VERSION_INDEX = "ts_a7_verification_event_version_unique"


async def _duplicate_exists(collection, group_id, match=None):
    pipeline = []
    if match:
        pipeline.append({"$match": match})
    pipeline.extend([
        {"$group": {"_id": group_id, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$limit": 1},
    ])
    return bool(await collection.aggregate(pipeline).to_list(length=1))


async def main():
    url = os.environ.get("MONGO_URL")
    if not url:
        raise SystemExit("MONGO_URL is required")
    client = AsyncIOMotorClient(url)
    db = client[os.environ.get("DB_NAME", "indeed_clone")]
    try:
        malformed_org = await db.organizations.find_one({
            "$or": [
                {"organization_id": {"$exists": False}},
                {"organization_id": None},
                {"version": {"$exists": False}},
                {"version": None},
                {"legal_name": {"$exists": False}},
                {"legal_name": None},
                {"verification_state": {"$exists": False}},
                {"verification_state": None},
            ]
        })
        if malformed_org:
            raise SystemExit("malformed organizations detected; indexes not created")

        if await _duplicate_exists(db.organizations, "$organization_id"):
            raise SystemExit("duplicate organization_id values detected; indexes not created")
        if await _duplicate_exists(
            db.organizations,
            "$legacy_company_id",
            {"legacy_company_id": {"$type": "string"}},
        ):
            raise SystemExit("duplicate legacy_company_id mappings detected; indexes not created")
        if await _duplicate_exists(
            db.organizations,
            {"registration_country": "$registration_country", "registration_id": "$registration_id"},
            {
                "registration_country": {"$type": "string"},
                "registration_id": {"$type": "string"},
            },
        ):
            raise SystemExit("duplicate legal organization identities detected; indexes not created")

        malformed_event = await db.organization_verification_events.find_one({
            "$or": [
                {"organization_id": {"$exists": False}},
                {"organization_id": None},
                {"organization_version": {"$exists": False}},
                {"organization_version": None},
                {"occurred_at": {"$exists": False}},
                {"occurred_at": None},
            ]
        })
        if malformed_event:
            raise SystemExit("malformed organization verification events detected; indexes not created")
        if await _duplicate_exists(
            db.organization_verification_events,
            {"organization_id": "$organization_id", "organization_version": "$organization_version"},
        ):
            raise SystemExit("duplicate organization verification events per version detected; indexes not created")

        await db.organizations.create_index(
            [("organization_id", 1)], unique=True, name=ORG_ID_INDEX
        )
        await db.organizations.create_index(
            [("verification_state", 1)], name=VERIFICATION_STATE_INDEX
        )
        await db.organizations.create_index(
            [("legacy_company_id", 1)],
            unique=True,
            name=LEGACY_COMPANY_INDEX,
            partialFilterExpression={"legacy_company_id": {"$type": "string"}},
        )
        await db.organizations.create_index(
            [("registration_country", 1), ("registration_id", 1)],
            unique=True,
            name=LEGAL_IDENTITY_INDEX,
            partialFilterExpression={
                "registration_country": {"$type": "string"},
                "registration_id": {"$type": "string"},
            },
        )
        await db.organization_verification_events.create_index(
            [("organization_id", 1), ("occurred_at", 1)],
            name=EVENT_TIMELINE_INDEX,
        )
        await db.organization_verification_events.create_index(
            [("organization_id", 1), ("organization_version", 1)],
            unique=True,
            name=EVENT_VERSION_INDEX,
        )
        print(
            "TS-A7 organization indexes ready; no automatic companies/partner_profiles backfill performed"
        )
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
