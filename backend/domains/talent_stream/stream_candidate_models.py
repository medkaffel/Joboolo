"""Internal B7 Stream Candidate projection contracts.

Derived/reconstructible projection aggregating sources B3-B6.
Never an authority for Permission, Trust, Grant, reveal, CV access, or Contact Governor.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from domains.shared.ids import (
    CandidateId,
    IntentEventId,
    JobId,
    OpportunitySpecId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import EngineVersion, EntityVersion, SchemaVersion
from domains.matching.opportunity_fit_models import HardEligibilityState, OpportunityFitState
from domains.talent_stream.stream_models import nonblank_identifier, positive_entity_version, utc_millisecond


class StreamCandidateSource(str, Enum):
    """Closed internal enum for B7 sources. No private implicit source."""

    APPLICATION = "application"
    DECLARED_INTEREST = "declared_interest"
    SHARED_FAVORITE = "shared_favorite"
    DISCOVERY = "discovery"


@dataclass(frozen=True, slots=True, repr=False)
class ApplicationEvidence:
    """Minimal application evidence. No CV, no identity, no recruiter notes."""

    application_id: str
    status: str
    applied_at: datetime

    def __post_init__(self) -> None:
        nonblank_identifier(self.application_id, "application_id")
        nonblank_identifier(self.status, "status")
        object.__setattr__(
            self,
            "applied_at",
            utc_millisecond(self.applied_at, "applied_at"),
        )


@dataclass(frozen=True, slots=True, repr=False)
class DeclaredInterestEvidence:
    """Minimal B4 declared interest evidence. Deterministic representative only."""

    event_id: IntentEventId
    occurred_at: datetime

    def __post_init__(self) -> None:
        nonblank_identifier(self.event_id, "event_id")
        object.__setattr__(
            self,
            "occurred_at",
            utc_millisecond(self.occurred_at, "occurred_at"),
        )


@dataclass(frozen=True, slots=True, repr=False)
class SharedFavoriteEvidence:
    """Minimal B5 shared favorite evidence. CorrelationId = SavedJob B5 cycle."""

    event_id: IntentEventId
    correlation_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        nonblank_identifier(self.event_id, "event_id")
        nonblank_identifier(self.correlation_id, "correlation_id")
        object.__setattr__(
            self,
            "occurred_at",
            utc_millisecond(self.occurred_at, "occurred_at"),
        )


@dataclass(frozen=True, slots=True, repr=False)
class DiscoveryEvidence:
    """Minimal discovery evidence. Conceptually separate from Intent."""

    candidate_preferences_version: EntityVersion
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_preferences_version",
            positive_entity_version(self.candidate_preferences_version, "candidate_preferences_version"),
        )
        object.__setattr__(
            self,
            "updated_at",
            utc_millisecond(self.updated_at, "updated_at"),
        )


@dataclass(frozen=True, slots=True, repr=False)
class ProfessionalMatchSummary:
    """Minimal A5 Professional Match summary. No threshold invented in B7."""

    candidate_profile_version: EntityVersion
    role_dna_version: EntityVersion
    match_engine_version: EngineVersion
    professional_match_score: int
    evidence_coverage: int
    computed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_profile_version",
            positive_entity_version(self.candidate_profile_version, "candidate_profile_version"),
        )
        object.__setattr__(
            self,
            "role_dna_version",
            positive_entity_version(self.role_dna_version, "role_dna_version"),
        )
        nonblank_identifier(self.match_engine_version, "match_engine_version")
        if type(self.professional_match_score) is not int or not 0 <= self.professional_match_score <= 100:
            raise ValueError("professional_match_score must be an int between 0 and 100")
        if type(self.evidence_coverage) is not int or not 0 <= self.evidence_coverage <= 100:
            raise ValueError("evidence_coverage must be an int between 0 and 100")
        object.__setattr__(
            self,
            "computed_at",
            utc_millisecond(self.computed_at, "computed_at"),
        )


@dataclass(frozen=True, slots=True, repr=False)
class OpportunityFitSummary:
    """Minimal A6 Opportunity Fit summary. Reuses A6 enums where possible."""

    candidate_preferences_version: EntityVersion
    opportunity_spec_version: EntityVersion
    fit_engine_version: EngineVersion
    hard_eligibility_state: HardEligibilityState
    opportunity_fit_state: OpportunityFitState
    evidence_coverage: int
    computed_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_preferences_version",
            positive_entity_version(self.candidate_preferences_version, "candidate_preferences_version"),
        )
        object.__setattr__(
            self,
            "opportunity_spec_version",
            positive_entity_version(self.opportunity_spec_version, "opportunity_spec_version"),
        )
        nonblank_identifier(self.fit_engine_version, "fit_engine_version")
        if type(self.hard_eligibility_state) is not HardEligibilityState:
            raise ValueError("hard_eligibility_state must be a HardEligibilityState")
        if type(self.opportunity_fit_state) is not OpportunityFitState:
            raise ValueError("opportunity_fit_state must be an OpportunityFitState")
        if type(self.evidence_coverage) is not int or not 0 <= self.evidence_coverage <= 100:
            raise ValueError("evidence_coverage must be an int between 0 and 100")
        object.__setattr__(
            self,
            "computed_at",
            utc_millisecond(self.computed_at, "computed_at"),
        )


STREAM_CANDIDATE_SCHEMA_VERSION = "stream-candidate-v1"


@dataclass(frozen=True, slots=True, repr=False)
class StreamCandidate:
    """Immutable Stream Candidate projection.

    At least one source among: application, declared_interest, shared_favorite, discovery.
    Multiple sources allowed simultaneously. No Talent Score. No ranking.
    """

    stream_id: TalentStreamId
    stream_version: EntityVersion
    requirement_version: EntityVersion
    generation_id: str
    candidate_id: CandidateId
    role_dna_id: RoleDNAId
    role_dna_version: EntityVersion
    opportunity_spec_id: OpportunitySpecId
    opportunity_spec_version: EntityVersion
    application_evidence: Optional[ApplicationEvidence] = None
    declared_interest_evidence: Optional[DeclaredInterestEvidence] = None
    shared_favorite_evidence: Optional[SharedFavoriteEvidence] = None
    discovery_evidence: Optional[DiscoveryEvidence] = None
    professional_match_summary: Optional[ProfessionalMatchSummary] = None
    opportunity_fit_summary: Optional[OpportunityFitSummary] = None
    computed_at: datetime = None

    def __post_init__(self) -> None:
        nonblank_identifier(self.stream_id, "stream_id")
        object.__setattr__(
            self,
            "stream_version",
            positive_entity_version(self.stream_version, "stream_version"),
        )
        object.__setattr__(
            self,
            "requirement_version",
            positive_entity_version(self.requirement_version, "requirement_version"),
        )
        nonblank_identifier(self.generation_id, "generation_id")
        nonblank_identifier(self.candidate_id, "candidate_id")
        nonblank_identifier(self.role_dna_id, "role_dna_id")
        object.__setattr__(
            self,
            "role_dna_version",
            positive_entity_version(self.role_dna_version, "role_dna_version"),
        )
        nonblank_identifier(self.opportunity_spec_id, "opportunity_spec_id")
        object.__setattr__(
            self,
            "opportunity_spec_version",
            positive_entity_version(self.opportunity_spec_version, "opportunity_spec_version"),
        )
        if self.computed_at is not None:
            object.__setattr__(
                self,
                "computed_at",
                utc_millisecond(self.computed_at, "computed_at"),
            )

        sources_present = sum(
            1
            for ev in (
                self.application_evidence,
                self.declared_interest_evidence,
                self.shared_favorite_evidence,
                self.discovery_evidence,
            )
            if ev is not None
        )
        if sources_present < 1:
            raise ValueError("StreamCandidate requires at least one source")

        if self.application_evidence is not None:
            if type(self.application_evidence) is not ApplicationEvidence:
                raise ValueError("invalid application_evidence")
        if self.declared_interest_evidence is not None:
            if type(self.declared_interest_evidence) is not DeclaredInterestEvidence:
                raise ValueError("invalid declared_interest_evidence")
        if self.shared_favorite_evidence is not None:
            if type(self.shared_favorite_evidence) is not SharedFavoriteEvidence:
                raise ValueError("invalid shared_favorite_evidence")
        if self.discovery_evidence is not None:
            if type(self.discovery_evidence) is not DiscoveryEvidence:
                raise ValueError("invalid discovery_evidence")
        if self.professional_match_summary is not None:
            if type(self.professional_match_summary) is not ProfessionalMatchSummary:
                raise ValueError("invalid professional_match_summary")
        if self.opportunity_fit_summary is not None:
            if type(self.opportunity_fit_summary) is not OpportunityFitSummary:
                raise ValueError("invalid opportunity_fit_summary")

        forbidden_fields = {
            "first_name",
            "last_name",
            "email",
            "phone",
            "cv",
            "document_id",
            "current_employer",
            "permission",
            "grant",
            "trust",
            "contact_governor",
            "visibility_state",
            "reveal_state",
            "source_organization",
            "competitor_company",
            "source_campaign",
            "raw_saved_job",
            "talent_score",
            "intent_counter",
        }
        for field in forbidden_fields:
            if hasattr(self, field):
                raise ValueError(f"forbidden field {field} in StreamCandidate")