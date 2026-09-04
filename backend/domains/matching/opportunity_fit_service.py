"""Snapshot orchestration for deterministic Hard Eligibility / Opportunity Fit."""
from datetime import datetime
from typing import Optional

from domains.opportunities.models import (
    CompensationBasis,
    CompensationConstraint,
    LocationConstraint,
    OpportunityFactSource,
    OpportunitySpecification,
    OpportunitySpecStatus,
    WorkArrangement,
)
from domains.opportunities.repository import OpportunitySpecRepository
from domains.preferences.models import (
    CandidatePreferences,
    CompensationPreference,
    DiscoverySettings,
    MobilityPreference,
    SearchState,
    WorkMode,
)
from domains.preferences.repository import CandidatePreferencesRepository
from domains.shared.ids import CandidateId, CandidatePreferencesId, JobId, OpportunitySpecId
from domains.shared.versioning import EngineVersion, EntityVersion
from .opportunity_fit_engine import OPPORTUNITY_FIT_ENGINE_VERSION, calculate_opportunity_fit
from .opportunity_fit_models import OpportunityFitResult


class OpportunityFitInputNotFoundError(LookupError):
    pass


class OpportunityFitSnapshotUnavailableError(RuntimeError):
    pass


def _preferences_from_document(doc: dict) -> CandidatePreferences:
    discovery = doc.get("discovery") or {}
    compensation = doc.get("compensation")
    mobility = doc.get("mobility")
    return CandidatePreferences(
        preferences_id=CandidatePreferencesId(doc["_id"]),
        candidate_id=CandidateId(doc["candidate_id"]),
        version=EntityVersion(int(doc["version"])),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        search_state=SearchState(doc.get("search_state", SearchState.PASSIVE.value)),
        discovery=DiscoverySettings(
            enabled=bool(discovery.get("enabled", False)),
            allow_compatible_opportunities=bool(
                discovery.get("allow_compatible_opportunities", False)
            ),
            ask_before_reveal=bool(discovery.get("ask_before_reveal", False)),
            anonymous_only=bool(discovery.get("anonymous_only", False)),
        ),
        target_roles=tuple(doc.get("target_roles", [])),
        compensation=(
            None
            if compensation is None
            else CompensationPreference(
                minimum=compensation.get("minimum"),
                target=compensation.get("target"),
                currency=compensation.get("currency", "EUR"),
            )
        ),
        mobility=(
            None
            if mobility is None
            else MobilityPreference(
                locations=tuple(mobility.get("locations", [])),
                radius_km=mobility.get("radius_km"),
            )
        ),
        work_mode=WorkMode(doc.get("work_mode", WorkMode.ANY.value)),
        contract_types=tuple(doc.get("contract_types", [])),
        availability=doc.get("availability"),
        excluded_company_ids=tuple(doc.get("excluded_company_ids", [])),
        current_employer_company_id=doc.get("current_employer_company_id"),
        contact_frequency_preference=doc.get("contact_frequency_preference"),
    )


def _opportunity_from_document(doc: dict) -> OpportunitySpecification:
    compensation = doc.get("compensation")
    location = doc.get("location")
    return OpportunitySpecification(
        opportunity_spec_id=OpportunitySpecId(doc["opportunity_spec_id"]),
        version=EntityVersion(int(doc["version"])),
        status=OpportunitySpecStatus(doc["status"]),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        compensation=(
            None
            if compensation is None
            else CompensationConstraint(
                minimum=compensation.get("minimum"),
                maximum=compensation.get("maximum"),
                currency=compensation.get("currency", "EUR"),
                basis=(
                    None
                    if compensation.get("basis") is None
                    else CompensationBasis(compensation["basis"])
                ),
            )
        ),
        location=(
            None
            if location is None
            else LocationConstraint(
                locations=tuple(location.get("locations", [])),
                radius_km=location.get("radius_km"),
            )
        ),
        work_arrangement=(
            None
            if doc.get("work_arrangement") is None
            else WorkArrangement(doc["work_arrangement"])
        ),
        contract_types=(
            None
            if doc.get("contract_types") is None
            else tuple(doc.get("contract_types", []))
        ),
        schedule=doc.get("schedule"),
        target_start=doc.get("target_start"),
        industry_constraints=(
            None
            if doc.get("industry_constraints") is None
            else tuple(doc.get("industry_constraints", []))
        ),
        company_constraints=(
            None
            if doc.get("company_constraints") is None
            else tuple(doc.get("company_constraints", []))
        ),
        must_have_requirements=(
            None
            if doc.get("must_have_requirements") is None
            else tuple(doc.get("must_have_requirements", []))
        ),
        nice_to_have_requirements=(
            None
            if doc.get("nice_to_have_requirements") is None
            else tuple(doc.get("nice_to_have_requirements", []))
        ),
        provenance=OpportunityFactSource(
            doc.get("provenance", OpportunityFactSource.MANUAL.value)
        ),
        source_job_id=(
            None if doc.get("source_job_id") is None else JobId(doc["source_job_id"])
        ),
        source_ref=doc.get("source_ref"),
        version_provenance=(
            None
            if doc.get("version_provenance") is None
            else OpportunityFactSource(doc["version_provenance"])
        ),
        version_provenance_ref=doc.get("version_provenance_ref"),
    )


class OpportunityFitService:
    def __init__(
        self,
        db,
        engine_version: EngineVersion = OPPORTUNITY_FIT_ENGINE_VERSION,
    ):
        self.preferences_repo = CandidatePreferencesRepository(db)
        self.opportunity_repo = OpportunitySpecRepository(db)
        self.engine_version = engine_version

    async def compute(
        self,
        candidate_id: CandidateId,
        opportunity_spec_id: OpportunitySpecId,
        opportunity_spec_version: EntityVersion,
        *,
        candidate_preferences_version: Optional[EntityVersion] = None,
        computed_at: Optional[datetime] = None,
    ) -> OpportunityFitResult:
        preferences_doc = await self.preferences_repo.get(str(candidate_id))
        if preferences_doc is None:
            raise OpportunityFitInputNotFoundError("Candidate Preferences not found")

        current_preferences_version = EntityVersion(int(preferences_doc["version"]))
        if (
            candidate_preferences_version is not None
            and current_preferences_version != candidate_preferences_version
        ):
            raise OpportunityFitSnapshotUnavailableError(
                "requested Candidate Preferences version is not available; "
                f"requested {int(candidate_preferences_version)}, "
                f"current {int(current_preferences_version)}"
            )

        opportunity_doc = await self.opportunity_repo.get(
            str(opportunity_spec_id), int(opportunity_spec_version)
        )
        if opportunity_doc is None:
            raise OpportunityFitInputNotFoundError(
                "Opportunity Specification version not found"
            )

        return calculate_opportunity_fit(
            _preferences_from_document(preferences_doc),
            _opportunity_from_document(opportunity_doc),
            engine_version=self.engine_version,
            computed_at=computed_at,
        )
