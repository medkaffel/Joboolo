"""Explainable Professional Match bounded context (TS-A5)."""

from .engine import MATCH_ENGINE_VERSION, calculate_professional_match
from .models import (
    MatchComponent,
    MatchDimension,
    MatchReasonCode,
    MatchState,
    ProfessionalMatchResult,
)
from .service import (
    MatchInputNotFoundError,
    MatchSnapshotUnavailableError,
    ProfessionalMatchService,
)

__all__ = [
    "MATCH_ENGINE_VERSION",
    "calculate_professional_match",
    "MatchComponent",
    "MatchDimension",
    "MatchReasonCode",
    "MatchState",
    "ProfessionalMatchResult",
    "MatchInputNotFoundError",
    "MatchSnapshotUnavailableError",
    "ProfessionalMatchService",
]
