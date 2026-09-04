#!/usr/bin/env python3
"""Explicit TS-A10 non-TTL indexes for privacy lifecycle audit and revocation lookup."""
import asyncio
import os

from motor.motor_asyncio import AsyncIOMotorClient

EVENT_COMMAND_INDEX = "ts_a10_privacy_command_unique"
EVENT_GRANT_TIMELINE_INDEX = "ts_a10_privacy_grant_timeline"
EVENT_CANDIDATE_TIMELINE_INDEX = "ts_a10_privacy_candidate_timeline"
GRANT_REVOCATION_INDEX = "ts_a10_grant_revocation"


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
    events = db.talent_stream_privacy_events
    grants = db.talent_stream_grants
    try:
        malformed_event = await events.find_one({
            "$or": [
                {"command_id": {"$exists": False}}, {"grant_id": {"$exists": False}},
                {"candidate_id": {"$exists": False}}, {"authority": {"$exists": False}},
                {"reason_code": {"$exists": False}}, {"policy_version": {"$exists": False}},
                {"actor_id": {"$exists": False}}, {"occurred_at": {"$exists": False}},
                {"command_id": {"$not": {"$type": "string"}}},
                {"grant_id": {"$not": {"$type": "string"}}},
                {"candidate_id": {"$not": {"$type": "string"}}},
                {"authority": {"$not": {"$type": "string"}}},
                {"reason_code": {"$not": {"$type": "string"}}},
                {"policy_version": {"$not": {"$type": "string"}}},
                {"actor_id": {"$not": {"$type": "string"}}},
                {"occurred_at": {"$not": {"$type": "date"}}},
                {"command_id": ""}, {"grant_id": ""}, {"candidate_id": ""},
                {"policy_version": ""}, {"actor_id": ""},
                {"authority": {"$nin": ["candidate", "privacy_admin", "system_policy"]}},
                {"reason_code": {"$nin": ["consent_withdrawn", "privacy_request", "policy_invalidated", "security_response", "admin_correction"]}},
            ]
        })
        if malformed_event:
            raise SystemExit("malformed TS-A10 privacy events detected; indexes not created")

        identity_mismatch = await events.find_one({
            "$expr": {"$ne": ["$_id", {"$concat": ["privacy_event:", "$command_id"]}]}
        })
        if identity_mismatch:
            raise SystemExit("privacy event identity mismatch detected; indexes not created")

        candidate_authority_mismatch = await events.find_one({
            "authority": "candidate",
            "$expr": {"$ne": ["$actor_id", "$candidate_id"]},
        })
        if candidate_authority_mismatch:
            raise SystemExit("candidate privacy event authority mismatch detected; indexes not created")

        invalid_authority_reason = await events.find_one({
            "$or": [
                {"authority": "candidate", "reason_code": {"$ne": "consent_withdrawn"}},
                {"authority": "system_policy", "reason_code": {"$ne": "policy_invalidated"}},
                {"authority": "privacy_admin", "reason_code": {"$nin": ["privacy_request", "security_response", "admin_correction"]}},
            ]
        })
        if invalid_authority_reason:
            raise SystemExit("privacy event authority/reason mismatch detected; indexes not created")

        malformed_revocation = await grants.find_one({
            "$or": [
                {"revoked_at": {"$exists": True, "$ne": None, "$not": {"$type": "date"}}},
                {"revocation_command_id": {"$exists": True, "$not": {"$type": "string"}}},
                {"revocation_policy_version": {"$exists": True, "$not": {"$type": "string"}}},
                {"revocation_reason_code": {"$exists": True, "$not": {"$type": "string"}}},
                {"revocation_authority": {"$exists": True, "$not": {"$type": "string"}}},
                {"revocation_actor_id": {"$exists": True, "$not": {"$type": "string"}}},
                {"privacy_updated_at": {"$exists": True, "$not": {"$type": "date"}}},
                {"revocation_command_id": ""}, {"revocation_policy_version": ""},
                {"revocation_reason_code": ""}, {"revocation_authority": ""},
                {"revocation_actor_id": ""},
                {"revocation_authority": {"$exists": True, "$nin": ["candidate", "privacy_admin", "system_policy"]}},
                {"revocation_reason_code": {"$exists": True, "$nin": ["consent_withdrawn", "privacy_request", "policy_invalidated", "security_response", "admin_correction"]}},
            ]
        })
        if malformed_revocation:
            raise SystemExit("malformed TS-A10 grant revocation metadata detected; indexes not created")

        # Legacy/pre-A10 grants may legitimately have only revoked_at. Once any
        # A10-specific metadata is present, however, the complete A10 audit bundle
        # is mandatory so partial/tampered idempotency metadata cannot be indexed.
        partial_a10_revocation = await grants.find_one({
            "$and": [
                {"$or": [
                    {"revocation_command_id": {"$exists": True}},
                    {"revocation_policy_version": {"$exists": True}},
                    {"revocation_reason_code": {"$exists": True}},
                    {"revocation_authority": {"$exists": True}},
                    {"revocation_actor_id": {"$exists": True}},
                    {"privacy_updated_at": {"$exists": True}},
                ]},
                {"$or": [
                    {"revocation_command_id": {"$exists": False}},
                    {"revocation_policy_version": {"$exists": False}},
                    {"revocation_reason_code": {"$exists": False}},
                    {"revocation_authority": {"$exists": False}},
                    {"revocation_actor_id": {"$exists": False}},
                    {"privacy_updated_at": {"$exists": False}},
                    {"revoked_at": None},
                ]},
            ]
        })
        if partial_a10_revocation:
            raise SystemExit("incomplete TS-A10 grant revocation metadata detected; indexes not created")

        invalid_revocation_authority = await grants.find_one({
            "revocation_command_id": {"$exists": True},
            "$or": [
                {"revocation_authority": "candidate", "$expr": {"$ne": ["$revocation_actor_id", "$candidate_id"]}},
                {"revocation_authority": "candidate", "revocation_reason_code": {"$ne": "consent_withdrawn"}},
                {"revocation_authority": "system_policy", "revocation_reason_code": {"$ne": "policy_invalidated"}},
                {"revocation_authority": "privacy_admin", "revocation_reason_code": {"$nin": ["privacy_request", "security_response", "admin_correction"]}},
            ],
        })
        if invalid_revocation_authority:
            raise SystemExit("TS-A10 grant revocation authority/reason mismatch detected; indexes not created")

        invalid_revocation_time = await grants.find_one({
            "revocation_command_id": {"$exists": True},
            "$expr": {"$lt": ["$privacy_updated_at", "$revoked_at"]},
        })
        if invalid_revocation_time:
            raise SystemExit("TS-A10 privacy_updated_at predates revoked_at; indexes not created")

        if await _duplicate_exists(events, "$command_id"):
            raise SystemExit("duplicate privacy command_id values detected; indexes not created")

        await events.create_index("command_id", unique=True, name=EVENT_COMMAND_INDEX)
        await events.create_index([("grant_id", 1), ("occurred_at", 1)], name=EVENT_GRANT_TIMELINE_INDEX)
        await events.create_index([("candidate_id", 1), ("occurred_at", 1)], name=EVENT_CANDIDATE_TIMELINE_INDEX)
        # Operational lookup only. Revocation authorization is evaluated from current data; this is NOT a TTL index.
        await grants.create_index("revoked_at", name=GRANT_REVOCATION_INDEX)
        print("TS-A10 privacy indexes ready; no TTL, deletion, anonymization, or backfill performed")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())
