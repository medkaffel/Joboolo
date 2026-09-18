"""TS-B8-001: Privacy-safe Anonymous Talent Card Contracts & Policy.

Level 1 — Anonymous Talent only. No PII, no free text from profiles,
no candidate identifiers, no provenance metadata.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from domains.matching.opportunity_fit_models import HardEligibilityState, OpportunityFitState


ANONYMOUS_TALENT_POLICY_VERSION = "anonymous-talent-v1"

_CARD_REF_PATTERN = re.compile(r"^ts-b8-card-v1:[0-9a-f]{64}$")


class ExperienceBand(str, Enum):
    UNKNOWN = "unknown"
    EARLY_0_2 = "early_0_2"
    ESTABLISHED_3_5 = "established_3_5"
    EXPERIENCED_6_10 = "experienced_6_10"
    ADVANCED_11_15 = "advanced_11_15"
    VETERAN_16_PLUS = "veteran_16_plus"


class SeniorityBand(str, Enum):
    UNKNOWN = "unknown"
    EARLY_CAREER = "early_career"
    MID_LEVEL = "mid_level"
    SENIOR = "senior"
    LEADERSHIP = "leadership"


class MatchBand(str, Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


class EvidenceCoverageBand(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True, repr=False)
class AnonymousTalentFacts:
    card_ref: str
    experience_years: Optional[int]
    seniority: Optional[str]
    professional_match_score: int
    match_evidence_coverage: int
    hard_eligibility_state: HardEligibilityState
    opportunity_fit_state: OpportunityFitState

    def __post_init__(self) -> None:
        if not isinstance(self.card_ref, str) or not _CARD_REF_PATTERN.match(self.card_ref):
            raise ValueError("card_ref must match ts-b8-card-v1:<64 lowercase hex>")
        if self.experience_years is not None:
            if not isinstance(self.experience_years, int) or self.experience_years < 0:
                raise ValueError("experience_years must be a non-negative integer or None")
        if self.seniority is not None and not isinstance(self.seniority, str):
            raise ValueError("seniority must be a string or None")
        if not isinstance(self.professional_match_score, int) or not 0 <= self.professional_match_score <= 100:
            raise ValueError("professional_match_score must be an integer between 0 and 100")
        if not isinstance(self.match_evidence_coverage, int) or not 0 <= self.match_evidence_coverage <= 100:
            raise ValueError("match_evidence_coverage must be an integer between 0 and 100")
        object.__setattr__(self, "hard_eligibility_state", HardEligibilityState(self.hard_eligibility_state))
        object.__setattr__(self, "opportunity_fit_state", OpportunityFitState(self.opportunity_fit_state))


@dataclass(frozen=True, slots=True, repr=False)
class AnonymousTalentCard:
    card_ref: str
    policy_version: str
    experience_band: ExperienceBand
    seniority_band: SeniorityBand
    professional_match_band: MatchBand
    evidence_coverage_band: EvidenceCoverageBand
    hard_eligibility_state: HardEligibilityState
    opportunity_fit_state: OpportunityFitState

    def __post_init__(self) -> None:
        if not isinstance(self.card_ref, str) or not _CARD_REF_PATTERN.match(self.card_ref):
            raise ValueError("card_ref must match ts-b8-card-v1:<64 lowercase hex>")
        if self.policy_version != ANONYMOUS_TALENT_POLICY_VERSION:
            raise ValueError(f"policy_version must be {ANONYMOUS_TALENT_POLICY_VERSION}")
        object.__setattr__(self, "experience_band", ExperienceBand(self.experience_band))
        object.__setattr__(self, "seniority_band", SeniorityBand(self.seniority_band))
        object.__setattr__(self, "professional_match_band", MatchBand(self.professional_match_band))
        object.__setattr__(self, "evidence_coverage_band", EvidenceCoverageBand(self.evidence_coverage_band))
        object.__setattr__(self, "hard_eligibility_state", HardEligibilityState(self.hard_eligibility_state))
        object.__setattr__(self, "opportunity_fit_state", OpportunityFitState(self.opportunity_fit_state))


def _experience_band(years: Optional[int]) -> ExperienceBand:
    if years is None:
        return ExperienceBand.UNKNOWN
    if years <= 2:
        return ExperienceBand.EARLY_0_2
    if years <= 5:
        return ExperienceBand.ESTABLISHED_3_5
    if years <= 10:
        return ExperienceBand.EXPERIENCED_6_10
    if years <= 15:
        return ExperienceBand.ADVANCED_11_15
    return ExperienceBand.VETERAN_16_PLUS


def _seniority_band(raw: Optional[str]) -> SeniorityBand:
    if raw is None:
        return SeniorityBand.UNKNOWN
    normalized = " ".join(raw.strip().lower().split())
    if normalized in {
        "intern", "internship", "entry", "entry level", "entry-level", "junior", "trainee"
    }:
        return SeniorityBand.EARLY_CAREER
    if normalized in {"mid", "mid-level", "mid level", "intermediate"}:
        return SeniorityBand.MID_LEVEL
    if normalized in {"senior", "sr", "lead", "principal", "staff"}:
        return SeniorityBand.SENIOR
    if normalized in {
        "manager", "head", "director", "vp", "vice president", "executive", "c-level", "c level",
        "chief", "cto", "cio", "ceo", "cfo", "cmo"
    }:
        return SeniorityBand.LEADERSHIP
    return SeniorityBand.UNKNOWN


def _match_band(score: int) -> MatchBand:
    if score < 40:
        return MatchBand.LOW
    if score < 60:
        return MatchBand.MODERATE
    if score < 80:
        return MatchBand.STRONG
    if score < 90:
        return MatchBand.VERY_STRONG
    return MatchBand.VERY_STRONG


def _evidence_band(coverage: int) -> EvidenceCoverageBand:
    if coverage < 40:
        return EvidenceCoverageBand.LOW
    if coverage < 70:
        return EvidenceCoverageBand.MEDIUM
    return EvidenceCoverageBand.HIGH


def render_anonymous_talent_card(facts: AnonymousTalentFacts) -> AnonymousTalentCard:
    """Pure policy renderer. No I/O, no clock, no random, no config, no permission lookup."""
    if not isinstance(facts, AnonymousTalentFacts):
        raise TypeError("facts must be an AnonymousTalentFacts instance")
    return AnonymousTalentCard(
        card_ref=facts.card_ref,
        policy_version=ANONYMOUS_TALENT_POLICY_VERSION,
        experience_band=_experience_band(facts.experience_years),
        seniority_band=_seniority_band(facts.seniority),
        professional_match_band=_match_band(facts.professional_match_score),
        evidence_coverage_band=_evidence_band(facts.match_evidence_coverage),
        hard_eligibility_state=facts.hard_eligibility_state,
        opportunity_fit_state=facts.opportunity_fit_state,
    )


__all__ = [
    "ANONYMOUS_TALENT_POLICY_VERSION",
    "ExperienceBand",
    "SeniorityBand",
    "MatchBand",
    "EvidenceCoverageBand",
    "AnonymousTalentFacts",
    "AnonymousTalentCard",
    "render_anonymous_talent_card",
]