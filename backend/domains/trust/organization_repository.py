"""Mongo persistence for current Organization state and append-only verification events."""
from typing import Optional


class OrganizationRepository:
    def __init__(self, db):
        self.organizations = db.organizations
        self.events = db.organization_verification_events
        self.companies = db.companies

    async def get(self, organization_id: str, session=None) -> Optional[dict]:
        return await self.organizations.find_one({"_id": organization_id}, session=session)

    async def legacy_company_exists(self, legacy_company_id: str, session=None) -> bool:
        return await self.companies.find_one({"_id": legacy_company_id}, session=session) is not None

    async def insert(self, document: dict, session=None) -> dict:
        await self.organizations.insert_one(document, session=session)
        return document

    async def update_with_version(
        self,
        organization_id: str,
        expected_version: int,
        changes: dict,
        session=None,
    ) -> Optional[dict]:
        result = await self.organizations.update_one(
            {"_id": organization_id, "version": expected_version},
            {"$set": changes, "$inc": {"version": 1}},
            session=session,
        )
        if result.modified_count != 1:
            return None
        return await self.get(organization_id, session=session)

    async def insert_event(self, event: dict, session=None) -> dict:
        await self.events.insert_one(event, session=session)
        return event
