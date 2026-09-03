# Stream Requirement — Composition of Role DNA + Opportunity Specification
# TS-A0-001: Domain Contracts & Business Invariants
# Canonical relationship: Role DNA + Opportunity Specification = Stream Requirement

from typing import Optional
from pydantic import BaseModel, Field
from datetime import datetime
from ..shared.ids import (
    StreamId, RoleDNAId, OpportunitySpecId,
    RoleDNAVersion, OpportunitySpecVersion,
)
from ..shared.versioning import StreamRequirementVersion as SRVersion
from ..roles.role_dna import RoleDNARef
from .opportunity_spec import OpportunitySpecRef


class StreamRequirement(BaseModel):
    """
    Composed Stream Requirement binding Role DNA + Opportunity Specification.
    A Stream binds to a version/snapshot of its Stream Requirement.
    A source job changing later must not silently redefine an existing Stream.
    Updating a Stream requirement is an explicit operation (ARCHITECTURE.md §16).
    """
    stream_id: StreamId
    requirement_version: SRVersion

    # Composed references (frozen at composition time)
    role_dna: RoleDNARef
    opportunity_spec: OpportunitySpecRef

    # Explicit composition metadata
    composed_at: datetime = Field(default_factory=datetime.utcnow)
    composed_by: str  # UserId or system identifier
    composition_reason: Optional[str] = None  # "created", "updated", "rebased"

    class Config:
        frozen = True


class StreamRequirementInput(BaseModel):
    """
    Input for composing a Stream Requirement (contract for A4/B2/later lots).
    A0-001 freezes the input shape; composition logic is A4+.
    """
    role_dna_id: RoleDNAId
    role_dna_version: RoleDNAVersion
    opportunity_spec_id: OpportunitySpecId
    opportunity_spec_version: OpportunitySpecVersion
    composed_by: str
    composition_reason: Optional[str] = None

    class Config:
        frozen = True


class StreamRequirementUpdate(BaseModel):
    """
    Input for updating a Stream Requirement (explicit operation, not silent mutation).
    ARCHITECTURE.md §16: "A source job changing later must not silently redefine an existing Stream.
    Updating a Stream requirement is an explicit operation."
    """
    stream_id: StreamId
    current_requirement_version: SRVersion
    new_role_dna_id: Optional[RoleDNAId] = None
    new_role_dna_version: Optional[RoleDNAVersion] = None
    new_opportunity_spec_id: Optional[OpportunitySpecId] = None
    new_opportunity_spec_version: Optional[OpportunitySpecVersion] = None
    update_reason: str
    updated_by: str

    class Config:
        frozen = True