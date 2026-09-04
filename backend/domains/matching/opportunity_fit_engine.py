"""Pure deterministic Hard Eligibility / Opportunity Fit engine v1.

Only Candidate Preferences A2 and Opportunity Specification A4 participate.
Professional Match, Discovery, Intent, Trust, Permission, exclusions and CV access
are deliberately absent.
"""
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence, Tuple

from domains.opportunities.models import OpportunitySpecification
from domains.preferences.models import CandidatePreferences, WorkMode
from domains.shared.versioning import EngineVersion
from .opportunity_fit_models import (
    HardEligibilityState,
    OpportunityFitComponent,
    OpportunityFitDimension,
    OpportunityFitReasonCode,
    OpportunityFitResult,
    OpportunityFitState,
)


OPPORTUNITY_FIT_ENGINE_VERSION = EngineVersion("opportunity-fit-v1.0.0")


def _norm(value: Optional[str]) -> str:
    return " ".join((value or "").casefold().split())


def _values(prefix: str, values: Iterable[str]) -> Tuple[str, ...]:
    return tuple(f"{prefix}:{value}" for value in values)


def _component(
    dimension: OpportunityFitDimension,
    state: OpportunityFitState,
    *,
    fit_relevant: bool,
    hard: bool,
    reasons: Sequence[OpportunityFitReasonCode],
    candidate: Sequence[str] = (),
    opportunity: Sequence[str] = (),
) -> OpportunityFitComponent:
    return OpportunityFitComponent(
        dimension=dimension,
        state=state,
        fit_relevant=fit_relevant,
        hard_eligibility_relevant=hard,
        reason_codes=tuple(dict.fromkeys(reasons)),
        candidate_evidence=tuple(candidate),
        opportunity_evidence=tuple(opportunity),
    )


def _compensation_component(
    preferences: CandidatePreferences,
    opportunity: OpportunitySpecification,
) -> OpportunityFitComponent:
    candidate = preferences.compensation
    constraint = opportunity.compensation
    hard = candidate is not None and candidate.minimum is not None

    if candidate is None and constraint is None:
        return _component(
            OpportunityFitDimension.COMPENSATION,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=False,
            hard=False,
            reasons=(
                OpportunityFitReasonCode.SPEC_UNSPECIFIED,
                OpportunityFitReasonCode.CANDIDATE_PREFERENCE_MISSING,
            ),
        )
    if constraint is None:
        evidence = () if candidate is None else (
            f"currency:{candidate.currency}",
            *(() if candidate.minimum is None else (f"minimum:{candidate.minimum}",)),
            *(() if candidate.target is None else (f"target:{candidate.target}",)),
        )
        return _component(
            OpportunityFitDimension.COMPENSATION,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=True,
            hard=hard,
            reasons=(OpportunityFitReasonCode.SPEC_UNSPECIFIED,),
            candidate=evidence,
        )
    opportunity_evidence = (
        f"currency:{constraint.currency}",
        *(() if constraint.minimum is None else (f"minimum:{constraint.minimum}",)),
        *(() if constraint.maximum is None else (f"maximum:{constraint.maximum}",)),
        *(() if constraint.basis is None else (f"basis:{constraint.basis.value}",)),
    )
    if candidate is None:
        return _component(
            OpportunityFitDimension.COMPENSATION,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=True,
            hard=False,
            reasons=(OpportunityFitReasonCode.CANDIDATE_PREFERENCE_MISSING,),
            opportunity=opportunity_evidence,
        )
    candidate_evidence = (
        f"currency:{candidate.currency}",
        *(() if candidate.minimum is None else (f"minimum:{candidate.minimum}",)),
        *(() if candidate.target is None else (f"target:{candidate.target}",)),
    )
    if _norm(candidate.currency) != _norm(constraint.currency):
        return _component(
            OpportunityFitDimension.COMPENSATION,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=True,
            hard=hard,
            reasons=(OpportunityFitReasonCode.CURRENCY_NOT_COMPARABLE,),
            candidate=candidate_evidence,
            opportunity=opportunity_evidence,
        )
    return _component(
        OpportunityFitDimension.COMPENSATION,
        OpportunityFitState.UNRESOLVED,
        fit_relevant=True,
        hard=hard,
        reasons=(OpportunityFitReasonCode.COMPENSATION_BASIS_UNAVAILABLE,),
        candidate=candidate_evidence,
        opportunity=opportunity_evidence,
    )


