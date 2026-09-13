"""Strict read-only Mongo adapter for TS-B3 application sources."""
from pymongo.errors import PyMongoError

from mongo_index_safety import CollectionRequirement, IndexRequirement, verify_metadata
from domains.talent_stream.index_requirements import TS_INDEX_REQUIREMENTS
from domains.talent_stream.stream_repository import TalentStreamRepository


APPLICATION_SOURCE_REQUIREMENT = CollectionRequirement(
    "applications",
    (
        IndexRequirement(
            name="job_id_1_candidate_id_1",
            keys=(("job_id", 1), ("candidate_id", 1)),
            critical=True,
            unique=True,
        ),
    ),
)

_TS_REQUIREMENTS = tuple(
    requirement
    for requirement in TS_INDEX_REQUIREMENTS
    if requirement.name in {"talent_streams", "opportunity_specs", "organizations"}
)
_READINESS_REQUIREMENTS = _TS_REQUIREMENTS + (APPLICATION_SOURCE_REQUIREMENT,)

USER_FIELDS = {"_id": 1, "user_type": 1, "is_active": 1}
OPPORTUNITY_FIELDS = {
    "_id": 1,
    "opportunity_spec_id": 1,
    "version": 1,
    "provenance": 1,
    "source_job_id": 1,
    "source_ref": 1,
    "version_provenance": 1,
    "version_provenance_ref": 1,
}
JOB_FIELDS = {
    "_id": 1,
    "employer_id": 1,
    "company_id": 1,
    "source": 1,
    "is_partner": 1,
    "partner_id": 1,
    "campaign_id": 1,
    "external_url": 1,
    "external_ref": 1,
}
COMPANY_FIELDS = {"_id": 1, "owner_id": 1}
ORGANIZATION_FIELDS = {"_id": 1, "organization_id": 1, "legacy_company_id": 1}
APPLICATION_FIELDS = {
    "_id": 1,
    "candidate_id": 1,
    "job_id": 1,
    "status": 1,
    "created_at": 1,
}


class ApplicationSourceRepositoryError(RuntimeError):
    pass


class ApplicationSourceReadinessError(ApplicationSourceRepositoryError):
    pass


class ApplicationSourceRepository:
    def __init__(self, db):
        self.db = db
        self.streams = TalentStreamRepository(db)

    async def readiness(self):
        names = {requirement.name for requirement in _READINESS_REQUIREMENTS}
        try:
            collections = {}
            cursor = await self.db.list_collections(filter={"name": {"$in": sorted(names)}})
            async for record in cursor:
                collections[record["name"]] = record
            indexes = {}
            for name in names:
                if collections.get(name, {}).get("type") == "collection":
                    indexes[name] = await self.db[name].index_information()
            report = verify_metadata(_READINESS_REQUIREMENTS, collections, indexes)
        except Exception:
            raise ApplicationSourceReadinessError(
                "application source metadata unavailable"
            ) from None
        if not report.ok:
            raise ApplicationSourceReadinessError(
                "application source storage is not ready"
            )
        return report

    async def get_stream(self, stream_id):
        return await self.streams.get(stream_id)

    async def get_user(self, recruiter_id):
        try:
            return await self.db.users.find_one({"_id": recruiter_id}, USER_FIELDS)
        except PyMongoError:
            raise ApplicationSourceRepositoryError("application source read failed") from None

    async def get_opportunity(self, opportunity_spec_id, version):
        try:
            return await self.db.opportunity_specs.find_one(
                {"opportunity_spec_id": opportunity_spec_id, "version": version},
                OPPORTUNITY_FIELDS,
            )
        except PyMongoError:
            raise ApplicationSourceRepositoryError("application source read failed") from None

    async def get_job(self, job_id):
        try:
            return await self.db.jobs.find_one({"_id": job_id}, JOB_FIELDS)
        except PyMongoError:
            raise ApplicationSourceRepositoryError("application source read failed") from None

    async def get_company(self, company_id):
        try:
            return await self.db.companies.find_one({"_id": company_id}, COMPANY_FIELDS)
        except PyMongoError:
            raise ApplicationSourceRepositoryError("application source read failed") from None

    async def get_organization(self, organization_id):
        try:
            return await self.db.organizations.find_one(
                {"_id": organization_id}, ORGANIZATION_FIELDS,
            )
        except PyMongoError:
            raise ApplicationSourceRepositoryError("application source read failed") from None

    async def list_applications(self, job_id, *, after, limit):
        query = {"job_id": job_id}
        if after is not None:
            query["$or"] = [
                {"created_at": {"$gt": after.applied_at}},
                {
                    "created_at": after.applied_at,
                    "_id": {"$gt": after.application_id},
                },
            ]
        try:
            cursor = self.db.applications.find(query, APPLICATION_FIELDS)
            cursor = cursor.sort([("created_at", 1), ("_id", 1)]).limit(limit)
            return await cursor.to_list(length=limit)
        except PyMongoError:
            raise ApplicationSourceRepositoryError("application source read failed") from None
