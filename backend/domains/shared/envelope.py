"""Immutable metadata, envelope, and actor context value objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generic, TypeVar
from uuid import uuid4


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Metadata:
    """Immutable metadata for domain events and envelopes."""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = field(default_factory=lambda: uuid4().hex)
    causation_id: str | None = None
    tags: dict[str, str] = field(default_factory=dict)


ActorId = str


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Immutable actor context for domain operations."""
    actor_id: ActorId
    actor_type: str  # "candidate", "recruiter", "system", etc.
    organization_id: str | None = None
    mandate_id: str | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class DomainEnvelope(Generic[T]):
    """Immutable domain event envelope."""
    event_type: str
    payload: T
    metadata: Metadata
    actor: ActorContext | None = None

    def with_correlation(self, correlation_id: str) -> DomainEnvelope[T]:
        return DomainEnvelope(
            event_type=self.event_type,
            payload=self.payload,
            metadata=Metadata(
                created_at=self.metadata.created_at,
                correlation_id=correlation_id,
                causation_id=self.metadata.correlation_id,
                tags=self.metadata.tags,
            ),
            actor=self.actor,
        )