def _location_component(
    preferences: CandidatePreferences,
    opportunity: OpportunitySpecification,
) -> OpportunityFitComponent:
    mobility = preferences.mobility
    constraint = opportunity.location
    candidate_locations = () if mobility is None else tuple(mobility.locations)
    hard = bool(candidate_locations)

    if constraint is None:
        return _component(
            OpportunityFitDimension.LOCATION_MOBILITY,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=bool(candidate_locations),
            hard=hard,
            reasons=(OpportunityFitReasonCode.SPEC_UNSPECIFIED,),
            candidate=_values("location", candidate_locations),
        )
    opportunity_locations = tuple(constraint.locations)
    if not candidate_locations:
        return _component(
            OpportunityFitDimension.LOCATION_MOBILITY,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=True,
            hard=True,
            reasons=(OpportunityFitReasonCode.CANDIDATE_PREFERENCE_MISSING,),
            opportunity=_values("location", opportunity_locations),
        )
    candidate_terms = {_norm(value) for value in candidate_locations if _norm(value)}
    opportunity_terms = {_norm(value) for value in opportunity_locations if _norm(value)}
    if candidate_terms & opportunity_terms:
        return _component(
            OpportunityFitDimension.LOCATION_MOBILITY,
            OpportunityFitState.COMPATIBLE,
            fit_relevant=True,
            hard=True,
            reasons=(OpportunityFitReasonCode.EXACT_TEXT_MATCH,),
            candidate=_values("location", candidate_locations),
            opportunity=_values("location", opportunity_locations),
        )
    return _component(
        OpportunityFitDimension.LOCATION_MOBILITY,
        OpportunityFitState.UNRESOLVED,
        fit_relevant=True,
        hard=True,
        reasons=(OpportunityFitReasonCode.GEO_NORMALIZATION_REQUIRED,),
        candidate=_values("location", candidate_locations),
        opportunity=_values("location", opportunity_locations),
    )


def _work_arrangement_component(
    preferences: CandidatePreferences,
    opportunity: OpportunitySpecification,
) -> OpportunityFitComponent:
    candidate = preferences.work_mode
    constraint = opportunity.work_arrangement

    if candidate is WorkMode.ANY:
        return _component(
            OpportunityFitDimension.WORK_ARRANGEMENT,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=constraint is not None,
            hard=constraint is not None,
            reasons=(OpportunityFitReasonCode.CANDIDATE_DEFAULT_NOT_PROOF,),
            candidate=(f"work_mode:{candidate.value}",),
            opportunity=(
                () if constraint is None else (f"work_arrangement:{constraint.value}",)
            ),
        )
    if constraint is None:
        return _component(
            OpportunityFitDimension.WORK_ARRANGEMENT,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=True,
            hard=True,
            reasons=(OpportunityFitReasonCode.SPEC_UNSPECIFIED,),
            candidate=(f"work_mode:{candidate.value}",),
        )
    if candidate.value == constraint.value:
        return _component(
            OpportunityFitDimension.WORK_ARRANGEMENT,
            OpportunityFitState.COMPATIBLE,
            fit_relevant=True,
            hard=True,
            reasons=(OpportunityFitReasonCode.EXPLICIT_MATCH,),
            candidate=(f"work_mode:{candidate.value}",),
            opportunity=(f"work_arrangement:{constraint.value}",),
        )
    return _component(
        OpportunityFitDimension.WORK_ARRANGEMENT,
        OpportunityFitState.INCOMPATIBLE,
        fit_relevant=True,
        hard=True,
        reasons=(OpportunityFitReasonCode.EXPLICIT_MISMATCH,),
        candidate=(f"work_mode:{candidate.value}",),
        opportunity=(f"work_arrangement:{constraint.value}",),
    )


