"""Mongo persistence adapter for TS-A10 privacy lifecycle writes and audit events."""
from typing import Optional


class PrivacyRepository:
    def __init__(self, db):
        self.grants = db.talent_stream_grants
        self.events = db.talent_stream_privacy_events

    async def get_grant(self, grant_id: str, session=None) -> Optional[dict]:
        return await self.grants.find_one({"_id": grant_id}, session=session)

    async def get_event_by_command_id(self, command_id: str, session=None) -> Optional[dict]:
        return await self.events.find_one({"command_id": command_id}, session=session)

    async def revoke_grant_if_unrevoked(self, grant_id: str, candidate_id: str, effective_at, changes: dict, session=None) -> Optional[dict]:
        result = await self.grants.update_one(
            {
                "_id": grant_id,
                "candidate_id": candidate_id,
                "$or": [
                    {"revoked_at": None},
                    {"revoked_at": {"$gt": effective_at}},
                ],
            },
            {"$set": changes},
            session=session,
        )
        if result.modified_count != 1:
            return None
        return await self.grants.find_one({"_id": grant_id}, session=session)

    async def insert_event(self, document: dict, session=None) -> dict:
        await self.events.insert_one(document, session=session)
        return document
