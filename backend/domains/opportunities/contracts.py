"""Minimal OpportunitySpecification and StreamRequirement contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ..shared.ids import (
    HiringCompanyId,
    MandateId,
    OpportunitySpecId,
    OpportunitySpecVersion,
    StreamRequirementVersion,
)
from ..shared.versioning import StreamRequirementVersionVO, VersionedRef
from ..shared.envelope import Metadata
from ..roles.contracts import RoleDNA, RoleDNAId, RoleDNAVersion, TaxonomyRefs, TaxonomyRef


@dataclass(frozen=True, slots=True)
class OpportunitySpecification:
    """Minimal OpportunitySpecification shape - no create/update commands/services."""
    id: OpportunitySpecId
    version: OpportunitySpecVersion
    hiring_company_id: HiringCompanyId
    mandate_id: MandateId | None = None
    title: str = ""
    description: str = ""
    location: str | None = None
    remote_policy: str | None = None  # "remote", "hybrid", "onsite"
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "EUR"
    employment_type: str | None = None  # "full_time", "part_time", "contract"
    experience_level: str | None = None
    required_skills: tuple[str, ...] = field(default_factory=tuple)
    preferred_skills: tuple[str, ...] = field(default_factory=tuple)
    taxonomy_refs: TaxonomyRefs = field(default_factory=lambda: TaxonomyRefs(
        primary=TaxonomyRef(taxonomy="", code="", label="")
    ))
    is_active: bool = True
    published_at: datetime | None = None
    expires_at: datetime | None = None
    metadata: Metadata = field(default_factory=Metadata)

    # No create/update commands/services


@dataclass(frozen=True, slots=True)
class StreamRequirement:
    """StreamRequirement composed of versioned RoleDNA and OpportunitySpec refs."""
    version: StreamRequirementVersion
    role_dna_ref: VersionedRef[RoleDNAId]
    opportunity_spec_ref: VersionedRef[OpportunitySpecId]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Metadata = field(default_factory=Metadata)

    @property
    def role_dna_id(self) -> RoleDNAId:
        return self.role_dna_ref.id

    @property
    def role_dna_version(self) -> RoleDNAVersion:
        return RoleDNAVersion(self.role_dna_ref.version)

    @property
    def opportunity_spec_id(self) -> OpportunitySpecId:
        return self.opportunity_spec_ref.id

    @property
    def opportunity_spec_version(self) -> OpportunitySpecVersion:
        return OpportunitySpecVersion(self.opportunity_spec_ref.version)