"""Mongo persistence adapters for TS-A8 current trust state and audit events."""
from typing import Optional


class RecruitingTrustRepository:
    def __init__(self, db):
        self.memberships = db.organization_memberships
        self.recruiter_verifications = db.recruiter_verifications
        self.mandates = db.recruiting_mandates
        self.events = db.recruiting_trust_events
        self.organizations = db.organizations
        self.users = db.users

    async def get_user(self, recruiter_user_id: str, session=None) -> Optional[dict]:
        return await self.users.find_one({"_id": recruiter_user_id}, session=session)

    async def get_organization(self, organization_id: str, session=None) -> Optional[dict]:
        return await self.organizations.find_one({"_id": organization_id}, session=session)

    async def get_membership(self, membership_id: str, session=None) -> Optional[dict]:
        return await self.memberships.find_one({"_id": membership_id}, session=session)

    async def get_membership_by_pair(self, recruiter_user_id: str, organization_id: str, session=None) -> Optional[dict]:
        return await self.memberships.find_one({"recruiter_user_id": recruiter_user_id, "organization_id": organization_id}, session=session)

    async def get_recruiter_verification(self, recruiter_user_id: str, session=None) -> Optional[dict]:
        return await self.recruiter_verifications.find_one({"_id": recruiter_user_id}, session=session)

    async def get_mandate(self, mandate_id: str, session=None) -> Optional[dict]:
        return await self.mandates.find_one({"_id": mandate_id}, session=session)

    async def insert_membership(self, document: dict, session=None):
        await self.memberships.insert_one(document, session=session); return document

    async def insert_recruiter_verification(self, document: dict, session=None):
        await self.recruiter_verifications.insert_one(document, session=session); return document

    async def insert_mandate(self, document: dict, session=None):
        await self.mandates.insert_one(document, session=session); return document

    async def insert_event(self, document: dict, session=None):
        await self.events.insert_one(document, session=session); return document

    async def _update(self, collection, subject_id: str, expected_version: int, changes: dict, session=None) -> Optional[dict]:
        result = await collection.update_one({"_id": subject_id, "version": expected_version}, {"$set": changes, "$inc": {"version": 1}}, session=session)
        if result.modified_count != 1: return None
        return await collection.find_one({"_id": subject_id}, session=session)

    async def update_membership(self, membership_id: str, expected_version: int, changes: dict, session=None) -> Optional[dict]:
        return await self._update(self.memberships, membership_id, expected_version, changes, session=session)

    async def update_recruiter_verification(self, recruiter_user_id: str, expected_version: int, changes: dict, session=None) -> Optional[dict]:
        return await self._update(self.recruiter_verifications, recruiter_user_id, expected_version, changes, session=session)

    async def update_mandate(self, mandate_id: str, expected_version: int, changes: dict, session=None) -> Optional[dict]:
        return await self._update(self.mandates, mandate_id, expected_version, changes, session=session)
