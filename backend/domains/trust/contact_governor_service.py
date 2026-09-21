"""Fail-closed Contact Governor orchestration for TS-B9-001."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from domains.talent_stream.decisions import (
    ContactGovernorDecision,
    PermissionDecision,
    TrustDecision,
)
from domains.trust.contact_governor_models import (
    ContactGovernorPolicyV1,
    ContactGovernorReasonCode,
    ContactGovernorRequest,
    ContactGovernorReservationLedger,
    CurrentGovernorFactsReader,
    CurrentRecruitingTrustEvaluator,
    GovernorEligibilityClassification,
    GovernorFactsReadResult,
    GovernorFactsStatus,
    GovernorFitClassification,
    GovernorMatchClassification,
    GovernorReservationCommand,
    GovernorReservationOutcome,
    GovernorReservationResult,
    IntroductionPermissionEvaluator,
    derive_request_fingerprint,
    derive_reservation_id,
    require_governor_time,
)


_UNAVAILABLE_MESSAGE = "contact governor unavailable"


class ContactGovernorUnavailableError(RuntimeError):
    """Fixed, redacted configuration/clock failure."""


@dataclass(frozen=True, slots=True, repr=False)
class ContactGovernorResult:
    decision: ContactGovernorDecision
    reservation_id: Optional[str] = None
    reservation_expires_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if type(self.decision) is not ContactGovernorDecision:
            raise ValueError("decision must be ContactGovernorDecision")
        if self.decision.allowed:
            if type(self.reservation_id) is not str or not self.reservation_id:
                raise ValueError("allowed decision requires reservation_id")
            require_governor_time(
                self.reservation_expires_at,
                "reservation_expires_at",
            )
        elif self.reservation_id is not None or self.reservation_expires_at is not None:
            raise ValueError("denied decision must not expose reservation data")


class ContactGovernorService:
    def __init__(
        self,
        *,
        policy: ContactGovernorPolicyV1,
        trust_evaluator: CurrentRecruitingTrustEvaluator,
        permission_evaluator: IntroductionPermissionEvaluator,
        facts_reader: CurrentGovernorFactsReader,
        reservation_ledger: ContactGovernorReservationLedger,
        clock: Callable[[], datetime],
    ) -> None:
        if type(policy) is not ContactGovernorPolicyV1:
            raise ContactGovernorUnavailableError(_UNAVAILABLE_MESSAGE)
        if not callable(clock):
            raise ContactGovernorUnavailableError(_UNAVAILABLE_MESSAGE)
        self._policy = policy
        self._trust_evaluator = trust_evaluator
        self._permission_evaluator = permission_evaluator
        self._facts_reader = facts_reader
        self._reservation_ledger = reservation_ledger
        self._clock = clock

    async def evaluate(self, request: ContactGovernorRequest) -> ContactGovernorResult:
        if type(request) is not ContactGovernorRequest:
            raise ContactGovernorUnavailableError(_UNAVAILABLE_MESSAGE)
        try:
            evaluated_at = require_governor_time(self._clock(), "clock result")
        except Exception:
            raise ContactGovernorUnavailableError(_UNAVAILABLE_MESSAGE) from None

        # Both current decisions are re-evaluated on every request. Explicit
        # denial outranks dependency failure, and Trust denial outranks
        # Permission denial when both deny.
        trust: Optional[TrustDecision] = None
        permission: Optional[PermissionDecision] = None
        trust_failed = False
        permission_failed = False
        try:
            trust = await self._trust_evaluator.evaluate_current_trust(
                request.recruiting_actor,
                evaluated_at=evaluated_at,
            )
            if not self._valid_upstream_decision(trust, TrustDecision, evaluated_at):
                trust_failed = True
        except Exception:
            trust_failed = True
        try:
            permission = await self._permission_evaluator.evaluate_introduction_permission(
                candidate_id=request.candidate_id,
                stream_id=request.stream_id,
                recruiting_actor=request.recruiting_actor,
                evaluated_at=evaluated_at,
            )
            if not self._valid_upstream_decision(
                permission,
                PermissionDecision,
                evaluated_at,
            ):
                permission_failed = True
        except Exception:
            permission_failed = True

        if not trust_failed and trust is not None and not trust.allowed:
            return self._denied(ContactGovernorReasonCode.TRUST_DENIED, evaluated_at)
        if not permission_failed and permission is not None and not permission.allowed:
            return self._denied(ContactGovernorReasonCode.PERMISSION_DENIED, evaluated_at)
        if trust_failed or permission_failed:
            return self._denied(ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE, evaluated_at)

        try:
            facts_result = await self._facts_reader.read_current_governor_facts(request)
        except Exception:
            return self._denied(ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE, evaluated_at)
        if type(facts_result) is not GovernorFactsReadResult:
            return self._denied(ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE, evaluated_at)
        if facts_result.status is GovernorFactsStatus.MISSING:
            return self._denied(ContactGovernorReasonCode.CANDIDATE_FACTS_MISSING, evaluated_at)
        if facts_result.status is GovernorFactsStatus.STALE:
            return self._denied(ContactGovernorReasonCode.CANDIDATE_FACTS_STALE, evaluated_at)

        facts = facts_result.facts
        if facts is None or not facts.matches(request):
            return self._denied(ContactGovernorReasonCode.CANDIDATE_FACTS_STALE, evaluated_at)
        safe_projection_ref = f"governor_facts:{derive_request_fingerprint(request)}"
        if facts.match_classification is GovernorMatchClassification.MISSING:
            return self._denied(
                ContactGovernorReasonCode.PROFESSIONAL_MATCH_MISSING,
                evaluated_at,
                evidence_ref=safe_projection_ref,
            )
        if facts.fit_classification is GovernorFitClassification.MISSING:
            return self._denied(
                ContactGovernorReasonCode.OPPORTUNITY_FIT_MISSING,
                evaluated_at,
                evidence_ref=safe_projection_ref,
            )
        if facts.eligibility_classification is GovernorEligibilityClassification.INELIGIBLE:
            return self._denied(
                ContactGovernorReasonCode.HARD_ELIGIBILITY_INELIGIBLE,
                evaluated_at,
                evidence_ref=safe_projection_ref,
            )
        if facts.eligibility_classification is GovernorEligibilityClassification.UNRESOLVED:
            return self._denied(
                ContactGovernorReasonCode.HARD_ELIGIBILITY_UNRESOLVED,
                evaluated_at,
                evidence_ref=safe_projection_ref,
            )
        if facts.fit_classification is GovernorFitClassification.INCOMPATIBLE:
            return self._denied(
                ContactGovernorReasonCode.OPPORTUNITY_FIT_INCOMPATIBLE,
                evaluated_at,
                evidence_ref=safe_projection_ref,
            )
        if facts.fit_classification is GovernorFitClassification.UNRESOLVED:
            return self._denied(
                ContactGovernorReasonCode.OPPORTUNITY_FIT_UNRESOLVED,
                evaluated_at,
                evidence_ref=safe_projection_ref,
            )
        if (
            facts.professional_match_score is None
            or facts.professional_match_score
            < self._policy.minimum_professional_match_score
        ):
            return self._denied(
                ContactGovernorReasonCode.PROFESSIONAL_MATCH_BELOW_THRESHOLD,
                evaluated_at,
                evidence_ref=safe_projection_ref,
            )

        try:
            command = GovernorReservationCommand(
                request=request,
                policy=self._policy,
                evaluated_at=evaluated_at,
                reservation_id=derive_reservation_id(request),
                request_fingerprint=derive_request_fingerprint(request),
                reservation_expires_at=evaluated_at + self._policy.reservation_lease,
            )
            reservation = await self._reservation_ledger.reserve(command)
            if type(reservation) is not GovernorReservationResult:
                return self._denied(
                    ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE,
                    evaluated_at,
                )
            return self._from_reservation(
                reservation,
                command,
                evaluated_at,
                safe_projection_ref,
            )
        except Exception:
            return self._denied(ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE, evaluated_at)

    @staticmethod
    def _valid_upstream_decision(
        decision: object,
        expected_type: type,
        evaluated_at: datetime,
    ) -> bool:
        return (
            type(decision) is expected_type
            and type(decision.allowed) is bool
            and decision.evaluated_at == evaluated_at
        )

    def _decision(
        self,
        *,
        allowed: bool,
        reason: ContactGovernorReasonCode,
        evaluated_at: datetime,
        evidence_refs: tuple[str, ...] = (),
    ) -> ContactGovernorDecision:
        return ContactGovernorDecision(
            allowed=allowed,
            reason_codes=(reason.value,),
            policy_version=self._policy.policy_version,
            evaluated_at=evaluated_at,
            evidence_refs=evidence_refs,
        )

    def _denied(
        self,
        reason: ContactGovernorReasonCode,
        evaluated_at: datetime,
        *,
        evidence_ref: Optional[str] = None,
    ) -> ContactGovernorResult:
        evidence_refs = () if evidence_ref is None else (evidence_ref,)
        return ContactGovernorResult(
            decision=self._decision(
                allowed=False,
                reason=reason,
                evaluated_at=evaluated_at,
                evidence_refs=evidence_refs,
            )
        )

    def _from_reservation(
        self,
        result: GovernorReservationResult,
        command: GovernorReservationCommand,
        evaluated_at: datetime,
        safe_projection_ref: str,
    ) -> ContactGovernorResult:
        outcome_reasons = {
            GovernorReservationOutcome.DUPLICATE: ContactGovernorReasonCode.DUPLICATE_CONTACT,
            GovernorReservationOutcome.FREQUENCY_CAP_REACHED: ContactGovernorReasonCode.FREQUENCY_CAP_REACHED,
            GovernorReservationOutcome.COMPANY_COOLING_ACTIVE: ContactGovernorReasonCode.COMPANY_COOLING_ACTIVE,
            GovernorReservationOutcome.ACTIVE_RESERVATION_LIMIT_REACHED: ContactGovernorReasonCode.ACTIVE_RESERVATION_LIMIT_REACHED,
            GovernorReservationOutcome.IDEMPOTENCY_CONFLICT: ContactGovernorReasonCode.IDEMPOTENCY_CONFLICT,
        }
        if result.outcome in outcome_reasons:
            return self._denied(outcome_reasons[result.outcome], evaluated_at)
        if result.outcome not in {
            GovernorReservationOutcome.RESERVED,
            GovernorReservationOutcome.IDEMPOTENT_REPLAY,
        }:
            return self._denied(ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE, evaluated_at)
        if (
            result.reservation_id != command.reservation_id
            or result.reservation_expires_at is None
            or result.reservation_expires_at <= evaluated_at
        ):
            return self._denied(ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE, evaluated_at)
        if (
            result.outcome is GovernorReservationOutcome.RESERVED
            and result.reservation_expires_at != command.reservation_expires_at
        ):
            return self._denied(ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE, evaluated_at)
        reason = (
            ContactGovernorReasonCode.ALLOWED
            if result.outcome is GovernorReservationOutcome.RESERVED
            else ContactGovernorReasonCode.ALLOWED_IDEMPOTENT_REPLAY
        )
        reservation_ref = f"contact_governor_reservation:{result.reservation_id}"
        return ContactGovernorResult(
            decision=self._decision(
                allowed=True,
                reason=reason,
                evaluated_at=evaluated_at,
                evidence_refs=(safe_projection_ref, reservation_ref),
            ),
            reservation_id=result.reservation_id,
            reservation_expires_at=result.reservation_expires_at,
        )
