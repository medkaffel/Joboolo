"""Read-only Mongo persistence adapters for TS-A9 current permission evaluation."""
from typing import Optional

from domains.talent_stream.contracts import GrantScope


class PermissionRepository:
    def __init__(self, db):
        self.candidate_preferences = db.candidate_preferences
        self.organizations = db.organizations
        self.grants = db.talent_stream_grants

    async def get_candidate_preferences(self, candidate_id: str) -> Optional[dict]:
        return await self.candidate_preferences.find_one({"candidate_id": candidate_id})

    async def get_organization(self, organization_id: str) -> Optional[dict]:
        return await self.organizations.find_one({"_id": organization_id})

    async def find_grants(
        self,
        candidate_id: str,
        organization_id: str,
        stream_id: str,
        required_scope: GrantScope,
        document_id: Optional[str] = None,
    ) -> list[dict]:
        query = {
            "candidate_id": candidate_id,
            "grantee_organization_id": organization_id,
            "stream_id": stream_id,
            "scopes": required_scope.value,
        }
        if required_scope is GrantScope.CV:
            query["document_id"] = document_id
        cursor = self.grants.find(query)
        return [document async for document in cursor]
