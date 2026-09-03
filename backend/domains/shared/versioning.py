# Versioning primitives for domain entities
# TS-A0-001: Domain Contracts & Business Invariants
# Provides VersionedRef and Versioned base for snapshot/version binding

from typing import Generic, TypeVar, Protocol
from pydantic import BaseModel, Field
from datetime import datetime
from .ids import (
    ProfileVersion,
    PreferencesVersion,
    RoleDNAVersion,
    OpportunitySpecVersion,
    MatchEngineVersion,
    IntentEngineVersion,
    PolicyVersion,
    ConsentVersion,
    EventSchemaVersion,
)

T = TypeVar("T")


class VersionedRef(BaseModel, Generic[T]):
    """
    Reference to a versioned entity.
    Used to bind Streams, Matches, and Projections to specific snapshots.
    """
    id: str
    version: T
    snapshot_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True


class Versioned(BaseModel, Generic[T]):
    """
    Base for versioned domain entities.
    Authoritative source data carries its version; projections reference versions.
    """
    id: str
    version: T
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True


# Convenience type aliases for common versioned refs
ProfileRef = VersionedRef[ProfileVersion]
PreferencesRef = VersionedRef[PreferencesVersion]
RoleDNARef = VersionedRef[RoleDNAVersion]
OpportunitySpecRef = VersionedRef[OpportunitySpecVersion]
MatchEngineRef = VersionedRef[MatchEngineVersion]
IntentEngineRef = VersionedRef[IntentEngineVersion]
PolicyRef = VersionedRef[PolicyVersion]
ConsentRef = VersionedRef[ConsentVersion]
EventSchemaRef = VersionedRef[EventSchemaVersion]


class StreamRequirementVersion(BaseModel):
    """
    Composite version binding for a Stream Requirement.
    A Stream binds to a specific RoleDNA + OpportunitySpec combination.
    """
    role_dna: RoleDNARef
    opportunity_spec: OpportunitySpecRef
    composed_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True