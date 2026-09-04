from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from domains.matching.opportunity_fit_engine import OPPORTUNITY_FIT_ENGINE_VERSION, calculate_opportunity_fit
from domains.matching.opportunity_fit_models import (
    HardEligibilityState, OpportunityFitDimension, OpportunityFitReasonCode,
    OpportunityFitResult, OpportunityFitState,
)
from domains.matching.opportunity_fit_service import (
    OpportunityFitInputNotFoundError, OpportunityFitService,
    OpportunityFitSnapshotUnavailableError,
)
from domains.opportunities.models import (
    CompensationBasis, CompensationConstraint, LocationConstraint,
    OpportunitySpecification, OpportunitySpecStatus, WorkArrangement,
)
from domains.preferences.models import (
    CandidatePreferences, CompensationPreference, MobilityPreference, WorkMode,
)
from domains.shared.ids import CandidateId, CandidatePreferencesId, OpportunitySpecId
from domains.shared.versioning import EntityVersion

NOW = datetime(2026, 9, 4, tzinfo=timezone.utc)


def prefs(**overrides):
    values = dict(
        preferences_id=CandidatePreferencesId("candidate_preferences:c1"),
        candidate_id=CandidateId("c1"), version=EntityVersion(3),
        created_at=NOW, updated_at=NOW,
    )
    values.update(overrides)
    return CandidatePreferences(**values)


def opportunity(**overrides):
    values = dict(
        opportunity_spec_id=OpportunitySpecId("opp:1"), version=EntityVersion(2),
        status=OpportunitySpecStatus.ACTIVE, created_at=NOW, updated_at=NOW,
    )
    values.update(overrides)
    return OpportunitySpecification(**values)


def comp(result, dimension):
    return next(item for item in result.components if item.dimension is dimension)


def test_engine_version_is_explicit():
    assert OPPORTUNITY_FIT_ENGINE_VERSION == "opportunity-fit-v1.0.0"


def test_result_contract_has_no_opaque_or_forbidden_dimensions():
    fields = OpportunityFitResult.__dataclass_fields__
    for forbidden in ("professional_match", "intent", "discovery", "permission", "trust", "fit_score", "cv"):
        assert forbidden not in fields


@pytest.mark.parametrize("candidate,expected", [
    (WorkMode.REMOTE, OpportunityFitState.COMPATIBLE),
    (WorkMode.ONSITE, OpportunityFitState.INCOMPATIBLE),
])
def test_work_arrangement_exact_or_mismatch(candidate, expected):
    result = calculate_opportunity_fit(
        prefs(work_mode=candidate), opportunity(work_arrangement=WorkArrangement.REMOTE), computed_at=NOW
    )
    value = comp(result, OpportunityFitDimension.WORK_ARRANGEMENT)
    assert value.state is expected
    assert value.hard_eligibility_relevant is True


def test_work_mode_any_default_is_not_positive_proof():
    value = comp(
        calculate_opportunity_fit(prefs(), opportunity(work_arrangement=WorkArrangement.REMOTE), computed_at=NOW),
        OpportunityFitDimension.WORK_ARRANGEMENT,
    )
    assert value.state is OpportunityFitState.UNRESOLVED
    assert value.hard_eligibility_relevant is True
    assert OpportunityFitReasonCode.CANDIDATE_DEFAULT_NOT_PROOF in value.reason_codes


def test_specific_work_mode_with_unknown_spec_is_hard_unresolved():
    value = comp(
        calculate_opportunity_fit(prefs(work_mode=WorkMode.HYBRID), opportunity(), computed_at=NOW),
        OpportunityFitDimension.WORK_ARRANGEMENT,
    )
    assert value.state is OpportunityFitState.UNRESOLVED and value.hard_eligibility_relevant


@pytest.mark.parametrize("candidate,offered,expected", [
    (("CDI",), ("CDI",), OpportunityFitState.COMPATIBLE),
    (("cdi",), ("CDI",), OpportunityFitState.COMPATIBLE),
    (("CDI",), ("freelance",), OpportunityFitState.INCOMPATIBLE),
])
def test_contract_comparison(candidate, offered, expected):
    value = comp(
        calculate_opportunity_fit(prefs(contract_types=candidate), opportunity(contract_types=offered), computed_at=NOW),
        OpportunityFitDimension.CONTRACT,
    )
    assert value.state is expected


def test_empty_candidate_contract_default_is_not_positive_proof():
    value = comp(
        calculate_opportunity_fit(prefs(), opportunity(contract_types=("CDI",)), computed_at=NOW),
        OpportunityFitDimension.CONTRACT,
    )
    assert value.state is OpportunityFitState.UNRESOLVED and value.hard_eligibility_relevant


