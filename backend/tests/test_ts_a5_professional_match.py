from datetime import datetime, timezone

import pytest

from domains.matching.engine import MATCH_ENGINE_VERSION, WEIGHTS, calculate_professional_match
from domains.matching.models import MatchDimension, MatchReasonCode, MatchState, ProfessionalMatchResult
from domains.matching.service import MatchSnapshotUnavailableError, ProfessionalMatchService
from domains.profiles.models import (
    CandidateProfessionalProfile,
    FactSource,
    OccupationFact,
    SkillFact,
)
from domains.roles.models import RoleDNA, RoleDNAStatus, RoleFactSource, RoleSkill
from domains.shared.ids import CandidateId, CandidateProfileId, RoleDNAId
from domains.shared.versioning import EntityVersion


NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def profile(**kwargs):
    data = dict(
        profile_id=CandidateProfileId("candidate_profile:c1"),
        candidate_id=CandidateId("c1"),
        version=EntityVersion(3),
        created_at=NOW,
        updated_at=NOW,
    )
    data.update(kwargs)
    return CandidateProfessionalProfile(**data)


def role(**kwargs):
    data = dict(
        role_dna_id=RoleDNAId("role:backend"),
        version=EntityVersion(2),
        status=RoleDNAStatus.ACTIVE,
        canonical_title="Backend Engineer",
        created_at=NOW,
        updated_at=NOW,
    )
    data.update(kwargs)
    return RoleDNA(**data)


def component(result, dimension):
    return next(value for value in result.components if value.dimension is dimension)


def test_engine_weights_are_explicit_and_sum_to_one_hundred():
    assert sum(WEIGHTS.values()) == 100


def test_capability_matching_respects_term_boundaries():
    result = calculate_professional_match(
        profile(
            occupations=(
                OccupationFact(title="Backend Engineer", source=FactSource.CANDIDATE_DECLARED),
            ),
            summary="MongoDB platform engineer",
        ),
        role(capabilities=("Go",)),
        computed_at=NOW,
    )
    capability = component(result, MatchDimension.CAPABILITIES)
    assert capability.state is MatchState.UNKNOWN
    assert capability.matched_evidence == ()


def test_unsupported_experience_band_stays_unknown_not_gap():
    result = calculate_professional_match(
        profile(
            occupations=(
                OccupationFact(title="Backend Engineer", source=FactSource.CANDIDATE_DECLARED),
            ),
            experience_years=8,
        ),
        role(experience_band="expert confirmé"),
        computed_at=NOW,
    )
    experience = component(result, MatchDimension.EXPERIENCE_SENIORITY)
    assert experience.state is MatchState.UNKNOWN
    assert experience.gaps == ()
    assert MatchReasonCode.EXPERIENCE_BAND_UNSUPPORTED in experience.reason_codes


def test_exact_professional_evidence_scores_full_when_fully_covered():
    result = calculate_professional_match(
        profile(
            occupations=(
                OccupationFact(title="Backend Engineer", source=FactSource.CANDIDATE_DECLARED),
            ),
            skills=(
                SkillFact(name="Python", source=FactSource.CANDIDATE_DECLARED),
            ),
        ),
        role(
            skills=(
                RoleSkill(label="Python", source=RoleFactSource.MANUAL),
            ),
        ),
        computed_at=NOW,
    )
    assert result.professional_match_score == 100
    assert result.evidence_coverage == 100
    assert result.match_engine_version == MATCH_ENGINE_VERSION


def test_missing_skill_evidence_reduces_coverage_without_inventing_gap():
    result = calculate_professional_match(
        profile(
            occupations=(
                OccupationFact(title="Backend Engineer", source=FactSource.CANDIDATE_DECLARED),
            )
        ),
        role(
            skills=(
                RoleSkill(label="Python", source=RoleFactSource.MANUAL),
                RoleSkill(label="MongoDB", source=RoleFactSource.MANUAL),
            )
        ),
        computed_at=NOW,
    )
    skills = component(result, MatchDimension.SKILLS)
    assert skills.state is MatchState.UNKNOWN
    assert skills.gaps == ()
    assert skills.evidence_coverage == 0
    assert MatchReasonCode.MISSING_CANDIDATE_EVIDENCE in skills.reason_codes
    assert result.professional_match_score == 100
    assert result.evidence_coverage < 100


def test_explicit_seniority_mismatch_is_a_gap():
    result = calculate_professional_match(
        profile(
            occupations=(
                OccupationFact(title="Backend Engineer", source=FactSource.CANDIDATE_DECLARED),
            ),
            seniority="junior",
        ),
        role(seniority_band="senior"),
        computed_at=NOW,
    )
    experience = component(result, MatchDimension.EXPERIENCE_SENIORITY)
    assert experience.state is MatchState.GAP
    assert experience.score == 0
    assert experience.evidence_coverage == 100


