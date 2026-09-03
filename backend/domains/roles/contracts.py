"""Roles domain contracts.

Contract-only: defines Role DNA, taxonomy references, and normalization interfaces.
No runtime persistence or business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Protocol

from backend.domains.shared.ids import (
    OccupationTaxonomyId,
    RoleDNAId,
    SkillTaxonomyId,
)
from backend.domains.shared.versioning import EntityVersion, Versioned, VersionedRef


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class RoleDNA:
    """Professional role description — versioned entity.

    Describes the role itself, not the commercial conditions of one opportunity.
    Salary, location, remote policy, contract are NOT Role DNA attributes.
    """
    role_dna_id: RoleDNAId
    version: int
    updated_at: datetime
    updated_by: str  # actor id (recruiter/organization/system)

    # Core role definition
    occupation_code: str                                    # normalized occupation taxonomy code
    occupation_label: str
    role_family: str | None = None                          # e.g., "engineering", "sales", "finance"
    seniority: Literal["junior", "mid", "senior", "lead", "executive"] = "mid"
    hard_skills: list[str] = field(default_factory=list)    # normalized skill codes (must-have)
    secondary_skills: list[str] = field(default_factory=list)  # nice-to-have / transferable
    responsibilities: list[str] = field(default_factory=list)
    experience_requirements: str | None = None              # free-text or structured
    certifications: list[str] = field(default_factory=list)
    management_dimension: bool = False
    language_requirements: list[str] = field(default_factory=list)

    # Provenance / traceability
    source_type: Literal["own_job", "reference_job", "external_job", "natural_language", "manual"] = "manual"
    source_job_id: str | None = None
    source_organization_id: str | None = None
    source_campaign_id: str | None = None

    def to_versioned(self) -> Versioned[RoleDNA]:
        return Versioned(value=self, version=self.version, updated_at=self.updated_at)

    def to_ref(self) -> VersionedRef:
        return VersionedRef(entity_id=self.role_dna_id, version=self.version)


@dataclass(frozen=True, slots=True)
class OccupationTaxonomyRef:
    """Reference to a normalized occupation taxonomy entry."""
    taxonomy_id: OccupationTaxonomyId
    code: str
    label: str
    parent_code: str | None = None
    version: str = "1.0"


@dataclass(frozen=True, slots=True)
class SkillTaxonomyRef:
    """Reference to a normalized skill taxonomy entry."""
    taxonomy_id: SkillTaxonomyId
    code: str
    label: str
    category: str | None = None
    version: str = "1.0"


# --- Normalization contracts (interfaces, no implementation) ---

class RoleNormalizer(Protocol):
    """Contract for normalizing a raw role description into Role DNA.

    Implementations live in later lots (A3+). This defines the input/output shape.
    """

    def normalize(
        self,
        raw_title: str,
        raw_description: str | None,
        raw_requirements: list[str] | None,
        source_context: NormalizationSourceContext,
    ) -> NormalizationResult:
        """Produce a RoleDNA draft from raw inputs."""
        ...


@dataclass(frozen=True, slots=True)
class NormalizationSourceContext:
    """Context for role normalization."""
    source_type: Literal["own_job", "reference_job", "external_job", "natural_language"]
    source_job_id: str | None = None
    source_organization_id: str | None = None
    source_campaign_id: str | None = None
    recruiter_id: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Result of role normalization — may include ambiguities for human review."""
    role_dna_draft: RoleDNA
    confidence: float  # 0.0 - 1.0
    ambiguities: list[str] = field(default_factory=list)      # e.g., "seniority unclear"
    suggested_questions: list[str] = field(default_factory=list)  # for recruiter clarification
    taxonomy_matches: list[OccupationTaxonomyRef] = field(default_factory=list)
    skill_matches: list[SkillTaxonomyRef] = field(default_factory=list)


class OccupationTaxonomy(Protocol):
    """Contract for occupation taxonomy lookup."""

    def lookup_by_code(self, code: str) -> OccupationTaxonomyRef | None:
        ...

    def search(self, query: str, limit: int = 10) -> list[OccupationTaxonomyRef]:
        ...

    def get_children(self, parent_code: str) -> list[OccupationTaxonomyRef]:
        ...


class SkillTaxonomy(Protocol):
    """Contract for skill taxonomy lookup."""

    def lookup_by_code(self, code: str) -> SkillTaxonomyRef | None:
        ...

    def search(self, query: str, limit: int = 20) -> list[SkillTaxonomyRef]:
        ...

    def get_related_skills(self, skill_code: str, limit: int = 10) -> list[SkillTaxonomyRef]:
        ...