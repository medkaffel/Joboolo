# CV Access & Talent Stream CV Grant
# TS-A0-001: Domain Contracts & Business Invariants
# BUSINESS_RULES.md §13: Preserve strict document ACL; add only active scoped Talent Stream CV-grant path
# Architecture Review Amendment: Use TALENT_STREAM_CV_GRANT (not generic TALENT_STREAM_GRANT)

from typing import Optional, Literal, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from ..shared.ids import (
    CandidateId, RecruiterId, OrganizationId, GrantId, ContactRequestId,
    ConsentVersion, PolicyVersion,
)


class CVGrantReason(str, Enum):
    """
    Reason for CV grant creation.
    TALENT_STREAM_CV_GRANT is explicit and scope-specific (Architecture Review Amendment).
    """
    TALENT_STREAM_CV_GRANT = "talent_stream_cv_grant"  # From accepted Talent Stream introduction
    APPLICATION_CV_GRANT = "application_cv_grant"       # Existing application workflow
    CANDIDATE_DIRECT_SHARE = "candidate_direct_share"   # Candidate explicitly shares CV


class CVGrantScope(str, Enum):
    """
    Scope of CV grant — which document, for whom, for what purpose.
    BUSINESS_RULES.md §13.7: CV grant is scoped to candidate/document/recruiter/org/Stream/purpose.
    """
    SPECIFIC_CV_STREAM = "specific_cv_stream"           # Specific CV for specific Stream
    SPECIFIC_CV_RECRUITER = "specific_cv_recruiter"     # Specific CV for specific recruiter
    SPECIFIC_CV_ORG = "specific_cv_org"                 # Specific CV for organization


class TalentStreamCVGrant(BaseModel):
    """
    Active scoped Talent Stream CV Grant.
    BUSINESS_RULES.md §13: ALLOW CV IF owner OR admin OR exact authorized application OR active scoped Talent Stream CV grant.
    NEVER introduce broad `if employer: allow` (BUSINESS_RULES.md §13.6).
    Profile access != Identity access != CV access (BUSINESS_RULES.md §12.5, §12.6, TALENT_STREAM_SPEC.md §11).
    """
    id: GrantId
    grant_reason: CVGrantReason = CVGrantReason.TALENT_STREAM_CV_GRANT
    
    # Scope
    candidate_id: CandidateId
    cv_document_id: str  # Specific CV document reference
    scope: CVGrantScope
    
    # Recruiter/Org context
    recruiter_id: Optional[RecruiterId] = None
    organization_id: OrganizationId
    mandate_id: Optional[str] = None
    stream_id: Optional[str] = None  # StreamId
    contact_request_id: Optional[ContactRequestId] = None
    
    # Authorization metadata
    consent_version: Optional[ConsentVersion] = None
    policy_version: PolicyVersion
    
    # Lifecycle
    granted_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    revoked_reason: Optional[str] = None
    
    # Current status (derived, not authoritative)
    is_active: bool = True
    
    class Config:
        frozen = True


class CVAccessRequest(BaseModel):
    """
    Request to access a candidate's CV.
    Current authorization MUST be checked at action time (BUSINESS_RULES.md §14).
    Cached projection is NOT authorization source of truth (BUSINESS_RULES.md §14.1).
    """
    cv_document_id: str
    candidate_id: CandidateId
    requester_id: str  # RecruiterId or UserId
    requester_type: Literal["recruiter", "admin", "candidate_owner", "system"]
    organization_id: Optional[OrganizationId] = None
    mandate_id: Optional[str] = None
    stream_id: Optional[str] = None
    contact_request_id: Optional[ContactRequestId] = None
    purpose: str
    requested_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True


class CVAccessDecision(BaseModel):
    """
    CV access authorization decision.
    Must evaluate CURRENT state: grant status, expiry, revocation, exclusions.
    """
    request: CVAccessRequest
    allowed: bool
    reason: str
    grant_id: Optional[GrantId] = None
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)
    policy_version: PolicyVersion

    class Config:
        frozen = True