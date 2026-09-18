"""TS-B8-001 tests: Anonymous Talent privacy policy."""
import pytest

from domains.privacy.anonymous_talent import (
    ANONYMOUS_TALENT_POLICY_VERSION,
    AnonymousTalentCard,
    AnonymousTalentFacts,
    ExperienceBand,
    EvidenceCoverageBand,
    MatchBand,
    SeniorityBand,
    render_anonymous_talent_card,
)
from domains.matching.opportunity_fit_models import HardEligibilityState, OpportunityFitState


class TestAnonymousTalentFactsContract:
    def test_valid_facts(self):
        facts = AnonymousTalentFacts(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            experience_years=5,
            seniority="senior",
            professional_match_score=75,
            match_evidence_coverage=60,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        assert facts.experience_years == 5
        assert facts.seniority == "senior"

    def test_experience_years_none(self):
        facts = AnonymousTalentFacts(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            experience_years=None,
            seniority=None,
            professional_match_score=50,
            match_evidence_coverage=50,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        assert facts.experience_years is None

    def test_boolean_rejected_on_experience_years(self):
        for bool_val in (True, False):
            with pytest.raises(ValueError):
                AnonymousTalentFacts(
                    card_ref="ts-b8-card-v1:" + "a" * 64,
                    experience_years=bool_val,
                    seniority=None,
                    professional_match_score=50,
                    match_evidence_coverage=50,
                    hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                    opportunity_fit_state=OpportunityFitState.COMPATIBLE,
                )

    def test_boolean_rejected_on_professional_match_score(self):
        for bool_val in (True, False):
            with pytest.raises(ValueError):
                AnonymousTalentFacts(
                    card_ref="ts-b8-card-v1:" + "a" * 64,
                    experience_years=5,
                    seniority=None,
                    professional_match_score=bool_val,
                    match_evidence_coverage=50,
                    hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                    opportunity_fit_state=OpportunityFitState.COMPATIBLE,
                )

    def test_boolean_rejected_on_match_evidence_coverage(self):
        for bool_val in (True, False):
            with pytest.raises(ValueError):
                AnonymousTalentFacts(
                    card_ref="ts-b8-card-v1:" + "a" * 64,
                    experience_years=5,
                    seniority=None,
                    professional_match_score=50,
                    match_evidence_coverage=bool_val,
                    hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                    opportunity_fit_state=OpportunityFitState.COMPATIBLE,
                )

    def test_valid_ints_accepted(self):
        for val in (0, 1, 100):
            facts = AnonymousTalentFacts(
                card_ref="ts-b8-card-v1:" + "a" * 64,
                experience_years=val,
                seniority=None,
                professional_match_score=val,
                match_evidence_coverage=val,
                hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                opportunity_fit_state=OpportunityFitState.COMPATIBLE,
            )
            assert facts.experience_years == val
            assert facts.professional_match_score == val
            assert facts.match_evidence_coverage == val

    def test_invalid_card_ref_rejected(self):
        with pytest.raises(ValueError, match="card_ref must match"):
            AnonymousTalentFacts(
                card_ref="candidate-123",
                experience_years=0,
                seniority=None,
                professional_match_score=50,
                match_evidence_coverage=50,
                hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                opportunity_fit_state=OpportunityFitState.COMPATIBLE,
            )

    def test_invalid_card_ref_formats_rejected(self):
        invalid_refs = [
            "ts-b8-card-v1:" + "A" * 64,
            "ts-b8-card-v1:" + "a" * 63,
            "ts-b8-card-v1:" + "a" * 65,
            "wrong-prefix:" + "a" * 64,
            "email@example.com",
            "",
        ]
        for ref in invalid_refs:
            with pytest.raises(ValueError, match="card_ref must match"):
                AnonymousTalentFacts(
                    card_ref=ref,
                    experience_years=0,
                    seniority=None,
                    professional_match_score=50,
                    match_evidence_coverage=50,
                    hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                    opportunity_fit_state=OpportunityFitState.COMPATIBLE,
                )

    def test_extra_fields_rejected(self):
        with pytest.raises(TypeError):
            AnonymousTalentFacts(
                card_ref="ts-b8-card-v1:" + "a" * 64,
                experience_years=5,
                seniority="senior",
                professional_match_score=75,
                match_evidence_coverage=60,
                hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                opportunity_fit_state=OpportunityFitState.COMPATIBLE,
                candidate_id="candidate-1",
            )

    def test_prohibited_field_names_rejected(self):
        prohibited_fields = [
            "candidate_id",
            "current_employer",
            "current_location",
            "headline",
            "summary",
            "profile_id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "address",
            "company",
            "employer",
            "institution",
            "portfolio",
            "cv",
            "document_id",
            "experience_years_raw",
        ]
        for field in prohibited_fields:
            with pytest.raises(TypeError, match=field):
                AnonymousTalentFacts(
                    card_ref="ts-b8-card-v1:" + "a" * 64,
                    experience_years=5,
                    seniority="senior",
                    professional_match_score=75,
                    match_evidence_coverage=60,
                    hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                    opportunity_fit_state=OpportunityFitState.COMPATIBLE,
                    **{field: "value"}
                )


class TestAnonymousTalentCardContract:
    def test_card_has_exactly_allowed_fields(self):
        card = AnonymousTalentCard(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            policy_version=ANONYMOUS_TALENT_POLICY_VERSION,
            experience_band=ExperienceBand.ESTABLISHED_3_5,
            seniority_band=SeniorityBand.SENIOR,
            professional_match_band=MatchBand.STRONG,
            evidence_coverage_band=EvidenceCoverageBand.MEDIUM,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        fields = set(card.__dataclass_fields__.keys())
        expected = {
            "card_ref", "policy_version", "experience_band", "seniority_band",
            "professional_match_band", "evidence_coverage_band",
            "hard_eligibility_state", "opportunity_fit_state"
        }
        assert fields == expected

    def test_no_pii_field_names(self):
        card = AnonymousTalentCard(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            policy_version=ANONYMOUS_TALENT_POLICY_VERSION,
            experience_band=ExperienceBand.ESTABLISHED_3_5,
            seniority_band=SeniorityBand.SENIOR,
            professional_match_band=MatchBand.STRONG,
            evidence_coverage_band=EvidenceCoverageBand.MEDIUM,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        field_names = [f.lower() for f in card.__dataclass_fields__.keys()]
        prohibited = [
            "candidate", "name", "email", "phone", "location", "employer", "company",
            "cv", "document", "profile", "portfolio", "education", "certification",
            "experience_years", "headline", "summary", "source", "event", "correlation",
            "grant", "permission", "trust", "free_text", "raw", "employer", "institution"
        ]
        for p in prohibited:
            assert not any(p in f for f in field_names), f"Prohibited term '{p}' found in field names"


class TestExperienceBands:
    @pytest.mark.parametrize("years,expected", [
        (None, ExperienceBand.UNKNOWN),
        (0, ExperienceBand.EARLY_0_2),
        (1, ExperienceBand.EARLY_0_2),
        (2, ExperienceBand.EARLY_0_2),
        (3, ExperienceBand.ESTABLISHED_3_5),
        (5, ExperienceBand.ESTABLISHED_3_5),
        (6, ExperienceBand.EXPERIENCED_6_10),
        (10, ExperienceBand.EXPERIENCED_6_10),
        (11, ExperienceBand.ADVANCED_11_15),
        (15, ExperienceBand.ADVANCED_11_15),
        (16, ExperienceBand.VETERAN_16_PLUS),
        (40, ExperienceBand.VETERAN_16_PLUS),
    ])
    def test_experience_boundaries(self, years, expected):
        facts = AnonymousTalentFacts(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            experience_years=years,
            seniority=None,
            professional_match_score=50,
            match_evidence_coverage=50,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        card = render_anonymous_talent_card(facts)
        assert card.experience_band == expected


class TestSeniorityBands:
    @pytest.mark.parametrize("raw,expected", [
        ("junior", SeniorityBand.EARLY_CAREER),
        ("Junior", SeniorityBand.EARLY_CAREER),
        ("JUNIOR", SeniorityBand.EARLY_CAREER),
        ("intern", SeniorityBand.EARLY_CAREER),
        ("internship", SeniorityBand.EARLY_CAREER),
        ("entry", SeniorityBand.EARLY_CAREER),
        ("entry level", SeniorityBand.EARLY_CAREER),
        ("entry-level", SeniorityBand.EARLY_CAREER),
        ("trainee", SeniorityBand.EARLY_CAREER),
        ("mid", SeniorityBand.MID_LEVEL),
        ("mid-level", SeniorityBand.MID_LEVEL),
        ("mid level", SeniorityBand.MID_LEVEL),
        ("intermediate", SeniorityBand.MID_LEVEL),
        ("Senior", SeniorityBand.SENIOR),
        ("senior", SeniorityBand.SENIOR),
        ("sr", SeniorityBand.SENIOR),
        ("lead", SeniorityBand.SENIOR),
        ("principal", SeniorityBand.SENIOR),
        ("staff", SeniorityBand.SENIOR),
        ("manager", SeniorityBand.LEADERSHIP),
        ("head", SeniorityBand.LEADERSHIP),
        ("director", SeniorityBand.LEADERSHIP),
        ("vp", SeniorityBand.LEADERSHIP),
        ("vice president", SeniorityBand.LEADERSHIP),
        ("executive", SeniorityBand.LEADERSHIP),
        ("c-level", SeniorityBand.LEADERSHIP),
        ("c level", SeniorityBand.LEADERSHIP),
        ("cto", SeniorityBand.LEADERSHIP),
        ("ceo", SeniorityBand.LEADERSHIP),
        ("unknown specific title xyz", SeniorityBand.UNKNOWN),
        ("random value", SeniorityBand.UNKNOWN),
        (None, SeniorityBand.UNKNOWN),
    ])
    def test_seniority_mapping(self, raw, expected):
        facts = AnonymousTalentFacts(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            experience_years=5,
            seniority=raw,
            professional_match_score=50,
            match_evidence_coverage=50,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        card = render_anonymous_talent_card(facts)
        assert card.seniority_band == expected, f"raw='{raw}' -> {card.seniority_band}, expected {expected}"


class TestMatchBands:
    @pytest.mark.parametrize("score,expected", [
        (0, MatchBand.LOW),
        (39, MatchBand.LOW),
        (40, MatchBand.MODERATE),
        (59, MatchBand.MODERATE),
        (60, MatchBand.STRONG),
        (79, MatchBand.STRONG),
        (80, MatchBand.VERY_STRONG),
        (89, MatchBand.VERY_STRONG),
        (90, MatchBand.VERY_STRONG),
        (100, MatchBand.VERY_STRONG),
    ])
    def test_match_boundaries(self, score, expected):
        facts = AnonymousTalentFacts(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            experience_years=5,
            seniority="senior",
            professional_match_score=score,
            match_evidence_coverage=50,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        card = render_anonymous_talent_card(facts)
        assert card.professional_match_band == expected


class TestEvidenceBands:
    @pytest.mark.parametrize("coverage,expected", [
        (0, EvidenceCoverageBand.LOW),
        (39, EvidenceCoverageBand.LOW),
        (40, EvidenceCoverageBand.MEDIUM),
        (69, EvidenceCoverageBand.MEDIUM),
        (70, EvidenceCoverageBand.HIGH),
        (100, EvidenceCoverageBand.HIGH),
    ])
    def test_evidence_boundaries(self, coverage, expected):
        facts = AnonymousTalentFacts(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            experience_years=5,
            seniority="senior",
            professional_match_score=50,
            match_evidence_coverage=coverage,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        card = render_anonymous_talent_card(facts)
        assert card.evidence_coverage_band == expected


class TestDeterminism:
    def test_same_input_produces_same_output(self):
        facts = AnonymousTalentFacts(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            experience_years=7,
            seniority="Lead",
            professional_match_score=85,
            match_evidence_coverage=75,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        card1 = render_anonymous_talent_card(facts)
        card2 = render_anonymous_talent_card(facts)
        assert card1 == card2


class TestCardRefValidation:
    def test_valid_card_ref_accepted(self):
        facts = AnonymousTalentFacts(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            experience_years=5,
            seniority="senior",
            professional_match_score=50,
            match_evidence_coverage=50,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        card = render_anonymous_talent_card(facts)
        assert card.card_ref == facts.card_ref

    def test_invalid_card_ref_in_facts_rejected(self):
        with pytest.raises(ValueError):
            AnonymousTalentFacts(
                card_ref="candidate-123",
                experience_years=5,
                seniority="senior",
                professional_match_score=50,
                match_evidence_coverage=50,
                hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                opportunity_fit_state=OpportunityFitState.COMPATIBLE,
            )

    def test_invalid_card_ref_in_card_rejected(self):
        with pytest.raises(ValueError):
            AnonymousTalentCard(
                card_ref="candidate-123",
                policy_version=ANONYMOUS_TALENT_POLICY_VERSION,
                experience_band=ExperienceBand.ESTABLISHED_3_5,
                seniority_band=SeniorityBand.SENIOR,
                professional_match_band=MatchBand.STRONG,
                evidence_coverage_band=EvidenceCoverageBand.MEDIUM,
                hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                opportunity_fit_state=OpportunityFitState.COMPATIBLE,
            )


class TestReprRedacted:
    def test_repr_does_not_expose_content(self):
        card = AnonymousTalentCard(
            card_ref="ts-b8-card-v1:" + "a" * 64,
            policy_version=ANONYMOUS_TALENT_POLICY_VERSION,
            experience_band=ExperienceBand.ESTABLISHED_3_5,
            seniority_band=SeniorityBand.SENIOR,
            professional_match_band=MatchBand.STRONG,
            evidence_coverage_band=EvidenceCoverageBand.MEDIUM,
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
        )
        # repr=False means default dataclass repr is suppressed
        repr_str = repr(card)
        # Should not contain the card_ref value or other fields
        assert "a" * 64 not in repr_str
        # It will show something like AnonymousTalentCard(...)


class TestNoFreeTextFromProfile:
    def test_facts_construction_rejects_free_text_fields(self):
        prohibited = [
            ("headline", "Software Engineer"),
            ("summary", "Experienced developer..."),
            ("experience_description", "Worked at..."),
            ("raw_skills", "Python, Java"),
            ("raw_experience", "Company X..."),
        ]
        for field, value in prohibited:
            with pytest.raises(TypeError, match=field):
                AnonymousTalentFacts(
                    card_ref="ts-b8-card-v1:" + "a" * 64,
                    experience_years=5,
                    seniority="senior",
                    professional_match_score=50,
                    match_evidence_coverage=50,
                    hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                    opportunity_fit_state=OpportunityFitState.COMPATIBLE,
                    **{field: value}
                )


class TestOpportunityFitStates:
    def test_hard_eligibility_states_preserved(self):
        for state in [HardEligibilityState.ELIGIBLE, HardEligibilityState.INELIGIBLE, HardEligibilityState.UNRESOLVED]:
            facts = AnonymousTalentFacts(
                card_ref="ts-b8-card-v1:" + "a" * 64,
                experience_years=5,
                seniority="senior",
                professional_match_score=50,
                match_evidence_coverage=50,
                hard_eligibility_state=state,
                opportunity_fit_state=OpportunityFitState.COMPATIBLE,
            )
            card = render_anonymous_talent_card(facts)
            assert card.hard_eligibility_state == state

    def test_opportunity_fit_states_preserved(self):
        for state in [
            OpportunityFitState.COMPATIBLE,
            OpportunityFitState.INCOMPATIBLE,
            OpportunityFitState.UNRESOLVED,
            OpportunityFitState.NOT_APPLICABLE,
        ]:
            facts = AnonymousTalentFacts(
                card_ref="ts-b8-card-v1:" + "a" * 64,
                experience_years=5,
                seniority="senior",
                professional_match_score=50,
                match_evidence_coverage=50,
                hard_eligibility_state=HardEligibilityState.ELIGIBLE,
                opportunity_fit_state=state,
            )
            card = render_anonymous_talent_card(facts)
            assert card.opportunity_fit_state == state