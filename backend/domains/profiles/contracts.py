"""Profiles domain contracts.

Contract-only: defines the shape and invariants of profile, preferences, and discovery state.
No runtime persistence or business logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from backend.domains.shared.ids import (
    CandidateId,
    DiscoveryStateId,
    PreferencesId,
    ProfileId,
)
from backend.domains.shared.versioning import EntityVersion, Versioned, VersionedRef


def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)


class DiscoveryMode(str, Enum):
    """Candidate-controlled discovery setting.

    DISCOVERY != INTENT — this is a separate permission/preference state.
    """
    DISABLED = "disabled"
    ENABLED_SIMILAR = "enabled_similar"          # allow discovery for compatible opportunities
    ASK_BEFORE_REVEAL = "ask_before_reveal"      # require candidate approval before profile reveal
    ANONYMOUS_ONLY = "anonymous_only"            # only anonymous cards may be shown


@dataclass(frozen=True, slots=True)
class ProfessionalProfile:
    """Candidate professional facts for matching — versioned entity."""
    profile_id: ProfileId
    candidate_id: CandidateId
    version: int
    updated_at: datetime
    updated_by: CandidateId

    # Core professional data (extensible)
    occupations: list[str] = field(default_factory=list)      # normalized occupation codes
    skills: list[str] = field(default_factory=list)           # normalized skill codes
    seniority_level: str | None = None                        # e.g., "junior", "mid", "senior", "lead", "exec"
    experience_years: int | None = None
    certifications: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    management_experience: bool = False
    industry_exposure: list[str] = field(default_factory=list)
    education_level: str | None = None
    portfolio_urls: list[str] = field(default_factory=list)

    def to_versioned(self) -> Versioned[ProfessionalProfile]:
        return Versioned(value=self, version=self.version, updated_at=self.updated_at)

    def to_ref(self) -> VersionedRef:
        return VersionedRef(entity_id=self.profile_id, version=self.version)


@dataclass(frozen=True, slots=True)
class CandidatePreferences:
    """Candidate preferences for opportunities — versioned entity.

    These represent what the candidate wants or accepts in an opportunity.
    """
    preferences_id: PreferencesId
    candidate_id: CandidateId
    version: int
    updated_at: datetime
    updated_by: CandidateId

    target_roles: list[str] = field(default_factory=list)           # normalized occupation/role codes
    salary_min: int | None = None                                 # annual gross in base currency
    salary_currency: str = "EUR"
    locations: list[str] = field(default_factory=list)            # preferred locations (generalized)
    mobility_radius_km: int | None = None
    remote_policy: Literal["remote", "hybrid", "onsite", "any"] = "any"
    contract_types: list[str] = field(default_factory=list)       # e.g., "permanent", "contract", "freelance"
    industries: list[str] = field(default_factory=list)
    availability_weeks: int | None = None                         # notice period / availability
    contact_frequency_max_per_week: int = 3
    excluded_companies: list[str] = field(default_factory=list)   # company identifiers
    exclude_current_employer: bool = True
    excluded_agencies: list[str] = field(default_factory=list)
    willing_similar_opportunities: bool = True

    def to_versioned(self) -> Versioned[CandidatePreferences]:
        return Versioned(value=self, version=self.version, updated_at=self.updated_at)

    def to_ref(self) -> VersionedRef:
        return VersionedRef(entity_id=self.preferences_id, version=self.version)


@dataclass(frozen=True, slots=True)
class DiscoveryState:
    """Candidate-controlled discovery authorization state.

    DISCOVERY != INTENT — this is a separate permission/preference state.
    Discovery enablement is not an intent event.
    """
    discovery_state_id: DiscoveryStateId
    candidate_id: CandidateId
    version: int
    updated_at: datetime
    updated_by: CandidateId

    mode: DiscoveryMode = DiscoveryMode.DISABLED
    similar_opportunities_allowed: bool = False
    ask_before_reveal: bool = True
    anonymous_only: bool = False
    contact_frequency_max_per_week: int = 3
    salary_min: int | None = None
    locations: list[str] = field(default_factory=list)
    remote_policy: Literal["remote", "hybrid", "onsite", "any"] = "any"
    contract_types: list[str] = field(default_factory=list)
    excluded_companies: list[str] = field(default_factory=list)
    exclude_current_employer: bool = True
    excluded_agencies: list[str] = field(default_factory=list)
    revoked_at: datetime | None = None

    def to_versioned(self) -> Versioned[DiscoveryState]:
        return Versioned(value=self, version=self.version, updated_at=self.updated_at)

    def to_ref(self) -> VersionedRef:
        return VersionedRef(entity_id=self.discovery_state_id, version=self.version)

    def is_eligible_for_discovery(self) -> bool:
        """Check if candidate is currently eligible for Discovery Pool retrieval."""
        return (
            self.mode != DiscoveryMode.DISABLED
            and self.revoked_at is None
            and self.similar_opportunities_allowed
        )


@dataclass(frozen=True, slots=True)
class DiscoveryPoolEligibility:
    """Computed eligibility for Discovery Pool — not stored, derived at retrieval time.

    Combines DiscoveryState with current Preferences to determine if a candidate
    can appear in a specific Stream's Discovery Pool.
    """
    candidate_id: CandidateId
    discovery_state_ref: VersionedRef
    preferences_ref: VersionedRef
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    evaluated_at: datetime = field(default_factory=utcnow)