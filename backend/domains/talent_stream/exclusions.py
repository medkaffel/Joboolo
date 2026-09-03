# Candidate Exclusions
# TS-A0-001: Domain Contracts & Business Invariants
# BUSINESS_RULES.md §10: Exclusions apply before recruiter contact/reveal
# Current-employer exclusion is security/privacy rule, not cosmetic preference

from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from ..shared.ids import CandidateId, CompanyId, OrganizationId


class ExclusionScope(str, Enum):
    """
    Scope of exclusion enforcement.
    """
    CONTACT = "contact"           # Block contact request creation
    REVEAL = "reveal"             # Block profile/identity reveal
    CV_ACCESS = "cv_access"       # Block CV access
    ALL = "all"                   # Block all Talent Stream actions


class ExclusionType(str, Enum):
    """
    Types of exclusions.
    BUSINESS_RULES.md §10: Current employer, specific companies, former employers, agencies.
    """
    CURRENT_EMPLOYER = "current_employer"
    SPECIFIC_COMPANY = "specific_company"
    FORMER_EMPLOYER = "former_employer"
    AGENCY = "agency"
    COMPANY_GROUP = "company_group"


class ExclusionCheck(BaseModel):
    """
    Exclusion check result for a specific recruiter/org/company.
    Run BEFORE contact/reveal (BUSINESS_RULES.md §10.4, §11.3).
    Stale projections must NOT bypass newly added exclusions (BUSINESS_RULES.md §10.5).
    """
    candidate_id: CandidateId
    target_recruiter_id: Optional[str] = None
    target_organization_id: Optional[OrganizationId] = None
    target_company_id: Optional[CompanyId] = None
    scope: ExclusionScope
    
    is_excluded: bool
    matched_exclusions: List[ExclusionType] = Field(default_factory=list)
    matched_company_ids: List[CompanyId] = Field(default_factory=list)
    matched_organization_ids: List[OrganizationId] = Field(default_factory=list)
    reason: str
    checked_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True


class CurrentEmployerExclusion(BaseModel):
    """
    Current-employer exclusion — critical security/privacy rule (BUSINESS_RULES.md §10.3).
    Accidental exposure is a critical trust incident and must be auditable (BUSINESS_RULES.md §10.6).
    """
    candidate_id: CandidateId
    company_id: CompanyId
    company_name: Optional[str] = None
    verified: bool = False  # Verified via candidate declaration or trusted source
    declared_at: datetime = Field(default_factory=datetime.utcnow)
    verified_at: Optional[datetime] = None
    source: Literal["candidate_declared", "inferred", "verified"] = "candidate_declared"

    class Config:
        frozen = True


class CandidateExclusions(BaseModel):
    """
    Complete exclusion set for a candidate.
    Used by Contact Governor and permission checks.
    """
    candidate_id: CandidateId
    current_employer: Optional[CurrentEmployerExclusion] = None
    excluded_companies: List[CompanyId] = Field(default_factory=list)
    excluded_former_employers: List[CompanyId] = Field(default_factory=list)
    excluded_agencies: List[OrganizationId] = Field(default_factory=list)
    excluded_company_groups: List[str] = Field(default_factory=list)  # Group identifiers
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True