# Intent Event Contracts & Provenance
# TS-A0-001: Domain Contracts & Business Invariants
# ARCHITECTURE.md §13: CPC/billing click events and candidate-intent events are separate domains

from typing import Optional, Literal, Dict, Any, List
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from ..shared.ids import (
    CandidateId, JobId, RoleDNAId, IntentEventId,
    CompanyId, OrganizationId, EventSchemaVersion,
)
from ..shared.versioning import VersionedRef
from ..shared.envelope import Metadata


class IntentEventType(str, Enum):
    """
    Canonical intent event types.
    Discovery enablement is NOT an intent event (BUSINESS_RULES.md §2.8, TALENT_STREAM_SPEC.md §8).
    """
    # Declared intent (explicit candidate action)
    DECLARED_JOB_INTEREST = "declared_job_interest"           # "I'm interested" for a specific job
    DECLARED_ROLE_INTEREST = "declared_role_interest"         # Explicit interest in role family/cluster
    DECLARED_COMPANY_INTEREST = "declared_company_interest"   # Explicit interest in a company
    SHARED_FAVORITE = "shared_favorite"                       # Explicitly shared favorite/interest
    ACCEPTED_INTRODUCTION = "accepted_introduction"           # Candidate accepted a contact request
    SUBMITTED_APPLICATION = "submitted_application"           # Full application submitted

    # Observed intent (behavioral signals)
    JOB_VIEW = "job_view"                                     # Job page view
    REPEAT_JOB_VIEWS = "repeat_job_views"                     # Multiple views of same job
    EXTERNAL_CLICK = "external_click"                         # Joboolo-controlled external redirect click
    ROLE_EXPLORATION = "role_exploration"                     # Exploration of several similar roles
    SAVED_JOB = "saved_job"                                   # Private save (NOT sharing consent per BUSINESS_RULES.md §2.1)


class IntentSourceType(str, Enum):
    """
    Source of the intent signal for provenance tracking.
    Internal use only — never exposed as competitor intelligence (BUSINESS_RULES.md §6.3, §6.5).
    """
    JOBOOLO_JOB = "joboolo_job"                               # Job on Joboolo platform
    REFERENCE_JOB = "reference_job"                           # Another allowed Joboolo job used as model
    EXTERNAL_URL = "external_url"                             # External job URL (later phase)
    NATURAL_LANGUAGE = "natural_language"                     # Recruiter free-text need
    CANDIDATE_ACTION = "candidate_action"                     # Direct candidate UI action
    SYSTEM_INFERRED = "system_inferred"                       # System aggregation/inference


class IntentEventProvenance(BaseModel):
    """
    Provenance metadata for intent events.
    Retained internally for source-protection/evidence policy (ARCHITECTURE.md §13).
    MUST NEVER become recruiter-visible competitor intelligence.
    """
    source_type: IntentSourceType
    source_job_id: Optional[JobId] = None
    source_role_dna_id: Optional[RoleDNAId] = None
    source_organization_id: Optional[OrganizationId] = None  # Source company/org if known
    source_campaign_id: Optional[str] = None                 # Campaign if paid/organic context
    consent_context: Optional[str] = None                    # Consent text version if declared
    privacy_context: Optional[str] = None                    # Privacy settings at event time
    attribution_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    class Config:
        frozen = True


class IntentEvent(BaseModel):
    """
    Base canonical intent event envelope.
    ARCHITECTURE.md §13: Intent event envelope conceptually supports:
    event_id, schema_version, candidate_id, event_type, occurred_at, job_id, role_dna_id,
    source_type, source_organization_id, source_campaign_id, consent_context, privacy_context, retention_until, created_at
    """
    event_id: IntentEventId
    schema_version: EventSchemaVersion
    candidate_id: CandidateId
    event_type: IntentEventType
    occurred_at: datetime
    
    # Optional context links
    job_id: Optional[JobId] = None
    role_dna_id: Optional[RoleDNAId] = None
    
    # Provenance (internal only)
    provenance: IntentEventProvenance
    
    # Retention
    retention_until: Optional[datetime] = None
    
    # Audit
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True


class DeclaredIntentEvent(IntentEvent):
    """
    Explicitly declared intent by candidate.
    High confidence; candidate actively signaled interest.
    """
    event_type: Literal[
        IntentEventType.DECLARED_JOB_INTEREST,
        IntentEventType.DECLARED_ROLE_INTEREST,
        IntentEventType.DECLARED_COMPANY_INTEREST,
        IntentEventType.SHARED_FAVORITE,
        IntentEventType.ACCEPTED_INTRODUCTION,
        IntentEventType.SUBMITTED_APPLICATION,
    ]
    
    # Declared intent carries explicit candidate consent context
    consent_version: Optional[str] = None  # ConsentVersion reference
    
    class Config:
        frozen = True


class ObservedIntentEvent(IntentEvent):
    """
    Observed/inferred intent from candidate behavior.
    Probabilistic — must not be presented as certain psychological truth (BUSINESS_RULES.md §6.9).
    Recruiter-facing language: "recent activity/interest on similar roles" (TALENT_STREAM_SPEC.md §8).
    """
    event_type: Literal[
        IntentEventType.JOB_VIEW,
        IntentEventType.REPEAT_JOB_VIEWS,
        IntentEventType.EXTERNAL_CLICK,
        IntentEventType.ROLE_EXPLORATION,
        IntentEventType.SAVED_JOB,
    ]
    
    # Observed signals may support ranking/aggregation but do not auto-grant access (TALENT_STREAM_SPEC.md §8)
    signal_strength: float = Field(default=0.5, ge=0.0, le=1.0)
    
    class Config:
        frozen = True