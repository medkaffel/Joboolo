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


@dataclass(frozen=True)
class DiscoveryState:
    """Candidate-controlled Discovery authorization, distinct from search state,
    Intent and Permission.

    Controls are deliberately orthogonal rather than a single mode. A candidate
    may pause active job search while keeping Discovery enabled. Discovery alone
    never authorizes identity, CV, contact or messaging access.
    """

    candidate_id: CandidateId
    enabled: bool
    allow_compatible_opportunities: bool
    ask_before_reveal: bool
    anonymous_only: bool
    preferences_version: EntityVersion
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.enabled and (
            self.allow_compatible_opportunities or self.ask_before_reveal or self.anonymous_only
        ):
            raise ValueError("disabled discovery cannot enable discovery sub-controls")


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

    def __post_init__(self) -> None:
        if not self.scopes:
            raise ValueError("grant requires at least one scope")
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("grant scopes must be unique")
        if GrantScope.CV in self.scopes and self.document_id is None:
            raise ValueError("CV scope requires a specific document_id")
        if self.document_id is not None and GrantScope.CV not in self.scopes:
            raise ValueError("document_id is only valid for a CV-scoped grant")
        if self.expires_at is not None and self.expires_at <= self.issued_at:
            raise ValueError("grant expiry must be after issue time")
        if self.revoked_at is not None and self.revoked_at < self.issued_at:
            raise ValueError("grant revocation cannot predate issue time")

    def is_active_at(self, now: datetime) -> bool:
        """Evaluate temporal validity from current data, never from TTL deletion."""
        if now < self.issued_at:
            return False
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
