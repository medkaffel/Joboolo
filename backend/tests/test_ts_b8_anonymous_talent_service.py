"""TS-B8-003 G0: active-generation Anonymous Talent page service."""
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256

import pytest

from domains.matching.opportunity_fit_models import (
    HardEligibilityState,
    OpportunityFitState,
)
from domains.privacy.anonymous_talent import (
    ANONYMOUS_TALENT_POLICY_VERSION,
    AnonymousTalentCard,
    AnonymousTalentFacts,
)
from domains.shared.ids import CandidateId, OpportunitySpecId, RoleDNAId, TalentStreamId
from domains.shared.versioning import EngineVersion, EntityVersion
from domains.talent_stream.anonymous_talent_adapter import (
    AnonymousTalentProjectionUnavailableError,
)
from domains.talent_stream.anonymous_talent_service import (
    CURSOR_VERSION,
    AnonymousTalentCursorError,
    AnonymousTalentPage,
    AnonymousTalentPageService,
    AnonymousTalentPageUnavailableError,
)
from domains.talent_stream.stream_candidate_models import (
    DiscoveryEvidence,
    OpportunityFitSummary,
    ProfessionalMatchSummary,
    StreamCandidate,
)
from domains.talent_stream.stream_candidate_persistence import ProjectionState


NOW = datetime(2026, 9, 21, 10, 0, tzinfo=timezone.utc)
CURSOR_KEY = b"cursor-key-for-b8-g0-tests-00000"


def candidate(candidate_id="candidate-1", **changes):
    values = {
        "stream_id": TalentStreamId("stream-1"),
        "stream_version": EntityVersion(2),
        "requirement_version": EntityVersion(3),
        "generation_id": "generation-1",
        "candidate_id": CandidateId(candidate_id),
        "role_dna_id": RoleDNAId("role-1"),
        "role_dna_version": EntityVersion(4),
        "opportunity_spec_id": OpportunitySpecId("spec-1"),
        "opportunity_spec_version": EntityVersion(5),
        "computed_at": NOW,
        "discovery_evidence": DiscoveryEvidence(EntityVersion(6), NOW),
        "professional_match_summary": ProfessionalMatchSummary(
            candidate_profile_version=EntityVersion(7),
            role_dna_version=EntityVersion(4),
            match_engine_version=EngineVersion("match-v1"),
            professional_match_score=84,
            evidence_coverage=76,
            computed_at=NOW,
        ),
        "opportunity_fit_summary": OpportunityFitSummary(
            candidate_preferences_version=EntityVersion(6),
            opportunity_spec_version=EntityVersion(5),
            fit_engine_version=EngineVersion("fit-v1"),
            hard_eligibility_state=HardEligibilityState.ELIGIBLE,
            opportunity_fit_state=OpportunityFitState.COMPATIBLE,
            evidence_coverage=68,
            computed_at=NOW,
        ),
    }
    values.update(changes)
    return StreamCandidate(**values)


def projection_state(**changes):
    values = {
        "stream_id": TalentStreamId("stream-1"),
        "state_version": 8,
        "active_generation_id": "generation-1",
        "stream_version": 2,
        "requirement_version": 3,
        "role_dna_id": RoleDNAId("role-1"),
        "role_dna_version": 4,
        "opportunity_spec_id": OpportunitySpecId("spec-1"),
        "opportunity_spec_version": 5,
        "candidate_count": 2,
        "published_at": NOW,
    }
    values.update(changes)
    return ProjectionState(**values)


class FakeRepository:
    def __init__(self, *, state=None, pages=None, state_reads=None, error=None):
        self.state = state
        self.pages = pages or {}
        self.state_reads = list(state_reads) if state_reads is not None else None
        self.error = error
        self.state_calls = []
        self.page_calls = []

    async def get_projection_state(self, stream_id):
        self.state_calls.append(stream_id)
        if self.error == "state":
            raise RuntimeError("repository detail must not escape")
        if self.state_reads is not None:
            return self.state_reads.pop(0)
        return self.state

    async def find_generation(
        self, stream_id, generation_id, *, after_candidate_id, limit
    ):
        self.page_calls.append(
            (stream_id, generation_id, after_candidate_id, limit)
        )
        if self.error == "page":
            raise RuntimeError("repository detail must not escape")
        return list(self.pages.get(after_candidate_id, ()))


