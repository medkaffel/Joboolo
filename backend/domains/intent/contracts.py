"""Intent domain contracts: Intent event types, provenance, and dimension definitions.

Contract-only: defines the shape of intent events and dimensions.
No runtime persistence or business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from backend.domains.shared.ids import CandidateId, IntentEventId, RoleDNAId
from backend.domains.shared.envelope import DomainEnvelope, Metadata
from backend.domains.shared.versioning import VersionedRef


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class IntentEventType(str, Enum):
    """Types of intent events — declared vs observed."""
    # Declared intent (explicit candidate action)
    DECLARED_INTEREST = "declared_interest"              # "I'm interested" for a role/opportunity
    SHARED_FAVORITE = "shared_favorite"                  # explicitly shared favorite/interest
    ACCEPTED_INTRODUCTION = "accepted_introduction"      # candidate accepts an introduction
    SUBMITTED_APPLICATION = "submitted_application"      # candidate submits an application

    # Observed intent (behavioral signals)
    JOB_VIEW = "job_view"
    REPEAT_JOB_VIEWS = "repeat_job_views"
    EXTERNAL_REDIRECT_CLICK = "external_redirect_click"  # Joboolo-controlled external click
    ROLE_EXPLORATION = "role_exploration"                # recent exploration of similar roles


class IntentSourceType(str, Enum):
    """Source of the intent signal."""
    JOBOOLO_JOB = "joboolo_job"
    EXTERNAL_JOB = "external_job"
    NATURAL_LANGUAGE = "natural_language"
    TALENT_STREAM = "talent_stream"
    PARTNER_FEED = "partner_feed"


class IntentDimension(str, Enum):
    """Four distinct intent dimensions — kept separate."""
    JOB_INTENT = "job_intent"           # interest in one specific job
    ROLE_INTENT = "role_intent"         # interest in a family/cluster of similar roles
    COMPANY_INTENT = "company_intent"   # interest in one company (not auto-transferable)
    MARKET_INTENT = "market_intent"     # general employment market activity


@dataclass(frozen=True, slots=True)
class IntentEventBase:
    """Base fields for all intent events."""
    event_id: IntentEventId
    candidate_id: CandidateId
    event_type: IntentEventType
    source_type: IntentSourceType
    occurred_at: datetime

    # Provenance (retained internally for source protection/evidence policy)
    job_id: str | None = None
    role_dna_id: RoleDNAId | None = None
    source_organization_id: str | None = None
    source_campaign_id: str | None = None

    # Context
    consent_context: str | None = None       # e.g., "explicit_declared", "implicit_observed"
    privacy_context: str | None = None       # e.g., "public", "authenticated_candidate"
    retention_until: datetime | None = None  # policy-driven retention


@dataclass(frozen=True, slots=True)
class DeclaredIntentEvent(IntentEventBase):
    """Explicit candidate-declared intent."""
    event_type: Literal[
        IntentEventType.DECLARED_INTEREST,
        IntentEventType.SHARED_FAVORITE,
        IntentEventType.ACCEPTED_INTRODUCTION,
        IntentEventType.SUBMITTED_APPLICATION,
    ]
    # Declaration-specific context
    declaration_text: str | None = None
    related_stream_id: str | None = None
    related_contact_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class ObservedIntentEvent(IntentEventBase):
    """Observed behavioral intent signal."""
    event_type: Literal[
        IntentEventType.JOB_VIEW,
        IntentEventType.REPEAT_JOB_VIEWS,
        IntentEventType.EXTERNAL_REDIRECT_CLICK,
        IntentEventType.ROLE_EXPLORATION,
    ]
    # Observation-specific context
    view_duration_seconds: int | None = None
    scroll_depth_pct: int | None = None
    interaction_count: int = 1
    referrer: str | None = None


# Discriminated union for envelope payloads
IntentEvent = DeclaredIntentEvent | ObservedIntentEvent


@dataclass(frozen=True, slots=True)
class IntentEnvelope(DomainEnvelope[IntentEvent]):
    """Envelope for intent events with standard metadata."""
    pass


# --- Intent Aggregates (derived, reconstructible) ---

@dataclass(frozen=True, slots=True)
class RoleIntentSignal:
    """A single signal contributing to Role Intent."""
    role_dna_ref: VersionedRef
    event_ref: VersionedRef  # reference to IntentEvent
    weight: float            # signal strength 0.0 - 1.0
    dimension: IntentDimension = IntentDimension.ROLE_INTENT
    independent_source: bool = False  # true if from independent source (for Independent Signal Rule)


@dataclass(frozen=True, slots=True)
class RoleIntentAggregate:
    """Aggregated Role Intent for a candidate/role cluster — derived, reconstructible."""
    aggregate_id: str  # RoleIntentAggregateId
    candidate_id: CandidateId
    role_cluster_id: str | None = None  # when role clustering is available
    role_dna_refs: list[VersionedRef] = field(default_factory=list)
    signals: list[RoleIntentSignal] = field(default_factory=list)
    confidence: float = 0.0              # aggregated confidence 0.0 - 1.0
    recency_score: float = 0.0           # decayed recency
    independent_signal_count: int = 0    # count of independent sources
    updated_at: datetime = field(default_factory=utcnow)
    intent_engine_version: str = "1.0"


@dataclass(frozen=True, slots=True)
class JobIntentAggregate:
    """Aggregated Job Intent for a specific job — derived, reconstructible."""
    candidate_id: CandidateId
    job_id: str
    events: list[VersionedRef] = field(default_factory=list)
    confidence: float = 0.0
    last_activity_at: datetime | None = None
    intent_engine_version: str = "1.0"


@dataclass(frozen=True, slots=True)
class CompanyIntentAggregate:
    """Aggregated Company Intent — NOT automatically transferable to competitors."""
    candidate_id: CandidateId
    company_id: str
    events: list[VersionedRef] = field(default_factory=list)
    confidence: float = 0.0
    last_activity_at: datetime | None = None
    intent_engine_version: str = "1.0"


@dataclass(frozen=True, slots=True)
class MarketIntentAggregate:
    """Aggregated Market Intent — general employment market activity."""
    candidate_id: CandidateId
    signals: list[VersionedRef] = field(default_factory=list)
    activity_level: Literal["low", "moderate", "high"] = "low"
    last_activity_at: datetime | None = None
    intent_engine_version: str = "1.0"


# --- Independent Signal Rule contract (policy, evaluated in later lots) ---

@dataclass(frozen=True, slots=True)
class IndependentSignalPolicy:
    """Policy configuration for Independent Signal Rule — versioned policy."""
    policy_version: str
    min_independent_sources: int = 2
    min_signal_weight_per_source: float = 0.3
    require_explicit_discovery_or_permission: bool = True
    allow_direct_acceptance_as_independent: bool = True
    cooling_period_days: int | None = None  # Source Protection Window integration