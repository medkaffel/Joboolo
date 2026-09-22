"""Strict BSON mapping for the authoritative B10 Contact Request aggregate.

This module performs no Mongo I/O and never repairs or coerces stored data.
PyMongo's UTC-naive BSON datetimes are normalized only while rehydrating a
document; domain inputs remain aware, whole-millisecond timestamps.
"""
from __future__ import annotations

from datetime import datetime, timezone

from bson.int64 import Int64

from domains.shared.ids import (
    CandidateId,
    ContactRequestId,
    HiringCompanyId,
    IdempotencyKey,
    MandateId,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import SchemaVersion
from domains.talent_stream.contact_request_models import (
    ContactRequest,
    ContactRequestState,
)
from domains.talent_stream.contracts import RecruitingActorContext
from domains.trust.contact_governor_models import require_governor_time


CONTACT_REQUEST_REQUIRED_FIELDS = {
    "_id",
    "schema_version",
    "version",
    "state",
    "command_fingerprint",
    "idempotency_key",
    "reservation_id",
    "governor_request_fingerprint",
    "governor_policy_version",
    "anonymous_card_ref",
    "candidate_id",
    "stream_id",
    "generation_id",
    "projection_state_version",
    "stream_version",
    "requirement_version",
    "role_dna_id",
    "role_dna_version",
    "opportunity_spec_id",
    "opportunity_spec_version",
    "recruiter_user_id",
    "requesting_organization_id",
    "hiring_company_id",
    "reservation_activity_at",
    "reservation_expires_at",
    "created_at",
    "handoff_job_id",
}
CONTACT_REQUEST_OPTIONAL_FIELDS = {"mandate_id"}


def _shape(value, required, optional, field):
    if type(value) is not dict:
        raise ValueError(f"{field} must be a BSON object")
    if value.keys() - required - optional:
        raise ValueError(f"{field} has unknown fields")
    if not required <= value.keys():
        raise ValueError(f"{field} is missing required fields")


def _nonblank(value, field):
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")
    return value


def _positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, Int64)) or value < 1:
        raise ValueError(f"{field} must be a positive integer")
    return int(value)


def _storage_time(value, field):
    if type(value) is not datetime:
        raise ValueError(f"{field} must be a datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return require_governor_time(value, field)


def contact_request_to_document(request: ContactRequest) -> dict:
    """Serialize an already-strict domain aggregate without adding payload."""

    if type(request) is not ContactRequest:
        raise ValueError("request must be ContactRequest")
    actor = request.recruiting_actor
    document = {
        "_id": str(request.contact_request_id),
        "schema_version": str(request.schema_version),
        "version": request.version,
        "state": request.state.value,
        "command_fingerprint": request.command_fingerprint,
        "idempotency_key": str(request.idempotency_key),
        "reservation_id": request.reservation_id,
        "governor_request_fingerprint": request.governor_request_fingerprint,
        "governor_policy_version": request.governor_policy_version,
        "anonymous_card_ref": request.anonymous_card_ref,
        "candidate_id": str(request.candidate_id),
        "stream_id": str(request.stream_id),
        "generation_id": request.generation_id,
        "projection_state_version": request.projection_state_version,
        "stream_version": request.stream_version,
        "requirement_version": request.requirement_version,
        "role_dna_id": str(request.role_dna_id),
        "role_dna_version": request.role_dna_version,
        "opportunity_spec_id": str(request.opportunity_spec_id),
        "opportunity_spec_version": request.opportunity_spec_version,
        "recruiter_user_id": str(actor.recruiter_user_id),
        "requesting_organization_id": str(actor.requesting_organization_id),
        "hiring_company_id": str(actor.hiring_company_id),
        "reservation_activity_at": request.reservation_activity_at,
        "reservation_expires_at": request.reservation_expires_at,
        "created_at": request.created_at,
        "handoff_job_id": request.handoff_job_id,
    }
    if actor.mandate_id is not None:
        document["mandate_id"] = str(actor.mandate_id)
    return document


def contact_request_from_document(document: dict) -> ContactRequest:
    """Strictly rehydrate one BSON document through frozen B10.1 contracts."""

    _shape(
        document,
        CONTACT_REQUEST_REQUIRED_FIELDS,
        CONTACT_REQUEST_OPTIONAL_FIELDS,
        "contact request document",
    )
    mandate = None
    if "mandate_id" in document:
        mandate = MandateId(_nonblank(document["mandate_id"], "mandate_id"))
    actor = RecruitingActorContext(
        recruiter_user_id=RecruiterUserId(
            _nonblank(document["recruiter_user_id"], "recruiter_user_id")
        ),
        requesting_organization_id=OrganizationId(
            _nonblank(
                document["requesting_organization_id"],
                "requesting_organization_id",
            )
        ),
        hiring_company_id=HiringCompanyId(
            _nonblank(document["hiring_company_id"], "hiring_company_id")
        ),
        mandate_id=mandate,
    )
    try:
        state = ContactRequestState(_nonblank(document["state"], "state"))
    except ValueError:
        raise ValueError("unsupported contact request state") from None
    return ContactRequest(
        contact_request_id=ContactRequestId(_nonblank(document["_id"], "_id")),
        command_fingerprint=_nonblank(
            document["command_fingerprint"], "command_fingerprint"
        ),
        idempotency_key=IdempotencyKey(
            _nonblank(document["idempotency_key"], "idempotency_key")
        ),
        reservation_id=_nonblank(document["reservation_id"], "reservation_id"),
        governor_request_fingerprint=_nonblank(
            document["governor_request_fingerprint"],
            "governor_request_fingerprint",
        ),
        governor_policy_version=_nonblank(
            document["governor_policy_version"], "governor_policy_version"
        ),
        anonymous_card_ref=_nonblank(
            document["anonymous_card_ref"], "anonymous_card_ref"
        ),
        candidate_id=CandidateId(
            _nonblank(document["candidate_id"], "candidate_id")
        ),
        stream_id=TalentStreamId(_nonblank(document["stream_id"], "stream_id")),
        generation_id=_nonblank(document["generation_id"], "generation_id"),
        projection_state_version=_positive_int(
            document["projection_state_version"], "projection_state_version"
        ),
        stream_version=_positive_int(document["stream_version"], "stream_version"),
        requirement_version=_positive_int(
            document["requirement_version"], "requirement_version"
        ),
        role_dna_id=RoleDNAId(_nonblank(document["role_dna_id"], "role_dna_id")),
        role_dna_version=_positive_int(
            document["role_dna_version"], "role_dna_version"
        ),
        opportunity_spec_id=OpportunitySpecId(
            _nonblank(document["opportunity_spec_id"], "opportunity_spec_id")
        ),
        opportunity_spec_version=_positive_int(
            document["opportunity_spec_version"], "opportunity_spec_version"
        ),
        recruiting_actor=actor,
        reservation_activity_at=_storage_time(
            document["reservation_activity_at"], "reservation_activity_at"
        ),
        reservation_expires_at=_storage_time(
            document["reservation_expires_at"], "reservation_expires_at"
        ),
        created_at=_storage_time(document["created_at"], "created_at"),
        handoff_job_id=_nonblank(document["handoff_job_id"], "handoff_job_id"),
        state=state,
        version=_positive_int(document["version"], "version"),
        schema_version=SchemaVersion(
            _nonblank(document["schema_version"], "schema_version")
        ),
    )


__all__ = [
    "CONTACT_REQUEST_REQUIRED_FIELDS",
    "CONTACT_REQUEST_OPTIONAL_FIELDS",
    "contact_request_to_document",
    "contact_request_from_document",
]
