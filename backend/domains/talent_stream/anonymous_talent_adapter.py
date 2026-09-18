"""TS-B8-002: Exact-version A1/B7 Anonymous Talent Adapter.

Builds AnonymousTalentFacts from StreamCandidate + current A1 profile with
strict version equality. No profile history, no auto-materialization.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Optional

from domains.privacy.anonymous_talent import (
    AnonymousTalentFacts,
    AnonymousTalentCard,
    render_anonymous_talent_card,
)
from domains.matching.opportunity_fit_models import HardEligibilityState, OpportunityFitState
from domains.profiles.repository import CandidateProfileRepository
from domains.talent_stream.stream_candidate_models import StreamCandidate


class AnonymousTalentAdapterError(RuntimeError):
    """Generic adapter failure."""


class AnonymousTalentProjectionUnavailableError(AnonymousTalentAdapterError):
    """Exact profile version mismatch, missing data, or incoherent B7 projection."""


def derive_anonymous_talent_card_ref(
    *,
    key: bytes,
    stream_id: str,
    generation_id: str,
    candidate_id: str,
) -> str:
    """Deterministic HMAC-SHA256 card_ref. No clock, no random, no I/O, no global config.

    Args:
        key: Secret key, must be bytes with len >= 32.
        stream_id: Talent Stream identifier.
        generation_id: Generation identifier.
        candidate_id: Candidate identifier.

    Returns:
        Format: ts-b8-card-v1:<64 lowercase hex>
    """
    if type(key) is not bytes or len(key) < 32:
        raise ValueError("card_ref key must be bytes with length >= 32")

    payload = json.dumps(
        ["ts-b8-card-v1", stream_id, generation_id, candidate_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    digest = hmac.new(key, payload, hashlib.sha256).hexdigest()
    return f"ts-b8-card-v1:{digest}"


@dataclass(frozen=True, slots=True, repr=False)
class AnonymousTalentFactsAdapter:
    """Adapts B7 StreamCandidate + A1 current profile to AnonymousTalentFacts.

    Enforces:
    - professional_match_summary present
    - opportunity_fit_summary present
    - B7 role/opportunity version consistency
    - Current A1 profile exists and candidate_id matches exactly
    - Current profile version == B7 match profile version (exact)
    """

    profile_repository: CandidateProfileRepository
    card_ref_key: bytes

    def __post_init__(self) -> None:
        if type(self.card_ref_key) is not bytes or len(self.card_ref_key) < 32:
            raise ValueError("card_ref_key must be bytes with length >= 32")
        if not isinstance(self.profile_repository, CandidateProfileRepository):
            raise ValueError("profile_repository must be a CandidateProfileRepository instance")

    async def build(self, candidate: StreamCandidate) -> AnonymousTalentFacts:
        """Build AnonymousTalentFacts from StreamCandidate and current A1 profile.

        Raises:
            AnonymousTalentProjectionUnavailableError: If any validation fails.
        """
        if type(candidate) is not StreamCandidate:
            raise AnonymousTalentAdapterError("candidate must be a StreamCandidate instance")

        match_summary = candidate.professional_match_summary
        fit_summary = candidate.opportunity_fit_summary

        if match_summary is None:
            raise AnonymousTalentProjectionUnavailableError("anonymous talent facts unavailable")
        if fit_summary is None:
            raise AnonymousTalentProjectionUnavailableError("anonymous talent facts unavailable")

        if int(match_summary.role_dna_version) != int(candidate.role_dna_version):
            raise AnonymousTalentProjectionUnavailableError("anonymous talent facts unavailable")
        if int(fit_summary.opportunity_spec_version) != int(candidate.opportunity_spec_version):
            raise AnonymousTalentProjectionUnavailableError("anonymous talent facts unavailable")

        profile_doc = await self.profile_repository.get(str(candidate.candidate_id))
        if profile_doc is None:
            raise AnonymousTalentProjectionUnavailableError("anonymous talent facts unavailable")

        if str(profile_doc.get("candidate_id")) != str(candidate.candidate_id):
            raise AnonymousTalentProjectionUnavailableError("anonymous talent facts unavailable")

        profile_version = profile_doc.get("version")
        if type(profile_version) is not int:
            raise AnonymousTalentProjectionUnavailableError("anonymous talent facts unavailable")
        if profile_version != int(match_summary.candidate_profile_version):
            raise AnonymousTalentProjectionUnavailableError("anonymous talent facts unavailable")

        experience_years = profile_doc.get("experience_years")
        if experience_years is not None and type(experience_years) is not int:
            raise AnonymousTalentProjectionUnavailableError("anonymous talent facts unavailable")

        seniority = profile_doc.get("seniority")
        if seniority is not None and type(seniority) is not str:
            raise AnonymousTalentProjectionUnavailableError("anonymous talent facts unavailable")

        card_ref = derive_anonymous_talent_card_ref(
            key=self.card_ref_key,
            stream_id=str(candidate.stream_id),
            generation_id=candidate.generation_id,
            candidate_id=str(candidate.candidate_id),
        )

        return AnonymousTalentFacts(
            card_ref=card_ref,
            experience_years=experience_years,
            seniority=seniority,
            professional_match_score=int(match_summary.professional_match_score),
            match_evidence_coverage=int(match_summary.evidence_coverage),
            hard_eligibility_state=fit_summary.hard_eligibility_state,
            opportunity_fit_state=fit_summary.opportunity_fit_state,
        )


__all__ = [
    "AnonymousTalentAdapterError",
    "AnonymousTalentProjectionUnavailableError",
    "derive_anonymous_talent_card_ref",
    "AnonymousTalentFactsAdapter",
]