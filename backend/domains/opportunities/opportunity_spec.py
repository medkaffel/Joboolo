# Opportunity Specification — Commercial conditions of a specific recruiting need
# TS-A0-001: Domain Contracts & Business Invariants
# Versioned entity; distinct from Role DNA (TALENT_STREAM_SPEC.md §6, BUSINESS_RULES.md §4)

from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from ..shared.ids import OpportunitySpecId, OpportunitySpecVersion, RoleDNAId, CompanyId
from ..shared.versioning import Versioned


class ContractType(str, Enum):
    CDI = "CDI"
    CDD = "CDD"
    STAGE = "Stage"
    FREELANCE = "Freelance"
    INTERIM = "Interim"
    TITULAIRE = "Titulaire"


class RemotePolicy(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on_site"
    FLEXIBLE = "flexible"


class RequirementPriority(str, Enum):
    MUST_HAVE = "must_have"
    NICE_TO_HAVE = "nice_to_have"


class OpportunitySpecification(Versioned[OpportunitySpecVersion]):
    """
    Canonical Opportunity Specification describing constraints of ONE specific recruiting need.
    Distinct from Role DNA — Role DNA describes the role, Opportunity Spec describes the opportunity.
    
    (TALENT_STREAM_SPEC.md §6, BUSINESS_RULES.md §4):
    - Opportunity Specification describes the constraints of one specific recruiting need
    - Salary, location, remote policy, contract are Opportunity Spec attributes, NOT universal Role DNA
    - Role DNA + Opportunity Specification = Stream Requirement
    - A Stream binds to a version/snapshot of its Stream Requirement
    - A source job changing later must not silently redefine an existing Stream
    """
    id: OpportunitySpecId
    version: OpportunitySpecVersion

    # Link to Role DNA (separate entity)
    role_dna_id: RoleDNAId
    role_dna_version: str  # RoleDNAVersion at time of composition

    # Commercial/opportunity constraints
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_currency: str = "EUR"
    salary_is_negotiable: bool = True

    location: Optional[str] = None
    location_radius_km: Optional[int] = None
    remote_policy: Optional[RemotePolicy] = None

    contract_type: Optional[ContractType] = None
    schedule: Optional[str] = None  # e.g., "full_time", "part_time", "shift"

    # Company/sector constraints
    hiring_company_id: Optional[CompanyId] = None
    sector_constraints: List[str] = Field(default_factory=list)

    # Requirements with priority
    requirements: List[dict] = Field(default_factory=list)  # {text, priority: RequirementPriority}

    # Target availability
    target_start_date: Optional[datetime] = None
    urgency: Optional[str] = None

    # Confidential recruiting (TALENT_STREAM_SPEC.md §20)
    is_confidential: bool = False
    confidential_reason: Optional[str] = None

    # Source tracking (for audit, not recruiter exposure)
    source_type: Optional[str] = None  # "own_job", "reference_job", "external_url", "natural_language"
    source_job_id: Optional[str] = None
    source_reference: Optional[str] = None

    class Config:
        frozen = True


class OpportunitySpecRef(BaseModel):
    """
    Reference to a specific OpportunitySpec version for Stream binding.
    """
    opportunity_spec_id: OpportunitySpecId
    opportunity_spec_version: OpportunitySpecVersion
    snapshot_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True