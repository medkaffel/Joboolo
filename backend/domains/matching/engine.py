"""Pure deterministic Professional Match engine v2.

Only Candidate Professional Profile and Role DNA professional facts participate.
Opportunity Fit, Discovery, Intent, Trust, Permission and recruiter state are
deliberately absent.
"""
import re
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence, Tuple

from domains.profiles.models import CandidateProfessionalProfile, SkillFact
from domains.roles.models import RoleDNA, RoleSkill
from domains.shared.versioning import EngineVersion
from .models import (
    MatchComponent,
    MatchDimension,
    MatchReasonCode,
    MatchState,
    ProfessionalMatchResult,
)


MATCH_ENGINE_VERSION = EngineVersion("professional-match-v2.0.0")

WEIGHTS = {
    MatchDimension.OCCUPATION: 25,
    MatchDimension.SKILLS: 35,
    MatchDimension.EXPERIENCE_SENIORITY: 20,
    MatchDimension.CAPABILITIES: 10,
    MatchDimension.CERTIFICATIONS: 5,
    MatchDimension.LANGUAGES: 5,
}


def _norm(value: Optional[str]) -> str:
    return " ".join((value or "").casefold().split())


def _percent(numerator: float, denominator: float) -> int:
    if denominator <= 0:
        return 0
    return max(0, min(100, int(round(100 * numerator / denominator))))


def _not_applicable(dimension: MatchDimension) -> MatchComponent:
    return MatchComponent(
        dimension=dimension,
        weight=WEIGHTS[dimension],
        applicable=False,
        state=MatchState.NOT_APPLICABLE,
        score=0,
        evidence_coverage=0,
        reason_codes=(MatchReasonCode.NOT_REQUIRED,),
    )


def _state(matched: int, gaps: int, unknown: int, required: int) -> MatchState:
    if required == 0:
        return MatchState.NOT_APPLICABLE
    if matched == required:
        return MatchState.MATCH
    if matched and (gaps or unknown):
        return MatchState.PARTIAL
    if gaps and not matched and not unknown:
        return MatchState.GAP
    if gaps and unknown:
        return MatchState.PARTIAL
    return MatchState.UNKNOWN


def _component(
    dimension: MatchDimension,
    required: int,
    matched: Sequence[str],
    gaps: Sequence[str],
    unknown: Sequence[str],
    reason_codes: Sequence[MatchReasonCode],
) -> MatchComponent:
    if required == 0:
        return _not_applicable(dimension)
    evaluated = len(matched) + len(gaps)
    return MatchComponent(
        dimension=dimension,
        weight=WEIGHTS[dimension],
        applicable=True,
        state=_state(len(matched), len(gaps), len(unknown), required),
        score=_percent(len(matched), evaluated),
        evidence_coverage=_percent(evaluated, required),
        matched_evidence=tuple(matched),
        gaps=tuple(gaps),
        unknown_evidence=tuple(unknown),
        reason_codes=tuple(dict.fromkeys(reason_codes)),
    )


def _occupation_component(profile: CandidateProfessionalProfile, role: RoleDNA) -> MatchComponent:
    role_terms = {_norm(role.canonical_title)}
    role_terms.update(_norm(alias) for alias in role.aliases if _norm(alias))

    candidate_terms = set()
    for occupation in profile.occupations:
        candidate_terms.add(_norm(occupation.title))
        if occupation.normalized_occupation:
            candidate_terms.add(_norm(occupation.normalized_occupation))
    candidate_terms.discard("")

    if not candidate_terms:
        return _component(
            MatchDimension.OCCUPATION,
            1,
            (),
            (),
            (f"occupation:{role.canonical_title}",),
            (MatchReasonCode.MISSING_CANDIDATE_EVIDENCE,),
        )

    if role_terms & candidate_terms:
        return _component(
            MatchDimension.OCCUPATION,
            1,
            (f"occupation:{role.canonical_title}",),
            (),
            (),
            (MatchReasonCode.EXACT_TEXT_MATCH,),
        )

    return _component(
        MatchDimension.OCCUPATION,
        1,
        (),
        (f"occupation:{role.canonical_title}",),
        (),
        (MatchReasonCode.EXPLICIT_MISMATCH,),
    )


