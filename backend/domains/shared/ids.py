# Generic ID types using NewType for static type separation
# TS-A0-001: Domain Contracts & Business Invariants
# These provide compile-time separation; runtime they remain str/UUID

from typing import NewType
import uuid

# Core entity IDs
CandidateId = NewType("CandidateId", str)
CompanyId = NewType("CompanyId", str)
OrganizationId = NewType("OrganizationId", str)
RecruiterId = NewType("RecruiterId", str)
JobId = NewType("JobId", str)

# Role & Opportunity IDs
RoleDNAId = NewType("RoleDNAId", str)
OpportunitySpecId = NewType("OpportunitySpecId", str)
StreamId = NewType("StreamId", str)

# Intent & Contact IDs
IntentEventId = NewType("IntentEventId", str)
ContactRequestId = NewType("ContactRequestId", str)
GrantId = NewType("GrantId", str)

# Mandate & Recruiting
MandateId = NewType("MandateId", str)

# Version types (semantic version identifiers)
ProfileVersion = NewType("ProfileVersion", str)
PreferencesVersion = NewType("PreferencesVersion", str)
RoleDNAVersion = NewType("RoleDNAVersion", str)
OpportunitySpecVersion = NewType("OpportunitySpecVersion", str)
MatchEngineVersion = NewType("MatchEngineVersion", str)
IntentEngineVersion = NewType("IntentEngineVersion", str)
PolicyVersion = NewType("PolicyVersion", str)
ConsentVersion = NewType("ConsentVersion", str)
EventSchemaVersion = NewType("EventSchemaVersion", str)


def new_candidate_id() -> CandidateId:
    return CandidateId(str(uuid.uuid4()))


def new_company_id() -> CompanyId:
    return CompanyId(str(uuid.uuid4()))


def new_organization_id() -> OrganizationId:
    return OrganizationId(str(uuid.uuid4()))


def new_recruiter_id() -> RecruiterId:
    return RecruiterId(str(uuid.uuid4()))


def new_job_id() -> JobId:
    return JobId(str(uuid.uuid4()))


def new_role_dna_id() -> RoleDNAId:
    return RoleDNAId(str(uuid.uuid4()))


def new_opportunity_spec_id() -> OpportunitySpecId:
    return OpportunitySpecId(str(uuid.uuid4()))


def new_stream_id() -> StreamId:
    return StreamId(str(uuid.uuid4()))


def new_intent_event_id() -> IntentEventId:
    return IntentEventId(str(uuid.uuid4()))


def new_contact_request_id() -> ContactRequestId:
    return ContactRequestId(str(uuid.uuid4()))


def new_grant_id() -> GrantId:
    return GrantId(str(uuid.uuid4()))


def new_mandate_id() -> MandateId:
    return MandateId(str(uuid.uuid4()))


def new_profile_version() -> ProfileVersion:
    return ProfileVersion(str(uuid.uuid4()))


def new_preferences_version() -> PreferencesVersion:
    return PreferencesVersion(str(uuid.uuid4()))


def new_role_dna_version() -> RoleDNAVersion:
    return RoleDNAVersion(str(uuid.uuid4()))


def new_opportunity_spec_version() -> OpportunitySpecVersion:
    return OpportunitySpecVersion(str(uuid.uuid4()))


def new_match_engine_version() -> MatchEngineVersion:
    return MatchEngineVersion(str(uuid.uuid4()))


def new_intent_engine_version() -> IntentEngineVersion:
    return IntentEngineVersion(str(uuid.uuid4()))


def new_policy_version() -> PolicyVersion:
    return PolicyVersion(str(uuid.uuid4()))


def new_consent_version() -> ConsentVersion:
    return ConsentVersion(str(uuid.uuid4()))


def new_event_schema_version() -> EventSchemaVersion:
    return EventSchemaVersion(str(uuid.uuid4()))