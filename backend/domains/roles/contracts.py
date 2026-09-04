"""Minimal RoleDNA shape and taxonomy reference value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..shared.ids import RoleDNAId, RoleDNAVersion
from ..shared.versioning import VersionedRef
from ..shared.envelope import Metadata


__all__ = [
    "TaxonomyRef",
    "TaxonomyRefs",
    "RoleDNA",
    "RoleDNAId",
    "RoleDNAVersion",
]


@dataclass(frozen=True, slots=True)
class TaxonomyRef:
    """Immutable taxonomy reference."""
    taxonomy: str  # e.g., "ESCO", "O*NET", "ROME"
    code: str
    label: str
    version: str = "latest"


@dataclass(frozen=True, slots=True)
class TaxonomyRefs:
    """Collection of taxonomy references for a role."""
    primary: TaxonomyRef
    alternatives: tuple[TaxonomyRef, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class RoleDNA:
    """Minimal RoleDNA shape - no normalization service, no similarity/cluster contracts."""
    id: RoleDNAId
    version: RoleDNAVersion
    title: str
    description: str
    taxonomy_refs: TaxonomyRefs
    required_skills: tuple[str, ...] = field(default_factory=tuple)
    preferred_skills: tuple[str, ...] = field(default_factory=tuple)
    experience_level: str | None = None  # e.g., "junior", "senior", "lead"
    education_level: str | None = None
    metadata: Metadata = field(default_factory=Metadata)

    # NO normalization service/protocol, NO similarity/cluster contracts