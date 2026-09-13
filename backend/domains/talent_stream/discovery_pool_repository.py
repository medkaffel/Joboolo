"""Read-only Mongo access for TS-B6 Discovery Pool retrieval."""
from pymongo.errors import PyMongoError

from mongo_index_safety import verify_metadata
from domains.talent_stream.index_requirements import CANDIDATE_PREFERENCES_REQUIREMENT
from domains.talent_stream.stream_repository import TalentStreamRepository


PREFERENCES_FIELDS = {
    "_id": 1,
    "candidate_id": 1,
    "version": 1,
    "search_state": 1,
    "discovery": 1,
    "excluded_company_ids": 1,
    "updated_at": 1,
}
USER_FIELDS = {"_id": 1, "user_type": 1, "is_active": 1}


class DiscoveryPoolRepositoryError(RuntimeError):
    pass


class DiscoveryPoolReadinessError(DiscoveryPoolRepositoryError):
    pass


class DiscoveryPoolRepository:
    def __init__(self, db):
        self.db = db
        self.streams = TalentStreamRepository(db)

    async def readiness(self):
        name = CANDIDATE_PREFERENCES_REQUIREMENT.name
        try:
            await self.streams.readiness()
            collections = {}
            cursor = await self.db.list_collections(filter={"name": name})
            async for record in cursor:
                collections[record["name"]] = record
            indexes = {}
            if collections.get(name, {}).get("type") == "collection":
                indexes[name] = await self.db[name].index_information()
            report = verify_metadata(
                (CANDIDATE_PREFERENCES_REQUIREMENT,), collections, indexes,
            )
        except Exception:
            raise DiscoveryPoolReadinessError(
                "Discovery Pool metadata unavailable"
            ) from None
        # A13 treats the B6 index as performance-only globally, but B6 refuses
        # to run without every declared scan prerequisite to prevent a full scan.
        b6_mismatch = any(
            diagnostic.index_position == 2 for diagnostic in report.diagnostics
        )
        if not report.ok or b6_mismatch:
            raise DiscoveryPoolReadinessError("Discovery Pool storage is not ready")
        return report

    async def get_stream(self, stream_id):
        return await self.streams.get(stream_id)

    async def list_preferences(self, *, after_candidate_id, limit):
        query = {
            "discovery.enabled": True,
            "discovery.allow_compatible_opportunities": True,
        }
        if after_candidate_id is not None:
            query["candidate_id"] = {"$gt": after_candidate_id}
        try:
            cursor = self.db.candidate_preferences.find(query, PREFERENCES_FIELDS)
            cursor = cursor.sort([("candidate_id", 1)]).limit(limit)
            return await cursor.to_list(length=limit)
        except PyMongoError:
            raise DiscoveryPoolRepositoryError("Discovery Pool read failed") from None

    async def get_preferences(self, candidate_id):
        try:
            return await self.db.candidate_preferences.find_one(
                {"candidate_id": candidate_id}, PREFERENCES_FIELDS,
            )
        except PyMongoError:
            raise DiscoveryPoolRepositoryError("Discovery Pool read failed") from None

    async def get_user(self, candidate_id):
        try:
            return await self.db.users.find_one({"_id": candidate_id}, USER_FIELDS)
        except PyMongoError:
            raise DiscoveryPoolRepositoryError("Discovery Pool read failed") from None
