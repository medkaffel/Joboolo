"""Candidate Preferences bounded context (TS-A2)."""

from .models import CandidatePreferences, CandidatePreferencesPatch, DiscoverySettings
from .service import PreferencesConflictError, CandidatePreferencesService

__all__ = [
    "CandidatePreferences",
    "CandidatePreferencesPatch",
    "DiscoverySettings",
    "PreferencesConflictError",
    "CandidatePreferencesService",
]
