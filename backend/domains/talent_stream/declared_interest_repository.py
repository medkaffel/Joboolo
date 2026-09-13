"""Narrow TS-B4 reads plus writes delegated exclusively to canonical A11."""
from pymongo.errors import PyMongoError

from domains.intent.repository import IntentEventRepository
from domains.intent.service import IntentEventService
from domains.talent_stream.index_requirements import TS_INDEX_REQUIREMENTS
from mongo_index_safety import verify_metadata


_A11_REQUIREMENTS = tuple(
    requirement
    for requirement in TS_INDEX_REQUIREMENTS
    if requirement.name == "talent_intent_events"
)

USER_FIELDS = {"_id": 1, "user_type": 1, "is_active": 1}
JOB_FIELDS = {"_id": 1, "is_active": 1, "expires_at": 1, "campaign_id": 1}
CAMPAIGN_FIELDS = {
    "_id": 1,
    "status": 1,
    "start_date": 1,
    "end_date": 1,
    "billing_mode": 1,
    "budget_limit": 1,
    "spent": 1,
}


class DeclaredInterestRepositoryError(RuntimeError):
    pass


class DeclaredInterestReadinessError(DeclaredInterestRepositoryError):
    pass


class DeclaredInterestRepository:
    def __init__(self, db):
        self.db = db
        self.events = IntentEventRepository(db)
        self.event_service = IntentEventService(db)

    async def readiness(self):
        """Verify the deployed A11 metadata; never repair or migrate at runtime."""
        names = {requirement.name for requirement in _A11_REQUIREMENTS}
        try:
            collections = {}
            cursor = await self.db.list_collections(
                filter={"name": {"$in": sorted(names)}},
            )
            async for record in cursor:
                collections[record["name"]] = record
            indexes = {}
            for name in names:
                if collections.get(name, {}).get("type") == "collection":
                    indexes[name] = await self.db[name].index_information()
            report = verify_metadata(_A11_REQUIREMENTS, collections, indexes)
        except Exception:
            raise DeclaredInterestReadinessError(
                "declared-interest storage metadata unavailable"
            ) from None
        if not report.ok:
            raise DeclaredInterestReadinessError(
                "declared-interest storage is not ready"
            )
        return report

    async def get_user(self, candidate_id):
        try:
            return await self.db.users.find_one(
                {"_id": candidate_id}, USER_FIELDS,
            )
        except PyMongoError:
            raise DeclaredInterestRepositoryError(
                "declared-interest read failed"
            ) from None

    async def get_job(self, job_id):
        try:
            return await self.db.jobs.find_one({"_id": job_id}, JOB_FIELDS)
        except PyMongoError:
            raise DeclaredInterestRepositoryError(
                "declared-interest read failed"
            ) from None

    async def get_campaign(self, campaign_id):
        try:
            return await self.db.campaigns.find_one(
                {"_id": campaign_id}, CAMPAIGN_FIELDS,
            )
        except PyMongoError:
            raise DeclaredInterestRepositoryError(
                "declared-interest read failed"
            ) from None

    async def get_event_by_idempotency_key(self, key):
        try:
            return await self.events.get_by_idempotency_key(key)
        except PyMongoError:
            raise DeclaredInterestRepositoryError(
                "declared-interest read failed"
            ) from None

    async def record(self, event):
        try:
            return await self.event_service.record(event)
        except PyMongoError:
            raise DeclaredInterestRepositoryError(
                "declared-interest write failed"
            ) from None
