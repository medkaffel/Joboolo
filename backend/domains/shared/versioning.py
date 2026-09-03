"""Generic version metadata and value objects for domain entities.

Contract-only: no runtime persistence logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, TypeVar


T = TypeVar("T")


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class VersionedRef:
    """Reference to a versioned entity: (entity_id, version)."""
    entity_id: str
    version: int


@dataclass(frozen=True, slots=True)
class Versioned(Generic[T]):
    """A versioned value carrying its entity version."""
    value: T
    version: int
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class StreamRequirementVersion:
    """Snapshot of a Stream Requirement composition."""
    role_dna_ref: VersionedRef
    opportunity_spec_ref: VersionedRef
    composed_at: datetime
    composed_by: str  # actor id (recruiter/organization)
    policy_version: str  # authorization/privacy/source-protection policy version


@dataclass(frozen=True, slots=True)
class EntityVersion:
    """Minimal version metadata for any domain entity."""
    entity_id: str
    version: int
    updated_at: datetime
    updated_by: str