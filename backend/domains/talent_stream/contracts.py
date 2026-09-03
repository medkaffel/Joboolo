"""Talent Stream domain contracts.

Contract-only: defines Stream aggregate, candidate projections, contact requests, grants.
No runtime persistence or business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from backend.domains.shared.ids import (
    CandidateId,
    ContactRequestId,
    GrantId,
    OrganizationId,
    RecruiterId,
    StreamId,
    StreamRequirementId,
)
from backend.domains.shared.versioning import VersionedRef


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class StreamStatus(str, Enum):
    """Stream lifecycle status."""
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"
    ARCHIVED = "archived"


class StreamSourceType(str, Enum):
    """Source of the Stream Requirement."""
    OWN_JOB = "own_job"
    REFERENCE_JOB = "reference_job"
    EXTERNAL_JOB = "external_job"
    NATURAL_LANGUAGE = "natural_language"


@dataclass(frozen=True, slots=True)
class TalentStream:
    """Stream aggregate root — binds to a versioned Stream Requirement."""
    # Required fields first
    stream_id: StreamId
    stream_requirement_ref: VersionedRef
    recruiter_id: RecruiterId
    organization_id: OrganizationId

    # Optional fields with defaults
    status: StreamStatus = StreamStatus.DRAFT
    hiring_company_id: str | None = None
    mandate_id: str | None = None
    source_type: StreamSourceType = StreamSourceType.OWN_JOB
    source_job_id: str | None = None
    source_organization_id: str | None = None

    # Configuration
    breadth_policy: Literal["precise", "balanced", "exploratory"] = "balanced"
    max_candidates: int = 100
    auto_refresh: bool = True

    # Versioning / audit
    version: int = 1
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    updated_by: str = ""

    def to_ref(self) -> VersionedRef:
        return VersionedRef(entity_id=self.stream_id, version=self.version)


class TalentCategory(str, Enum):
    """Conceptual talent categories for recruiter UX (not authorization)."""
    APPLICANTS = "applicants"
    WARM_TALENTS = "warm_talents"
    POTENTIAL_TALENTS = "potential_talents"


class VisibilityLevel(str, Enum):
    """Progressive reveal levels."""
    MARKET_AGGREGATE = "market_aggregate"
    ANONYMOUS_TALENT = "anonymous_talent"
    PROFILE_PREVIEW = "profile_preview"
    IDENTITY = "identity"
    CV = "cv"


@dataclass(frozen=True, slots=True)
class StreamCandidateProjection:
    """Recruiter-facing candidate projection for a Stream — derived, reconstructible.

    Snapshots support audit/explanation; current authorization is recalculated before sensitive actions.
    """
    # Required fields first
    stream_id: StreamId
    candidate_id: CandidateId
    candidate_profile_version: int
    candidate_preferences_version: int
    role_dna_version: int
    opportunity_spec_version: int
    match_engine_version: str
    intent_engine_version: str
    policy_version: str
    professional_match: float
    opportunity_fit: float

    # Optional fields with defaults
    role_intent: float = 0.0
    market_intent: float = 0.0
    eligibility_state: Literal["eligible", "excluded", "pending", "source_protected"] = "pending"
    visibility_hint: VisibilityLevel = VisibilityLevel.MARKET_AGGREGATE
    reason_codes: list[str] = field(default_factory=list)
    permission_snapshot_id: str | None = None
    trust_snapshot_id: str | None = None
    computed_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None


class ContactRequestStatus(str, Enum):
    """Contact request lifecycle."""
    PENDING_GOVERNOR = "pending_governor"
    GOVERNOR_APPROVED = "governor_approved"
    GOVERNOR_DENIED = "governor_denied"
    SENT = "sent"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass(frozen=True, slots=True)
class ContactRequest:
    """Contact request — orchestrated introduction request."""
    contact_request_id: ContactRequestId
    stream_id: StreamId
    candidate_id: CandidateId
    recruiter_id: RecruiterId
    organization_id: OrganizationId

    status: ContactRequestStatus = ContactRequestStatus.PENDING_GOVERNOR
    role_summary: str = ""
    location_summary: str = ""
    salary_summary: str | None = None
    contract_summary: str | None = None
    company_revealed: bool = False
    governor_decision_at: datetime | None = None
    governor_reason: str | None = None
    candidate_decision_at: datetime | None = None
    candidate_decision_reason: str | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


class GrantScope(str, Enum):
    """Scoped grant types — distinct permissions."""
    PROFILE = "profile"
    IDENTITY = "identity"
    CV = "cv"
    MESSAGING = "messaging"


class GrantStatus(str, Enum):
    """Grant lifecycle."""
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CONSUMED = "consumed"


@dataclass(frozen=True, slots=True)
class Grant:
    """Scoped authorization grant — versioned, expirable, revocable."""
    grant_id: GrantId
    candidate_id: CandidateId
    recruiter_id: RecruiterId
    organization_id: OrganizationId
    scope: GrantScope

    stream_id: StreamId | None = None
    contact_request_id: ContactRequestId | None = None
    status: GrantStatus = GrantStatus.ACTIVE
    resource_id: str | None = None
    resource_type: str | None = None
    policy_version: str = ""
    granted_at: datetime = field(default_factory=utcnow)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_by: str | None = None
    revoked_reason: str | None = None

    def is_active(self, at: datetime | None = None) -> bool:
        """Check if grant is currently active."""
        check_time = at or utcnow()
        if self.status != GrantStatus.ACTIVE:
            return False
        if self.expires_at and self.expires_at <= check_time:
            return False
        if self.revoked_at and self.revoked_at <= check_time:
            return False
        return True