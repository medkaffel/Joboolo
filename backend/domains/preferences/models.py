"""Domain model for Candidate Preferences + Discovery State (TS-A2)."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from domains.shared.ids import CandidateId, CandidatePreferencesId
from domains.shared.versioning import EntityVersion


class SearchState(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    PASSIVE = "passive"


class WorkMode(str, Enum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"
    ANY = "any"


@dataclass(frozen=True)
class DiscoverySettings:
    enabled: bool = False
    allow_compatible_opportunities: bool = False
    ask_before_reveal: bool = False
    anonymous_only: bool = False

    def __post_init__(self) -> None:
        if not self.enabled and (
            self.allow_compatible_opportunities or self.ask_before_reveal or self.anonymous_only
        ):
            raise ValueError("disabled discovery cannot enable discovery sub-controls")


@dataclass(frozen=True)
class CompensationPreference:
    minimum: Optional[int] = None
    target: Optional[int] = None
    currency: str = "EUR"

    def __post_init__(self) -> None:
        if self.minimum is not None and self.minimum < 0:
            raise ValueError("minimum compensation cannot be negative")
        if self.target is not None and self.target < 0:
            raise ValueError("target compensation cannot be negative")
        if self.minimum is not None and self.target is not None and self.target < self.minimum:
            raise ValueError("target compensation cannot be below minimum")


@dataclass(frozen=True)
class MobilityPreference:
    locations: Tuple[str, ...] = ()
    radius_km: Optional[int] = None

    def __post_init__(self) -> None:
        if self.radius_km is not None and self.radius_km < 0:
            raise ValueError("radius_km cannot be negative")


@dataclass(frozen=True)
class CandidatePreferences:
    preferences_id: CandidatePreferencesId
    candidate_id: CandidateId
    version: EntityVersion
    created_at: datetime
    updated_at: datetime
    search_state: SearchState = SearchState.PASSIVE
    discovery: DiscoverySettings = DiscoverySettings()
    target_roles: Tuple[str, ...] = ()
    compensation: Optional[CompensationPreference] = None
    mobility: Optional[MobilityPreference] = None
    work_mode: WorkMode = WorkMode.ANY
    contract_types: Tuple[str, ...] = ()
    availability: Optional[str] = None
    excluded_company_ids: Tuple[str, ...] = ()
    current_employer_company_id: Optional[str] = None
    contact_frequency_preference: Optional[str] = None

    def __post_init__(self) -> None:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot predate created_at")


@dataclass(frozen=True)
class CandidatePreferencesPatch:
    search_state: Optional[SearchState] = None
    discovery: Optional[DiscoverySettings] = None
    target_roles: Optional[Tuple[str, ...]] = None
    compensation: Optional[CompensationPreference] = None
    mobility: Optional[MobilityPreference] = None
    work_mode: Optional[WorkMode] = None
    contract_types: Optional[Tuple[str, ...]] = None
    availability: Optional[str] = None
    excluded_company_ids: Optional[Tuple[str, ...]] = None
    current_employer_company_id: Optional[str] = None
    contact_frequency_preference: Optional[str] = None
