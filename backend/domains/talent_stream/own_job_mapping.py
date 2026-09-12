"""Pure TS-B2 mapping from one owned internal Job to A3/A4 inputs.

The raw Mongo document is deliberately consumed without a legacy Pydantic
model: absent source facts stay absent instead of receiving response defaults.
This module performs no persistence, authorization side effect, networking or
Talent Stream creation.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Mapping

from domains.opportunities.models import (
    CompensationConstraint,
    LocationConstraint,
    OpportunityFactSource,
    OpportunitySpecStatus,
    OpportunitySpecification,
)
from domains.roles.models import RoleDNA, RoleDNAStatus, RoleFactSource
from domains.shared.ids import JobId, OpportunitySpecId, RecruiterUserId, RoleDNAId
from domains.shared.versioning import EntityVersion
from domains.talent_stream.contracts import (
    OpportunitySpecificationRef,
    RoleDNARef,
    StreamRequirementSnapshot,
)


OWN_JOB_MAPPING_VERSION = "ts-b2-own-job-v1"
_KNOWN_JOB_TYPES = frozenset({"CDI", "CDD", "Stage", "Freelance", "Intérim", "Titulaire"})
_EXTERNAL_MARKERS = ("partner_id", "campaign_id", "external_url", "external_ref")
_FINGERPRINT_LISTS = ("requirements", "benefits", "tags")


class OwnJobMappingError(ValueError):
    """The raw source cannot safely be mapped by the B2 contract."""


class OwnJobSourceConflictError(RuntimeError):
    """A scoped B2 command no longer denotes the same source content."""


@dataclass(frozen=True, slots=True)
class OwnJobPreparation:
    source_fingerprint: str
    role_dna: RoleDNA
    opportunity_specification: OpportunitySpecification
    requirement_snapshot: StreamRequirementSnapshot


def _nonblank(value, field_name):
    if type(value) is not str or not value.strip():
        raise OwnJobMappingError(f"{field_name} must be a nonblank string")
    return value.strip()


def _optional_text(source, field_name):
    if field_name not in source or source[field_name] is None:
        return None
    if type(source[field_name]) is not str:
        raise OwnJobMappingError(f"{field_name} must be a string when present")
    value = source[field_name].strip()
    return value or None


def _optional_amount(source, field_name):
    if field_name not in source or source[field_name] is None:
        return None
    value = source[field_name]
    if type(value) is not int or value < 0:
        raise OwnJobMappingError(f"{field_name} must be a non-negative integer")
    return value


def _optional_list(source, field_name):
    if field_name not in source or source[field_name] is None:
        return None
    value = source[field_name]
    if type(value) is not list or any(type(item) is not str or not item.strip() for item in value):
        raise OwnJobMappingError(f"{field_name} must contain only nonblank strings")
    return tuple(item.strip() for item in value)


def _utc_millisecond(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise OwnJobMappingError("captured_at must be timezone-aware")
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond % 1000:
        raise OwnJobMappingError("captured_at must use BSON millisecond precision")
    return normalized


def _validate_expiry(source):
    if "expires_at" not in source or source["expires_at"] is None:
        return
    value = source["expires_at"]
    if type(value) is datetime:
        return
    if type(value) is str and value.strip():
        try:
            datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            return
        except ValueError:
            pass
    raise OwnJobMappingError("job.expires_at must be a valid datetime when present")


def _digest(payload):
    encoded = json.dumps(
        payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def deterministic_own_job_ids(recruiter_id, job_id, command_id):
    recruiter_id = _nonblank(recruiter_id, "recruiter_id")
    job_id = _nonblank(job_id, "job_id")
    command_id = _nonblank(command_id, "command_id")
    identity = _digest({
        "command_id": command_id,
        "job_id": job_id,
        "mapping_version": OWN_JOB_MAPPING_VERSION,
        "recruiter_id": recruiter_id,
    })
    return (
        RoleDNAId(f"ts-b2:role:{identity}"),
        OpportunitySpecId(f"ts-b2:opportunity:{identity}"),
    )


def _validated_source(raw_job, recruiter_id, job_id):
    if not isinstance(raw_job, Mapping):
        raise OwnJobMappingError("own job source must be a mapping")
    recruiter_id = _nonblank(recruiter_id, "recruiter_id")
    job_id = _nonblank(job_id, "job_id")
    if _nonblank(raw_job.get("_id"), "job._id") != job_id:
        raise OwnJobMappingError("job identity mismatch")
    if _nonblank(raw_job.get("employer_id"), "job.employer_id") != recruiter_id:
        raise OwnJobMappingError("job is not owned by the requesting recruiter")
    company_id = _nonblank(raw_job.get("company_id"), "job.company_id")
    title = _nonblank(raw_job.get("title"), "job.title")

    if "is_partner" in raw_job and type(raw_job["is_partner"]) is not bool:
        raise OwnJobMappingError("job.is_partner must be boolean when present")
    if raw_job.get("is_partner") is True or any(raw_job.get(key) is not None for key in _EXTERNAL_MARKERS):
        raise OwnJobMappingError("partner, imported and external jobs are not B2 own-job sources")
    if "is_remote" in raw_job and type(raw_job["is_remote"]) is not bool:
        raise OwnJobMappingError("job.is_remote must be boolean when present")
    if "is_active" in raw_job and type(raw_job["is_active"]) is not bool:
        raise OwnJobMappingError("job.is_active must be boolean when present")
    _validate_expiry(raw_job)

    description = _optional_text(raw_job, "description")
    location = _optional_text(raw_job, "location")
    minimum = _optional_amount(raw_job, "salary_min")
    maximum = _optional_amount(raw_job, "salary_max")
    if minimum is not None and maximum is not None and maximum < minimum:
        raise OwnJobMappingError("salary_max cannot be below salary_min")
    currency = _optional_text(raw_job, "salary_currency")
    if (minimum is not None or maximum is not None) and currency is None:
        raise OwnJobMappingError("explicit salary currency is required with salary amounts")

    job_type = _optional_text(raw_job, "job_type")
    if job_type is not None and job_type not in _KNOWN_JOB_TYPES:
        raise OwnJobMappingError("unsupported job_type")
    lists = {field: _optional_list(raw_job, field) for field in _FINGERPRINT_LISTS}
    return {
        "job_id": job_id,
        "recruiter_id": recruiter_id,
        "company_id": company_id,
        "title": title,
        "description": description,
        "location": location,
        "salary_min": minimum,
        "salary_max": maximum,
        "salary_currency": currency,
        "job_type": job_type,
        "is_remote": raw_job.get("is_remote"),
        **lists,
    }


def own_job_source_fingerprint(raw_job, recruiter_id, job_id):
    source = _validated_source(raw_job, recruiter_id, job_id)
    return "sha256:" + _digest({
        "mapping_version": OWN_JOB_MAPPING_VERSION,
        "source": source,
    })


def prepare_own_job_requirement(raw_job, recruiter_id, command_id, captured_at):
    """Return deterministic draft A3/A4 values and the exact B1 snapshot."""
    if not isinstance(raw_job, Mapping):
        raise OwnJobMappingError("own job source must be a mapping")
    job_id = _nonblank(raw_job.get("_id"), "job._id")
    recruiter_id = _nonblank(recruiter_id, "recruiter_id")
    command_id = _nonblank(command_id, "command_id")
    source = _validated_source(raw_job, recruiter_id, job_id)
    captured_at = _utc_millisecond(captured_at)
    source_fingerprint = own_job_source_fingerprint(raw_job, recruiter_id, job_id)
    role_id, opportunity_id = deterministic_own_job_ids(recruiter_id, job_id, command_id)
    provenance_ref = f"{OWN_JOB_MAPPING_VERSION}:{source_fingerprint}"

    role = RoleDNA(
        role_dna_id=role_id,
        version=EntityVersion(1),
        status=RoleDNAStatus.DRAFT,
        canonical_title=source["title"],
        created_at=captured_at,
        updated_at=captured_at,
        provenance=RoleFactSource.IMPORTED,
        source_job_id=job_id,
        version_provenance=RoleFactSource.IMPORTED,
        version_provenance_ref=provenance_ref,
    )
    compensation = None
    if source["salary_min"] is not None or source["salary_max"] is not None:
        compensation = CompensationConstraint(
            minimum=source["salary_min"],
            maximum=source["salary_max"],
            currency=source["salary_currency"],
            basis=None,
        )
    opportunity = OpportunitySpecification(
        opportunity_spec_id=opportunity_id,
        version=EntityVersion(1),
        status=OpportunitySpecStatus.DRAFT,
        created_at=captured_at,
        updated_at=captured_at,
        compensation=compensation,
        location=(
            None if source["location"] is None
            else LocationConstraint(locations=(source["location"],), radius_km=None)
        ),
        work_arrangement=None,
        contract_types=None if source["job_type"] is None else (source["job_type"],),
        provenance=OpportunityFactSource.INTERNAL_JOB,
        source_job_id=JobId(job_id),
        source_ref=provenance_ref,
        version_provenance=OpportunityFactSource.INTERNAL_JOB,
        version_provenance_ref=provenance_ref,
    )
    snapshot = StreamRequirementSnapshot(
        role_dna=RoleDNARef(role.role_dna_id, role.version),
        opportunity_spec=OpportunitySpecificationRef(
            opportunity.opportunity_spec_id, opportunity.version,
        ),
        requirement_version=EntityVersion(1),
        captured_at=captured_at,
    )
    return OwnJobPreparation(source_fingerprint, role, opportunity, snapshot)
