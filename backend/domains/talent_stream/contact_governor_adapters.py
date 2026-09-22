"""Current-state adapters from Talent Stream dependencies into the B9 gate.

This is the only B9 bridge allowed to know the concrete A8, A9 and B7 models.
It derives the narrow trust-owned governor classifications without copying
source evidence or candidate provenance into Contact Governor decisions.
"""

from __future__ import annotations

from datetime import datetime

from domains.matching.opportunity_fit_models import (
    HardEligibilityState,
    OpportunityFitState,
)
from domains.permissions.models import PermissionAction, PermissionRequestContext
from domains.permissions.service import PermissionService
from domains.shared.versioning import PolicyVersion
from domains.talent_stream.stream_candidate_models import StreamCandidate
from domains.talent_stream.stream_candidate_persistence import ProjectionState
from domains.talent_stream.stream_candidate_repository import StreamCandidateRepository
from domains.trust.contact_governor_models import (
    ContactGovernorRequest,
    GovernorCandidateFacts,
    GovernorEligibilityClassification,
    GovernorFactsReadResult,
    GovernorFactsStatus,
    GovernorFitClassification,
    GovernorMatchClassification,
)
from domains.trust.recruiting_service import RecruitingTrustService


_ADAPTER_UNAVAILABLE = "contact governor adapter unavailable"


class ContactGovernorAdapterError(RuntimeError):
    """Fixed, redacted failure at the concrete dependency boundary."""


class RecruitingTrustEvaluatorAdapter:
    """Adapt current A8 Trust evaluation to the trust-owned B9 protocol."""

    __slots__ = ("_service", "_policy_version")

    def __init__(
        self,
        service: RecruitingTrustService,
        *,
        policy_version: PolicyVersion,
    ) -> None:
        if type(policy_version) is not str or not policy_version.strip():
            raise ContactGovernorAdapterError(_ADAPTER_UNAVAILABLE)
        self._service = service
        self._policy_version = policy_version

    async def evaluate_current_trust(self, recruiting_actor, *, evaluated_at: datetime):
        try:
            return await self._service.evaluate_recruiting_actor_trust(
                recruiting_actor,
                policy_version=self._policy_version,
                evaluated_at=evaluated_at,
            )
        except Exception:
            raise ContactGovernorAdapterError(_ADAPTER_UNAVAILABLE) from None


class IntroductionPermissionEvaluatorAdapter:
    """Adapt A9's current introduction Permission check to the B9 protocol."""

    __slots__ = ("_service",)

    def __init__(self, service: PermissionService) -> None:
        self._service = service

    async def evaluate_introduction_permission(
        self,
        *,
        candidate_id,
        stream_id,
        recruiting_actor,
        evaluated_at: datetime,
    ):
        try:
            context = PermissionRequestContext(
                candidate_id=candidate_id,
                action=PermissionAction.REQUEST_INTRODUCTION,
                recruiting_actor=recruiting_actor,
                stream_id=stream_id,
            )
            return await self._service.evaluate(context, evaluated_at=evaluated_at)
        except Exception:
            raise ContactGovernorAdapterError(_ADAPTER_UNAVAILABLE) from None