def test_explicit_empty_opportunity_contract_is_no_constraint():
    value = comp(
        calculate_opportunity_fit(prefs(contract_types=("CDI",)), opportunity(contract_types=()), computed_at=NOW),
        OpportunityFitDimension.CONTRACT,
    )
    assert value.state is OpportunityFitState.NOT_APPLICABLE


def test_unknown_contract_spec_is_unresolved_for_declared_candidate_boundary():
    value = comp(
        calculate_opportunity_fit(prefs(contract_types=("CDI",)), opportunity(contract_types=None), computed_at=NOW),
        OpportunityFitDimension.CONTRACT,
    )
    assert value.state is OpportunityFitState.UNRESOLVED and value.hard_eligibility_relevant


def test_compensation_same_currency_still_unresolved_without_candidate_basis():
    value = comp(calculate_opportunity_fit(
        prefs(compensation=CompensationPreference(minimum=60000, target=70000, currency="EUR")),
        opportunity(compensation=CompensationConstraint(minimum=65000, maximum=80000, currency="EUR", basis=CompensationBasis.ANNUAL)),
        computed_at=NOW,
    ), OpportunityFitDimension.COMPENSATION)
    assert value.state is OpportunityFitState.UNRESOLVED
    assert OpportunityFitReasonCode.COMPENSATION_BASIS_UNAVAILABLE in value.reason_codes
    assert value.hard_eligibility_relevant


def test_compensation_currency_difference_never_becomes_mismatch():
    value = comp(calculate_opportunity_fit(
        prefs(compensation=CompensationPreference(minimum=60000, currency="EUR")),
        opportunity(compensation=CompensationConstraint(maximum=90000, currency="USD")), computed_at=NOW,
    ), OpportunityFitDimension.COMPENSATION)
    assert value.state is OpportunityFitState.UNRESOLVED
    assert OpportunityFitReasonCode.CURRENCY_NOT_COMPARABLE in value.reason_codes


def test_compensation_target_only_is_soft_unresolved():
    value = comp(calculate_opportunity_fit(
        prefs(compensation=CompensationPreference(target=70000)),
        opportunity(compensation=CompensationConstraint(maximum=90000)), computed_at=NOW,
    ), OpportunityFitDimension.COMPENSATION)
    assert not value.hard_eligibility_relevant


def test_candidate_minimum_with_unknown_compensation_spec_is_hard_unresolved():
    value = comp(calculate_opportunity_fit(
        prefs(compensation=CompensationPreference(minimum=60000)), opportunity(), computed_at=NOW,
    ), OpportunityFitDimension.COMPENSATION)
    assert value.state is OpportunityFitState.UNRESOLVED and value.hard_eligibility_relevant


def test_location_exact_normalized_text_is_positive_evidence():
    value = comp(calculate_opportunity_fit(
        prefs(mobility=MobilityPreference(locations=("Paris",))),
        opportunity(location=LocationConstraint(locations=(" paris ",))), computed_at=NOW,
    ), OpportunityFitDimension.LOCATION_MOBILITY)
    assert value.state is OpportunityFitState.COMPATIBLE


@pytest.mark.parametrize("offered", [("Versailles",), ("Paris 8e",)])
def test_location_non_exact_match_stays_unresolved(offered):
    value = comp(calculate_opportunity_fit(
        prefs(mobility=MobilityPreference(locations=("Paris",), radius_km=30)),
        opportunity(location=LocationConstraint(locations=offered, radius_km=10)), computed_at=NOW,
    ), OpportunityFitDimension.LOCATION_MOBILITY)
    assert value.state is OpportunityFitState.UNRESOLVED
    assert OpportunityFitReasonCode.GEO_NORMALIZATION_REQUIRED in value.reason_codes


def test_declared_location_with_unknown_spec_is_hard_unresolved():
    value = comp(calculate_opportunity_fit(
        prefs(mobility=MobilityPreference(locations=("Lyon",))), opportunity(), computed_at=NOW,
    ), OpportunityFitDimension.LOCATION_MOBILITY)
    assert value.state is OpportunityFitState.UNRESOLVED and value.hard_eligibility_relevant


def test_availability_exact_text_is_compatible():
    value = comp(calculate_opportunity_fit(
        prefs(availability="1 month"), opportunity(target_start=" 1 MONTH "), computed_at=NOW,
    ), OpportunityFitDimension.AVAILABILITY)
    assert value.state is OpportunityFitState.COMPATIBLE