def _contract_component(
    preferences: CandidatePreferences,
    opportunity: OpportunitySpecification,
) -> OpportunityFitComponent:
    candidate_values = tuple(preferences.contract_types)
    opportunity_values = opportunity.contract_types

    if opportunity_values == ():
        return _component(
            OpportunityFitDimension.CONTRACT,
            OpportunityFitState.NOT_APPLICABLE,
            fit_relevant=False,
            hard=False,
            reasons=(OpportunityFitReasonCode.EXPLICIT_NO_CONSTRAINT,),
            candidate=_values("contract", candidate_values),
        )
    if not candidate_values:
        return _component(
            OpportunityFitDimension.CONTRACT,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=opportunity_values is not None,
            hard=opportunity_values is not None,
            reasons=(OpportunityFitReasonCode.CANDIDATE_DEFAULT_NOT_PROOF,),
            opportunity=(
                ()
                if opportunity_values is None
                else _values("contract", opportunity_values)
            ),
        )
    if opportunity_values is None:
        return _component(
            OpportunityFitDimension.CONTRACT,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=True,
            hard=True,
            reasons=(OpportunityFitReasonCode.SPEC_UNSPECIFIED,),
            candidate=_values("contract", candidate_values),
        )
    candidate_terms = {_norm(value) for value in candidate_values if _norm(value)}
    opportunity_terms = {_norm(value) for value in opportunity_values if _norm(value)}
    if candidate_terms & opportunity_terms:
        return _component(
            OpportunityFitDimension.CONTRACT,
            OpportunityFitState.COMPATIBLE,
            fit_relevant=True,
            hard=True,
            reasons=(OpportunityFitReasonCode.CONTRACT_OVERLAP,),
            candidate=_values("contract", candidate_values),
            opportunity=_values("contract", opportunity_values),
        )
    return _component(
        OpportunityFitDimension.CONTRACT,
        OpportunityFitState.INCOMPATIBLE,
        fit_relevant=True,
        hard=True,
        reasons=(OpportunityFitReasonCode.CONTRACT_NO_OVERLAP,),
        candidate=_values("contract", candidate_values),
        opportunity=_values("contract", opportunity_values),
    )


def _availability_component(
    preferences: CandidatePreferences,
    opportunity: OpportunitySpecification,
) -> OpportunityFitComponent:
    candidate = preferences.availability
    target = opportunity.target_start
    hard = candidate is not None and target is not None

    if candidate is None and target is None:
        return _component(
            OpportunityFitDimension.AVAILABILITY,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=False,
            hard=False,
            reasons=(
                OpportunityFitReasonCode.SPEC_UNSPECIFIED,
                OpportunityFitReasonCode.CANDIDATE_PREFERENCE_MISSING,
            ),
        )
    if candidate is None:
        return _component(
            OpportunityFitDimension.AVAILABILITY,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=True,
            hard=True,
            reasons=(OpportunityFitReasonCode.CANDIDATE_PREFERENCE_MISSING,),
            opportunity=(f"target_start:{target}",),
        )
    if target is None:
        return _component(
            OpportunityFitDimension.AVAILABILITY,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=True,
            hard=True,
            reasons=(OpportunityFitReasonCode.SPEC_UNSPECIFIED,),
            candidate=(f"availability:{candidate}",),
        )
    if _norm(candidate) == _norm(target):
        return _component(
            OpportunityFitDimension.AVAILABILITY,
            OpportunityFitState.COMPATIBLE,
            fit_relevant=True,
            hard=True,
            reasons=(OpportunityFitReasonCode.EXACT_TEXT_MATCH,),
            candidate=(f"availability:{candidate}",),
            opportunity=(f"target_start:{target}",),
        )
    return _component(
        OpportunityFitDimension.AVAILABILITY,
        OpportunityFitState.UNRESOLVED,
        fit_relevant=True,
        hard=hard,
        reasons=(OpportunityFitReasonCode.FREE_TEXT_NOT_COMPARABLE,),
        candidate=(f"availability:{candidate}",),
        opportunity=(f"target_start:{target}",),
    )


def _unmapped_scalar_component(
    dimension: OpportunityFitDimension,
    value: Optional[str],
) -> OpportunityFitComponent:
    if value is None:
        return _component(
            dimension,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=False,
            hard=False,
            reasons=(OpportunityFitReasonCode.SPEC_UNSPECIFIED,),
        )
    return _component(
        dimension,
        OpportunityFitState.UNRESOLVED,
        fit_relevant=True,
        hard=True,
        reasons=(OpportunityFitReasonCode.NO_CANDIDATE_PREFERENCE_FIELD,),
        opportunity=(f"{dimension.value}:{value}",),
    )


