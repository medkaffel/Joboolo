# Discovery State — Candidate-controlled permission for recruiter discovery
# TS-A0-001: Domain Contracts & Business Invariants
# CRITICAL: Discovery != Intent — this is a separate permission/preference state

from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from ..shared.ids import CandidateId


class DiscoveryMode(str, Enum):
    """
    Candidate-controlled discovery modes.
    Discovery enablement is NOT an Intent event (BUSINESS_RULES.md §2.8).
    """
    DISABLED = "disabled"
    ENABLED_COMPATIBLE = "enabled_compatible"           # Verified recruiters for compatible opportunities
    ENABLED_ASK_BEFORE_REVEAL = "enabled_ask_before_reveal"  # Ask before reveal/contact
    ANONYMOUS_ONLY = "anonymous_only"                   # Anonymous preview only
    PROFILE_REVEAL_AFTER_ACCEPT = "profile_reveal_after_accept"  # Reveal after acceptance


class DiscoveryState(BaseModel):
    """
    Separate candidate-controlled state for Talent Stream discovery.
    This is a PERMISSION/PREFERENCE state, NOT an Intent event.
    
    Rules (BUSINESS_RULES.md §3, TALENT_STREAM_SPEC.md §5):
    - Discovery != Intent
    - Absence of recent Intent does not mean absence of potential interest
    - "Search paused" and "Discovery enabled" may coexist
    - Refusing/disabling Talent Stream must never reduce chances in submitted applications
    - Talent Stream activation must never be required to apply to a job
    """
    candidate_id: CandidateId
    mode: DiscoveryMode = DiscoveryMode.DISABLED
    
    # Filters for discovery eligibility
    salary_min: Optional[int] = None
    salary_currency: str = "EUR"
    preferred_locations: List[str] = Field(default_factory=list)
    mobility_radius_km: Optional[int] = None
    remote_policy: Optional[str] = None
    contract_types: List[str] = Field(default_factory=list)
    excluded_companies: List[str] = Field(default_factory=list)
    exclude_current_employer: bool = True
    excluded_agencies: List[str] = Field(default_factory=list)
    max_contacts_per_week: Optional[int] = None
    
    # Willingness for similar opportunities (TALENT_STREAM_SPEC.md §10.3)
    allow_similar_opportunities: bool = False
    
    # Status tracking
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    updated_by_candidate: bool = True  # Distinguishes candidate action from system sync

    class Config:
        frozen = True


class DiscoveryPoolEligibility(BaseModel):
    """
    Protocol for determining if a candidate is eligible for the Discovery Pool.
    This is a CONTRACT/PROTOCOL — implementation belongs to later lots (B6).
    A0-001 freezes only the SEMANTIC BOUNDARY: Discovery is separate from Intent.
    """
    candidate_id: CandidateId
    is_eligible: bool
    reason_codes: List[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True


# Intent is explicitly NOT owned by profiles domain
# Intent events live in intent/ domain (ARCHITECTURE.md §4)
# DiscoveryState is the ONLY discovery-related concept in profiles/