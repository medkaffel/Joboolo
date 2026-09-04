"""IntentEvent types, dimensions, provenance, and minimal event shape."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from ..shared.ids import IntentEventId, CandidateId, OpportunitySpecId, RoleDNAId
from ..shared.envelope import Metadata


class IntentEventType(str, Enum):
    """Allowed intent event types - explicitly restricted list."""
    DECLARED_INTEREST = "declared_interest"
    SHARED_FAVORITE = "shared_favorite"
    SUBMITTED_APPLICATION = "submitted_application"
    JOB_VIEW = "job_view"
    REPEAT_JOB_VIEW = "repeat_job_view"
    EXTERNAL_REDIRECT_CLICK = "external_redirect_click"
    ROLE_EXPLORATION = "role_exploration"

    # FORBIDDEN: ACCEPTED_INTRODUCTION, DECLINED_INTRODUCTION as Intent
    # FORBIDDEN: any Intent aggregate types


class IntentDimension(str, Enum):
    """Four intent dimensions."""
    ROLE = "role"
    JOB = "job"
    COMPANY = "company"
    MARKET = "market"


@dataclass(frozen=True, slots=True)
class IntentProvenance:
    """Immutable provenance metadata for an intent event."""
    source: str  # e.g., "candidate_portal", "recruiter_invitation", "external_job_board"
    channel: str | None = None  # e.g., "organic", "paid", "referral"
    referrer_url: str | None = None
    utm_params: dict[str, str] = field(default_factory=dict)
    session_id: str | None = None
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(frozen=True, slots=True)
class IntentEvent:
    """Minimal immutable intent event shape - no aggregates, no policies, no algorithms."""
    id: IntentEventId
    event_type: IntentEventType
    dimension: IntentDimension
    candidate_id: CandidateId
    provenance: IntentProvenance
    # Polymorphic payload - minimal required fields per event type
    opportunity_spec_id: OpportunitySpecId | None = None
    role_dna_id: RoleDNAId | None = None
    company_id: str | None = None
    market_segment: str | None = None
    signal_strength: float = 1.0  # Raw signal, NOT a weighted score
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Metadata = field(default_factory=Metadata)

    # FORBIDDEN: any Intent aggregate (RoleIntentAggregate, JobIntentAggregate, etc.)
    # FORBIDDEN: IndependentSignalPolicy
    # FORBIDDEN: weights/confidence/recency algorithms
    # FORBIDDEN: any numeric threshold/default policy
    # Discovery is not an Intent event