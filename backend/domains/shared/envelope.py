"""Generic Event/Command envelope with metadata and actor context.

Contract-only: no runtime dispatch logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, Literal, TypeVar
from uuid import uuid4

from backend.domains.shared.ids import CandidateId, OrganizationId, RecruiterId

T = TypeVar("T")


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Context of the actor initiating a command or producing an event."""
    actor_type: Literal["candidate", "recruiter", "system", "partner"]
    actor_id: str  # CandidateId | RecruiterId | OrganizationId | "system"
    organization_id: OrganizationId | None = None
    mandate_id: str | None = None
    ip_hash: str | None = None
    user_agent_hash: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class Metadata:
    """Standard metadata for domain events and commands."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: int = 1
    occurred_at: datetime = field(default_factory=utcnow)
    actor: ActorContext | None = None
    causation_id: str | None = None  # command/event that caused this
    correlation_id: str | None = None  # groups related events


@dataclass(frozen=True, slots=True)
class DomainEnvelope(Generic[T]):
    """Generic envelope wrapping a domain event or command payload."""
    metadata: Metadata
    payload: T

    @classmethod
    def create(cls, payload: T, actor: ActorContext | None = None, **metadata_kwargs: Any) -> DomainEnvelope[T]:
        metadata = Metadata(actor=actor, **metadata_kwargs)
        return cls(metadata=metadata, payload=payload)