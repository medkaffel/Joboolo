"""Typed ID definitions for Talent Stream domains.

Uses typing.NewType for static distinction only — no runtime protection claimed.
"""
from __future__ import annotations

import uuid
from typing import NewType

CandidateId = NewType("CandidateId", str)
RecruiterId = NewType("RecruiterId", str)
OrganizationId = NewType("OrganizationId", str)
HiringCompanyId = NewType("HiringCompanyId", str)
MandateId = NewType("MandateId", str)
ProfileId = NewType("ProfileId", str)
PreferencesId = NewType("PreferencesId", str)
DiscoveryStateId = NewType("DiscoveryStateId", str)
RoleDNAId = NewType("RoleDNAId", str)
OccupationTaxonomyId = NewType("OccupationTaxonomyId", str)
SkillTaxonomyId = NewType("SkillTaxonomyId", str)
OpportunitySpecId = NewType("OpportunitySpecId", str)
StreamRequirementId = NewType("StreamRequirementId", str)
StreamId = NewType("StreamId", str)
ContactRequestId = NewType("ContactRequestId", str)
GrantId = NewType("GrantId", str)
IntentEventId = NewType("IntentEventId", str)
RoleIntentAggregateId = NewType("RoleIntentAggregateId", str)
MatchEngineVersion = NewType("MatchEngineVersion", str)
IntentEngineVersion = NewType("IntentEngineVersion", str)
PolicyVersion = NewType("PolicyVersion", str)
PermissionSnapshotId = NewType("PermissionSnapshotId", str)
TrustSnapshotId = NewType("TrustSnapshotId", str)
SourceProtectionRecordId = NewType("SourceProtectionRecordId", str)


def new_id() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def candidate_id() -> CandidateId:
    return CandidateId(new_id())


def recruiter_id() -> RecruiterId:
    return RecruiterId(new_id())


def organization_id() -> OrganizationId:
    return OrganizationId(new_id())


def hiring_company_id() -> HiringCompanyId:
    return HiringCompanyId(new_id())


def mandate_id() -> MandateId:
    return MandateId(new_id())


def profile_id() -> ProfileId:
    return ProfileId(new_id())


def preferences_id() -> PreferencesId:
    return PreferencesId(new_id())


def discovery_state_id() -> DiscoveryStateId:
    return DiscoveryStateId(new_id())


def role_dna_id() -> RoleDNAId:
    return RoleDNAId(new_id())


def occupation_taxonomy_id() -> OccupationTaxonomyId:
    return OccupationTaxonomyId(new_id())


def skill_taxonomy_id() -> SkillTaxonomyId:
    return SkillTaxonomyId(new_id())


def opportunity_spec_id() -> OpportunitySpecId:
    return OpportunitySpecId(new_id())


def stream_requirement_id() -> StreamRequirementId:
    return StreamRequirementId(new_id())


def stream_id() -> StreamId:
    return StreamId(new_id())


def contact_request_id() -> ContactRequestId:
    return ContactRequestId(new_id())


def grant_id() -> GrantId:
    return GrantId(new_id())


def intent_event_id() -> IntentEventId:
    return IntentEventId(new_id())


def role_intent_aggregate_id() -> RoleIntentAggregateId:
    return RoleIntentAggregateId(new_id())


def match_engine_version(v: str) -> MatchEngineVersion:
    return MatchEngineVersion(v)


def intent_engine_version(v: str) -> IntentEngineVersion:
    return IntentEngineVersion(v)


def policy_version(v: str) -> PolicyVersion:
    return PolicyVersion(v)


def permission_snapshot_id() -> PermissionSnapshotId:
    return PermissionSnapshotId(new_id())


def trust_snapshot_id() -> TrustSnapshotId:
    return TrustSnapshotId(new_id())


def source_protection_record_id() -> SourceProtectionRecordId:
    return SourceProtectionRecordId(new_id())