def _skill_matches(candidate: SkillFact, required: RoleSkill) -> Tuple[bool, MatchReasonCode]:
    if (
        candidate.normalization_ref
        and required.normalization_ref
        and candidate.normalization_ref == required.normalization_ref
    ):
        return True, MatchReasonCode.SHARED_NORMALIZATION_REF

    candidate_terms = {_norm(candidate.name), _norm(candidate.normalized_name)}
    role_terms = {_norm(required.label), _norm(required.normalized_code)}
    candidate_terms.discard("")
    role_terms.discard("")
    if candidate_terms & role_terms:
        return True, MatchReasonCode.EXACT_TEXT_MATCH
    return False, MatchReasonCode.MISSING_CANDIDATE_EVIDENCE


def _skills_component(profile: CandidateProfessionalProfile, role: RoleDNA) -> MatchComponent:
    if not role.skills:
        return _not_applicable(MatchDimension.SKILLS)

    matched = []
    unknown = []
    reasons = []
    for required in role.skills:
        match_reason = None
        for candidate in profile.skills:
            ok, reason = _skill_matches(candidate, required)
            if ok:
                match_reason = reason
                break
        if match_reason:
            matched.append(f"skill:{required.label}")
            reasons.append(match_reason)
        else:
            unknown.append(f"skill:{required.label}")
            reasons.append(MatchReasonCode.MISSING_CANDIDATE_EVIDENCE)

    return _component(
        MatchDimension.SKILLS,
        len(role.skills),
        matched,
        (),
        unknown,
        reasons,
    )


def _parse_experience_band(value: str) -> Optional[Tuple[Optional[int], Optional[int]]]:
    text = _norm(value).replace("years", "").replace("year", "").replace("ans", "").strip()
    match = re.fullmatch(r"(\d+)\s*\+", text)
    if match:
        return int(match.group(1)), None
    match = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", text)
    if match:
        low, high = int(match.group(1)), int(match.group(2))
        return (low, high) if low <= high else None
    match = re.fullmatch(r"(\d+)", text)
    if match:
        exact = int(match.group(1))
        return exact, exact
    return None


def _experience_component(
    profile: CandidateProfessionalProfile, role: RoleDNA
) -> MatchComponent:
    required = int(bool(role.seniority_band)) + int(bool(role.experience_band))
    if required == 0:
        return _not_applicable(MatchDimension.EXPERIENCE_SENIORITY)

    matched = []
    gaps = []
    unknown = []
    reasons = []

    if role.seniority_band:
        if profile.seniority is None:
            unknown.append(f"seniority:{role.seniority_band}")
            reasons.append(MatchReasonCode.MISSING_CANDIDATE_EVIDENCE)
        elif _norm(profile.seniority) == _norm(role.seniority_band):
            matched.append(f"seniority:{role.seniority_band}")
            reasons.append(MatchReasonCode.EXACT_TEXT_MATCH)
        else:
            gaps.append(f"seniority:{role.seniority_band}")
            reasons.append(MatchReasonCode.EXPLICIT_MISMATCH)

    if role.experience_band:
        parsed = _parse_experience_band(role.experience_band)
        if parsed is None:
            unknown.append(f"experience_band:{role.experience_band}")
            reasons.append(MatchReasonCode.EXPERIENCE_BAND_UNSUPPORTED)
        elif profile.experience_years is None:
            unknown.append(f"experience_band:{role.experience_band}")
            reasons.append(MatchReasonCode.MISSING_CANDIDATE_EVIDENCE)
        else:
            minimum, maximum = parsed
            years = profile.experience_years
            compatible = years >= (minimum or 0) and (maximum is None or years <= maximum)
            if compatible:
                matched.append(f"experience_years:{years}")
                reasons.append(MatchReasonCode.EXPERIENCE_BAND_MATCH)
            else:
                gaps.append(f"experience_band:{role.experience_band}")
                reasons.append(MatchReasonCode.EXPERIENCE_BAND_MISMATCH)

    return _component(
        MatchDimension.EXPERIENCE_SENIORITY,
        required,
        matched,
        gaps,
        unknown,
        reasons,
    )


