"""Explainable Hard Eligibility / Opportunity Fit contracts for TS-A6."""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Tuple

from domains.shared.ids import CandidateId, OpportunitySpecId
from domains.shared.versioning import EngineVersion, EntityVersion


class HardEligibilityState(str, Enum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    UNRESOLVED = "unresolved"


class OpportunityFitDimension(str, Enum):
    COMPENSATION = "compensation"
    LOCATION_MOBILITY = "location_mobility"
    WORK_ARRANGEMENT = "work_arrangement"
    CONTRACT = "contract"
    AVAILABILITY = "availability"
    SCHEDULE = "schedule"
    INDUSTRY = "industry"
    COMPANY = "company"
    MUST_HAVE = "must_have"
    NICE_TO_HAVE = "nice_to_have"


class OpportunityFitState(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


class OpportunityFitReasonCode(str, Enum):
    EXPLICIT_MATCH = "explicit_match"
    EXPLICIT_MISMATCH = "explicit_mismatch"
    EXACT_TEXT_MATCH = "exact_text_match"
    SPEC_UNSPECIFIED = "spec_unspecified"
    CANDIDATE_PREFERENCE_MISSING = "candidate_preference_missing"
    CANDIDATE_DEFAULT_NOT_PROOF = "candidate_default_not_proof"
    CURRENCY_NOT_COMPARABLE = "currency_not_comparable"
    COMPENSATION_BASIS_UNAVAILABLE = "compensation_basis_unavailable"
    GEO_NORMALIZATION_REQUIRED = "geo_normalization_required"
    CONTRACT_OVERLAP = "contract_overlap"
    CONTRACT_NO_OVERLAP = "contract_no_overlap"
    EXPLICIT_NO_CONSTRAINT = "explicit_no_constraint"
    FREE_TEXT_NOT_COMPARABLE = "free_text_not_comparable"
    NO_CANDIDATE_PREFERENCE_FIELD = "no_candidate_preference_field"
    OPPORTUNITY_SPEC_CONSTRAINT_PRESENT = "opportunity_spec_constraint_present"


@dataclass(frozen=True)
class OpportunityFitComponent:
    dimension: OpportunityFitDimension
    state: OpportunityFitState
    hard_eligibility_relevant: bool
    reason_codes: Tuple[OpportunityFitReasonCode, ...]
    candidate_evidence: Tuple[str, ...] = ()
    opportunity_evidence: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("Opportunity Fit component requires at least one reason code")
        if self.state is OpportunityFitState.INCOMPATIBLE and not self.hard_eligibility_relevant:
            raise ValueError("incompatible component must be hard-eligibility relevant in A6 v1")


@dataclass(frozen=True)
class OpportunityFitResult:
    candidate_id: CandidateId
    candidate_preferences_version: EntityVersion
    opportunity_spec_id: OpportunitySpecId
    opportunity_spec_version: EntityVersion
    engine_version: EngineVersion
    hard_eligibility_state: HardEligibilityState
    evidence_coverage: int
    components: Tuple[OpportunityFitComponent, ...]
    computed_at: datetime

    def __post_init__(self) -> None:
        if not 0 <= self.evidence_coverage <= 100:
            raise ValueError("evidence_coverage must be between 0 and 100")
        dimensions = [component.dimension for component in self.components]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("Opportunity Fit dimensions must be unique")
