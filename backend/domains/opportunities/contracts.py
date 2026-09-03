"""Opportunities domain contracts.

Contract-only: defines Opportunity Specification, Stream Requirement composition.
No runtime persistence or business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from backend.domains.shared.ids import (
    OpportunitySpecId,
    RoleDNAId,
    StreamRequirementId,
)
from backend.domains.shared.versioning import (
    EntityVersion,
    StreamRequirementVersion,
    Versioned,
    VersionedRef,
)


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class OpportunitySpecification:
    """Constraints of one specific recruiting opportunity — versioned entity.

    Describes the commercial/operational conditions, NOT the professional role.
    Role DNA + Opportunity Specification = Stream Requirement.
    """
    opportunity_spec_id: OpportunitySpecId
    version: int
    updated_at: datetime
    updated_by: str  # actor id (recruiter/organization)

    # Compensation & location
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "EUR"
    salary_type: Literal["annual", "hourly", "daily", "monthly"] = "annual"
    locations: list[str] = field(default_factory=list)       # specific locations
    remote_policy: Literal["remote", "hybrid", "onsite", "flexible"] = "flexible"
    mobility_radius_km: int | None = None

    # Contract & schedule
    contract_type: Literal["permanent", "fixed_term", "contract", "freelance", "apprenticeship", "internship"] = "permanent"
    schedule: Literal["full_time", "part_time", "flexible"] = "full_time"

    # Sector & company constraints
    industry_sectors: list[str] = field(default_factory=list)
    company_size_preference: Literal["startup", "sme", "large", "any"] = "any"
    hiring_company_name: str | None = None                  # for confidential: hidden initially
    hiring_company_id: str | None = None

    # Requirements classification
    must_have_requirements: list[str] = field(default_factory=list)   # free-text or structured codes
    nice_to_have_requirements: list[str] = field(default_factory=list)

    # Availability
    target_start_date: datetime | None = None
    urgency: Literal["low", "normal", "high", "urgent"] = "normal"

    def to_versioned(self) -> Versioned[OpportunitySpecification]:
        return Versioned(value=self, version=self.version, updated_at=self.updated_at)

    def to_ref(self) -> VersionedRef:
        return VersionedRef(entity_id=self.opportunity_spec_id, version=self.version)


@dataclass(frozen=True, slots=True)
class StreamRequirement:
    """Canonical recruiter need: Role DNA + Opportunity Specification — versioned entity.

    A Stream binds to a version/snapshot of its Stream Requirement.
    A source job changing later must not silently redefine an existing Stream.
    """
    stream_requirement_id: StreamRequirementId
    version: int
    updated_at: datetime
    updated_by: str

    role_dna_ref: VersionedRef
    opportunity_spec_ref: VersionedRef

    # Composition metadata
    composed_at: datetime
    composed_by: str
    policy_version: str  # authorization/privacy/source-protection policy version at composition

    def to_versioned(self) -> Versioned[StreamRequirement]:
        return Versioned(value=self, version=self.version, updated_at=self.updated_at)

    def to_ref(self) -> VersionedRef:
        return VersionedRef(entity_id=self.stream_requirement_id, version=self.version)

    def to_snapshot(self) -> StreamRequirementVersion:
        return StreamRequirementVersion(
            role_dna_ref=self.role_dna_ref,
            opportunity_spec_ref=self.opportunity_spec_ref,
            composed_at=self.composed_at,
            composed_by=self.composed_by,
            policy_version=self.policy_version,
        )


# --- Input/Update contracts for later lot consumption ---

@dataclass(frozen=True, slots=True)
class StreamRequirementInput:
    """Input for creating a new Stream Requirement."""
    role_dna_id: RoleDNAId
    opportunity_spec_id: OpportunitySpecId
    composed_by: str
    policy_version: str


@dataclass(frozen=True, slots=True)
class StreamRequirementUpdate:
    """Input for creating a new version of a Stream Requirement (explicit operation)."""
    stream_requirement_id: StreamRequirementId
    new_role_dna_id: RoleDNAId | None = None
    new_opportunity_spec_id: OpportunitySpecId | None = None
    updated_by: str = ""
    policy_version: str = ""
    reason: str = ""