"""Immutable internal contracts for TS-B6 Discovery Pool retrieval."""
from dataclasses import dataclass

from domains.matching.models import ProfessionalMatchResult
from domains.matching.opportunity_fit_models import OpportunityFitResult
from domains.shared.ids import CandidateId, OpportunitySpecId, RoleDNAId, TalentStreamId
from domains.shared.versioning import EntityVersion
from domains.talent_stream.contracts import DiscoveryState
from domains.talent_stream.stream_models import nonblank_identifier, positive_entity_version


@dataclass(frozen=True, slots=True, repr=False)
class DiscoveryPoolCursor:
    stream_id: TalentStreamId
    stream_version: EntityVersion
    requirement_version: EntityVersion
    role_dna_id: RoleDNAId
    role_dna_version: EntityVersion
    opportunity_spec_id: OpportunitySpecId
    opportunity_spec_version: EntityVersion
    after_candidate_id: CandidateId

    def __post_init__(self) -> None:
        for value, name in (
            (self.stream_id, "cursor.stream_id"),
            (self.role_dna_id, "cursor.role_dna_id"),
            (self.opportunity_spec_id, "cursor.opportunity_spec_id"),
            (self.after_candidate_id, "cursor.after_candidate_id"),
        ):
            nonblank_identifier(value, name)
        for value, name in (
            (self.stream_version, "cursor.stream_version"),
            (self.requirement_version, "cursor.requirement_version"),
            (self.role_dna_version, "cursor.role_dna_version"),
            (self.opportunity_spec_version, "cursor.opportunity_spec_version"),
        ):
            positive_entity_version(value, name)


@dataclass(frozen=True, slots=True, repr=False)
class DiscoveryPoolCandidate:
    candidate_id: CandidateId
    discovery_state: DiscoveryState
    professional_match: ProfessionalMatchResult
    opportunity_fit: OpportunityFitResult

    def __post_init__(self) -> None:
        nonblank_identifier(self.candidate_id, "candidate_id")
        if type(self.discovery_state) is not DiscoveryState:
            raise ValueError("invalid Discovery state")
        if type(self.professional_match) is not ProfessionalMatchResult:
            raise ValueError("invalid Professional Match result")
        if type(self.opportunity_fit) is not OpportunityFitResult:
            raise ValueError("invalid Opportunity Fit result")
        if not (
            self.discovery_state.candidate_id
            == self.professional_match.candidate_id
            == self.opportunity_fit.candidate_id
            == self.candidate_id
        ):
            raise ValueError("candidate result identity mismatch")


@dataclass(frozen=True, slots=True, repr=False)
class DiscoveryPoolPage:
    items: tuple[DiscoveryPoolCandidate, ...]
    next_cursor: DiscoveryPoolCursor | None
    scanned_count: int

    def __post_init__(self) -> None:
        if type(self.items) is not tuple or any(
            type(item) is not DiscoveryPoolCandidate for item in self.items
        ):
            raise ValueError("Discovery Pool items must be immutable")
        if self.next_cursor is not None and type(self.next_cursor) is not DiscoveryPoolCursor:
            raise ValueError("invalid Discovery Pool cursor")
        if isinstance(self.scanned_count, bool) or type(self.scanned_count) is not int:
            raise ValueError("scanned_count must be an integer")
        if not 0 <= self.scanned_count <= 100 or len(self.items) > self.scanned_count:
            raise ValueError("invalid Discovery Pool page counts")
