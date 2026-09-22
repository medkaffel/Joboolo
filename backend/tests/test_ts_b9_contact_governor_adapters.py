"""Hermetic B9.3 tests for the A8/A9/B7 current-state adapters."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from domains.matching.opportunity_fit_models import (
    HardEligibilityState,
    OpportunityFitState,
)
from domains.permissions.models import PermissionAction
from domains.shared.versioning import ConsentPolicyVersion, PolicyVersion
from domains.talent_stream.contact_governor_adapters import (
    ContactGovernorAdapterError,
    IntroductionPermissionEvaluatorAdapter,
    RecruitingTrustEvaluatorAdapter,
    StreamCandidateGovernorFactsReader,
)
from domains.talent_stream.contracts import RecruitingActorContext
from domains.talent_stream.decisions import PermissionDecision, TrustDecision
from domains.talent_stream.stream_candidate_models import (
    ApplicationEvidence,
    DeclaredInterestEvidence,
    DiscoveryEvidence,
    OpportunityFitSummary,
    ProfessionalMatchSummary,
    SharedFavoriteEvidence,
    StreamCandidate,
)
from domains.talent_stream.stream_candidate_persistence import ProjectionState
from domains.trust.contact_governor_models import (
    ActiveReservationLimitPolicy,
    CompanyCoolingPolicy,
    ContactGovernorPolicyV1,
    ContactGovernorReasonCode,
    ContactGovernorRequest,
    DuplicateProtectionPolicy,
    FrequencyCapPolicy,
    GovernorEligibilityClassification,
    GovernorFactsStatus,
    GovernorFitClassification,
    GovernorMatchClassification,
)
from domains.trust.contact_governor_service import ContactGovernorService


NOW = datetime(2026, 9, 22, 8, 0, 0, 123000, tzinfo=timezone.utc)


def actor():
    return RecruitingActorContext(
        recruiter_user_id="recruiter-sensitive",
        requesting_organization_id="requesting-sensitive",
        hiring_company_id="hiring-sensitive",
        mandate_id="mandate-sensitive",
    )


def request(**changes):
    values = dict(
        idempotency_key="attempt-1",
        candidate_id="candidate-sensitive",
        stream_id="stream-sensitive",
        generation_id="generation-7",
        projection_state_version=11,
        stream_version=5,
        requirement_version=3,
        role_dna_id="role-dna-1",
        role_dna_version=2,
        opportunity_spec_id="opportunity-1",
        opportunity_spec_version=4,
        recruiting_actor=actor(),
    )
    values.update(changes)
    return ContactGovernorRequest(**values)


def state(**changes):
    values = dict(
        stream_id="stream-sensitive",
        state_version=11,
        active_generation_id="generation-7",
        stream_version=5,
        requirement_version=3,
        role_dna_id="role-dna-1",
        role_dna_version=2,
        opportunity_spec_id="opportunity-1",
        opportunity_spec_version=4,
        candidate_count=1,
        published_at=NOW - timedelta(days=365),
    )
    values.update(changes)
    return ProjectionState(**values)


def candidate(**changes):
    values = dict(
        stream_id="stream-sensitive",
        stream_version=5,
        requirement_version=3,
        generation_id="generation-7",
        candidate_id="candidate-sensitive",
        role_dna_id="role-dna-1",
        role_dna_version=2,
        opportunity_spec_id="opportunity-1",
        opportunity_spec_version=4,
        computed_at=NOW,
        application_evidence=ApplicationEvidence("private-application", "active", NOW),
        declared_interest_evidence=DeclaredInterestEvidence("private-intent", NOW),
        shared_favorite_evidence=SharedFavoriteEvidence(
            "private-favorite", "private-cycle", NOW
        ),
        discovery_evidence=DiscoveryEvidence(71, NOW),
        professional_match_summary=ProfessionalMatchSummary(
            9, 2, "match-engine-v1", 81, 23, NOW
        ),
        opportunity_fit_summary=OpportunityFitSummary(
            37,
            4,
            "fit-engine-v1",
            HardEligibilityState.ELIGIBLE,
            OpportunityFitState.COMPATIBLE,
            19,
            NOW,
        ),
    )
    values.update(changes)
    return StreamCandidate(**values)


class TrustServiceSpy:
    def __init__(self, failure=None, result=None):
        self.failure = failure
        self.result = result
        self.calls = []

    async def evaluate_recruiting_actor_trust(
        self, recruiting_actor, *, policy_version, evaluated_at
    ):
        self.calls.append((recruiting_actor, policy_version, evaluated_at))
        if self.failure:
            raise self.failure
        if self.result is not None:
            return self.result
        return TrustDecision(
            allowed=True,
            reason_codes=("trusted",),
            policy_version=policy_version,
            evaluated_at=evaluated_at,
            evidence_refs=("private-a8-evidence",),
        )


class PermissionServiceSpy:
    def __init__(self, failure=None, result=None):
        self.failure = failure
        self.result = result
        self.calls = []

    async def evaluate(self, context, *, evaluated_at):
        self.calls.append((context, evaluated_at))
        if self.failure:
            raise self.failure
        if self.result is not None:
            return self.result
        return PermissionDecision(
            allowed=True,
            reason_codes=("permitted",),
            policy_version=PolicyVersion("permission-v1"),
            consent_policy_version=ConsentPolicyVersion("consent-v1"),
            evaluated_at=evaluated_at,
            evidence_refs=("private-a9-evidence",),
        )


class RepositorySpy:
    def __init__(self, states, projected_candidate=None, failure_at=None):
        self.states = list(states)
        self.projected_candidate = projected_candidate
        self.failure_at = failure_at
        self.calls = []

    async def get_projection_state(self, stream_id):
        self.calls.append(("state", stream_id))
        if self.failure_at == len(self.calls):
            raise RuntimeError("private repository state detail")
        return self.states.pop(0)

    async def get_generation_candidate(self, stream_id, generation_id, candidate_id):
        self.calls.append(("candidate", stream_id, generation_id, candidate_id))
        if self.failure_at == len(self.calls):
            raise RuntimeError("private repository candidate detail")
        return self.projected_candidate


class AllowTrustEvaluator:
    async def evaluate_current_trust(self, recruiting_actor, *, evaluated_at):
        return TrustDecision(
            allowed=True,
            reason_codes=("trusted",),
            policy_version=PolicyVersion("a8-v1"),
            evaluated_at=evaluated_at,
        )


class AllowPermissionEvaluator:
    async def evaluate_introduction_permission(
        self, *, candidate_id, stream_id, recruiting_actor, evaluated_at
    ):
        return PermissionDecision(
            allowed=True,
            reason_codes=("permitted",),
            policy_version=PolicyVersion("a9-v1"),
            consent_policy_version=ConsentPolicyVersion("consent-v1"),
            evaluated_at=evaluated_at,
        )


class MustNotReadFacts:
    async def read_current_governor_facts(self, command):
        raise AssertionError("facts must not be read after authorization denial/failure")


class MustNotReserve:
    async def reserve(self, command):
        raise AssertionError("ledger must not be called after authorization denial/failure")


def governor_with(*, trust, permission):
    return ContactGovernorService(
        policy=ContactGovernorPolicyV1(
            policy_version=PolicyVersion("governor-v1"),
            minimum_professional_match_score=50,
            frequency_cap_policy=FrequencyCapPolicy(enabled=False, caps=None),
            duplicate_protection_policy=DuplicateProtectionPolicy(
                enabled=False, scope=None, window=None
            ),
            company_cooling_policy=CompanyCoolingPolicy(
                enabled=False, scope=None, period=None
            ),
            active_reservation_limit_policy=ActiveReservationLimitPolicy(
                enabled=False, maximum_active_reservations=None
            ),
            reservation_lease=timedelta(minutes=1),
        ),
        trust_evaluator=trust,
        permission_evaluator=permission,
        facts_reader=MustNotReadFacts(),
        reservation_ledger=MustNotReserve(),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_a8_adapter_forwards_exact_actor_time_and_constructor_policy():
    service = TrustServiceSpy()
    adapter = RecruitingTrustEvaluatorAdapter(
        service, policy_version=PolicyVersion("a8-explicit-v9")
    )
    decision = await adapter.evaluate_current_trust(actor(), evaluated_at=NOW)
    assert decision.allowed is True
    assert service.calls == [(actor(), PolicyVersion("a8-explicit-v9"), NOW)]


@pytest.mark.asyncio
async def test_a8_adapter_returns_denial_unchanged():
    denied = TrustDecision(
        allowed=False,
        reason_codes=("membership_not_active",),
        policy_version=PolicyVersion("a8-v1"),
        evaluated_at=NOW,
        evidence_refs=("private-a8-membership",),
    )
    adapter = RecruitingTrustEvaluatorAdapter(
        TrustServiceSpy(result=denied), policy_version=PolicyVersion("a8-v1")
    )
    assert await adapter.evaluate_current_trust(actor(), evaluated_at=NOW) is denied


@pytest.mark.parametrize("invalid", [None, "", "   ", True, 7])
def test_a8_adapter_requires_an_explicit_nonblank_policy_version(invalid):
    with pytest.raises(ContactGovernorAdapterError) as exc:
        RecruitingTrustEvaluatorAdapter(TrustServiceSpy(), policy_version=invalid)
    assert str(exc.value) == "contact governor adapter unavailable"


@pytest.mark.asyncio
async def test_a8_adapter_exception_is_fixed_and_redacted():
    adapter = RecruitingTrustEvaluatorAdapter(
        TrustServiceSpy(RuntimeError("private-a8-stack")),
        policy_version=PolicyVersion("a8-v1"),
    )
    with pytest.raises(ContactGovernorAdapterError) as exc:
        await adapter.evaluate_current_trust(actor(), evaluated_at=NOW)
    assert str(exc.value) == "contact governor adapter unavailable"
    assert exc.value.__cause__ is None
    assert "private" not in repr(exc.value)


@pytest.mark.asyncio
async def test_a8_exception_fails_closed_through_governor_without_evidence():
    adapter = RecruitingTrustEvaluatorAdapter(
        TrustServiceSpy(RuntimeError("private-a8-stack")),
        policy_version=PolicyVersion("a8-v1"),
    )
    result = await governor_with(
        trust=adapter, permission=AllowPermissionEvaluator()
    ).evaluate(request())
    assert result.decision.allowed is False
    assert result.decision.reason_codes == (
        ContactGovernorReasonCode.GOVERNOR_UNAVAILABLE.value,
    )
    assert result.decision.evidence_refs == ()
    assert "private" not in repr(result)


@pytest.mark.asyncio
async def test_a9_adapter_builds_exact_introduction_context_and_forwards_time():
    service = PermissionServiceSpy()
    decision = await IntroductionPermissionEvaluatorAdapter(
        service
    ).evaluate_introduction_permission(
        candidate_id="candidate-sensitive",
        stream_id="stream-sensitive",
        recruiting_actor=actor(),
        evaluated_at=NOW,
    )
    context, evaluated_at = service.calls[0]
    assert decision.allowed is True
    assert context.candidate_id == "candidate-sensitive"
    assert context.stream_id == "stream-sensitive"
    assert context.recruiting_actor == actor()
    assert context.action is PermissionAction.REQUEST_INTRODUCTION
    assert context.document_id is None
    assert evaluated_at == NOW


@pytest.mark.asyncio
async def test_a9_adapter_exception_is_fixed_and_redacted():
    adapter = IntroductionPermissionEvaluatorAdapter(
        PermissionServiceSpy(RuntimeError("private-a9-stack"))
    )
    with pytest.raises(ContactGovernorAdapterError) as exc:
        await adapter.evaluate_introduction_permission(
            candidate_id="candidate-sensitive",
            stream_id="stream-sensitive",
            recruiting_actor=actor(),
            evaluated_at=NOW,
        )
    assert str(exc.value) == "contact governor adapter unavailable"
    assert exc.value.__cause__ is None
    assert "private" not in repr(exc.value)


@pytest.mark.asyncio
async def test_a9_exclusion_denial_remains_denial_without_governor_evidence_leak():
    denied = PermissionDecision(
        allowed=False,
        reason_codes=("candidate_organization_exclusion",),
        policy_version=PolicyVersion("a9-v1"),
        consent_policy_version=ConsentPolicyVersion("consent-v1"),
        evaluated_at=NOW,
        evidence_refs=("private-candidate-preference", "private-organization"),
    )
    adapter = IntroductionPermissionEvaluatorAdapter(
        PermissionServiceSpy(result=denied)
    )
    assert await adapter.evaluate_introduction_permission(
        candidate_id="candidate-sensitive",
        stream_id="stream-sensitive",
        recruiting_actor=actor(),
        evaluated_at=NOW,
    ) is denied

    result = await governor_with(
        trust=AllowTrustEvaluator(), permission=adapter
    ).evaluate(request())
    assert result.decision.allowed is False
    assert result.decision.reason_codes == (
        ContactGovernorReasonCode.PERMISSION_DENIED.value,
    )
    assert result.decision.evidence_refs == ()
    assert "private" not in repr(result)


@pytest.mark.asyncio
async def test_facts_reader_missing_state_is_missing_without_candidate_read():
    repository = RepositorySpy([None])
    result = await StreamCandidateGovernorFactsReader(
        repository
    ).read_current_governor_facts(request())
    assert result.status is GovernorFactsStatus.MISSING
    assert result.facts is None
    assert repository.calls == [("state", "stream-sensitive")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_change",
    [
        {"stream_id": "stream-other"},
        {"projection_state_version": 12},
        {"generation_id": "generation-other"},
        {"stream_version": 6},
        {"requirement_version": 4},
        {"role_dna_id": "role-dna-other"},
        {"role_dna_version": 3},
        {"opportunity_spec_id": "opportunity-other"},
        {"opportunity_spec_version": 5},
    ],
)
async def test_request_mismatch_against_current_pointer_is_stale(request_change):
    repository = RepositorySpy([state()])
    result = await StreamCandidateGovernorFactsReader(
        repository
    ).read_current_governor_facts(request(**request_change))
    assert result.status is GovernorFactsStatus.STALE
    assert result.facts is None
    assert len(repository.calls) == 1


@pytest.mark.asyncio
async def test_absent_exact_candidate_is_missing_without_fallback_or_refresh():
    current = state()
    repository = RepositorySpy([current], projected_candidate=None)
    result = await StreamCandidateGovernorFactsReader(
        repository
    ).read_current_governor_facts(request())
    assert result.status is GovernorFactsStatus.MISSING
    assert repository.calls == [
        ("state", "stream-sensitive"),
        ("candidate", "stream-sensitive", "generation-7", "candidate-sensitive"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state_change",
    [
        {"stream_id": "stream-other"},
        {"state_version": 12},
        {"active_generation_id": "generation-other"},
        {"stream_version": 6},
        {"requirement_version": 4},
        {"role_dna_id": "role-dna-other"},
        {"role_dna_version": 3},
        {"opportunity_spec_id": "opportunity-other"},
        {"opportunity_spec_version": 5},
    ],
)
async def test_authoritative_pointer_change_between_reads_is_stale(state_change):
    before = state()
    repository = RepositorySpy(
        [before, state(**state_change)], projected_candidate=candidate()
    )
    result = await StreamCandidateGovernorFactsReader(
        repository
    ).read_current_governor_facts(request())
    assert result.status is GovernorFactsStatus.STALE
    assert result.facts is None


@pytest.mark.asyncio
async def test_projection_disappearing_during_double_read_is_stale():
    result = await StreamCandidateGovernorFactsReader(
        RepositorySpy([state(), None], projected_candidate=candidate())
    ).read_current_governor_facts(request())
    assert result.status is GovernorFactsStatus.STALE
    assert result.facts is None


@pytest.mark.asyncio
async def test_published_at_age_and_change_do_not_make_exact_pointer_stale():
    before = state(published_at=NOW - timedelta(days=1000))
    after = replace(before, published_at=NOW)
    result = await StreamCandidateGovernorFactsReader(
        RepositorySpy([before, after], projected_candidate=candidate())
    ).read_current_governor_facts(request())
    assert result.status is GovernorFactsStatus.CURRENT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,expected",
    [
        (HardEligibilityState.ELIGIBLE, GovernorEligibilityClassification.ELIGIBLE),
        (HardEligibilityState.INELIGIBLE, GovernorEligibilityClassification.INELIGIBLE),
        (HardEligibilityState.UNRESOLVED, GovernorEligibilityClassification.UNRESOLVED),
    ],
)
async def test_exact_hard_eligibility_mapping(source, expected):
    projected = candidate(
        opportunity_fit_summary=replace(
            candidate().opportunity_fit_summary, hard_eligibility_state=source
        )
    )
    current = state()
    result = await StreamCandidateGovernorFactsReader(
        RepositorySpy([current, current], projected_candidate=projected)
    ).read_current_governor_facts(request())
    assert result.facts.eligibility_classification is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,expected",
    [
        (OpportunityFitState.COMPATIBLE, GovernorFitClassification.COMPATIBLE),
        (OpportunityFitState.NOT_APPLICABLE, GovernorFitClassification.NOT_APPLICABLE),
        (OpportunityFitState.INCOMPATIBLE, GovernorFitClassification.INCOMPATIBLE),
        (OpportunityFitState.UNRESOLVED, GovernorFitClassification.UNRESOLVED),
    ],
)
async def test_exact_opportunity_fit_mapping(source, expected):
    projected = candidate(
        opportunity_fit_summary=replace(
            candidate().opportunity_fit_summary, opportunity_fit_state=source
        )
    )
    current = state()
    result = await StreamCandidateGovernorFactsReader(
        RepositorySpy([current, current], projected_candidate=projected)
    ).read_current_governor_facts(request())
    assert result.facts.fit_classification is expected


@pytest.mark.asyncio
async def test_match_mapping_uses_only_presence_and_exact_score():
    current = state()
    result = await StreamCandidateGovernorFactsReader(
        RepositorySpy([current, current], projected_candidate=candidate())
    ).read_current_governor_facts(request())
    assert result.facts.match_classification is GovernorMatchClassification.PRESENT
    assert result.facts.professional_match_score == 81

    missing = await StreamCandidateGovernorFactsReader(
        RepositorySpy(
            [current, current],
            projected_candidate=candidate(professional_match_summary=None),
        )
    ).read_current_governor_facts(request())
    assert missing.facts.match_classification is GovernorMatchClassification.MISSING
    assert missing.facts.professional_match_score is None


@pytest.mark.asyncio
async def test_missing_fit_maps_to_missing_without_copying_fit_details():
    current = state()
    result = await StreamCandidateGovernorFactsReader(
        RepositorySpy(
            [current, current],
            projected_candidate=candidate(opportunity_fit_summary=None),
        )
    ).read_current_governor_facts(request())
    assert result.facts.fit_classification is GovernorFitClassification.MISSING
    assert result.facts.eligibility_classification is GovernorEligibilityClassification.UNRESOLVED


@pytest.mark.asyncio
async def test_candidate_preferences_version_is_not_an_invented_freshness_invariant():
    projected = candidate(
        opportunity_fit_summary=replace(
            candidate().opportunity_fit_summary,
            candidate_preferences_version=999,
        )
    )
    current = state()
    result = await StreamCandidateGovernorFactsReader(
        RepositorySpy([current, current], projected_candidate=projected)
    ).read_current_governor_facts(request())
    assert result.status is GovernorFactsStatus.CURRENT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate_change",
    [
        {"candidate_id": "candidate-other"},
        {"stream_id": "stream-other"},
        {"generation_id": "generation-other"},
        {"stream_version": 6},
        {"requirement_version": 4},
        {"role_dna_id": "role-other"},
        {"role_dna_version": 3},
        {"opportunity_spec_id": "opportunity-other"},
        {"opportunity_spec_version": 5},
    ],
)
async def test_candidate_scope_mismatch_is_fixed_redacted_failure(candidate_change):
    current = state()
    reader = StreamCandidateGovernorFactsReader(
        RepositorySpy(
            [current, current], projected_candidate=candidate(**candidate_change)
        )
    )
    with pytest.raises(ContactGovernorAdapterError) as exc:
        await reader.read_current_governor_facts(request())
    assert str(exc.value) == "contact governor adapter unavailable"
    assert exc.value.__cause__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("version_source", ["match", "fit"])
async def test_summary_authority_version_mismatch_is_fixed_failure(version_source):
    projected = candidate()
    if version_source == "match":
        projected = replace(
            projected,
            professional_match_summary=replace(
                projected.professional_match_summary, role_dna_version=999
            ),
        )
    else:
        projected = replace(
            projected,
            opportunity_fit_summary=replace(
                projected.opportunity_fit_summary, opportunity_spec_version=999
            ),
        )
    current = state()
    with pytest.raises(ContactGovernorAdapterError) as exc:
        await StreamCandidateGovernorFactsReader(
            RepositorySpy([current, current], projected_candidate=projected)
        ).read_current_governor_facts(request())
    assert str(exc.value) == "contact governor adapter unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_at", [1, 2, 3])
async def test_repository_failures_are_fixed_and_redacted(failure_at):
    current = state()
    reader = StreamCandidateGovernorFactsReader(
        RepositorySpy(
            [current, current],
            projected_candidate=candidate(),
            failure_at=failure_at,
        )
    )
    with pytest.raises(ContactGovernorAdapterError) as exc:
        await reader.read_current_governor_facts(request())
    assert str(exc.value) == "contact governor adapter unavailable"
    assert exc.value.__cause__ is None
    assert "repository" not in repr(exc.value)


@pytest.mark.asyncio
async def test_malformed_second_projection_state_is_fixed_and_redacted():
    reader = StreamCandidateGovernorFactsReader(
        RepositorySpy([state(), {"private": "malformed"}], projected_candidate=candidate())
    )
    with pytest.raises(ContactGovernorAdapterError) as exc:
        await reader.read_current_governor_facts(request())
    assert str(exc.value) == "contact governor adapter unavailable"
    assert exc.value.__cause__ is None
    assert "private" not in repr(exc.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "states,projected",
    [
        ([{"private": "malformed-state"}], None),
        ([state()], {"private": "malformed-candidate"}),
    ],
)
async def test_malformed_initial_state_or_candidate_is_fixed_and_redacted(
    states, projected
):
    reader = StreamCandidateGovernorFactsReader(
        RepositorySpy(states, projected_candidate=projected)
    )
    with pytest.raises(ContactGovernorAdapterError) as exc:
        await reader.read_current_governor_facts(request())
    assert str(exc.value) == "contact governor adapter unavailable"
    assert exc.value.__cause__ is None
    assert "private" not in repr(exc.value)


@pytest.mark.asyncio
async def test_derived_facts_contain_no_source_evidence_or_provenance():
    current = state()
    result = await StreamCandidateGovernorFactsReader(
        RepositorySpy([current, current], projected_candidate=candidate())
    ).read_current_governor_facts(request())
    assert result.status is GovernorFactsStatus.CURRENT
    serialized = repr(result)
    assert "private-application" not in serialized
    assert "private-intent" not in serialized
    assert "private-favorite" not in serialized
    assert "private-cycle" not in serialized
    assert "match-engine" not in serialized
    assert "fit-engine" not in serialized
    assert "evidence" not in serialized.lower()
    assert not {
        "application_evidence",
        "declared_interest_evidence",
        "shared_favorite_evidence",
        "discovery_evidence",
        "evidence_refs",
        "provenance",
    }.intersection(result.facts.__dataclass_fields__)


def test_only_talent_stream_adapter_bridges_concrete_b9_dependencies():
    backend = Path(__file__).resolve().parents[1]
    adapter_source = (
        backend / "domains" / "talent_stream" / "contact_governor_adapters.py"
    ).read_text(encoding="utf-8")
    assert "domains.trust.recruiting_service" in adapter_source
    assert "domains.permissions.service" in adapter_source
    assert "stream_candidate_repository" in adapter_source

    core_source = "\n".join(
        (backend / "domains" / "trust" / filename).read_text(encoding="utf-8")
        for filename in ("contact_governor_models.py", "contact_governor_service.py")
    )
    for forbidden in (
        "domains.matching",
        "domains.permissions",
        "stream_candidate_models",
        "stream_candidate_repository",
        "RecruitingTrustService",
        "PermissionService",
    ):
        assert forbidden not in core_source
