"""Domain model for Candidate Professional Profile / Talent Graph v1.

Professional facts live here. Preferences, Discovery, Intent, Permission and CV
access deliberately do not: those belong to separate bounded contexts.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from domains.shared.ids import CandidateId, CandidateProfileId
from domains.shared.versioning import EntityVersion


class FactSource(str, Enum):
    """Origin of a professional fact, not a normalization/transformation state."""

    CANDIDATE_DECLARED = "candidate_declared"
    LEGACY_USER = "legacy_user"
    IMPORTED = "imported"


@dataclass(frozen=True)
class SkillFact:
    name: str
    source: FactSource
    normalized_name: Optional[str] = None
    normalization_ref: Optional[str] = None
    evidence_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("skill name cannot be empty")
        if (self.normalized_name is None) != (self.normalization_ref is None):
            raise ValueError("normalized skill requires both normalized_name and normalization_ref")


@dataclass(frozen=True)
class OccupationFact:
    title: str
    source: FactSource
    normalized_occupation: Optional[str] = None
    normalization_ref: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("occupation title cannot be empty")
        if (self.normalized_occupation is None) != (self.normalization_ref is None):
            raise ValueError(
                "normalized occupation requires both normalized_occupation and normalization_ref"
            )


@dataclass(frozen=True)
class ExperienceFact:
    title: str
    source: FactSource
    employer: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    description: Optional[str] = None


@dataclass(frozen=True)
class EducationFact:
    label: str
    source: FactSource
    institution: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass(frozen=True)
class CertificationFact:
    label: str
    source: FactSource
    issuer: Optional[str] = None


@dataclass(frozen=True)
class LanguageFact:
    language: str
    source: FactSource
    level: Optional[str] = None


@dataclass(frozen=True)
class PortfolioFact:
    label: str
    url: str
    source: FactSource


@dataclass(frozen=True)
class CandidateProfessionalProfile:
    profile_id: CandidateProfileId
    candidate_id: CandidateId
    version: EntityVersion
    created_at: datetime
    updated_at: datetime
    headline: Optional[str] = None
    summary: Optional[str] = None
    current_location: Optional[str] = None
    experience_years: Optional[int] = None
    seniority: Optional[str] = None
    occupations: Tuple[OccupationFact, ...] = ()
    experiences: Tuple[ExperienceFact, ...] = ()
    skills: Tuple[SkillFact, ...] = ()
    certifications: Tuple[CertificationFact, ...] = ()
    languages: Tuple[LanguageFact, ...] = ()
    industries: Tuple[str, ...] = ()
    management_experience: Optional[bool] = None
    education: Tuple[EducationFact, ...] = ()
    portfolio: Tuple[PortfolioFact, ...] = ()

    def __post_init__(self) -> None:
        if self.experience_years is not None and self.experience_years < 0:
            raise ValueError("experience_years cannot be negative")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot predate created_at")


@dataclass(frozen=True)
class CandidateProfilePatch:
    """Partial mutation of professional facts only."""

    headline: Optional[str] = None
    summary: Optional[str] = None
    current_location: Optional[str] = None
    experience_years: Optional[int] = None
    seniority: Optional[str] = None
    occupations: Optional[Tuple[OccupationFact, ...]] = None
    experiences: Optional[Tuple[ExperienceFact, ...]] = None
    skills: Optional[Tuple[SkillFact, ...]] = None
    certifications: Optional[Tuple[CertificationFact, ...]] = None
    languages: Optional[Tuple[LanguageFact, ...]] = None
    industries: Optional[Tuple[str, ...]] = None
    management_experience: Optional[bool] = None
    education: Optional[Tuple[EducationFact, ...]] = None
    portfolio: Optional[Tuple[PortfolioFact, ...]] = None

    def __post_init__(self) -> None:
        if self.experience_years is not None and self.experience_years < 0:
            raise ValueError("experience_years cannot be negative")
