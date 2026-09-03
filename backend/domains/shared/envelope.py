# Domain event/envelope primitives
# TS-A0-001: Domain Contracts & Business Invariants
# Base envelope for domain events and commands with metadata

from typing import Generic, TypeVar, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from .ids import (
    CandidateId,
    RecruiterId,
    OrganizationId,
    EventSchemaVersion,
)
from .versioning import PolicyRef

T = TypeVar("T")


class Metadata(BaseModel):
    """
    Cross-cutting metadata for domain events and commands.
    """
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    trace_id: Optional[str] = None
    event_schema_version: EventSchemaVersion
    policy_version: Optional[PolicyRef] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class DomainEnvelope(BaseModel, Generic[T]):
    """
    Generic envelope for domain events and commands.
    Wraps payload with authoritative metadata.
    """
    event_id: str
    event_type: str
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
    payload: T
    metadata: Metadata

    class Config:
        frozen = True


class CommandEnvelope(BaseModel, Generic[T]):
    """
    Generic envelope for domain commands (intent to mutate).
    """
    command_id: str
    command_type: str
    issued_at: datetime = Field(default_factory=datetime.utcnow)
    payload: T
    metadata: Metadata

    class Config:
        frozen = True


# Actor context for authorization decisions
class ActorContext(BaseModel):
    """
    Minimal actor context for policy evaluation.
    Full verification state lives in trust/permissions domains.
    """
    candidate_id: Optional[CandidateId] = None
    recruiter_id: Optional[RecruiterId] = None
    organization_id: Optional[OrganizationId] = None
    mandate_id: Optional[str] = None  # MandateId from trust domain
    is_verified_recruiter: bool = False
    is_verified_organization: bool = False
    is_admin: bool = False