def test_availability_difference_is_unresolved_not_mismatch():
    value = comp(calculate_opportunity_fit(
        prefs(availability="1 month"), opportunity(target_start="ASAP"), computed_at=NOW,
    ), OpportunityFitDimension.AVAILABILITY)
    assert value.state is OpportunityFitState.UNRESOLVED
    assert OpportunityFitReasonCode.FREE_TEXT_NOT_COMPARABLE in value.reason_codes


def test_declared_availability_with_unknown_target_is_hard_unresolved():
    value = comp(calculate_opportunity_fit(
        prefs(availability="ASAP"), opportunity(), computed_at=NOW,
    ), OpportunityFitDimension.AVAILABILITY)
    assert value.state is OpportunityFitState.UNRESOLVED and value.hard_eligibility_relevant


def test_schedule_present_is_unresolved_hard_without_candidate_field():
    value = comp(calculate_opportunity_fit(prefs(), opportunity(schedule="night shift"), computed_at=NOW), OpportunityFitDimension.SCHEDULE)
    assert value.state is OpportunityFitState.UNRESOLVED and value.hard_eligibility_relevant


def test_schedule_unknown_is_unresolved_but_not_hard_relevant():
    value = comp(calculate_opportunity_fit(prefs(), opportunity(), computed_at=NOW), OpportunityFitDimension.SCHEDULE)
    assert value.state is OpportunityFitState.UNRESOLVED and not value.hard_eligibility_relevant


@pytest.mark.parametrize("field,dimension", [
    ("industry_constraints", OpportunityFitDimension.INDUSTRY),
    ("company_constraints", OpportunityFitDimension.COMPANY),
    ("must_have_requirements", OpportunityFitDimension.MUST_HAVE),
])
def test_unmapped_present_hard_constraint_stays_unresolved(field, dimension):
    value = comp(calculate_opportunity_fit(prefs(), opportunity(**{field: ("required",)}), computed_at=NOW), dimension)
    assert value.state is OpportunityFitState.UNRESOLVED and value.hard_eligibility_relevant


def test_nice_to_have_never_becomes_hard_eligibility_gate():
    value = comp(calculate_opportunity_fit(
        prefs(), opportunity(nice_to_have_requirements=("bonus",)), computed_at=NOW,
    ), OpportunityFitDimension.NICE_TO_HAVE)
    assert value.state is OpportunityFitState.UNRESOLVED and not value.hard_eligibility_relevant


def test_explicit_empty_unmapped_list_is_not_applicable():
    value = comp(calculate_opportunity_fit(prefs(), opportunity(industry_constraints=()), computed_at=NOW), OpportunityFitDimension.INDUSTRY)
    assert value.state is OpportunityFitState.NOT_APPLICABLE


def test_hard_incompatibility_wins_over_unresolved():
    result = calculate_opportunity_fit(
        prefs(work_mode=WorkMode.REMOTE, contract_types=("CDI",)),
        opportunity(work_arrangement=WorkArrangement.ONSITE, contract_types=None), computed_at=NOW,
    )
    assert result.hard_eligibility_state is HardEligibilityState.INELIGIBLE


def test_hard_unresolved_when_relevant_unknown_exists():
    result = calculate_opportunity_fit(prefs(work_mode=WorkMode.REMOTE), opportunity(), computed_at=NOW)
    assert result.hard_eligibility_state is HardEligibilityState.UNRESOLVED


def test_hard_eligible_when_all_hard_relevant_dimensions_are_resolved():
    result = calculate_opportunity_fit(
        prefs(work_mode=WorkMode.REMOTE, contract_types=("CDI",)),
        opportunity(
            work_arrangement=WorkArrangement.REMOTE, contract_types=("CDI",),
            industry_constraints=(), company_constraints=(),
            must_have_requirements=(), nice_to_have_requirements=(),
        ), computed_at=NOW,
    )
    assert result.hard_eligibility_state is HardEligibilityState.ELIGIBLE


def test_overall_opportunity_fit_preserves_unresolved_even_without_hard_blocker():
    result = calculate_opportunity_fit(
        prefs(compensation=CompensationPreference(target=70000)),
        opportunity(compensation=CompensationConstraint(maximum=90000), contract_types=()),
        computed_at=NOW,
    )
    assert result.opportunity_fit_state is OpportunityFitState.UNRESOLVED


def test_overall_opportunity_fit_is_incompatible_when_any_component_is_incompatible():
    result = calculate_opportunity_fit(
        prefs(work_mode=WorkMode.REMOTE),
        opportunity(work_arrangement=WorkArrangement.ONSITE), computed_at=NOW,
    )
    assert result.opportunity_fit_state is OpportunityFitState.INCOMPATIBLE


