"""Typed ID aliases and factory helpers for canonical Talent Stream identifiers."""

from __future__ import annotations

import uuid
from typing import NewType


CandidateId = NewType("CandidateId", str)
RecruiterUserId = NewType("RecruiterUserId", str)
OrganizationId = NewType("OrganizationId", str)
HiringCompanyId = NewType("HiringCompanyId", str)
MandateId = NewType("MandateId", str)
RoleDNAId = NewType("RoleDNAId", str)
OpportunitySpecId = NewType("OpportunitySpecId", str)
StreamId = NewType("StreamId", str)
IntentEventId = NewType("IntentEventId", str)
ContactRequestId = NewType("ContactRequestId", str)
GrantId = NewType("GrantId", str)
DocumentId = NewType("DocumentId", str)


StreamRequirementVersion = NewType("StreamRequirementVersion", str)
OpportunitySpecVersion = NewType("OpportunitySpecVersion", str)
RoleDNAVersion = NewType("RoleDNAVersion", str)


def new_candidate_id() -> CandidateId:
    return CandidateId(uuid.uuid4().hex)


def new_recruiter_user_id() -> RecruiterUserId:
    return RecruiterUserId(uuid.uuid4().hex)


def new_organization_id() -> OrganizationId:
    return OrganizationId(uuid.uuid4().hex)


def new_hiring_company_id() -> HiringCompanyId:
    return HiringCompanyId(uuid.uuid4().hex)


def new_mandate_id() -> MandateId:
    return MandateId(uuid.uuid4().hex)


def new_role_dna_id() -> RoleDNAId:
    return RoleDNAId(uuid.uuid4().hex)


def new_opportunity_spec_id() -> OpportunitySpecId:
    return OpportunitySpecId(uuid.uuid4().hex)


def new_stream_id() -> StreamId:
    return StreamId(uuid.uuid4().hex)


def new_intent_event_id() -> IntentEventId:
    return IntentEventId(uuid.uuid4().hex)


def new_contact_request_id() -> ContactRequestId:
    return ContactRequestId(uuid.uuid4().hex)


def new_grant_id() -> GrantId:
    return GrantId(uuid.uuid4().hex)


def new_document_id() -> DocumentId:
    return DocumentId(uuid.uuid4().hex)


def new_stream_requirement_version() -> StreamRequirementVersion:
    return StreamRequirementVersion(uuid.uuid4().hex)


def new_opportunity_spec_version() -> OpportunitySpecVersion:
    return OpportunitySpecVersion(uuid.uuid4().hex)


def new_role_dna_version() -> RoleDNAVersion:
    return RoleDNAVersion(uuid.uuid4().hex)