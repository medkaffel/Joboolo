"""Permissions domain contracts.

Contract-only: defines authorization decisions, exclusions, and current-permission checks.
No runtime persistence or business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Protocol

from backend.domains.shared.ids import (
    CandidateId,
    GrantId,
    OrganizationId,
    PermissionSnapshotId,
    RecruiterId,
)
from backend.domains.shared.versioning import VersionedRef


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class AuthorizationDecision(str, Enum):
    """Central policy decision result."""
    ALLOW = "allow"
    DENY = "deny"


class DenialReason(str, Enum):
    """Structured denial reasons for audit/explanation."""
    # Discovery / preference
    DISCOVERY_DISABLED = "discovery_disabled"
    PREFERENCES_INCOMPATIBLE = "preferences_incompatible"
    EXCLUDED_COMPANY = "excluded_company"
    EXCLUDED_CURRENT_EMPLOYER = "excluded_current_employer"
    EXCLUDED_AGENCY = "excluded_agency"
    CONTACT_FREQUENCY_EXCEEDED = "contact_frequency_exceeded"

    # Trust / recruiter
    RECRUITER_UNVERIFIED = "recruiter_unverified"
    ORGANIZATION_UNVERIFIED = "organization_unverified"
    MANDATE_INVALID = "mandate_invalid"
    RECRUITER_SUSPENDED = "recruiter_suspended"
    ORGANIZATION_SUSPENDED = "organization_suspended"

    # Source protection / Cross-Offer
    SOURCE_PROTECTION_ACTIVE = "source_protection_active"
    INDEPENDENT_SIGNAL_INSUFFICIENT = "independent_signal_insufficient"
    ORIGIN_NOT_NEUTRALIZED = "origin_not_neutralized"

    # Contact Governor
    GOVERNOR_FREQUENCY_CAP = "governor_frequency_cap"
    GOVERNOR_DUPLICATE = "governor_duplicate"
    GOVERNOR_MIN_ELIGIBILITY = "governor_min_eligibility"
    GOVERNOR_PRIOR_DECLINE = "governor_prior_decline"
    GOVERNOR_COOLING = "governor_cooling"
    GOVERNOR_SATURATION = "governor_saturation"

    # Grants / consent
    GRANT_EXPIRED = "grant_expired"
    GRANT_REVOKED = "grant_revoked"
    GRANT_SCOPE_INSUFFICIENT = "grant_scope_insufficient"
    NO_ACTIVE_GRANT = "no_active_grant"

    # Privacy
    ANONYMIZATION_REQUIRED = "anonymization_required"
    REIDENTIFICATION_RISK = "reidentification_risk"

    # Generic
    POLICY_VERSION_MISMATCH = "policy_version_mismatch"
    INSUFFICIENT_PERMISSION = "insufficient_permission"


@dataclass(frozen=True, slots=True)
class AuthorizationContext:
    """Input context for a permission decision — evaluated at action time."""
    candidate_id: CandidateId
    recruiter_id: RecruiterId
    organization_id: OrganizationId
    hiring_company_id: str | None = None
    mandate_id: str | None = None
    stream_id: str | None = None
    contact_request_id: str | None = None
    grant_id: GrantId | None = None
    requested_scope: str = ""  # e.g., "profile", "identity", "cv", "messaging"
    action: str = ""           # e.g., "request_introduction", "reveal_profile", "access_cv"
    policy_version: str = ""


@dataclass(frozen=True, slots=True)
class AuthorizationResult:
    """Result of a current-authorization check."""
    decision: AuthorizationDecision
    reason: DenialReason | None = None
    details: dict[str, str] = field(default_factory=dict)
    evaluated_at: datetime = field(default_factory=utcnow)
    policy_version: str = ""
    permission_snapshot_id: PermissionSnapshotId | None = None


@dataclass(frozen=True, slots=True)
class ExclusionCheck:
    """Candidate exclusion verification — runs before any recruiter contact/reveal."""
    candidate_id: CandidateId
    hiring_company_id: str
    recruiter_organization_id: OrganizationId
    agency_id: str | None = None

    current_employer_excluded: bool = False
    company_excluded: bool = False
    agency_excluded: bool = False
    former_employer_excluded: bool = False

    exclusion_details: dict[str, str] = field(default_factory=dict)
    checked_at: datetime = field(default_factory=utcnow)

    def has_exclusion(self) -> bool:
        return any([
            self.current_employer_excluded,
            self.company_excluded,
            self.agency_excluded,
            self.former_employer_excluded,
        ])


@dataclass(frozen=True, slots=True)
class PermissionSnapshot:
    """Audit snapshot of permission state at a point in time — not authorization source."""
    snapshot_id: PermissionSnapshotId
    candidate_id: CandidateId
    stream_id: str | None = None
    contact_request_id: str | None = None

    discovery_state_ref: VersionedRef | None = None
    preferences_ref: VersionedRef | None = None
    active_grants: list[GrantId] = field(default_factory=list)
    exclusions: list[str] = field(default_factory=list)
    policy_version: str = ""
    captured_at: datetime = field(default_factory=utcnow)


class CurrentPermissionCheck(Protocol):
    """Contract for the current-permission evaluation function.

    Implementations live in later lots (A9). This defines the input/output shape.
    """

    def evaluate(self, context: AuthorizationContext) -> AuthorizationResult:
        """Evaluate current authorization — never from cached projection alone."""
        ...


# --- Contact Governor policy contract ---

@dataclass(frozen=True, slots=True)
class ContactGovernorPolicy:
    """Contact Governor policy configuration — versioned policy."""
    policy_version: str

    max_invitations_per_candidate_per_week: int = 3
    max_invitations_per_recruiter_per_day: int = 50
    max_invitations_per_organization_per_day: int = 200
    min_professional_match_threshold: float = 0.6
    min_opportunity_fit_threshold: float = 0.5
    require_salary_compatibility: bool = True
    require_location_compatibility: bool = True
    duplicate_window_days: int = 30
    prior_decline_cooling_days: int = 90
    company_cooling_days: int = 14
    recruiter_trust_threshold: float = 0.7
    saturation_limit_per_stream: int = 100