"""Canonical domain contracts for TS-A0-001.

These types define boundaries only. They do not create Mongo collections, alter
existing routes, or authorize recruiter access.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from domains.shared.ids import (
    CandidateId,
    CandidatePreferencesId,
    CandidateProfileId,
    DocumentId,
    GrantId,
    HiringCompanyId,
    MandateId,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import (
    ConsentPolicyVersion,
    EngineVersion,
    EntityVersion,
    PolicyVersion,
)


class DiscoveryMode(str, Enum):
    DISABLED = "disabled"
    COMPATIBLE_OPPORTUNITIES = "compatible_opportunities"
    ASK_BEFORE_REVEAL = "ask_before_reveal"
    ANONYMOUS_ONLY = "anonymous_only"


@dataclass(frozen=True)
class DiscoveryState:
    candidate_id: CandidateId
    mode: DiscoveryMode
    preferences_version: EntityVersion
    updated_at: datetime

    @property
    def enabled(self) -> bool:
        return self.mode is not DiscoveryMode.DISABLED


@dataclass(frozen=True)
class CandidateProfileRef:
    profile_id: CandidateProfileId
    candidate_id: CandidateId
    version: EntityVersion


@dataclass(frozen=True)
class CandidatePreferencesRef:
    preferences_id: CandidatePreferencesId
    candidate_id: CandidateId
    version: EntityVersion


@dataclass(frozen=True)
class RoleDNARef:
    role_dna_id: RoleDNAId
    version: EntityVersion


@dataclass(frozen=True)
class OpportunitySpecificationRef:
    opportunity_spec_id: OpportunitySpecId
    version: EntityVersion


@dataclass(frozen=True)
class StreamRequirementSnapshot:
    role_dna: RoleDNARef
    opportunity_spec: OpportunitySpecificationRef
    requirement_version: EntityVersion
    captured_at: datetime


@dataclass(frozen=True)
class ProfessionalMatchRef:
    candidate_id: CandidateId
    role_dna: RoleDNARef
    candidate_profile_version: EntityVersion
    engine_version: EngineVersion
    computed_at: datetime


@dataclass(frozen=True)
class OpportunityFitRef:
    candidate_id: CandidateId
    opportunity_spec: OpportunitySpecificationRef
    candidate_preferences_version: EntityVersion
    engine_version: EngineVersion
    computed_at: datetime


class GrantScope(str, Enum):
    PROFILE_PREVIEW = "profile_preview"
    IDENTITY = "identity"
    CONTACT = "contact"
    CV = "cv"
    MESSAGING = "messaging"


@dataclass(frozen=True)
class GrantContract:
    grant_id: GrantId
    candidate_id: CandidateId
    grantee_organization_id: OrganizationId
    scopes: Tuple[GrantScope, ...]
    issued_at: datetime
    consent_policy_version: ConsentPolicyVersion
    stream_id: Optional[TalentStreamId] = None
    document_id: Optional[DocumentId] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    def is_active_at(self, now: datetime) -> bool:
        if self.revoked_at is not None and self.revoked_at <= now:
            return False
        if self.expires_at is not None and self.expires_at <= now:
            return False
        return True


@dataclass(frozen=True)
class RecruitingActorContext:
    recruiter_user_id: RecruiterUserId
    requesting_organization_id: OrganizationId
    hiring_company_id: HiringCompanyId
    mandate_id: Optional[MandateId]


@dataclass(frozen=True)
class StreamPolicySnapshot:
    policy_version: PolicyVersion
    evaluated_at: datetime