class FakeFactsBuilder:
    def __init__(self, *, error=None):
        self.error = error
        self.calls = []

    async def build(self, item):
        self.calls.append(item)
        if self.error is not None:
            raise self.error
        digest = sha256(str(item.candidate_id).encode("utf-8")).hexdigest()
        return AnonymousTalentFacts(
            card_ref=f"ts-b8-card-v1:{digest}",
            experience_years=8,
            seniority="senior",
            professional_match_score=item.professional_match_summary.professional_match_score,
            match_evidence_coverage=item.professional_match_summary.evidence_coverage,
            hard_eligibility_state=item.opportunity_fit_summary.hard_eligibility_state,
            opportunity_fit_state=item.opportunity_fit_summary.opportunity_fit_state,
        )


def service(repository, builder=None):
    return AnonymousTalentPageService(
        repository=repository,
        facts_builder=builder or FakeFactsBuilder(),
        cursor_key=CURSOR_KEY,
    )


def test_service_dependencies_and_cursor_key_are_validated_at_boundary():
    with pytest.raises(ValueError, match="get_projection_state"):
        AnonymousTalentPageService(object(), FakeFactsBuilder(), CURSOR_KEY)
    with pytest.raises(ValueError, match="provide build"):
        AnonymousTalentPageService(FakeRepository(), object(), CURSOR_KEY)
    with pytest.raises(ValueError, match="32 bytes"):
        AnonymousTalentPageService(FakeRepository(), FakeFactsBuilder(), b"short")


@pytest.mark.asyncio
async def test_nominal_page_reads_active_generation_and_returns_only_cards():
    first, second = candidate("candidate-1"), candidate("candidate-2")
    repository = FakeRepository(
        state=projection_state(), pages={None: [first, second]}
    )
    builder = FakeFactsBuilder()

    page = await service(repository, builder).get_page("stream-1", page_size=10)

    assert type(page) is AnonymousTalentPage
    assert len(page.cards) == 2
    assert all(type(card) is AnonymousTalentCard for card in page.cards)
    assert all(card.policy_version == ANONYMOUS_TALENT_POLICY_VERSION for card in page.cards)
    assert page.next_cursor is None
    assert repository.page_calls == [("stream-1", "generation-1", None, 11)]
    assert repository.state_calls == ["stream-1", "stream-1"]
    assert builder.calls == [first, second]
    assert all(not hasattr(card, "candidate_id") for card in page.cards)


@pytest.mark.asyncio
async def test_page_size_plus_one_yields_opaque_cursor_and_exact_next_page():
    first, second = candidate("candidate-1"), candidate("candidate-2")
    repository = FakeRepository(
        state=projection_state(),
        pages={None: [first, second], "candidate-1": [second]},
    )
    subject = service(repository)

    page_one = await subject.get_page("stream-1", page_size=1)
    assert len(page_one.cards) == 1
    assert page_one.next_cursor.startswith(f"{CURSOR_VERSION}:")
    assert "stream-1" not in page_one.next_cursor
    assert "candidate-1" not in page_one.next_cursor

    page_two = await subject.get_page(
        "stream-1", page_size=1, cursor=page_one.next_cursor
    )
    assert len(page_two.cards) == 1 and page_two.next_cursor is None
    assert repository.page_calls == [
        ("stream-1", "generation-1", None, 2),
        ("stream-1", "generation-1", "candidate-1", 2),
    ]


@pytest.mark.asyncio
async def test_empty_active_generation_returns_an_empty_page():
    repository = FakeRepository(
        state=projection_state(candidate_count=0), pages={None: []}
    )
    assert await service(repository).get_page("stream-1", 20) == AnonymousTalentPage(
        cards=(), next_cursor=None
    )


@pytest.mark.asyncio
async def test_missing_projection_state_fails_closed_without_generation_read():
    repository = FakeRepository(state=None)
    with pytest.raises(
        AnonymousTalentPageUnavailableError,
        match="^anonymous talent page unavailable$",
    ):
        await service(repository).get_page("stream-1", 20)
    assert repository.page_calls == []


@pytest.mark.asyncio
async def test_nonempty_state_with_no_candidates_fails_closed():
    repository = FakeRepository(
        state=projection_state(candidate_count=2), pages={None: []}
    )
    with pytest.raises(AnonymousTalentPageUnavailableError):
        await service(repository).get_page("stream-1", 20)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("stream_id", TalentStreamId("stream-other")),
        ("generation_id", "generation-other"),
        ("stream_version", EntityVersion(9)),
        ("requirement_version", EntityVersion(9)),
        ("role_dna_id", RoleDNAId("role-other")),
        ("role_dna_version", EntityVersion(9)),
        ("opportunity_spec_id", OpportunitySpecId("spec-other")),
        ("opportunity_spec_version", EntityVersion(9)),
    ],
)
async def test_every_candidate_scope_dimension_must_match_active_state(field_name, value):
    out_of_scope = replace(candidate(), **{field_name: value})
    repository = FakeRepository(
        state=projection_state(candidate_count=1), pages={None: [out_of_scope]}
    )
    with pytest.raises(
        AnonymousTalentPageUnavailableError,
        match="^anonymous talent page unavailable$",
    ):
        await service(repository).get_page("stream-1", 20)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "final_state",
    [
        projection_state(state_version=9),
        projection_state(active_generation_id="generation-2", state_version=9),
        None,
    ],
)
async def test_generation_change_during_render_fails_closed(final_state):
    initial = projection_state(candidate_count=1)
    repository = FakeRepository(
        state_reads=[initial, final_state], pages={None: [candidate()]}
    )
    with pytest.raises(
        AnonymousTalentPageUnavailableError,
        match="^anonymous talent page unavailable$",
    ):
        await service(repository).get_page("stream-1", 20)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["state", "page"])
