"""TS-B3 orchestration for exact, minimal and read-only application sources."""
from dataclasses import dataclass
from datetime import datetime, timezone

from bson.int64 import Int64

from domains.shared.ids import CandidateId, JobId
from domains.talent_stream.application_source_models import (
    ApplicationSource,
    ApplicationSourceCursor,
)
from domains.talent_stream.application_source_repository import (
    ApplicationSourceRepository,
)
from domains.talent_stream.own_job_source import own_job_source_violation
from domains.talent_stream.stream_models import nonblank_identifier
from domains.talent_stream.stream_repository import TalentStreamStoredDataError
from domains.talent_stream.stream_service import TalentStreamNotFoundError
from models import ApplicationStatus


MAX_APPLICATION_SOURCE_PAGE_SIZE = 100


class ApplicationSourceAccessError(LookupError):
    pass


class ApplicationSourceStoredDataError(RuntimeError):
    pass


class ApplicationSourceConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class _SecuredScope:
    stream_id: str
    job_id: str
    fingerprint: tuple


def _stored_utc_millisecond(value, field_name):
    if type(value) is not datetime:
        raise ApplicationSourceStoredDataError("invalid stored application source")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        value = value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise ApplicationSourceStoredDataError("invalid stored application source") from None
    if value.microsecond % 1000:
        raise ApplicationSourceStoredDataError("invalid stored application source")
    return value


def _stored_positive_integer(value, field_name):
    if isinstance(value, bool) or not isinstance(value, (int, Int64)) or value < 1:
        raise ApplicationSourceStoredDataError("invalid application source scope")
    return int(value)


def _stored_identifier(value, field_name):
    try:
        return nonblank_identifier(value, field_name)
    except ValueError:
        raise ApplicationSourceStoredDataError("invalid application source scope") from None


def _optional_provenance_ref(value):
    if value is None:
        return None
    return _stored_identifier(value, "provenance_ref")


def _application_from_document(document, expected_job_id):
    if type(document) is not dict or set(document) != {
        "_id", "candidate_id", "job_id", "status", "created_at",
    }:
        raise ApplicationSourceStoredDataError("invalid stored application source")
    try:
        application_id = nonblank_identifier(document["_id"], "application_id")
        candidate_id = nonblank_identifier(document["candidate_id"], "candidate_id")
        job_id = nonblank_identifier(document["job_id"], "job_id")
    except ValueError:
        raise ApplicationSourceStoredDataError("invalid stored application source") from None
    if job_id != expected_job_id or type(document["status"]) is not str:
        raise ApplicationSourceStoredDataError("invalid stored application source")
    try:
        status = ApplicationStatus(document["status"])
    except ValueError:
        raise ApplicationSourceStoredDataError("invalid stored application source") from None
    return ApplicationSource(
        application_id=application_id,
        candidate_id=CandidateId(candidate_id),
        job_id=JobId(job_id),
        status=status,
        applied_at=_stored_utc_millisecond(document["created_at"], "created_at"),
    )


