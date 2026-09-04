"""Minimal field-shape contracts for Candidate Professional Profile, Preferences, and Discovery State."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from ..shared.ids import CandidateId, DocumentId
from ..shared.envelope import Metadata


class DiscoveryMode(str, Enum):
    """Discovery modes - distinct from Intent."""
    PASSIVE = "passive"
    ACTIVE = "active"
    CURATED = "curated"


class ProfileVisibility(str, Enum):
    """Profile visibility levels."""
    PRIVATE = "private"
    RECRUITERS = "recruiters"
    PUBLIC = "public"


@dataclass(frozen=True, slots=True)
class CandidateProfessionalProfile:
    """Minimal professional profile shape - no Intent, no CV/Document access."""
    candidate_id: CandidateId
    headline: str
    skills: tuple[str, ...] = field(default_factory=tuple)
    experience_years: int | None = None
    current_role: str | None = None
    location: str | None = None
    preferred_locations: tuple[str, ...] = field(default_factory=tuple)
    remote_preference: str | None = None
    salary_expectation_min: int | None = None
    salary_expectation_max: int | None = None
    salary_currency: str = "EUR"
    availability_date: datetime | None = None
    profile_visibility: ProfileVisibility = ProfileVisibility.PRIVATE
    metadata: Metadata = field(default_factory=Metadata)

    # Discovery MUST NOT contain intent fields


@dataclass(frozen=True, slots=True)
class CandidatePreferences:
    """Candidate preferences for discovery and matching - distinct from Intent."""
    candidate_id: CandidateId
    preferred_roles: tuple[str, ...] = field(default_factory=tuple)
    preferred_industries: tuple[str, ...] = field(default_factory=tuple)
    preferred_company_sizes: tuple[str, ...] = field(default_factory=tuple)
    excluded_companies: tuple[str, ...] = field(default_factory=tuple)
    excluded_keywords: tuple[str, ...] = field(default_factory=tuple)
    min_salary: int | None = None
    max_salary: int | None = None
    currency: str = "EUR"
    remote_only: bool = False
    willing_to_relocate: bool = False
    discovery_mode: DiscoveryMode = DiscoveryMode.PASSIVE
    metadata: Metadata = field(default_factory=Metadata)


@dataclass(frozen=True, slots=True)
class DiscoveryState:
    """Discovery pool membership state - distinct from Intent, no intent fields."""
    candidate_id: CandidateId
    is_in_pool: bool = False
    pool_entered_at: datetime | None = None
    pool_exited_at: datetime | None = None
    discovery_mode: DiscoveryMode = DiscoveryMode.PASSIVE
    last_matched_at: datetime | None = None
    match_count: int = 0
    metadata: Metadata = field(default_factory=Metadata)

    # DiscoveryState MUST NOT contain intent fields, no eligibility logic