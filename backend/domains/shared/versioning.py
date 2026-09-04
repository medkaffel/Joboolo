"""Immutable versioned reference and stream requirement version value objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from .ids import (
    OpportunitySpecId,
    OpportunitySpecVersion,
    RoleDNAId,
    RoleDNAVersion,
    StreamRequirementVersion,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class VersionedRef(Generic[T]):
    """Immutable reference to a versioned entity."""
    id: T
    version: str


@dataclass(frozen=True, slots=True)
class StreamRequirementVersionVO:
    """Immutable value object representing a StreamRequirement version composition."""
    role_dna_ref: VersionedRef[RoleDNAId]
    opportunity_spec_ref: VersionedRef[OpportunitySpecId]
    version: StreamRequirementVersion

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