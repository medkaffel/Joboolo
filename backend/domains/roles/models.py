"""Role DNA v1 contracts. Opportunity-specific constraints deliberately excluded."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from domains.shared.ids import RoleDNAId
from domains.shared.versioning import EntityVersion


class RoleDNAStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class RoleFactSource(str, Enum):
    MANUAL = "manual"
    IMPORTED = "imported"
    SUGGESTED = "suggested"


@dataclass(frozen=True)
class RoleSkill:
    label: str
    source: RoleFactSource
    normalized_code: Optional[str] = None
    normalization_ref: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("role skill label cannot be empty")
        if (self.normalized_code is None) != (self.normalization_ref is None):
            raise ValueError("normalized role skill requires code + normalization_ref")


@dataclass(frozen=True)
class RoleDNA:
    role_dna_id: RoleDNAId
    version: EntityVersion
    status: RoleDNAStatus
    canonical_title: str
    created_at: datetime
    updated_at: datetime
    family_code: Optional[str] = None
    family_label: Optional[str] = None
    aliases: Tuple[str, ...] = ()
    skills: Tuple[RoleSkill, ...] = ()
    capabilities: Tuple[str, ...] = ()
    seniority_band: Optional[str] = None
    experience_band: Optional[str] = None
    certifications: Tuple[str, ...] = ()
    languages: Tuple[str, ...] = ()
    transferable_role_refs: Tuple[RoleDNAId, ...] = ()
    adjacent_role_refs: Tuple[RoleDNAId, ...] = ()
    taxonomy_version: Optional[str] = None
    provenance: RoleFactSource = RoleFactSource.MANUAL
    source_job_id: Optional[str] = None
    version_provenance: Optional[RoleFactSource] = None
    version_provenance_ref: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.canonical_title.strip():
            raise ValueError("canonical_title cannot be empty")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot predate created_at")
        if self.provenance is RoleFactSource.SUGGESTED and not self.source_job_id:
            raise ValueError("suggested Role DNA requires source_job_id provenance")
        if self.version_provenance in {RoleFactSource.IMPORTED, RoleFactSource.SUGGESTED} and not self.version_provenance_ref:
            raise ValueError("imported/suggested Role DNA version requires version_provenance_ref")


@dataclass(frozen=True)
class RoleDNARevision:
    version_provenance: RoleFactSource
    version_provenance_ref: Optional[str] = None
    canonical_title: Optional[str] = None
    family_code: Optional[str] = None
    family_label: Optional[str] = None
    aliases: Optional[Tuple[str, ...]] = None
    skills: Optional[Tuple[RoleSkill, ...]] = None
    capabilities: Optional[Tuple[str, ...]] = None
    seniority_band: Optional[str] = None
    experience_band: Optional[str] = None
    certifications: Optional[Tuple[str, ...]] = None
    languages: Optional[Tuple[str, ...]] = None
    transferable_role_refs: Optional[Tuple[RoleDNAId, ...]] = None
    adjacent_role_refs: Optional[Tuple[RoleDNAId, ...]] = None
    taxonomy_version: Optional[str] = None
    status: Optional[RoleDNAStatus] = None

    def __post_init__(self) -> None:
        if self.version_provenance in {RoleFactSource.IMPORTED, RoleFactSource.SUGGESTED} and not self.version_provenance_ref:
            raise ValueError("imported/suggested revision requires version_provenance_ref")
