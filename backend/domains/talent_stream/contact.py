# Contact Request & Lifecycle Events
# TS-A0-001: Domain Contracts & Business Invariants
# Canonical controlled flow (TALENT_STREAM_SPEC.md §12, BUSINESS_RULES.md §11, §14)

from typing import Optional, List, Literal, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from ..shared.ids import (
    StreamId, CandidateId, RecruiterId, OrganizationId, ContactRequestId, GrantId,
    ProfileVersion, PreferencesVersion, RoleDNAVersion, OpportunitySpecVersion,
    MatchEngineVersion, IntentEngineVersion, PolicyVersion,
)
from ..shared.versioning import VersionedRef
from ..profiles.profile import ProfileRef
from ..profiles.preferences import PreferencesRef
from ..roles.role_dna import RoleDNARef
from ..opportunities.opportunity_spec import OpportunitySpecRef


class ContactRequestStatus(str, Enum):
    """
    Contact request lifecycle states.
    TALENT_STREAM_SPEC.md §12: Request -> Candidate Decision -> Grant/Reveal/Messaging
    """
    PENDING = "pending"                 # Recruiter requested, awaiting candidate
    ACCEPTED = "accepted"               # Candidate accepted introduction
    DECLINED = "declined"               # Candidate explicitly declined
    IGNORED = "ignored"                 # Candidate ignored (expired/no response)
    EXPIRED = "expired"                 # Request expired without response
    REVOKED = "revoked"                 # Recruiter withdrew request
    GRANT_ACTIVATED = "grant_activated" # Grant created/activated from acceptance


class ContactLifecycleEventType(str, Enum):
    """
    Contact lifecycle event types for audit trail.
    """
    REQUEST_CREATED = "request_created"
    REQUEST_SENT = "request_sent"           # After Contact Governor approval
    CANDIDATE_NOTIFIED = "candidate_notified"
    CANDIDATE_VIEWED = "candidate_viewed"
    CANDIDATE_ACCEPTED = "candidate_accepted"
    CANDIDATE_DECLINED = "candidate_declined"
    CANDIDATE_IGNORED = "candidate_ignored"
    REQUEST_EXPIRED = "request_expired"
    REQUEST_REVOKED = "request_revoked"
    GRANT_CREATED = "grant_created"
    GRANT_ACTIVATED = "grant_activated"
    GRANT_REVOKED = "grant_revoked"
    PROFILE_REVEALED = "profile_revealed"
    IDENTITY_REVEALED = "identity_revealed"
    CV_GRANTED = "cv_granted"
    MESSAGING_ENABLED = "messaging_enabled"


class ContactLifecycleEvent(BaseModel):
    """
    Immutable audit event for contact request lifecycle.
    """
    event_id: str
    contact_request_id: ContactRequestId
    event_type: ContactLifecycleEventType
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
    actor_type: Literal["recruiter", "candidate", "system", "contact_governor"]
    actor_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        frozen = True


class CandidateDecision(str, Enum):
    """
    Candidate response to a contact request.
    TALENT_STREAM_SPEC.md §12.7: Candidate may accept, decline or ignore.
    BUSINESS_RULES.md §2.9: Declined/ignored must not reveal additional data or punish candidate.
    """
    ACCEPT = "accept"
    DECLINE = "decline"
    IGNORE = "ignore"


class ContactRequest(BaseModel):
    """
    Contact Request — Recruiter invitation for controlled introduction.
    Contact Governor runs BEFORE this is created/sent (BUSINESS_RULES.md §11, TALENT_STREAM_SPEC.md §12.4).
    """
    id: ContactRequestId
    stream_id: StreamId
    
    # Participants
    candidate_id: CandidateId
    recruiter_id: RecruiterId
    organization_id: OrganizationId
    mandate_id: Optional[str] = None  # MandateId from trust domain
    
    # Stream requirement snapshot at request time (for audit/explanation)
    stream_requirement_version: str  # StreamRequirementVersion
    profile_ref: ProfileRef
    preferences_ref: PreferencesRef
    role_dna_ref: RoleDNARef
    opportunity_spec_ref: OpportunitySpecRef
    match_engine_version: MatchEngineVersion
    intent_engine_version: IntentEngineVersion
    policy_version: PolicyVersion
    
    # Match/Fit context for candidate decision (TALENT_STREAM_SPEC.md §12.6)
    professional_match_summary: Dict[str, Any] = Field(default_factory=dict)
    opportunity_fit_summary: Dict[str, Any] = Field(default_factory=dict)
    intent_evidence_summary: Dict[str, Any] = Field(default_factory=dict)
    visibility_level: int = 1  # 0=aggregate, 1=anonymous, 2=profile preview, 3=identity
    
    # Opportunity context for candidate (TALENT_STREAM_SPEC.md §12.6)
    opportunity_context: Dict[str, Any] = Field(default_factory=dict)  # role, location, salary, company (unless confidential)
    
    # Status & timing
    status: ContactRequestStatus = ContactRequestStatus.PENDING
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None
    candidate_responded_at: Optional[datetime] = None
    candidate_decision: Optional[CandidateDecision] = None
    expires_at: Optional[datetime] = None
    
    # Grant linkage
    grant_id: Optional[GrantId] = None
    
    # Audit
    lifecycle_events: List[ContactLifecycleEvent] = Field(default_factory=list)

    class Config:
        frozen = True


class ContactRequestInput(BaseModel):
    """
    Input for creating a contact request (contract for B10/later lots).
    A0-001 freezes the input shape; orchestration logic is B10+.
    Contact Governor MUST run before creation (BUSINESS_RULES.md §11.1).
    """
    stream_id: StreamId
    candidate_id: CandidateId
    recruiter_id: RecruiterId
    organization_id: OrganizationId
    mandate_id: Optional[str] = None
    opportunity_context: Dict[str, Any]
    professional_match_summary: Dict[str, Any]
    opportunity_fit_summary: Dict[str, Any]
    intent_evidence_summary: Dict[str, Any]
    visibility_level: int
    expires_at: Optional[datetime] = None

    class Config:
        frozen = True