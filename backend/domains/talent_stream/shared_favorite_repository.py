"""Narrow TS-B5 reads; the sole write is delegated to canonical A11."""
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
SAVED_JOB_FIELDS = {
    "_id": 1,
    "user_id": 1,
    "job_id": 1,
    "created_at": 1,
    "updated_at": 1,
}
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
SAVED_JOB_INDEX_KEYS = [("user_id", 1), ("job_id", 1)]


class SharedFavoriteRepositoryError(RuntimeError):
    pass


class SharedFavoriteReadinessError(SharedFavoriteRepositoryError):
    pass


class SharedFavoriteRepository:
    def __init__(self, db):
        self.db = db
        self.events = IntentEventRepository(db)
        self.event_service = IntentEventService(db)

    async def a11_readiness(self):
        """Verify deployed A11 metadata without creating or repairing anything."""
        try:
            cursor = await self.db.list_collections(
                filter={"name": "talent_intent_events"},
            )
            collections = {}
            async for record in cursor:
                collections[record["name"]] = record
            indexes = {}
            if collections.get("talent_intent_events", {}).get("type") == "collection":
                indexes["talent_intent_events"] = (
                    await self.db.talent_intent_events.index_information()
                )
            report = verify_metadata(_A11_REQUIREMENTS, collections, indexes)
        except Exception:
            raise SharedFavoriteReadinessError(
                "shared-favorite A11 storage metadata unavailable"
            ) from None
        if not report.ok:
            raise SharedFavoriteReadinessError(
                "shared-favorite A11 storage is not ready"
            )
        return report

    async def saved_jobs_readiness(self):
        """Require the historical pair uniqueness; index names are irrelevant."""
        try:
            indexes = await self.db.saved_jobs.index_information()
        except Exception:
            raise SharedFavoriteReadinessError(
                "saved-jobs storage metadata unavailable"
            ) from None
        matching = [
            index for index in indexes.values()
            if list(index.get("key", ())) == SAVED_JOB_INDEX_KEYS
            and index.get("unique") is True
        ]
        if not matching:
            raise SharedFavoriteReadinessError(
                "saved-jobs unique candidate/job identity is not ready"
            )
        return True

    async def get_user(self, candidate_id):
        try:
            return await self.db.users.find_one(
                {"_id": candidate_id}, USER_FIELDS,
            )
        except PyMongoError:
            raise SharedFavoriteRepositoryError("shared-favorite read failed") from None

    async def get_saved_job(self, candidate_id, job_id, saved_job_id):
        try:
            return await self.db.saved_jobs.find_one(
                {
                    "_id": saved_job_id,
                    "user_id": candidate_id,
                    "job_id": job_id,
                },
                SAVED_JOB_FIELDS,
                collation={"locale": "simple"},
            )
        except PyMongoError:
            raise SharedFavoriteRepositoryError("shared-favorite read failed") from None

    async def get_job(self, job_id):
        try:
            return await self.db.jobs.find_one({"_id": job_id}, JOB_FIELDS)
        except PyMongoError:
            raise SharedFavoriteRepositoryError("shared-favorite read failed") from None

    async def get_campaign(self, campaign_id):
        try:
            return await self.db.campaigns.find_one(
                {"_id": campaign_id}, CAMPAIGN_FIELDS,
            )
        except PyMongoError:
            raise SharedFavoriteRepositoryError("shared-favorite read failed") from None

    async def get_event(self, event_id):
        try:
            return await self.events.get(event_id)
        except PyMongoError:
            raise SharedFavoriteRepositoryError("shared-favorite read failed") from None

    async def get_event_by_idempotency_key(self, key):
        try:
            return await self.events.get_by_idempotency_key(key)
        except PyMongoError:
            raise SharedFavoriteRepositoryError("shared-favorite read failed") from None

    async def record(self, event):
        try:
            return await self.event_service.record(event)
        except PyMongoError:
            raise SharedFavoriteRepositoryError("shared-favorite write failed") from None
