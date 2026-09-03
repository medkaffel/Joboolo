# Candidate Professional Profile — Authoritative professional facts
# TS-A0-001: Domain Contracts & Business Invariants
# Versioned entity; projections reference ProfileVersion

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from ..shared.ids import CandidateId, ProfileVersion
from ..shared.versioning import Versioned


class ProfessionalProfile(Versioned[ProfileVersion]):
    """
    Canonical professional profile for matching.
    Distinct from user identity, CV documents, and preferences.
    """
    candidate_id: CandidateId
    version: ProfileVersion

    # Normalized professional facts
    occupations: List[str] = Field(default_factory=list)  # Normalized occupation codes
    role_history: List[Dict[str, Any]] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    skill_evidence: Dict[str, Any] = Field(default_factory=dict)
    seniority_level: Optional[str] = None
    experience_years: Optional[int] = None
    certifications: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    industry_exposure: List[str] = Field(default_factory=list)
    management_experience: bool = False
    education: List[Dict[str, Any]] = Field(default_factory=list)
    portfolio_items: List[Dict[str, Any]] = Field(default_factory=list)

    # Enrichment metadata
    last_enriched_at: Optional[datetime] = None
    enrichment_version: Optional[str] = None

    class Config:
        frozen = True


class ProfileRef(BaseModel):
    """
    Reference to a specific profile version for Match/Stream binding.
    """
    candidate_id: CandidateId
    profile_version: ProfileVersion
    snapshot_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True