class ApplicationSourceService:
    def __init__(self, db):
        self.repository = ApplicationSourceRepository(db)

    async def _scope(self, recruiter_id, stream_id):
        recruiter_id = nonblank_identifier(recruiter_id, "recruiter_id")
        stream_id = nonblank_identifier(stream_id, "stream_id")

        user = await self.repository.get_user(recruiter_id)
        if not (
            type(user) is dict
            and user.get("_id") == recruiter_id
            and user.get("is_active") is True
            and user.get("user_type") in {"employer", "admin"}
        ):
            raise ApplicationSourceAccessError("application source not authorized")

        try:
            stream = await self.repository.get_stream(stream_id)
        except TalentStreamNotFoundError:
            stream = None
        if stream is None:
            raise ApplicationSourceAccessError("application source not authorized")
        actor = stream.recruiting_actor_context
        if str(actor.recruiter_user_id) != recruiter_id:
            raise ApplicationSourceAccessError("application source not authorized")

        reference = stream.requirement_snapshot.opportunity_spec
        opportunity_id = str(reference.opportunity_spec_id)
        opportunity_version = int(reference.version)
        opportunity = await self.repository.get_opportunity(
            opportunity_id, opportunity_version,
        )
        if type(opportunity) is not dict:
            raise ApplicationSourceAccessError("application source not authorized")
        stored_id = _stored_identifier(
            opportunity.get("opportunity_spec_id"), "opportunity_spec_id",
        )
        stored_version = _stored_positive_integer(
            opportunity.get("version"), "opportunity_spec.version",
        )
        if (
            stored_id != opportunity_id
            or stored_version != opportunity_version
            or opportunity.get("_id") != f"{opportunity_id}:v{opportunity_version}"
            or opportunity.get("provenance") != "internal_job"
            or opportunity.get("version_provenance") != "internal_job"
        ):
            raise ApplicationSourceAccessError("application source not authorized")
        job_id = _stored_identifier(opportunity.get("source_job_id"), "source_job_id")
        source_ref = _optional_provenance_ref(opportunity.get("source_ref"))
        version_ref = _optional_provenance_ref(
            opportunity.get("version_provenance_ref")
        )
        if version_ref is None or (source_ref is not None and source_ref != version_ref):
            raise ApplicationSourceAccessError("application source not authorized")

        job = await self.repository.get_job(job_id)
        if type(job) is not dict or job.get("_id") != job_id:
            raise ApplicationSourceAccessError("application source not authorized")
        if own_job_source_violation(job) is not None:
            raise ApplicationSourceAccessError("application source not authorized")
        company_id = job.get("company_id")
        if (
            type(company_id) is not str
            or not company_id.strip()
            or job.get("employer_id") != recruiter_id
        ):
            raise ApplicationSourceAccessError("application source not authorized")

        company = await self.repository.get_company(company_id)
        if not (
            type(company) is dict
            and company.get("_id") == company_id
            and company.get("owner_id") == recruiter_id
        ):
            raise ApplicationSourceAccessError("application source not authorized")

        organization_id = str(actor.hiring_company_id)
        organization = await self.repository.get_organization(organization_id)
        if not (
            type(organization) is dict
            and organization.get("_id") == organization_id
            and organization.get("organization_id") == organization_id
            and organization.get("legacy_company_id") == company_id
        ):
            raise ApplicationSourceAccessError("application source not authorized")

        return _SecuredScope(
            stream_id=stream_id,
            job_id=job_id,
            fingerprint=(
                recruiter_id,
                user.get("user_type"),
                stream_id,
                str(actor.recruiter_user_id),
                str(actor.hiring_company_id),
                stream.requirement_snapshot,
                opportunity_id,
                opportunity_version,
                opportunity.get("provenance"),
                opportunity.get("version_provenance"),
                source_ref,
                version_ref,
                job_id,
                job.get("employer_id"),
                company_id,
                company.get("owner_id"),
                organization_id,
                organization.get("legacy_company_id"),
            ),
        )

    async def list_page(self, recruiter_id, stream_id, *, after=None, limit=100):
        if isinstance(limit, bool) or type(limit) is not int or not 1 <= limit <= MAX_APPLICATION_SOURCE_PAGE_SIZE:
            raise ValueError("limit must be between 1 and 100")
        if after is not None and type(after) is not ApplicationSourceCursor:
            raise ValueError("invalid application source cursor")

        await self.repository.readiness()
        before = await self._scope(recruiter_id, stream_id)
        if after is not None and (
            after.stream_id != before.stream_id or after.job_id != before.job_id
        ):
            raise ValueError("application source cursor does not match scope")
        documents = await self.repository.list_applications(
            before.job_id, after=after, limit=limit,
        )
        sources = tuple(
            _application_from_document(document, before.job_id)
            for document in documents
        )
        if len({source.application_id for source in sources}) != len(sources):
            raise ApplicationSourceStoredDataError("duplicate stored application source")
        if len({source.candidate_id for source in sources}) != len(sources):
            raise ApplicationSourceStoredDataError("duplicate stored application source")

        try:
            after_scope = await self._scope(recruiter_id, stream_id)
        except (
            ApplicationSourceAccessError,
            ApplicationSourceStoredDataError,
            TalentStreamStoredDataError,
        ):
            raise ApplicationSourceConflictError("application source scope changed") from None
        if before.fingerprint != after_scope.fingerprint:
            raise ApplicationSourceConflictError("application source scope changed")
        return sources