def _professional_text(profile: CandidateProfessionalProfile) -> str:
    chunks = [profile.headline or "", profile.summary or ""]
    chunks.extend(experience.description or "" for experience in profile.experiences)
    return _norm(" ".join(chunks))


def _capabilities_component(
    profile: CandidateProfessionalProfile, role: RoleDNA
) -> MatchComponent:
    if not role.capabilities:
        return _not_applicable(MatchDimension.CAPABILITIES)

    corpus = _professional_text(profile)
    matched = []
    unknown = []
    reasons = []
    for capability in role.capabilities:
        normalized = _norm(capability)
        if normalized and normalized in corpus:
            matched.append(f"capability:{capability}")
            reasons.append(MatchReasonCode.CAPABILITY_TEXT_EVIDENCE)
        else:
            unknown.append(f"capability:{capability}")
            reasons.append(MatchReasonCode.MISSING_CANDIDATE_EVIDENCE)
    return _component(
        MatchDimension.CAPABILITIES,
        len(role.capabilities),
        matched,
        (),
        unknown,
        reasons,
    )


def _exact_requirement_component(
    dimension: MatchDimension,
    required_values: Iterable[str],
    candidate_values: Iterable[str],
    prefix: str,
) -> MatchComponent:
    required = [value for value in required_values if _norm(value)]
    if not required:
        return _not_applicable(dimension)
    candidates = {_norm(value) for value in candidate_values if _norm(value)}
    matched = []
    unknown = []
    reasons = []
    for value in required:
        if _norm(value) in candidates:
            matched.append(f"{prefix}:{value}")
            reasons.append(MatchReasonCode.EXACT_TEXT_MATCH)
        else:
            unknown.append(f"{prefix}:{value}")
            reasons.append(MatchReasonCode.MISSING_CANDIDATE_EVIDENCE)
    return _component(dimension, len(required), matched, (), unknown, reasons)


def _certifications_component(
    profile: CandidateProfessionalProfile, role: RoleDNA
) -> MatchComponent:
    return _exact_requirement_component(
        MatchDimension.CERTIFICATIONS,
        role.certifications,
        (certification.label for certification in profile.certifications),
        "certification",
    )


def _languages_component(
    profile: CandidateProfessionalProfile, role: RoleDNA
) -> MatchComponent:
    candidate_values = []
    for language in profile.languages:
        candidate_values.append(language.language)
        if language.level:
            candidate_values.append(f"{language.language} {language.level}")
    return _exact_requirement_component(
        MatchDimension.LANGUAGES,
        role.languages,
        candidate_values,
        "language",
    )


def calculate_professional_match(
    profile: CandidateProfessionalProfile,
    role: RoleDNA,
    *,
    engine_version: EngineVersion = MATCH_ENGINE_VERSION,
    computed_at: Optional[datetime] = None,
) -> ProfessionalMatchResult:
    """Compute Professional Match from professional facts only."""
    components = (
        _occupation_component(profile, role),
        _skills_component(profile, role),
        _experience_component(profile, role),
        _capabilities_component(profile, role),
        _certifications_component(profile, role),
        _languages_component(profile, role),
    )

    applicable_weight = sum(component.weight for component in components if component.applicable)
    evaluated_weight = sum(
        component.weight * component.evidence_coverage / 100
        for component in components
        if component.applicable
    )
    weighted_score = sum(
        component.weight
        * component.evidence_coverage
        / 100
        * component.score
        for component in components
        if component.applicable
    )

    overall_score = _percent(weighted_score, evaluated_weight * 100) if evaluated_weight else 0
    coverage = _percent(evaluated_weight, applicable_weight)

    return ProfessionalMatchResult(
        candidate_id=profile.candidate_id,
        candidate_profile_version=profile.version,
        role_dna_id=role.role_dna_id,
        role_dna_version=role.version,
        match_engine_version=engine_version,
        professional_match_score=overall_score,
        evidence_coverage=coverage,
        components=components,
        computed_at=computed_at or datetime.now(timezone.utc),
    )
