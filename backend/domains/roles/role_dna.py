# Role DNA — Professional role description (not commercial conditions)
# TS-A0-001: Domain Contracts & Business Invariants
# Versioned entity; Stream Requirement binds to RoleDNA version

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from ..shared.ids import RoleDNAId, RoleDNAVersion
from ..shared.versioning import Versioned


class RoleDNA(Versioned[RoleDNAVersion]):
    """
    Canonical Role DNA describing the professional role itself.
    NOT the commercial conditions of a specific opportunity.
    
    (TALENT_STREAM_SPEC.md §6, BUSINESS_RULES.md §4):
    - Role DNA describes the professional role
    - Salary, location, remote policy, contract are NOT universal Role DNA attributes
    - Role DNA + Opportunity Specification = Stream Requirement
    - A Stream binds to a version/snapshot of its Stream Requirement
    """
    id: RoleDNAId
    version: RoleDNAVersion

    # Canonical role identification
    occupation_code: str  # Normalized occupation taxonomy code
    occupation_label: str
    role_family: Optional[str] = None
    seniority: Optional[str] = None

    # Structured role definition
    hard_skills: List[str] = Field(default_factory=list)
    secondary_skills: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)
    experience_requirements: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    management_dimension: Optional[str] = None
    language_requirements: List[str] = Field(default_factory=list)

    # Embeddings for semantic similarity (versioned separately)
    embedding_vector: Optional[List[float]] = None
    embedding_model_version: Optional[str] = None

    # Source tracking (for audit, not recruiter exposure)
    source_type: Optional[str] = None  # "job", "manual", "llm_derived", "reference_job"
    source_job_id: Optional[str] = None  # JobId if derived from job
    source_reference: Optional[str] = None  # Free-form reference

    class Config:
        frozen = True


class RoleDNARef(BaseModel):
    """
    Reference to a specific RoleDNA version for Stream/ Match binding.
    """
    role_dna_id: RoleDNAId
    role_dna_version: RoleDNAVersion
    snapshot_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True