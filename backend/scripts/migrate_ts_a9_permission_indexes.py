#!/usr/bin/env python3
"""Explicit TS-A9 indexes for current scoped Talent Stream grant lookup."""
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

GRANT_ID_INDEX = "ts_a9_grant_id_unique"
GRANT_LOOKUP_INDEX = "ts_a9_grant_lookup"
GRANT_DOCUMENT_INDEX = "ts_a9_grant_document_lookup"
GRANT_EXPIRY_INDEX = "ts_a9_grant_expiry"


async def _duplicate_exists(collection, group_id):
    rows = await collection.aggregate([
        {"$group": {"_id": group_id, "count": {"$sum": 1}}},
        {"$match": {"count": {"$gt": 1}}},
        {"$limit": 1},
    ]).to_list(length=1)
    return bool(rows)


async def main():
    url = os.environ.get("MONGO_URL")
    if not url:
        raise SystemExit("MONGO_URL is required")
    client = AsyncIOMotorClient(url)
    db = client[os.environ.get("DB_NAME", "indeed_clone")]
    grants = db.talent_stream_grants
    try:
        malformed = await grants.find_one({
            "$or": [
                {"grant_id": {"$exists": False}},
                {"candidate_id": {"$exists": False}},
                {"grantee_organization_id": {"$exists": False}},
                {"stream_id": {"$exists": False}},
                {"scopes": {"$exists": False}},
                {"issued_at": {"$exists": False}},
                {"consent_policy_version": {"$exists": False}},
                {"grant_id": {"$not": {"$type": "string"}}},
                {"candidate_id": {"$not": {"$type": "string"}}},
                {"grantee_organization_id": {"$not": {"$type": "string"}}},
                {"stream_id": {"$not": {"$type": "string"}}},
                {"scopes": {"$not": {"$type": "array"}}},
                {"issued_at": {"$not": {"$type": "date"}}},
                {"consent_policy_version": {"$not": {"$type": "string"}}},
                {"grant_id": ""},
                {"candidate_id": ""},
                {"grantee_organization_id": ""},
                {"stream_id": ""},
                {"consent_policy_version": ""},
                {"scopes": {"$size": 0}},
                {"scopes": {"$elemMatch": {"$nin": ["profile_preview", "identity", "contact", "cv", "messaging"]}}},
                {"expires_at": {"$exists": True, "$ne": None, "$not": {"$type": "date"}}},
                {"revoked_at": {"$exists": True, "$ne": None, "$not": {"$type": "date"}}},
                {"document_id": {"$exists": True, "$ne": None, "$not": {"$type": "string"}}},
                {"document_id": ""},
            ]
        })
        if malformed:
            raise SystemExit("malformed TS-A9 grants detected; indexes not created")

        identity_mismatch = await grants.find_one({"$expr": {"$ne": ["$_id", "$grant_id"]}})
        if identity_mismatch:
            raise SystemExit("grant _id/grant_id mismatch detected; indexes not created")

        invalid_cv = await grants.find_one({
            "$or": [
                {"$and": [{"scopes": "cv"}, {"document_id": {"$exists": False}}]},
                {"$and": [{"scopes": "cv"}, {"document_id": None}]},
                {"$and": [{"document_id": {"$type": "string"}}, {"scopes": {"$ne": "cv"}}]},
            ]
        })
        if invalid_cv:
            raise SystemExit("invalid CV-scoped grants detected; indexes not created")

        duplicate_scope = await grants.find_one({
            "$expr": {
                "$ne": [
                    {"$size": "$scopes"},
                    {"$size": {"$setUnion": ["$scopes", []]}},
                ]
            }
        })
        if duplicate_scope:
            raise SystemExit("duplicate grant scopes detected; indexes not created")

        invalid_expiry = await grants.find_one({
            "expires_at": {"$type": "date"},
            "$expr": {"$lte": ["$expires_at", "$issued_at"]},
        })
        if invalid_expiry:
            raise SystemExit("invalid grant expiry detected; indexes not created")

        invalid_revocation = await grants.find_one({
            "revoked_at": {"$type": "date"},
            "$expr": {"$lt": ["$revoked_at", "$issued_at"]},
        })
        if invalid_revocation:
            raise SystemExit("invalid grant revocation detected; indexes not created")

        if await _duplicate_exists(grants, "$grant_id"):
            raise SystemExit("duplicate grant_id values detected; indexes not created")

        await grants.create_index("grant_id", unique=True, name=GRANT_ID_INDEX)
        await grants.create_index(
            [
                ("candidate_id", 1),
                ("grantee_organization_id", 1),
                ("stream_id", 1),
                ("scopes", 1),
            ],
            name=GRANT_LOOKUP_INDEX,
        )
        await grants.create_index(
            [
                ("candidate_id", 1),
                ("grantee_organization_id", 1),
                ("stream_id", 1),
                ("document_id", 1),
            ],
            name=GRANT_DOCUMENT_INDEX,
            partialFilterExpression={"document_id": {"$type": "string"}},
        )
        # Operational lookup only. Expiry is enforced by domain evaluation; this is NOT a TTL index.
        await grants.create_index("expires_at", name=GRANT_EXPIRY_INDEX)
        print("TS-A9 permission indexes ready; no grant backfill or TTL authorization performed")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
