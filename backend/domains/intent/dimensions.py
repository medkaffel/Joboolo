# Intent Dimensions — Job, Role, Company, Market
# TS-A0-001: Domain Contracts & Business Invariants
# BUSINESS_RULES.md §18: Keep four dimensions separate; Discovery is separate from all four

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from ..shared.ids import CandidateId, JobId, RoleDNAId, CompanyId
from .events import IntentEventType


class JobIntent(BaseModel):
    """
    Interest in ONE specific job.
    Evidence: application, declared interest, repeat views, accepted introduction for that job.
    """
    candidate_id: CandidateId
    job_id: JobId
    intent_events: List[IntentEventType] = Field(default_factory=list)
    strongest_signal: Optional[IntentEventType] = None
    first_signaled_at: Optional[datetime] = None
    last_signaled_at: Optional[datetime] = None
    signal_count: int = 0
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    recency_days: Optional[int] = None

    class Config:
        frozen = True


class RoleIntent(BaseModel):
    """
    Interest in a family/cluster of sufficiently similar roles.
    Principal intent dimension for Cross-Offer Talent Stream (TALENT_STREAM_SPEC.md §8, §17).
    Company Intent must NOT automatically become transferable competitor Role Intent (BUSINESS_RULES.md §6.8).
    """
    candidate_id: CandidateId
    role_cluster_id: Optional[str] = None  # Role Cluster reference (Phase C)
    role_dna_ids: List[RoleDNAId] = Field(default_factory=list)
    intent_events: List[IntentEventType] = Field(default_factory=list)
    independent_sources: int = 0  # Independent Signal Rule (BUSINESS_RULES.md §7)
    first_signaled_at: Optional[datetime] = None
    last_signaled_at: Optional[datetime] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    recency_days: Optional[int] = None
    evidence_summary: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        frozen = True


class CompanyIntent(BaseModel):
    """
    Interest in ONE specific company.
    MUST NOT automatically be transferred to competitors as Role Intent (BUSINESS_RULES.md §6.8, TALENT_STREAM_SPEC.md §8).
    """
    candidate_id: CandidateId
    company_id: CompanyId
    intent_events: List[IntentEventType] = Field(default_factory=list)
    first_signaled_at: Optional[datetime] = None
    last_signaled_at: Optional[datetime] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    recency_days: Optional[int] = None

    class Config:
        frozen = True


class MarketIntent(BaseModel):
    """
    Evidence that candidate is active in the employment market generally.
    General market activity signal, not tied to specific job/role/company.
    """
    candidate_id: CandidateId
    intent_events: List[IntentEventType] = Field(default_factory=list)
    active_job_search: bool = False
    recent_activity_count: int = 0
    first_signaled_at: Optional[datetime] = None
    last_signaled_at: Optional[datetime] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    recency_days: Optional[int] = None

    class Config:
        frozen = True


class IntentAggregate(BaseModel):
    """
    Combined view of all four intent dimensions for a candidate.
    Used for retrieval/ranking (Phase B/C); NOT an authorization source.
    """
    candidate_id: CandidateId
    job_intents: List[JobIntent] = Field(default_factory=list)
    role_intents: List[RoleIntent] = Field(default_factory=list)
    company_intents: List[CompanyIntent] = Field(default_factory=list)
    market_intent: Optional[MarketIntent] = None
    aggregated_at: datetime = Field(default_factory=datetime.utcnow)
    intent_engine_version: str  # IntentEngineVersion

    class Config:
        frozen = True