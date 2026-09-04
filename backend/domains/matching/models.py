"""Contracts for deterministic, explainable Professional Match (TS-A5)."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Tuple

from domains.shared.ids import CandidateId, RoleDNAId
from domains.shared.versioning import EngineVersion, EntityVersion


class MatchDimension(str, Enum):
    OCCUPATION = "occupation"
    SKILLS = "skills"
    EXPERIENCE_SENIORITY = "experience_seniority"
    CAPABILITIES = "capabilities"
    CERTIFICATIONS = "certifications"
    LANGUAGES = "languages"


class MatchState(str, Enum):
    MATCH = "match"
    PARTIAL = "partial"
    GAP = "gap"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class MatchReasonCode(str, Enum):
    NOT_REQUIRED = "not_required"
    EXACT_TEXT_MATCH = "exact_text_match"
    SHARED_NORMALIZATION_REF = "shared_normalization_ref"
    MISSING_CANDIDATE_EVIDENCE = "missing_candidate_evidence"
    EXPLICIT_MISMATCH = "explicit_mismatch"
    EXPERIENCE_BAND_MATCH = "experience_band_match"
    EXPERIENCE_BAND_MISMATCH = "experience_band_mismatch"
    EXPERIENCE_BAND_UNSUPPORTED = "experience_band_unsupported"
    CAPABILITY_TEXT_EVIDENCE = "capability_text_evidence"


@dataclass(frozen=True)
class MatchComponent:
    dimension: MatchDimension
    weight: int
    applicable: bool
    state: MatchState
    score: int
    evidence_coverage: int
    matched_evidence: Tuple[str, ...] = ()
    gaps: Tuple[str, ...] = ()
    unknown_evidence: Tuple[str, ...] = ()
    reason_codes: Tuple[MatchReasonCode, ...] = ()

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError("match component weight must be positive")
        if not 0 <= self.score <= 100:
            raise ValueError("match component score must be between 0 and 100")
        if not 0 <= self.evidence_coverage <= 100:
            raise ValueError("match component evidence_coverage must be between 0 and 100")
        if not self.applicable and self.state is not MatchState.NOT_APPLICABLE:
            raise ValueError("non-applicable component must use NOT_APPLICABLE state")


@dataclass(frozen=True)
class ProfessionalMatchResult:
    candidate_id: CandidateId
    candidate_profile_version: EntityVersion
    role_dna_id: RoleDNAId
    role_dna_version: EntityVersion
    match_engine_version: EngineVersion
    professional_match_score: int
    evidence_coverage: int
    components: Tuple[MatchComponent, ...]
    computed_at: datetime

    def __post_init__(self) -> None:
        if not 0 <= self.professional_match_score <= 100:
            raise ValueError("professional_match_score must be between 0 and 100")
        if not 0 <= self.evidence_coverage <= 100:
            raise ValueError("evidence_coverage must be between 0 and 100")
        dimensions = [component.dimension for component in self.components]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("Professional Match components must have unique dimensions")
