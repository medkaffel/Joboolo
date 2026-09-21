from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path

import pytest

import domains.trust.contact_governor_service as contact_governor_service_module
from domains.shared.ids import (
    CandidateId,
    HiringCompanyId,
    IdempotencyKey,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import ConsentPolicyVersion, PolicyVersion
from domains.talent_stream.contracts import RecruitingActorContext
from domains.talent_stream.decisions import (
    ContactGovernorDecision,
    PermissionDecision,
    TrustDecision,
)
from domains.trust.contact_governor_models import (
    ActiveReservationLimitPolicy,
    CompanyCoolingPolicy,
    ContactGovernorPolicyV1,
    ContactGovernorReasonCode,
    ContactGovernorRequest,
    CurrentGovernorFactsReader,
    CurrentRecruitingTrustEvaluator,
    GovernorCandidateFacts,
    GovernorCompanyCoolingScope,
    GovernorDuplicateScope,
    GovernorEligibilityClassification,
    GovernorFactsReadResult,
    GovernorFactsStatus,
    GovernorFitClassification,
    GovernorFrequencyCap,
    GovernorFrequencyScope,
    GovernorMatchClassification,
    GovernorReservationCommand,
    GovernorReservationOutcome,
    GovernorReservationResult,
    GovernorReservationState,
    DuplicateProtectionPolicy,
    FrequencyCapPolicy,
    IntroductionPermissionEvaluator,
    ContactGovernorReservationLedger,
    derive_request_fingerprint,
    derive_reservation_id,
    reservation_actor_scope,
)
from domains.trust.contact_governor_service import (
    ContactGovernorResult,
    ContactGovernorService,
    ContactGovernorUnavailableError,
)


NOW = datetime(2026, 9, 21, 8, 30, 0, 123000, tzinfo=timezone.utc)
GOVERNOR_POLICY = PolicyVersion("contact-governor-v1-config-a")
TRUST_POLICY = PolicyVersion("recruiting-trust-v1")
PERMISSION_POLICY = PolicyVersion("introduction-permission-v1")
CONSENT_POLICY = ConsentPolicyVersion("candidate-discovery-v1")


def actor(*, recruiter="recruiter-1", requesting="agency-1", hiring="company-1"):
    return RecruitingActorContext(
        recruiter_user_id=RecruiterUserId(recruiter),
        requesting_organization_id=OrganizationId(requesting),
        hiring_company_id=HiringCompanyId(hiring),
        mandate_id=None,
    )


def request(**changes):
    values = {
        "idempotency_key": IdempotencyKey("attempt-1"),
        "candidate_id": CandidateId("candidate-1"),
        "stream_id": TalentStreamId("stream-1"),
        "generation_id": "generation-7",
        "projection_state_version": 11,
        "stream_version": 5,
        "requirement_version": 3,
        "role_dna_id": RoleDNAId("role-dna-1"),
        "role_dna_version": 2,
        "opportunity_spec_id": OpportunitySpecId("opportunity-1"),
        "opportunity_spec_version": 4,
        "recruiting_actor": actor(),
    }
    values.update(changes)
    return ContactGovernorRequest(**values)


def policy(**changes):
    values = {
        "policy_version": GOVERNOR_POLICY,
        "minimum_professional_match_score": 72,
        "frequency_cap_policy": FrequencyCapPolicy(
            enabled=True,
            caps=(
                GovernorFrequencyCap(
                    scope=GovernorFrequencyScope.RECRUITER_CANDIDATE,
                    maximum_activity_count=3,
                    window=timedelta(days=7),
                ),
                GovernorFrequencyCap(
                    scope=GovernorFrequencyScope.REQUESTING_ORGANIZATION_CANDIDATE,
                    maximum_activity_count=5,
                    window=timedelta(days=30),
                ),
            ),
        ),
        "duplicate_protection_policy": DuplicateProtectionPolicy(
            enabled=True,
            scope=GovernorDuplicateScope.STREAM_CANDIDATE_REQUESTING_ORGANIZATION,
            window=timedelta(days=14),
        ),
        "company_cooling_policy": CompanyCoolingPolicy(
            enabled=True,
            scope=GovernorCompanyCoolingScope.HIRING_COMPANY_CANDIDATE,
            period=timedelta(days=21),
        ),
        "active_reservation_limit_policy": ActiveReservationLimitPolicy(
            enabled=True,
            maximum_active_reservations=2,
        ),
        "reservation_lease": timedelta(minutes=10),
    }
    values.update(changes)
    return ContactGovernorPolicyV1(**values)


def facts(for_request=None, **changes):
    command = for_request or request()
    values = {
        "candidate_id": command.candidate_id,
        "stream_id": command.stream_id,
        "generation_id": command.generation_id,
        "projection_state_version": command.projection_state_version,
        "stream_version": command.stream_version,
        "requirement_version": command.requirement_version,
        "role_dna_id": command.role_dna_id,
        "role_dna_version": command.role_dna_version,
        "opportunity_spec_id": command.opportunity_spec_id,
        "opportunity_spec_version": command.opportunity_spec_version,
        "match_classification": GovernorMatchClassification.PRESENT,
        "professional_match_score": 72,
        "eligibility_classification": GovernorEligibilityClassification.ELIGIBLE,
        "fit_classification": GovernorFitClassification.COMPATIBLE,
    }
    values.update(changes)
    return GovernorCandidateFacts(**values)


class FixedClock:
    def __init__(self, value=NOW):
        self.value = value
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


class FakeTrustEvaluator:
    def __init__(self, *, allowed=True, failure=None, result=None, events=None):
        self.allowed = allowed
        self.failure = failure
        self.result = result
        self.events = events
        self.calls = []

    async def evaluate_current_trust(self, recruiting_actor, *, evaluated_at):
        self.calls.append((recruiting_actor, evaluated_at))
        if self.events is not None:
            self.events.append("trust")
        if self.failure is not None:
            raise self.failure
        if self.result is not None:
            return self.result
        return TrustDecision(
            allowed=self.allowed,
            reason_codes=("trusted" if self.allowed else "not_trusted",),
            policy_version=TRUST_POLICY,
            evaluated_at=evaluated_at,
            evidence_refs=("sensitive-trust-evidence",),
        )


class FakePermissionEvaluator:
    def __init__(self, *, allowed=True, failure=None, result=None, events=None):
        self.allowed = allowed
        self.failure = failure
        self.result = result
        self.events = events
        self.calls = []

    async def evaluate_introduction_permission(
        self,
        *,
        candidate_id,
        stream_id,
        recruiting_actor,
        evaluated_at,
    ):
        self.calls.append((candidate_id, stream_id, recruiting_actor, evaluated_at))
        if self.events is not None:
            self.events.append("permission")
        if self.failure is not None:
            raise self.failure
        if self.result is not None:
            return self.result
        return PermissionDecision(
            allowed=self.allowed,
            reason_codes=("permitted" if self.allowed else "not_permitted",),
            policy_version=PERMISSION_POLICY,
            consent_policy_version=CONSENT_POLICY,
            evaluated_at=evaluated_at,
            evidence_refs=("sensitive-permission-evidence",),
        )


class FakeFactsReader:
    def __init__(self, result=None, failure=None, events=None):
        self.result = result
        self.failure = failure
        self.events = events
        self.calls = []

    async def read_current_governor_facts(self, command):
        self.calls.append(command)
        if self.events is not None:
            self.events.append("facts")
        if self.failure is not None:
            raise self.failure
        if self.result is not None:
            return self.result
        return GovernorFactsReadResult(
            status=GovernorFactsStatus.CURRENT,
            facts=facts(command),
        )


class FakeLedger:
    def __init__(
        self,
        outcome=GovernorReservationOutcome.RESERVED,
        failure=None,
        *,
        outcomes=None,
        events=None,
    ):
        self.outcome = outcome
        self.outcomes = outcomes
        self.failure = failure
        self.events = events
        self.calls = []

    async def reserve(self, command):
        self.calls.append(command)
        if self.failure is not None:
            raise self.failure
        outcome = (
            self.outcomes[len(self.calls) - 1]
            if self.outcomes is not None
            else self.outcome
        )
        if self.events is not None:
            self.events.append(f"ledger:{outcome.value}")
        if outcome in {
            GovernorReservationOutcome.RESERVED,
            GovernorReservationOutcome.IDEMPOTENT_REPLAY,
        }:
            return GovernorReservationResult(
                outcome=outcome,
                reservation_id=command.reservation_id,
                reservation_expires_at=command.reservation_expires_at,
            )
        return GovernorReservationResult(outcome=outcome)


def service(*, trust=None, permission=None, reader=None, ledger=None, clock=None, configured_policy=None):
    return ContactGovernorService(
        policy=configured_policy or policy(),
        trust_evaluator=trust or FakeTrustEvaluator(),
        permission_evaluator=permission or FakePermissionEvaluator(),
        facts_reader=reader or FakeFactsReader(),
        reservation_ledger=ledger or FakeLedger(),
        clock=clock or FixedClock(),
    )


def reason(result):
    assert isinstance(result.decision, ContactGovernorDecision)
    assert len(result.decision.reason_codes) == 1
    return result.decision.reason_codes[0]


class TestStrictContracts:
    def test_request_has_no_caller_selected_policy_or_time(self):
        names = {field.name for field in fields(ContactGovernorRequest)}
        assert "governor_policy_version" not in names
        assert "policy_version" not in names
        assert "evaluated_at" not in names

    @pytest.mark.parametrize(
        "field,value",
        [
            ("idempotency_key", ""),
            ("candidate_id", " "),
            ("stream_id", 1),
            ("generation_id", None),
            ("role_dna_id", ""),
            ("opportunity_spec_id", False),
            ("projection_state_version", 0),
            ("stream_version", True),
            ("requirement_version", -1),
            ("role_dna_version", 1.0),
            ("opportunity_spec_version", "2"),
        ],
    )
    def test_request_rejects_invalid_identifiers_and_versions(self, field, value):
        with pytest.raises(ValueError):
            request(**{field: value})

    @pytest.mark.parametrize(
        "bad_actor",
        [
            None,
            object(),
            actor(recruiter=""),
            actor(requesting=" "),
            actor(hiring=""),
        ],
    )
    def test_request_rejects_invalid_actor_context(self, bad_actor):
        with pytest.raises(ValueError):
            request(recruiting_actor=bad_actor)

    def test_policy_has_no_defaults_and_requires_every_dimension(self):
        signature = inspect.signature(ContactGovernorPolicyV1)
        assert all(
            parameter.default is inspect.Parameter.empty
            for parameter in signature.parameters.values()
        )
        assert set(signature.parameters) == {
            "policy_version",
            "minimum_professional_match_score",
            "frequency_cap_policy",
            "duplicate_protection_policy",
            "company_cooling_policy",
            "active_reservation_limit_policy",
            "reservation_lease",
        }

    @pytest.mark.parametrize("threshold", [True, -1, 101, 72.0, "72"])
    def test_policy_rejects_non_strict_match_threshold(self, threshold):
        with pytest.raises(ValueError):
            policy(minimum_professional_match_score=threshold)

    @pytest.mark.parametrize(
        "changes",
        [
            {"policy_version": ""},
            {"frequency_cap_policy": None},
            {"duplicate_protection_policy": None},
            {"company_cooling_policy": None},
            {"active_reservation_limit_policy": None},
            {"reservation_lease": timedelta(0)},
            {"reservation_lease": timedelta(microseconds=1)},
        ],
    )
    def test_policy_rejects_missing_or_invalid_required_configuration(self, changes):
        with pytest.raises(ValueError):
            policy(**changes)

    @pytest.mark.parametrize(
        "changes",
        [
            {"scope": "recruiter_candidate"},
            {"maximum_activity_count": 0},
            {"maximum_activity_count": True},
            {"window": timedelta(0)},
        ],
    )
    def test_frequency_cap_is_strict(self, changes):
        values = {
            "scope": GovernorFrequencyScope.RECRUITER_CANDIDATE,
            "maximum_activity_count": 1,
            "window": timedelta(days=1),
        }
        values.update(changes)
        with pytest.raises(ValueError):
            GovernorFrequencyCap(**values)

    @pytest.mark.parametrize("enabled", [0, 1, "true", None])
    @pytest.mark.parametrize(
        "policy_type,active_values,disabled_values",
        [
            (
                FrequencyCapPolicy,
                {
                    "caps": (
                        GovernorFrequencyCap(
                            scope=GovernorFrequencyScope.CANDIDATE_GLOBAL,
                            maximum_activity_count=1,
                            window=timedelta(days=1),
                        ),
                    )
                },
                {"caps": None},
            ),
            (
                DuplicateProtectionPolicy,
                {
                    "scope": GovernorDuplicateScope.STREAM_CANDIDATE_RECRUITER,
                    "window": timedelta(days=1),
                },
                {"scope": None, "window": None},
            ),
            (
                CompanyCoolingPolicy,
                {
                    "scope": GovernorCompanyCoolingScope.HIRING_COMPANY_CANDIDATE,
                    "period": timedelta(days=1),
                },
                {"scope": None, "period": None},
            ),
            (
                ActiveReservationLimitPolicy,
                {"maximum_active_reservations": 1},
                {"maximum_active_reservations": None},
            ),
        ],
    )
    def test_dimension_enabled_flag_is_strict_boolean(
        self,
        enabled,
        policy_type,
        active_values,
        disabled_values,
    ):
        values = active_values if enabled else disabled_values
        with pytest.raises(ValueError):
            policy_type(enabled=enabled, **values)

    def test_disabled_dimensions_are_explicit_and_carry_no_rule_values(self):
        configured = policy(
            frequency_cap_policy=FrequencyCapPolicy(enabled=False, caps=None),
            duplicate_protection_policy=DuplicateProtectionPolicy(
                enabled=False,
                scope=None,
                window=None,
            ),
            company_cooling_policy=CompanyCoolingPolicy(
                enabled=False,
                scope=None,
                period=None,
            ),
            active_reservation_limit_policy=ActiveReservationLimitPolicy(
                enabled=False,
                maximum_active_reservations=None,
            ),
        )
        assert configured.frequency_cap_policy.enabled is False
        assert configured.duplicate_protection_policy.enabled is False
        assert configured.company_cooling_policy.enabled is False
        assert configured.active_reservation_limit_policy.enabled is False

    @pytest.mark.parametrize(
        "policy_type",
        [
            FrequencyCapPolicy,
            DuplicateProtectionPolicy,
            CompanyCoolingPolicy,
            ActiveReservationLimitPolicy,
        ],
    )
    def test_dimension_policy_fields_have_no_defaults(self, policy_type):
        assert all(
            parameter.default is inspect.Parameter.empty
            for parameter in inspect.signature(policy_type).parameters.values()
        )

    @pytest.mark.parametrize(
        "factory,values",
        [
            (FrequencyCapPolicy, {"caps": ()}),
            (
                FrequencyCapPolicy,
                {
                    "caps": (
                        GovernorFrequencyCap(
                            scope=GovernorFrequencyScope.CANDIDATE_GLOBAL,
                            maximum_activity_count=1,
                            window=timedelta(days=1),
                        ),
                    )
                },
            ),
            (
                DuplicateProtectionPolicy,
                {
                    "scope": GovernorDuplicateScope.STREAM_CANDIDATE_RECRUITER,
                    "window": timedelta(days=1),
                },
            ),
            (
                CompanyCoolingPolicy,
                {
                    "scope": GovernorCompanyCoolingScope.HIRING_COMPANY_CANDIDATE,
                    "period": timedelta(days=1),
                },
            ),
            (
                ActiveReservationLimitPolicy,
                {"maximum_active_reservations": 1},
            ),
        ],
    )
    def test_disabled_dimensions_reject_any_active_rule_values(self, factory, values):
        with pytest.raises(ValueError):
            factory(enabled=False, **values)

    @pytest.mark.parametrize(
        "factory,values",
        [
            (FrequencyCapPolicy, {"caps": None}),
            (FrequencyCapPolicy, {"caps": ()}),
            (
                DuplicateProtectionPolicy,
                {"scope": None, "window": timedelta(days=1)},
            ),
            (
                DuplicateProtectionPolicy,
                {
                    "scope": GovernorDuplicateScope.STREAM_CANDIDATE_RECRUITER,
                    "window": None,
                },
            ),
            (
                CompanyCoolingPolicy,
                {"scope": None, "period": timedelta(days=1)},
            ),
            (
                CompanyCoolingPolicy,
                {
                    "scope": GovernorCompanyCoolingScope.HIRING_COMPANY_CANDIDATE,
                    "period": None,
                },
            ),
            (ActiveReservationLimitPolicy, {"maximum_active_reservations": None}),
            (ActiveReservationLimitPolicy, {"maximum_active_reservations": 0}),
            (ActiveReservationLimitPolicy, {"maximum_active_reservations": True}),
        ],
    )
    def test_enabled_dimensions_require_strict_complete_values(self, factory, values):
        with pytest.raises(ValueError):
            factory(enabled=True, **values)

    @pytest.mark.parametrize(
        "factory,values",
        [
            (
                DuplicateProtectionPolicy,
                {
                    "scope": GovernorDuplicateScope.STREAM_CANDIDATE_RECRUITER,
                    "window": timedelta(microseconds=1),
                },
            ),
            (
                CompanyCoolingPolicy,
                {
                    "scope": GovernorCompanyCoolingScope.HIRING_COMPANY_CANDIDATE,
                    "period": timedelta(microseconds=1),
                },
            ),
        ],
    )
    def test_policy_durations_reject_sub_millisecond_values(self, factory, values):
        with pytest.raises(ValueError, match="exact whole number of milliseconds"):
            factory(enabled=True, **values)

    def test_frequency_cap_window_rejects_sub_millisecond_value(self):
        with pytest.raises(ValueError, match="exact whole number of milliseconds"):
            GovernorFrequencyCap(
                scope=GovernorFrequencyScope.CANDIDATE_GLOBAL,
                maximum_activity_count=1,
                window=timedelta(microseconds=1),
            )

    def test_policy_rejects_duplicate_scope_window_caps(self):
        cap = GovernorFrequencyCap(
            scope=GovernorFrequencyScope.CANDIDATE_GLOBAL,
            maximum_activity_count=1,
            window=timedelta(days=1),
        )
        with pytest.raises(ValueError):
            FrequencyCapPolicy(
                enabled=True,
                caps=(cap, replace(cap, maximum_activity_count=2)),
            )

    @pytest.mark.parametrize("score", [None, True, -1, 101, 72.0])
    def test_present_match_requires_strict_score(self, score):
        with pytest.raises(ValueError):
            facts(professional_match_score=score)

    def test_missing_match_must_not_carry_score(self):
        with pytest.raises(ValueError):
            facts(match_classification=GovernorMatchClassification.MISSING)
        missing = facts(
            match_classification=GovernorMatchClassification.MISSING,
            professional_match_score=None,
        )
        assert missing.professional_match_score is None

    @pytest.mark.parametrize("status", [GovernorFactsStatus.MISSING, GovernorFactsStatus.STALE])
    def test_non_current_read_result_cannot_carry_facts(self, status):
        with pytest.raises(ValueError):
            GovernorFactsReadResult(status=status, facts=facts())

    def test_current_read_result_requires_facts(self):
        with pytest.raises(ValueError):
            GovernorFactsReadResult(status=GovernorFactsStatus.CURRENT, facts=None)


class TestIdentityAndLedgerBoundary:
    def test_sensitive_b9_dataclass_reprs_do_not_expose_identifiers(self):
        sensitive_request = request(
            candidate_id=CandidateId("candidate-sensitive-123"),
            stream_id=TalentStreamId("stream-sensitive-456"),
            generation_id="generation-sensitive-789",
            recruiting_actor=actor(
                recruiter="recruiter-sensitive-123",
                requesting="organization-sensitive-456",
                hiring="company-sensitive-789",
            ),
        )
        sensitive_facts = facts(sensitive_request)
        facts_result = GovernorFactsReadResult(
            status=GovernorFactsStatus.CURRENT,
            facts=sensitive_facts,
        )
        configured_policy = policy()
        reservation_command = GovernorReservationCommand(
            request=sensitive_request,
            policy=configured_policy,
            evaluated_at=NOW,
            reservation_id=derive_reservation_id(sensitive_request),
            request_fingerprint=derive_request_fingerprint(sensitive_request),
            reservation_expires_at=NOW + configured_policy.reservation_lease,
        )
        reservation_result = GovernorReservationResult(
            outcome=GovernorReservationOutcome.RESERVED,
            reservation_id=reservation_command.reservation_id,
            reservation_expires_at=reservation_command.reservation_expires_at,
        )
        contact_result = ContactGovernorResult(
            decision=ContactGovernorDecision(
                allowed=True,
                reason_codes=(ContactGovernorReasonCode.ALLOWED.value,),
                policy_version=configured_policy.policy_version,
                evaluated_at=NOW,
            ),
            reservation_id=reservation_command.reservation_id,
            reservation_expires_at=reservation_command.reservation_expires_at,
        )
        sensitive_values = (
            "candidate-sensitive-123",
            "stream-sensitive-456",
            "generation-sensitive-789",
            "recruiter-sensitive-123",
            "organization-sensitive-456",
            "company-sensitive-789",
            reservation_command.reservation_id,
            reservation_command.request_fingerprint,
        )
        for value in (
            sensitive_request,
            sensitive_facts,
            facts_result,
            reservation_command,
            reservation_result,
            contact_result,
        ):
            rendered = repr(value)
            assert all(sensitive not in rendered for sensitive in sensitive_values)

    def test_reservation_lifecycle_vocabulary_is_closed(self):
        assert {state.value for state in GovernorReservationState} == {
            "reserved",
            "consumed",
            "released",
        }

    def test_ledger_protocol_freezes_counting_and_atomicity_semantics(self):
        contract = inspect.getdoc(ContactGovernorReservationLedger)
        assert contract is not None
        contract = " ".join(contract.split())
        for required in (
            "atomic check-and-create",
            "non-expired ``reserved`` entries count provisionally",
            "``consumed`` entries count as activity",
            "``released`` entries",
            "expired unconsumed reservations",
            "activity timestamp is immutable",
            "actor scope plus idempotency key",
            "independent request fingerprint",
            "caller-owned ``evaluated_at``",
            "never reads a wall clock",
            "timezone-aware, whole-millisecond contract",
            "only before its lease expiry; equality is expired",
            "same contact request is idempotent even after the former lease expires",
            "different contact request conflicts",
            "Released entries cannot be consumed",
            "already released entry is idempotent",
            "consumed entries cannot be released",
            "session remains opaque",
            "caller-owned transaction",
        ):
            assert required in contract

    def test_ledger_lifecycle_signatures_are_explicit_and_session_is_opaque(self):
        consume = inspect.signature(ContactGovernorReservationLedger.consume)
        assert list(consume.parameters) == [
            "self",
            "reservation_id",
            "contact_request_id",
            "evaluated_at",
            "session",
        ]
        assert consume.parameters["evaluated_at"].kind is inspect.Parameter.KEYWORD_ONLY
        assert consume.parameters["evaluated_at"].annotation == "datetime"
        assert consume.parameters["session"].kind is inspect.Parameter.KEYWORD_ONLY
        assert consume.parameters["session"].default is None
        assert consume.parameters["session"].annotation is inspect.Parameter.empty

        release = inspect.signature(ContactGovernorReservationLedger.release)
        assert list(release.parameters) == ["self", "reservation_id", "session"]
        assert release.parameters["session"].kind is inspect.Parameter.KEYWORD_ONLY
        assert release.parameters["session"].default is None
        assert release.parameters["session"].annotation is inspect.Parameter.empty

    def test_reservation_identity_uses_actor_scope_and_idempotency_key_only(self):
        base = request()
        different_candidate = request(candidate_id=CandidateId("candidate-2"))
        assert reservation_actor_scope(base) == ("recruiter-1", "agency-1")
        assert derive_reservation_id(base) == derive_reservation_id(different_candidate)
        assert derive_reservation_id(base) != derive_reservation_id(
            request(idempotency_key=IdempotencyKey("attempt-2"))
        )
        assert derive_reservation_id(base) != derive_reservation_id(
            request(recruiting_actor=actor(recruiter="recruiter-2"))
        )
        assert derive_reservation_id(base) != derive_reservation_id(
            request(recruiting_actor=actor(requesting="agency-2"))
        )

    def test_request_fingerprint_is_separate_and_detects_payload_change(self):
        base = request()
        assert derive_request_fingerprint(base) == derive_request_fingerprint(
            request(idempotency_key=IdempotencyKey("another-key"))
        )
        assert derive_request_fingerprint(base) != derive_request_fingerprint(
            request(candidate_id=CandidateId("candidate-2"))
        )
        assert derive_request_fingerprint(base) != derive_request_fingerprint(
            request(recruiting_actor=actor(hiring="company-2"))
        )
        assert derive_request_fingerprint(base) != derive_request_fingerprint(
            request(projection_state_version=12)
        )

    def test_ledger_command_binds_canonical_identity_fingerprint_and_lease(self):
        command_request = request()
        configured_policy = policy()
        valid = GovernorReservationCommand(
            request=command_request,
            policy=configured_policy,
            evaluated_at=NOW,
            reservation_id=derive_reservation_id(command_request),
            request_fingerprint=derive_request_fingerprint(command_request),
            reservation_expires_at=NOW + configured_policy.reservation_lease,
        )
        assert valid.evaluated_at == NOW
        for field, value in (
            ("reservation_id", "invented"),
            ("request_fingerprint", "invented"),
            ("reservation_expires_at", NOW + timedelta(seconds=1)),
        ):
            with pytest.raises(ValueError):
                replace(valid, **{field: value})

    @pytest.mark.parametrize(
        "outcome",
        [
            GovernorReservationOutcome.DUPLICATE,
            GovernorReservationOutcome.FREQUENCY_CAP_REACHED,
            GovernorReservationOutcome.COMPANY_COOLING_ACTIVE,
            GovernorReservationOutcome.ACTIVE_RESERVATION_LIMIT_REACHED,
            GovernorReservationOutcome.IDEMPOTENCY_CONFLICT,
        ],
    )
    def test_denied_ledger_outcomes_cannot_expose_reservation(self, outcome):
        with pytest.raises(ValueError):
            GovernorReservationResult(
                outcome=outcome,
                reservation_id="reservation",
                reservation_expires_at=NOW + timedelta(minutes=1),
            )

    def test_protocols_are_narrow_and_structurally_satisfied_by_fakes(self):
        assert inspect.isclass(CurrentRecruitingTrustEvaluator)
        assert inspect.isclass(IntroductionPermissionEvaluator)
        assert inspect.isclass(CurrentGovernorFactsReader)
        assert inspect.isclass(ContactGovernorReservationLedger)
        assert hasattr(FakeTrustEvaluator(), "evaluate_current_trust")
        assert hasattr(FakePermissionEvaluator(), "evaluate_introduction_permission")
        assert hasattr(FakeFactsReader(), "read_current_governor_facts")
        assert hasattr(FakeLedger(), "reserve")


class TestServiceOrderingAndFailClosedBehavior:
    def test_missing_policy_fails_closed_with_fixed_redacted_error(self):
        with pytest.raises(
            ContactGovernorUnavailableError,
            match="^contact governor unavailable$",
        ):
            ContactGovernorService(
                policy=None,
                trust_evaluator=FakeTrustEvaluator(),
                permission_evaluator=FakePermissionEvaluator(),
                facts_reader=FakeFactsReader(),
                reservation_ledger=FakeLedger(),
                clock=FixedClock(),
            )

    @pytest.mark.asyncio
    async def test_clock_failure_is_a_fixed_redacted_error(self):
        governor = service(clock=FixedClock(RuntimeError("database-secret")))
        with pytest.raises(
            ContactGovernorUnavailableError,
            match="^contact governor unavailable$",
        ) as exc:
            await governor.evaluate(request())
        assert "database-secret" not in str(exc.value)
        assert exc.value.__cause__ is None

    @pytest.mark.asyncio
    async def test_trust_and_permission_are_re_evaluated_on_every_request(self):
        trust = FakeTrustEvaluator()
        permission = FakePermissionEvaluator()
        governor = service(trust=trust, permission=permission)
        await governor.evaluate(request())
        await governor.evaluate(request(idempotency_key=IdempotencyKey("attempt-2")))
        assert len(trust.calls) == 2
        assert len(permission.calls) == 2
        assert all(call[-1] == NOW for call in trust.calls + permission.calls)

    @pytest.mark.asyncio
    async def test_both_current_decisions_are_called_even_when_trust_denies(self):
        trust = FakeTrustEvaluator(allowed=False)
        permission = FakePermissionEvaluator(allowed=False)
        reader = FakeFactsReader()
        ledger = FakeLedger()
        result = await service(
            trust=trust,
            permission=permission,
            reader=reader,
            ledger=ledger,
        ).evaluate(request())
        assert reason(result) == ContactGovernorReasonCode.TRUST_DENIED.value
        assert len(trust.calls) == len(permission.calls) == 1
        assert reader.calls == []
        assert ledger.calls == []

    @pytest.mark.asyncio
    async def test_trust_denial_wins_over_permission_failure(self):
        result = await service(
            trust=FakeTrustEvaluator(allowed=False),
            permission=FakePermissionEvaluator(failure=RuntimeError("sensitive")),
        ).evaluate(request())
        assert reason(result) == ContactGovernorReasonCode.TRUST_DENIED.value
        assert result.decision.evidence_refs == ()

    @pytest.mark.asyncio
    async def test_permission_denial_wins_over_trust_failure(self):
        result = await service(
            trust=FakeTrustEvaluator(failure=RuntimeError("sensitive")),
            permission=FakePermissionEvaluator(allowed=False),
        ).evaluate(request())
        assert reason(result) == ContactGovernorReasonCode.PERMISSION_DENIED.value
        assert result.decision.evidence_refs == ()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("failed_dependency", ["trust", "permission"])
    async def test_upstream_exception_is_redacted_governor_unavailable(self, failed_dependency):
        trust = FakeTrustEvaluator()
        permission = FakePermissionEvaluator()
        target = trust if failed_dependency == "trust" else permission
        target.failure = RuntimeError("competitor-source-and-candidate-exclusion")
        result = await service(trust=trust, permission=permission).evaluate(request())
        assert reason(result) == ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE.value
        assert result.decision.evidence_refs == ()
        assert "competitor" not in repr(result)

    @pytest.mark.asyncio
    async def test_wrong_or_non_current_upstream_decision_fails_closed(self):
        stale = TrustDecision(
            allowed=True,
            reason_codes=("trusted",),
            policy_version=TRUST_POLICY,
            evaluated_at=NOW - timedelta(seconds=1),
        )
        result = await service(trust=FakeTrustEvaluator(result=stale)).evaluate(request())
        assert reason(result) == ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE.value

    @pytest.mark.asyncio
    async def test_facts_exception_is_redacted_and_ledger_is_not_called(self):
        ledger = FakeLedger()
        result = await service(
            reader=FakeFactsReader(failure=RuntimeError("excluded-by-current-employer")),
            ledger=ledger,
        ).evaluate(request())
        assert reason(result) == ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE.value
        assert result.decision.evidence_refs == ()
        assert ledger.calls == []
        assert "current-employer" not in repr(result)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "facts_result,expected",
        [
            (
                GovernorFactsReadResult(status=GovernorFactsStatus.MISSING, facts=None),
                ContactGovernorReasonCode.CANDIDATE_FACTS_MISSING,
            ),
            (
                GovernorFactsReadResult(status=GovernorFactsStatus.STALE, facts=None),
                ContactGovernorReasonCode.CANDIDATE_FACTS_STALE,
            ),
        ],
    )
    async def test_missing_and_stale_facts_fail_closed(self, facts_result, expected):
        result = await service(reader=FakeFactsReader(result=facts_result)).evaluate(request())
        assert reason(result) == expected.value

    @pytest.mark.asyncio
    async def test_facts_bound_to_another_b7_version_are_stale(self):
        command = request()
        mismatched = facts(command, projection_state_version=command.projection_state_version + 1)
        result = await service(
            reader=FakeFactsReader(
                result=GovernorFactsReadResult(
                    status=GovernorFactsStatus.CURRENT,
                    facts=mismatched,
                )
            )
        ).evaluate(command)
        assert reason(result) == ContactGovernorReasonCode.CANDIDATE_FACTS_STALE.value

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "changes,expected",
        [
            (
                {
                    "match_classification": GovernorMatchClassification.MISSING,
                    "professional_match_score": None,
                },
                ContactGovernorReasonCode.PROFESSIONAL_MATCH_MISSING,
            ),
            (
                {"fit_classification": GovernorFitClassification.MISSING},
                ContactGovernorReasonCode.OPPORTUNITY_FIT_MISSING,
            ),
            (
                {"eligibility_classification": GovernorEligibilityClassification.INELIGIBLE},
                ContactGovernorReasonCode.HARD_ELIGIBILITY_INELIGIBLE,
            ),
            (
                {"eligibility_classification": GovernorEligibilityClassification.UNRESOLVED},
                ContactGovernorReasonCode.HARD_ELIGIBILITY_UNRESOLVED,
            ),
            (
                {"fit_classification": GovernorFitClassification.INCOMPATIBLE},
                ContactGovernorReasonCode.OPPORTUNITY_FIT_INCOMPATIBLE,
            ),
            (
                {"fit_classification": GovernorFitClassification.UNRESOLVED},
                ContactGovernorReasonCode.OPPORTUNITY_FIT_UNRESOLVED,
            ),
            (
                {"professional_match_score": 71},
                ContactGovernorReasonCode.PROFESSIONAL_MATCH_BELOW_THRESHOLD,
            ),
        ],
    )
    async def test_match_eligibility_and_fit_fail_closed(self, changes, expected):
        command = request()
        reader = FakeFactsReader(
            result=GovernorFactsReadResult(
                status=GovernorFactsStatus.CURRENT,
                facts=facts(command, **changes),
            )
        )
        ledger = FakeLedger()
        result = await service(reader=reader, ledger=ledger).evaluate(command)
        assert reason(result) == expected.value
        assert ledger.calls == []

    @pytest.mark.asyncio
    async def test_missing_inputs_precede_other_candidate_gate_reasons(self):
        command = request()
        derived = facts(
            command,
            match_classification=GovernorMatchClassification.MISSING,
            professional_match_score=None,
            eligibility_classification=GovernorEligibilityClassification.INELIGIBLE,
            fit_classification=GovernorFitClassification.MISSING,
        )
        result = await service(
            reader=FakeFactsReader(
                GovernorFactsReadResult(GovernorFactsStatus.CURRENT, derived)
            )
        ).evaluate(command)
        assert reason(result) == ContactGovernorReasonCode.PROFESSIONAL_MATCH_MISSING.value

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "fit_classification",
        [GovernorFitClassification.COMPATIBLE, GovernorFitClassification.NOT_APPLICABLE],
    )
    async def test_compatible_and_not_applicable_fit_may_reserve(self, fit_classification):
        command = request()
        ledger = FakeLedger()
        result = await service(
            reader=FakeFactsReader(
                GovernorFactsReadResult(
                    GovernorFactsStatus.CURRENT,
                    facts(command, fit_classification=fit_classification),
                )
            ),
            ledger=ledger,
        ).evaluate(command)
        assert result.decision.allowed is True
        assert reason(result) == ContactGovernorReasonCode.ALLOWED.value
        assert len(ledger.calls) == 1

    @pytest.mark.asyncio
    async def test_match_threshold_is_policy_owned_and_inclusive(self):
        command = request()
        result = await service(
            configured_policy=policy(minimum_professional_match_score=73),
            reader=FakeFactsReader(
                GovernorFactsReadResult(
                    GovernorFactsStatus.CURRENT,
                    facts(command, professional_match_score=72),
                )
            ),
        ).evaluate(command)
        assert reason(result) == ContactGovernorReasonCode.PROFESSIONAL_MATCH_BELOW_THRESHOLD.value

        passing = await service(
            configured_policy=policy(minimum_professional_match_score=72),
            reader=FakeFactsReader(
                GovernorFactsReadResult(
                    GovernorFactsStatus.CURRENT,
                    facts(command, professional_match_score=72),
                )
            ),
        ).evaluate(command)
        assert passing.decision.allowed is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "outcome,expected",
        [
            (GovernorReservationOutcome.DUPLICATE, ContactGovernorReasonCode.DUPLICATE_CONTACT),
            (
                GovernorReservationOutcome.FREQUENCY_CAP_REACHED,
                ContactGovernorReasonCode.FREQUENCY_CAP_REACHED,
            ),
            (
                GovernorReservationOutcome.COMPANY_COOLING_ACTIVE,
                ContactGovernorReasonCode.COMPANY_COOLING_ACTIVE,
            ),
            (
                GovernorReservationOutcome.ACTIVE_RESERVATION_LIMIT_REACHED,
                ContactGovernorReasonCode.ACTIVE_RESERVATION_LIMIT_REACHED,
            ),
            (
                GovernorReservationOutcome.IDEMPOTENCY_CONFLICT,
                ContactGovernorReasonCode.IDEMPOTENCY_CONFLICT,
            ),
        ],
    )
    async def test_ledger_denials_are_closed_reason_codes(self, outcome, expected):
        result = await service(ledger=FakeLedger(outcome=outcome)).evaluate(request())
        assert result.decision.allowed is False
        assert reason(result) == expected.value
        assert result.decision.evidence_refs == ()

    @pytest.mark.asyncio
    async def test_ledger_exception_is_fixed_redacted_unavailable(self):
        result = await service(
            ledger=FakeLedger(failure=RuntimeError("mongo-index-detail"))
        ).evaluate(request())
        assert reason(result) == ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE.value
        assert result.decision.evidence_refs == ()
        assert "mongo" not in repr(result)

    @pytest.mark.asyncio
    async def test_reservation_command_failure_is_fixed_redacted_unavailable(
        self,
        monkeypatch,
    ):
        def fail_command_construction(**kwargs):
            raise ValueError("candidate-sensitive-internal-detail")

        monkeypatch.setattr(
            contact_governor_service_module,
            "GovernorReservationCommand",
            fail_command_construction,
        )
        result = await service().evaluate(request())
        assert reason(result) == ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE.value
        assert result.decision.evidence_refs == ()
        assert "candidate-sensitive-internal-detail" not in repr(result)

    @pytest.mark.asyncio
    async def test_success_uses_injected_policy_and_canonical_reservation_command(self):
        command = request()
        configured_policy = policy(policy_version=PolicyVersion("configured-v17"))
        ledger = FakeLedger()
        result = await service(
            configured_policy=configured_policy,
            ledger=ledger,
        ).evaluate(command)
        assert result.decision.allowed is True
        assert result.decision.policy_version == PolicyVersion("configured-v17")
        assert result.decision.evaluated_at == NOW
        assert result.reservation_id == derive_reservation_id(command)
        assert result.reservation_expires_at == NOW + configured_policy.reservation_lease
        ledger_command = ledger.calls[0]
        assert ledger_command.request_fingerprint == derive_request_fingerprint(command)
        assert ledger_command.policy is configured_policy

    @pytest.mark.asyncio
    async def test_idempotent_replay_is_allowed_and_explicit(self):
        result = await service(
            ledger=FakeLedger(outcome=GovernorReservationOutcome.IDEMPOTENT_REPLAY)
        ).evaluate(request())
        assert result.decision.allowed is True
        assert reason(result) == ContactGovernorReasonCode.ALLOWED_IDEMPOTENT_REPLAY.value

    @pytest.mark.asyncio
    async def test_same_scoped_request_replay_rechecks_current_inputs_in_order(self):
        events = []
        trust = FakeTrustEvaluator(events=events)
        permission = FakePermissionEvaluator(events=events)
        reader = FakeFactsReader(events=events)
        ledger = FakeLedger(
            outcomes=(
                GovernorReservationOutcome.RESERVED,
                GovernorReservationOutcome.IDEMPOTENT_REPLAY,
            ),
            events=events,
        )
        governor = service(
            trust=trust,
            permission=permission,
            reader=reader,
            ledger=ledger,
        )
        command = request()

        first = await governor.evaluate(command)
        second = await governor.evaluate(command)

        assert reason(first) == ContactGovernorReasonCode.ALLOWED.value
        assert reason(second) == ContactGovernorReasonCode.ALLOWED_IDEMPOTENT_REPLAY.value
        assert len(trust.calls) == 2
        assert len(permission.calls) == 2
        assert len(reader.calls) == 2
        assert len(ledger.calls) == 2
        assert ledger.calls[0].reservation_id == ledger.calls[1].reservation_id
        assert ledger.calls[0].request_fingerprint == ledger.calls[1].request_fingerprint
        assert events == [
            "trust",
            "permission",
            "facts",
            "ledger:reserved",
            "trust",
            "permission",
            "facts",
            "ledger:idempotent_replay",
        ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "later_denial,expected_reason",
        [
            ("trust", ContactGovernorReasonCode.TRUST_DENIED),
            ("permission", ContactGovernorReasonCode.PERMISSION_DENIED),
        ],
    )
    async def test_later_current_denial_blocks_existing_reservation_replay(
        self,
        later_denial,
        expected_reason,
    ):
        events = []
        trust = FakeTrustEvaluator(events=events)
        permission = FakePermissionEvaluator(events=events)
        reader = FakeFactsReader(events=events)
        ledger = FakeLedger(
            outcomes=(
                GovernorReservationOutcome.RESERVED,
                GovernorReservationOutcome.IDEMPOTENT_REPLAY,
            ),
            events=events,
        )
        governor = service(
            trust=trust,
            permission=permission,
            reader=reader,
            ledger=ledger,
        )
        command = request()
        first = await governor.evaluate(command)
        assert first.decision.allowed is True

        if later_denial == "trust":
            trust.allowed = False
        else:
            permission.allowed = False
        second = await governor.evaluate(command)

        assert second.decision.allowed is False
        assert reason(second) == expected_reason.value
        assert len(trust.calls) == 2
        assert len(permission.calls) == 2
        assert len(reader.calls) == 1
        assert len(ledger.calls) == 1
        assert events == [
            "trust",
            "permission",
            "facts",
            "ledger:reserved",
            "trust",
            "permission",
        ]

    @pytest.mark.asyncio
    async def test_evidence_is_safe_and_never_copies_upstream_details(self):
        result = await service().evaluate(request())
        assert result.decision.evidence_refs == (
            f"governor_facts:{derive_request_fingerprint(request())}",
            f"contact_governor_reservation:{result.reservation_id}",
        )
        serialized = repr(result)
        assert "sensitive-trust-evidence" not in serialized
        assert "sensitive-permission-evidence" not in serialized
        assert "source" not in serialized.lower()
        assert "exclusion" not in serialized.lower()