def test_shared_normalization_reference_matches_skill_without_fuzzy_logic():
    result = calculate_professional_match(
        profile(
            occupations=(
                OccupationFact(title="Backend Engineer", source=FactSource.CANDIDATE_DECLARED),
            ),
            skills=(
                SkillFact(
                    name="Py",
                    source=FactSource.CANDIDATE_DECLARED,
                    normalized_name="Python",
                    normalization_ref="taxonomy:v1:skill-python",
                ),
            ),
        ),
        role(
            skills=(
                RoleSkill(
                    label="Python 3",
                    source=RoleFactSource.MANUAL,
                    normalized_code="skill:python",
                    normalization_ref="taxonomy:v1:skill-python",
                ),
            ),
        ),
        computed_at=NOW,
    )
    skills = component(result, MatchDimension.SKILLS)
    assert skills.state is MatchState.MATCH
    assert MatchReasonCode.SHARED_NORMALIZATION_REF in skills.reason_codes


def test_typo_is_not_promoted_to_certain_skill_match():
    result = calculate_professional_match(
        profile(
            occupations=(
                OccupationFact(title="Backend Engineer", source=FactSource.CANDIDATE_DECLARED),
            ),
            skills=(
                SkillFact(name="Pyton", source=FactSource.CANDIDATE_DECLARED),
            ),
        ),
        role(
            skills=(
                RoleSkill(label="Python", source=RoleFactSource.MANUAL),
            ),
        ),
        computed_at=NOW,
    )
    skills = component(result, MatchDimension.SKILLS)
    assert skills.state is MatchState.UNKNOWN
    assert skills.matched_evidence == ()


def test_location_does_not_change_professional_match():
    base = dict(
        occupations=(
            OccupationFact(title="Backend Engineer", source=FactSource.CANDIDATE_DECLARED),
        ),
        skills=(SkillFact(name="Python", source=FactSource.CANDIDATE_DECLARED),),
    )
    target = role(skills=(RoleSkill(label="Python", source=RoleFactSource.MANUAL),))
    paris = calculate_professional_match(profile(current_location="Paris", **base), target, computed_at=NOW)
    lyon = calculate_professional_match(profile(current_location="Lyon", **base), target, computed_at=NOW)
    assert paris.professional_match_score == lyon.professional_match_score
    assert paris.evidence_coverage == lyon.evidence_coverage
    assert paris.components == lyon.components


def test_result_contract_contains_no_opportunity_intent_permission_or_trust():
    fields = ProfessionalMatchResult.__dataclass_fields__
    for forbidden in (
        "salary", "location", "remote", "contract", "availability",
        "intent", "discovery", "permission", "trust", "grant", "cv",
    ):
        assert forbidden not in fields


def test_same_snapshots_and_timestamp_are_reproducible():
    p = profile(
        occupations=(OccupationFact(title="Backend Engineer", source=FactSource.CANDIDATE_DECLARED),)
    )
    r = role()
    first = calculate_professional_match(p, r, computed_at=NOW)
    second = calculate_professional_match(p, r, computed_at=NOW)
    assert first == second


@pytest.mark.asyncio
async def test_service_rejects_unavailable_historical_profile_version():
    class Profiles:
        async def find_one(self, query, **kwargs):
            return {
                "_id": "candidate_profile:c1",
                "candidate_id": "c1",
                "version": 3,
                "created_at": NOW,
                "updated_at": NOW,
                "occupations": [],
                "experiences": [],
                "skills": [],
                "certifications": [],
                "languages": [],
                "industries": [],
                "education": [],
                "portfolio": [],
            }

    class Roles:
        async def find_one(self, query, **kwargs):
            return None

    class DB:
        candidate_profiles = Profiles()
        role_dnas = Roles()

    service = ProfessionalMatchService(DB())
    with pytest.raises(MatchSnapshotUnavailableError):
        await service.compute(
            CandidateId("c1"),
            RoleDNAId("role:backend"),
            EntityVersion(2),
            candidate_profile_version=EntityVersion(2),
            computed_at=NOW,
        )


@pytest.mark.asyncio
async def test_service_reads_exact_requested_role_version():
    captured = {}

    class Profiles:
        async def find_one(self, query, **kwargs):
            return {
                "_id": "candidate_profile:c1",
                "candidate_id": "c1",
                "version": 3,
                "created_at": NOW,
                "updated_at": NOW,
                "occupations": [
                    {
                        "title": "Backend Engineer",
                        "source": "candidate_declared",
                        "normalized_occupation": None,
                        "normalization_ref": None,
                    }
                ],
                "experiences": [],
                "skills": [],
                "certifications": [],
                "languages": [],
                "industries": [],
                "education": [],
                "portfolio": [],
            }

    class Roles:
        async def find_one(self, query, **kwargs):
            captured["query"] = query
            return {
                "_id": "role:backend:v2",
                "role_dna_id": "role:backend",
                "version": 2,
                "status": "active",
                "canonical_title": "Backend Engineer",
                "created_at": NOW,
                "updated_at": NOW,
                "aliases": [],
                "skills": [],
                "capabilities": [],
                "certifications": [],
                "languages": [],
                "transferable_role_refs": [],
                "adjacent_role_refs": [],
                "provenance": "manual",
            }

    class DB:
        candidate_profiles = Profiles()
        role_dnas = Roles()

    result = await ProfessionalMatchService(DB()).compute(
        CandidateId("c1"),
        RoleDNAId("role:backend"),
        EntityVersion(2),
        candidate_profile_version=EntityVersion(3),
        computed_at=NOW,
    )
    assert captured["query"] == {"role_dna_id": "role:backend", "version": 2}
    assert result.role_dna_version == EntityVersion(2)