def _unmapped_list_component(
    dimension: OpportunityFitDimension,
    values: Optional[Tuple[str, ...]],
    *,
    hard_if_present: bool,
) -> OpportunityFitComponent:
    if values == ():
        return _component(
            dimension,
            OpportunityFitState.NOT_APPLICABLE,
            fit_relevant=False,
            hard=False,
            reasons=(OpportunityFitReasonCode.EXPLICIT_NO_CONSTRAINT,),
        )
    if values is None:
        return _component(
            dimension,
            OpportunityFitState.UNRESOLVED,
            fit_relevant=False,
            hard=False,
            reasons=(OpportunityFitReasonCode.SPEC_UNSPECIFIED,),
        )
    return _component(
        dimension,
        OpportunityFitState.UNRESOLVED,
        fit_relevant=True,
        hard=hard_if_present,
        reasons=(
            OpportunityFitReasonCode.NO_CANDIDATE_PREFERENCE_FIELD,
            OpportunityFitReasonCode.OPPORTUNITY_SPEC_CONSTRAINT_PRESENT,
        ),
        opportunity=_values(dimension.value, values),
    )


def _hard_eligibility(
    components: Sequence[OpportunityFitComponent],
) -> HardEligibilityState:
    relevant = [
        component for component in components if component.hard_eligibility_relevant
    ]
    if any(
        component.state is OpportunityFitState.INCOMPATIBLE for component in relevant
    ):
        return HardEligibilityState.INELIGIBLE
    if any(
        component.state is OpportunityFitState.UNRESOLVED for component in relevant
    ):
        return HardEligibilityState.UNRESOLVED
    return HardEligibilityState.ELIGIBLE


def _overall_fit(components: Sequence[OpportunityFitComponent]) -> OpportunityFitState:
    relevant = [component for component in components if component.fit_relevant]
    if any(
        component.state is OpportunityFitState.INCOMPATIBLE for component in relevant
    ):
        return OpportunityFitState.INCOMPATIBLE
    if any(
        component.state is OpportunityFitState.UNRESOLVED for component in relevant
    ):
        return OpportunityFitState.UNRESOLVED
    if any(
        component.state is OpportunityFitState.COMPATIBLE for component in relevant
    ):
        return OpportunityFitState.COMPATIBLE
    return OpportunityFitState.NOT_APPLICABLE


def _coverage(components: Sequence[OpportunityFitComponent]) -> int:
    considered = [component for component in components if component.fit_relevant]
    if not considered:
        return 100
    resolved = [
        component
        for component in considered
        if component.state
        in {OpportunityFitState.COMPATIBLE, OpportunityFitState.INCOMPATIBLE}
    ]
    return int(round(100 * len(resolved) / len(considered)))


def calculate_opportunity_fit(
    preferences: CandidatePreferences,
    opportunity: OpportunitySpecification,
    *,
    engine_version: EngineVersion = OPPORTUNITY_FIT_ENGINE_VERSION,
    computed_at: Optional[datetime] = None,
) -> OpportunityFitResult:
    """Compute A6 compatibility from candidate preferences and opportunity facts only."""
    components = (
        _compensation_component(preferences, opportunity),
        _location_component(preferences, opportunity),
        _work_arrangement_component(preferences, opportunity),
        _contract_component(preferences, opportunity),
        _availability_component(preferences, opportunity),
        _unmapped_scalar_component(
            OpportunityFitDimension.SCHEDULE, opportunity.schedule
        ),
        _unmapped_list_component(
            OpportunityFitDimension.INDUSTRY,
            opportunity.industry_constraints,
            hard_if_present=True,
        ),
        _unmapped_list_component(
            OpportunityFitDimension.COMPANY,
            opportunity.company_constraints,
            hard_if_present=True,
        ),
        _unmapped_list_component(
            OpportunityFitDimension.MUST_HAVE,
            opportunity.must_have_requirements,
            hard_if_present=True,
        ),
        _unmapped_list_component(
            OpportunityFitDimension.NICE_TO_HAVE,
            opportunity.nice_to_have_requirements,
            hard_if_present=False,
        ),
    )
    return OpportunityFitResult(
        candidate_id=preferences.candidate_id,
        candidate_preferences_version=preferences.version,
        opportunity_spec_id=opportunity.opportunity_spec_id,
        opportunity_spec_version=opportunity.version,
        engine_version=engine_version,
        hard_eligibility_state=_hard_eligibility(components),
        opportunity_fit_state=_overall_fit(components),
        evidence_coverage=_coverage(components),
        components=components,
        computed_at=computed_at or datetime.now(timezone.utc),
    )
