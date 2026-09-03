# Profiles Domain Contracts
# TS-A0-001: Domain Contracts & Business Invariants
# Owns: Candidate Professional Profile, Candidate Preferences, Discovery State
# Boundary: Discovery != Intent — Discovery is a preference/permission state, not Intent

from .profile import (
    ProfessionalProfile,
    ProfileVersion,
    ProfileRef,
)
from .preferences import (
    CandidatePreferences,
    PreferencesVersion,
    PreferencesRef,
)
from .discovery import (
    DiscoveryState,
    DiscoveryMode,
    DiscoveryPoolEligibility,
)

__all__ = [
    "ProfessionalProfile",
    "ProfileVersion",
    "ProfileRef",
    "CandidatePreferences",
    "PreferencesVersion",
    "PreferencesRef",
    "DiscoveryState",
    "DiscoveryMode",
    "DiscoveryPoolEligibility",
]