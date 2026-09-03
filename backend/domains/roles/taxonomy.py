# Occupation & Skill Taxonomy References
# TS-A0-001: Domain Contracts & Business Invariants
# References to external/managed taxonomies — not the taxonomy data itself

from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime
from ..shared.ids import RoleDNAId


class OccupationTaxonomyRef(BaseModel):
    """
    Reference to a normalized occupation taxonomy entry.
    Roles domain owns role normalization; taxonomy may be external (ROME, ISCO, O*NET, custom).
    """
    taxonomy_id: str  # e.g., "ROME", "ISCO", "CUSTOM"
    taxonomy_version: str
    code: str
    label: str
    parent_code: Optional[str] = None
    level: int = 0
    aliases: List[str] = Field(default_factory=list)

    class Config:
        frozen = True


class SkillTaxonomyRef(BaseModel):
    """
    Reference to a normalized skill taxonomy entry.
    """
    taxonomy_id: str  # e.g., "ESCO", "O*NET", "CUSTOM"
    taxonomy_version: str
    code: str
    label: str
    category: Optional[str] = None
    aliases: List[str] = Field(default_factory=list)

    class Config:
        frozen = True


class RoleNormalizationInput(BaseModel):
    """
    Input for role normalization (contract for A3/later lots).
    A0-001 freezes the input shape; normalization logic is A3+.
    """
    raw_title: str
    raw_description: Optional[str] = None
    raw_requirements: List[str] = Field(default_factory=list)
    raw_skills: List[str] = Field(default_factory=list)
    company_context: Optional[str] = None
    industry_hint: Optional[str] = None

    class Config:
        frozen = True


class NormalizedRoleDNA(BaseModel):
    """
    Output of role normalization (contract for A3/later lots).
    A0-001 freezes the output shape; normalization logic is A3+.
    """
    occupation: OccupationTaxonomyRef
    seniority: Optional[str] = None
    hard_skills: List[SkillTaxonomyRef] = Field(default_factory=list)
    secondary_skills: List[SkillTaxonomyRef] = Field(default_factory=list)
    management_dimension: Optional[str] = None
    language_requirements: List[SkillTaxonomyRef] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_codes: List[str] = Field(default_factory=list)

    class Config:
        frozen = True