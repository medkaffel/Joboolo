#!/usr/bin/env python3
"""TS-A8 explicit indexes for recruiter membership, verification, mandate and audit."""
import asyncio, os
from motor.motor_asyncio import AsyncIOMotorClient

INDEXES = {
    "membership_id": "ts_a8_membership_id_unique",
    "membership_pair": "ts_a8_membership_pair_unique",
    "membership_state": "ts_a8_membership_state",
    "membership_org": "ts_a8_membership_org",
    "membership_recruiter": "ts_a8_membership_recruiter",
    "recruiter_id": "ts_a8_recruiter_verification_unique",
    "recruiter_state": "ts_a8_recruiter_verification_state",
    "mandate_id": "ts_a8_mandate_id_unique",
    "mandate_pair": "ts_a8_mandate_pair",
    "mandate_state": "ts_a8_mandate_state",
    "mandate_valid_until": "ts_a8_mandate_valid_until",
    "event_version": "ts_a8_trust_event_version_unique",
    "event_timeline": "ts_a8_trust_event_timeline",
}

async def _malformed(db):
    checks = (
        (db.organization_memberships, {"$or": [{"membership_id":{"$exists":False}}, {"recruiter_user_id":{"$exists":False}}, {"organization_id":{"$exists":False}}, {"version":{"$exists":False}}]}),
        (db.recruiter_verifications, {"$or": [{"recruiter_user_id":{"$exists":False}}, {"version":{"$exists":False}}]}),
        (db.recruiting_mandates, {"$or": [{"mandate_id":{"$exists":False}}, {"requesting_organization_id":{"$exists":False}}, {"hiring_company_id":{"$exists":False}}, {"version":{"$exists":False}}, {"valid_from":{"$exists":False}}, {"valid_until":{"$exists":False}}]}),
        (db.recruiting_trust_events, {"$or": [{"subject_type":{"$exists":False}}, {"subject_id":{"$exists":False}}, {"subject_version":{"$exists":False}}, {"occurred_at":{"$exists":False}}]}),
    )
    for collection, query in checks:
        if await collection.find_one(query): return True
    if await db.recruiting_mandates.find_one({"$expr":{"$eq":["$requesting_organization_id","$hiring_company_id"]}}): return True
    return False

async def _duplicate(db, collection_name, group_id):
    rows = await db[collection_name].aggregate([
        {"$group":{"_id":group_id,"count":{"$sum":1}}}, {"$match":{"count":{"$gt":1}}}, {"$limit":1}
    ]).to_list(length=1)
    return bool(rows)

async def main():
    url = os.environ.get("MONGO_URL")
    if not url: raise SystemExit("MONGO_URL is required")
    client = AsyncIOMotorClient(url); db = client[os.environ.get("DB_NAME","indeed_clone")]
    try:
        if await _malformed(db): raise SystemExit("malformed TS-A8 trust documents detected; indexes not created")
        duplicate_specs = (
            ("organization_memberships", "$membership_id"),
            ("organization_memberships", {"recruiter_user_id":"$recruiter_user_id","organization_id":"$organization_id"}),
            ("recruiter_verifications", "$recruiter_user_id"),
            ("recruiting_mandates", "$mandate_id"),
            ("recruiting_trust_events", {"subject_type":"$subject_type","subject_id":"$subject_id","subject_version":"$subject_version"}),
        )
        for collection, group_id in duplicate_specs:
            if await _duplicate(db, collection, group_id): raise SystemExit(f"duplicate {collection} identity detected; indexes not created")
        await db.organization_memberships.create_index("membership_id", unique=True, name=INDEXES["membership_id"])
        await db.organization_memberships.create_index([("recruiter_user_id",1),("organization_id",1)], unique=True, name=INDEXES["membership_pair"])
        await db.organization_memberships.create_index("state", name=INDEXES["membership_state"])
        await db.organization_memberships.create_index("organization_id", name=INDEXES["membership_org"])
        await db.organization_memberships.create_index("recruiter_user_id", name=INDEXES["membership_recruiter"])
        await db.recruiter_verifications.create_index("recruiter_user_id", unique=True, name=INDEXES["recruiter_id"])
        await db.recruiter_verifications.create_index("state", name=INDEXES["recruiter_state"])
        await db.recruiting_mandates.create_index("mandate_id", unique=True, name=INDEXES["mandate_id"])
        await db.recruiting_mandates.create_index([("requesting_organization_id",1),("hiring_company_id",1)], name=INDEXES["mandate_pair"])
        await db.recruiting_mandates.create_index("state", name=INDEXES["mandate_state"])
        await db.recruiting_mandates.create_index("valid_until", name=INDEXES["mandate_valid_until"])
        await db.recruiting_trust_events.create_index([("subject_type",1),("subject_id",1),("subject_version",1)], unique=True, name=INDEXES["event_version"])
        await db.recruiting_trust_events.create_index([("subject_type",1),("subject_id",1),("occurred_at",1)], name=INDEXES["event_timeline"])
        print("TS-A8 trust indexes ready; no owner/company/partner backfill performed")
    finally: client.close()

if __name__ == "__main__": asyncio.run(main())