class TestArchitectureBoundary:
    def test_core_has_no_matching_b7_permissions_or_persistence_imports(self):
        root = Path(__file__).resolve().parents[1]
        sources = "\n".join(
            (root / "domains" / "trust" / filename).read_text(encoding="utf-8")
            for filename in (
                "contact_governor_models.py",
                "contact_governor_service.py",
            )
        ).lower()
        forbidden = (
            "domains.matching",
            "stream_candidate_models",
            "stream_candidate_repository",
            "domains.permissions",
            "motor",
            "pymongo",
            "mongodb",
            "mongo_client",
        )
        for token in forbidden:
            assert token not in sources

    def test_core_defines_no_contact_request_grant_reveal_or_messaging_workflow(self):
        root = Path(__file__).resolve().parents[1]
        sources = "\n".join(
            (root / "domains" / "trust" / filename).read_text(encoding="utf-8")
            for filename in (
                "contact_governor_models.py",
                "contact_governor_service.py",
            )
        )
        forbidden_symbols = (
            "ContactRequestService",
            "GrantService",
            "RevealService",
            "MessagingService",
            "CrossOffer",
        )
        for symbol in forbidden_symbols:
            assert symbol not in sources

    def test_no_talent_score_or_evidence_coverage_gate_exists(self):
        root = Path(__file__).resolve().parents[1]
        sources = "\n".join(
            (root / "domains" / "trust" / filename).read_text(encoding="utf-8")
            for filename in (
                "contact_governor_models.py",
                "contact_governor_service.py",
            )
        ).lower()
        assert "talent_score" not in sources
        assert "evidence_coverage" not in sources
