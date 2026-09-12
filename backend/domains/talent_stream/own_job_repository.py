"""Narrow TS-B2 reads for an owned internal Job and A3/A4 readiness."""
from copy import deepcopy

from pymongo.errors import PyMongoError

from mongo_index_safety import verify_metadata
from domains.talent_stream.index_requirements import TS_INDEX_REQUIREMENTS


_REQUIREMENTS = tuple(
    requirement for requirement in TS_INDEX_REQUIREMENTS
    if requirement.name in {"role_dnas", "opportunity_specs"}
)
_JOB_FIELDS = {
    "_id": 1,
    "employer_id": 1,
    "company_id": 1,
    "title": 1,
    "description": 1,
    "location": 1,
    "salary_min": 1,
    "salary_max": 1,
    "salary_currency": 1,
    "job_type": 1,
    "is_remote": 1,
    "requirements": 1,
    "benefits": 1,
    "tags": 1,
    "is_active": 1,
    "expires_at": 1,
    "is_partner": 1,
    "partner_id": 1,
    "campaign_id": 1,
    "external_url": 1,
    "external_ref": 1,
}


class OwnJobRepositoryError(RuntimeError):
    pass


class OwnJobAccessError(OwnJobRepositoryError):
    pass


class OwnJobReadinessError(OwnJobRepositoryError):
    pass


class OwnJobRepository:
    def __init__(self, db):
        self.db = db

    async def get_owned_source(self, recruiter_id, job_id):
        """Read current ownership without using a public, counter-mutating route."""
        try:
            user = await self.db.users.find_one(
                {"_id": recruiter_id}, {"_id": 1, "user_type": 1, "is_active": 1},
            )
            job = await self.db.jobs.find_one({"_id": job_id}, _JOB_FIELDS)
            company_id = None if not isinstance(job, dict) else job.get("company_id")
            company = (
                None if type(company_id) is not str or not company_id.strip()
                else await self.db.companies.find_one(
                    {"_id": company_id}, {"_id": 1, "owner_id": 1},
                )
            )
        except PyMongoError:
            raise OwnJobRepositoryError("own-job source read failed") from None

        authorized_user = (
            isinstance(user, dict)
            and user.get("is_active") is True
            and user.get("user_type") in {"employer", "admin"}
        )
        owned = (
            isinstance(job, dict)
            and job.get("employer_id") == recruiter_id
            and isinstance(company, dict)
            and company.get("owner_id") == recruiter_id
        )
        if not authorized_user or not owned:
            raise OwnJobAccessError("own job not found or not authorized")
        return deepcopy(job)

    async def readiness(self):
        """Require the existing A3/A4 metadata contract before either write."""
        names = {requirement.name for requirement in _REQUIREMENTS}
        try:
            collections = {}
            cursor = await self.db.list_collections(filter={"name": {"$in": sorted(names)}})
            async for record in cursor:
                collections[record["name"]] = record
            indexes = {}
            for name in names:
                if collections.get(name, {}).get("type") == "collection":
                    indexes[name] = await self.db[name].index_information()
            report = verify_metadata(_REQUIREMENTS, collections, indexes)
        except Exception:
            raise OwnJobReadinessError("own-job target storage metadata unavailable") from None
        if not report.ok:
            raise OwnJobReadinessError("own-job target storage is not ready")
        return report