class StreamCandidateGovernorFactsReader:
    """Double-read B7's current pointer and derive only B9 gating facts."""

    __slots__ = ("_repository",)

    def __init__(self, repository: StreamCandidateRepository) -> None:
        self._repository = repository

    async def read_current_governor_facts(
        self,
        request: ContactGovernorRequest,
    ) -> GovernorFactsReadResult:
        try:
            if type(request) is not ContactGovernorRequest:
                raise ValueError("invalid governor request")
            state_before = await self._repository.get_projection_state(request.stream_id)
            if state_before is None:
                return GovernorFactsReadResult(GovernorFactsStatus.MISSING, None)
            if type(state_before) is not ProjectionState:
                raise ValueError("invalid projection state")
            if not self._request_matches_state(request, state_before):
                return GovernorFactsReadResult(GovernorFactsStatus.STALE, None)

            candidate = await self._repository.get_generation_candidate(
                request.stream_id,
                state_before.active_generation_id,
                request.candidate_id,
            )
            if candidate is None:
                return GovernorFactsReadResult(GovernorFactsStatus.MISSING, None)
            if type(candidate) is not StreamCandidate:
                raise ValueError("invalid stream candidate")
            self._validate_candidate_scope(candidate, state_before, request)
            facts = self._derive_facts(candidate, state_before)

            state_after = await self._repository.get_projection_state(request.stream_id)
            if state_after is None:
                return GovernorFactsReadResult(GovernorFactsStatus.STALE, None)
            if type(state_after) is not ProjectionState:
                raise ValueError("invalid projection state")
            if self._authority_identity(state_after) != self._authority_identity(
                state_before
            ):
                return GovernorFactsReadResult(GovernorFactsStatus.STALE, None)
            return GovernorFactsReadResult(
                GovernorFactsStatus.CURRENT,
                facts,
            )
        except ContactGovernorAdapterError:
            raise
        except Exception:
            raise ContactGovernorAdapterError(_ADAPTER_UNAVAILABLE) from None

    @staticmethod
    def _request_matches_state(
        request: ContactGovernorRequest,
        state: ProjectionState,
    ) -> bool:
        return (
            request.stream_id == state.stream_id
            and request.projection_state_version == state.state_version
            and request.generation_id == state.active_generation_id
            and request.stream_version == state.stream_version
            and request.requirement_version == state.requirement_version
            and request.role_dna_id == state.role_dna_id
            and request.role_dna_version == state.role_dna_version
            and request.opportunity_spec_id == state.opportunity_spec_id
            and request.opportunity_spec_version == state.opportunity_spec_version
        )

    @staticmethod
    def _authority_identity(state: ProjectionState) -> tuple[object, ...]:
        return (
            state.stream_id,
            state.state_version,
            state.active_generation_id,
            state.stream_version,
            state.requirement_version,
            state.role_dna_id,
            state.role_dna_version,
            state.opportunity_spec_id,
            state.opportunity_spec_version,
        )

    @staticmethod
    def _validate_candidate_scope(
        candidate: StreamCandidate,
        state: ProjectionState,
        request: ContactGovernorRequest,
    ) -> None:
        if (
            candidate.candidate_id != request.candidate_id
            or candidate.stream_id != state.stream_id
            or candidate.generation_id != state.active_generation_id
            or candidate.stream_version != state.stream_version
            or candidate.requirement_version != state.requirement_version
            or candidate.role_dna_id != state.role_dna_id
            or candidate.role_dna_version != state.role_dna_version
            or candidate.opportunity_spec_id != state.opportunity_spec_id
            or candidate.opportunity_spec_version != state.opportunity_spec_version
        ):
            raise ValueError("candidate projection scope mismatch")
        match = candidate.professional_match_summary
        if match is not None and match.role_dna_version != state.role_dna_version:
            raise ValueError("match version mismatch")
        fit = candidate.opportunity_fit_summary
        if fit is not None and (
            fit.opportunity_spec_version != state.opportunity_spec_version
        ):
            raise ValueError("fit version mismatch")

    @staticmethod
    def _derive_facts(
        candidate: StreamCandidate,
        state: ProjectionState,
    ) -> GovernorCandidateFacts:
        match = candidate.professional_match_summary
        if match is None:
            match_classification = GovernorMatchClassification.MISSING
            match_score = None
        else:
            match_classification = GovernorMatchClassification.PRESENT
            match_score = match.professional_match_score

        fit = candidate.opportunity_fit_summary
        if fit is None:
            eligibility = GovernorEligibilityClassification.UNRESOLVED
            fit_classification = GovernorFitClassification.MISSING
        else:
            eligibility = {
                HardEligibilityState.ELIGIBLE: GovernorEligibilityClassification.ELIGIBLE,
                HardEligibilityState.INELIGIBLE: GovernorEligibilityClassification.INELIGIBLE,
                HardEligibilityState.UNRESOLVED: GovernorEligibilityClassification.UNRESOLVED,
            }[fit.hard_eligibility_state]
            fit_classification = {
                OpportunityFitState.COMPATIBLE: GovernorFitClassification.COMPATIBLE,
                OpportunityFitState.NOT_APPLICABLE: GovernorFitClassification.NOT_APPLICABLE,
                OpportunityFitState.INCOMPATIBLE: GovernorFitClassification.INCOMPATIBLE,
                OpportunityFitState.UNRESOLVED: GovernorFitClassification.UNRESOLVED,
            }[fit.opportunity_fit_state]

        return GovernorCandidateFacts(
            candidate_id=candidate.candidate_id,
            stream_id=state.stream_id,
            generation_id=state.active_generation_id,
            projection_state_version=state.state_version,
            stream_version=state.stream_version,
            requirement_version=state.requirement_version,
            role_dna_id=state.role_dna_id,
            role_dna_version=state.role_dna_version,
            opportunity_spec_id=state.opportunity_spec_id,
            opportunity_spec_version=state.opportunity_spec_version,
            match_classification=match_classification,
            professional_match_score=match_score,
            eligibility_classification=eligibility,
            fit_classification=fit_classification,
        )
