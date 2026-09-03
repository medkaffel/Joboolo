# Candidate Preferences — What the candidate wants/accepts
# TS-A0-001: Domain Contracts & Business Invariants
# Versioned entity; Discovery State is separate from Preferences

from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum
from ..shared.ids import CandidateId, PreferencesVersion
from ..shared.versioning import Versioned


class ContractType(str, Enum):
    CDI = "CDI"
    CDD = "CDD"
    STAGE = "Stage"
    FREELANCE = "Freelance"
    INTERIM = "Interim"
    TITULAIRE = "Titulaire"


class RemotePolicy(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ON_SITE = "on_site"
    FLEXIBLE = "flexible"


class CandidatePreferences(Versioned[PreferencesVersion]):
    """
    Candidate preferences for opportunities.
    Does NOT include Discovery State — that is a separate permission/preference state.
    """
    candidate_id: CandidateId
    version: PreferencesVersion

    # Target roles
    target_roles: List[str] = Field(default_factory=list)  # Normalized occupation codes

    # Compensation
    salary_min: Optional[int] = None
    salary_currency: str = "EUR"

    # Location & mobility
    preferred_locations: List[str] = Field(default_factory=list)
    mobility_radius_km: Optional[int] = None
    willing_to_relocate: bool = False

    # Work arrangement
    remote_policy: Optional[RemotePolicy] = None
    contract_types: List[ContractType] = Field(default_factory=list)

    # Industry & sector
    preferred_industries: List[str] = Field(default_factory=list)
    excluded_industries: List[str] = Field(default_factory=list)

    # Availability
    notice_period_weeks: Optional[int] = None
    availability_date: Optional[datetime] = None

    # Contact preferences
    max_contacts_per_week: Optional[int] = None
    preferred_contact_channels: List[str] = Field(default_factory=list)

    # Exclusions (company-level)
    excluded_companies: List[str] = Field(default_factory=list)  # CompanyIds
    exclude_current_employer: bool = True
    excluded_former_employers: List[str] = Field(default_factory=list)
    excluded_agencies: List[str] = Field(default_factory=list)

    # Discovery opt-in is separate — see DiscoveryState
    # This is preferences for opportunity *compatibility*, not discovery permission

    class Config:
        frozen = True


class PreferencesRef(BaseModel):
    """
    Reference to a specific preferences version for Match/Stream binding.
    """
    candidate_id: CandidateId
    preferences_version: PreferencesVersion
    snapshot_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        frozen = True