async def test_repository_failures_are_redacted(failure):
    repository = FakeRepository(
        state=projection_state(candidate_count=1),
        pages={None: [candidate()]},
        error=failure,
    )
    with pytest.raises(
        AnonymousTalentPageUnavailableError,
        match="^anonymous talent page unavailable$",
    ):
        await service(repository).get_page("stream-1", 20)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_error",
    [
        AnonymousTalentProjectionUnavailableError("private adapter detail"),
        RuntimeError("unexpected private detail"),
    ],
)
async def test_facts_builder_failures_are_redacted(adapter_error):
    repository = FakeRepository(
        state=projection_state(candidate_count=1), pages={None: [candidate()]}
    )
    builder = FakeFactsBuilder(error=adapter_error)
    with pytest.raises(
        AnonymousTalentPageUnavailableError,
        match="^anonymous talent page unavailable$",
    ):
        await service(repository, builder).get_page("stream-1", 20)


@pytest.mark.asyncio
@pytest.mark.parametrize("page_size", [True, 0, -1, 101, 1.0, "20"])
async def test_page_size_is_a_strict_integer_in_one_to_one_hundred(page_size):
    repository = FakeRepository(state=projection_state())
    with pytest.raises(AnonymousTalentPageUnavailableError):
        await service(repository).get_page("stream-1", page_size)
    assert repository.state_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_id", [None, "", 1])
async def test_invalid_stream_id_is_rejected_before_repository_read(stream_id):
    repository = FakeRepository(state=projection_state())
    with pytest.raises(AnonymousTalentPageUnavailableError):
        await service(repository).get_page(stream_id, 20)
    assert repository.state_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor", ["", 1, b"token", "wrong-version:abc"])
async def test_invalid_or_tampered_cursor_fails_closed(cursor):
    repository = FakeRepository(state=projection_state())
    with pytest.raises(AnonymousTalentCursorError, match="^anonymous talent cursor invalid$"):
        await service(repository).get_page("stream-1", 20, cursor=cursor)
    assert repository.page_calls == []


@pytest.mark.asyncio
async def test_tampered_encrypted_cursor_is_rejected():
    first, second = candidate("candidate-1"), candidate("candidate-2")
    repository = FakeRepository(
        state=projection_state(), pages={None: [first, second]}
    )
    page = await service(repository).get_page("stream-1", 1)
    replacement = "A" if page.next_cursor[-1] != "A" else "B"
    tampered = page.next_cursor[:-1] + replacement

    with pytest.raises(AnonymousTalentCursorError):
        await service(repository).get_page("stream-1", 1, cursor=tampered)


@pytest.mark.asyncio
async def test_cursor_is_bound_to_stream_generation_and_state_version():
    first, second = candidate("candidate-1"), candidate("candidate-2")
    repository = FakeRepository(
        state=projection_state(), pages={None: [first, second]}
    )
    cursor = (await service(repository).get_page("stream-1", 1)).next_cursor

    for changed_state, requested_stream in (
        (projection_state(stream_id="stream-2"), "stream-2"),
        (projection_state(active_generation_id="generation-2", state_version=9), "stream-1"),
        (projection_state(state_version=9), "stream-1"),
    ):
        changed_repository = FakeRepository(state=changed_state)
        with pytest.raises(AnonymousTalentCursorError):
            await service(changed_repository).get_page(
                requested_stream, 1, cursor=cursor
            )
        assert changed_repository.page_calls == []


@pytest.mark.asyncio
async def test_lookahead_candidate_is_not_rendered_on_current_page():
    first, lookahead = candidate("candidate-1"), candidate("candidate-2")
    repository = FakeRepository(
        state=projection_state(), pages={None: [first, lookahead]}
    )
    builder = FakeFactsBuilder()
    page = await service(repository, builder).get_page("stream-1", 1)
    assert len(page.cards) == 1 and page.next_cursor is not None
    assert builder.calls == [first]