def test_no_expressed_fit_constraints_is_not_applicable_not_false_compatible():
    result = calculate_opportunity_fit(prefs(), opportunity(contract_types=(), industry_constraints=(), company_constraints=(), must_have_requirements=(), nice_to_have_requirements=()), computed_at=NOW)
    assert result.opportunity_fit_state is OpportunityFitState.NOT_APPLICABLE
    assert result.evidence_coverage == 100


def test_explicit_opportunity_constraint_with_default_candidate_keeps_fit_unresolved():
    result = calculate_opportunity_fit(prefs(), opportunity(work_arrangement=WorkArrangement.REMOTE), computed_at=NOW)
    assert result.opportunity_fit_state is OpportunityFitState.UNRESOLVED
    assert result.hard_eligibility_state is HardEligibilityState.UNRESOLVED


def test_evidence_coverage_is_separate_from_hard_eligibility():
    result = calculate_opportunity_fit(
        prefs(work_mode=WorkMode.REMOTE), opportunity(work_arrangement=WorkArrangement.ONSITE), computed_at=NOW,
    )
    assert result.hard_eligibility_state is HardEligibilityState.INELIGIBLE
    assert 0 <= result.evidence_coverage <= 100


def test_result_is_reproducible_with_fixed_timestamp():
    args = (prefs(work_mode=WorkMode.REMOTE), opportunity(work_arrangement=WorkArrangement.REMOTE))
    assert calculate_opportunity_fit(*args, computed_at=NOW) == calculate_opportunity_fit(*args, computed_at=NOW)


def test_exclusions_and_discovery_are_not_consumed_as_fit_evidence():
    result = calculate_opportunity_fit(
        prefs(excluded_company_ids=("company:x",), current_employer_company_id="company:y"),
        opportunity(company_constraints=()), computed_at=NOW,
    )
    rendered = repr(result)
    assert "company:x" not in rendered and "company:y" not in rendered
    assert "discovery" not in rendered.casefold()


class FakePreferencesRepo:
    def __init__(self, doc): self.doc, self.calls = doc, []
    async def get(self, candidate_id): self.calls.append(candidate_id); return self.doc


class FakeOpportunityRepo:
    def __init__(self, doc): self.doc, self.calls = doc, []
    async def get(self, spec_id, version): self.calls.append((spec_id, version)); return self.doc


def pref_doc(version=3):
    return {
        "_id": "candidate_preferences:c1", "candidate_id": "c1", "version": version,
        "created_at": NOW, "updated_at": NOW, "search_state": "passive",
        "discovery": {"enabled": False}, "target_roles": [], "work_mode": "remote",
        "contract_types": ["CDI"], "excluded_company_ids": ["company:x"],
    }


def opp_doc(version=2):
    return {
        "_id": "opp:1:v2", "opportunity_spec_id": "opp:1", "version": version,
        "status": "active", "created_at": NOW, "updated_at": NOW,
        "work_arrangement": "remote", "contract_types": ["CDI"],
        "industry_constraints": [], "company_constraints": [],
        "must_have_requirements": [], "nice_to_have_requirements": [],
        "provenance": "manual",
    }


def service(pref=None, opp=None):
    instance = OpportunityFitService(SimpleNamespace(candidate_preferences=None, opportunity_specs=None))
    instance.preferences_repo = FakePreferencesRepo(pref)
    instance.opportunity_repo = FakeOpportunityRepo(opp)
    return instance


@pytest.mark.asyncio
async def test_service_rejects_stale_preferences_version():
    instance = service(pref_doc(3), opp_doc(2))
    with pytest.raises(OpportunityFitSnapshotUnavailableError):
        await instance.compute(
            CandidateId("c1"), OpportunitySpecId("opp:1"), EntityVersion(2),
            candidate_preferences_version=EntityVersion(2), computed_at=NOW,
        )


@pytest.mark.asyncio
async def test_service_queries_exact_opportunity_version_and_returns_real_versions():
    instance = service(pref_doc(3), opp_doc(2))
    result = await instance.compute(
        CandidateId("c1"), OpportunitySpecId("opp:1"), EntityVersion(2),
        candidate_preferences_version=EntityVersion(3), computed_at=NOW,
    )
    assert instance.opportunity_repo.calls == [("opp:1", 2)]
    assert result.opportunity_spec_version == 2 and result.candidate_preferences_version == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["preferences", "opportunity"])
async def test_service_missing_input_is_explicit_error(missing):
    instance = service(None if missing == "preferences" else pref_doc(), None if missing == "opportunity" else opp_doc())
    with pytest.raises(OpportunityFitInputNotFoundError):
        await instance.compute(CandidateId("c1"), OpportunitySpecId("opp:1"), EntityVersion(2))
