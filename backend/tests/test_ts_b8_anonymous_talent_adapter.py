"""TS-B8-002 tests: Anonymous Talent Adapter exact-version and HMAC card_ref."""
import pytest

from domains.privacy.anonymous_talent import (
    ANONYMOUS_TALENT_POLICY_VERSION,
    AnonymousTalentFacts,
    ExperienceBand,
    SeniorityBand,
)
from domains.matching.opportunity_fit_models import HardEligibilityState, OpportunityFitState
from domains.profiles.models import (
    CandidateProfessionalProfile,
    CandidateProfileId,
    EntityVersion,
    FactSource,
)
from domains.profiles.repository import CandidateProfileRepository
from domains.shared.ids import CandidateId, OpportunitySpecId, RoleDNAId, TalentStreamId
from domains.talent_stream.anonymous_talent_adapter import (
    AnonymousTalentAdapterError,
    AnonymousTalentFactsAdapter,
    AnonymousTalentProjectionUnavailableError,
    derive_anonymous_talent_card_ref,
)
from domains.talent_stream.stream_candidate_models import (
    StreamCandidate,
    ProfessionalMatchSummary,
    OpportunityFitSummary,
    DiscoveryEvidence,
)


class FakeCandidateProfileRepository:
    """In-memory fake for CandidateProfileRepository.get()."""

    def __init__(self, docs):
        self._docs = docs

    async def get(self, candidate_id: str):
        return self._docs.get(candidate_id)


def _make_candidate(
    *,
    candidate_id: str = "candidate-1",
    stream_id: str = "stream-1",
    generation_id: str = "generation-1",
    role_dna_version: int = 1,
    opportunity_spec_version: int = 1,
    candidate_profile_version: int = 4,
    candidate_preferences_version: int = 2,
    professional_match_score: int = 75,
    evidence_coverage: int = 60,
    hard_eligibility_state: HardEligibilityState = HardEligibilityState.ELIGIBLE,
    opportunity_fit_state: OpportunityFitState = OpportunityFitState.COMPATIBLE,
    match_engine_version: str = "match-v1",
    fit_engine_version: str = "fit-v1",
) -> StreamCandidate:
    from datetime import datetime, timezone

    def _utc(ms=0):
        return datetime(2026, 1, 1, 12, 0, 0, ms * 1000, tzinfo=timezone.utc)

    return StreamCandidate(
        stream_id=TalentStreamId(stream_id),
        stream_version=EntityVersion("1"),
        requirement_version=EntityVersion("1"),
        generation_id=generation_id,
        candidate_id=CandidateId(candidate_id),
        role_dna_id=RoleDNAId("role-dna-1"),
        role_dna_version=EntityVersion(str(role_dna_version)),
        opportunity_spec_id=OpportunitySpecId("spec-1"),
        opportunity_spec_version=EntityVersion(str(opportunity_spec_version)),
        computed_at=_utc(100),
        discovery_evidence=DiscoveryEvidence(
            candidate_preferences_version=EntityVersion(str(candidate_preferences_version)),
            updated_at=_utc(50),
        ),
        professional_match_summary=ProfessionalMatchSummary(
            candidate_profile_version=EntityVersion(str(candidate_profile_version)),
            role_dna_version=EntityVersion(str(role_dna_version)),
            match_engine_version=match_engine_version,
            professional_match_score=professional_match_score,
            evidence_coverage=evidence_coverage,
            computed_at=_utc(200),
        ),
        opportunity_fit_summary=OpportunityFitSummary(
            candidate_preferences_version=EntityVersion(str(candidate_preferences_version)),
            opportunity_spec_version=EntityVersion(str(opportunity_spec_version)),
            fit_engine_version=fit_engine_version,
            hard_eligibility_state=hard_eligibility_state,
            opportunity_fit_state=opportunity_fit_state,
            evidence_coverage=evidence_coverage,
            computed_at=_utc(300),
        ),
    )


def _make_profile_doc(
    candidate_id: str = "candidate-1",
    version: int = 4,
    experience_years: int | None = 8,
    seniority: str | None = "senior",
    **extra_fields,
) -> dict:
    doc = {
        "candidate_id": candidate_id,
        "version": version,
        "experience_years": experience_years,
        "seniority": seniority,
    }
    doc.update(extra_fields)
    return doc


class TestCardRefDeterminism:
    def test_same_inputs_same_ref(self):
        key = b"a" * 32
        ref1 = derive_anonymous_talent_card_ref(
            key=key, stream_id="s1", generation_id="g1", candidate_id="c1"
        )
        ref2 = derive_anonymous_talent_card_ref(
            key=key, stream_id="s1", generation_id="g1", candidate_id="c1"
        )
        assert ref1 == ref2

    def test_different_candidate_different_ref(self):
        key = b"a" * 32
        ref1 = derive_anonymous_talent_card_ref(
            key=key, stream_id="s1", generation_id="g1", candidate_id="c1"
        )
        ref2 = derive_anonymous_talent_card_ref(
            key=key, stream_id="s1", generation_id="g1", candidate_id="c2"
        )
        assert ref1 != ref2

    def test_different_stream_different_ref(self):
        key = b"a" * 32
        ref1 = derive_anonymous_talent_card_ref(
            key=key, stream_id="s1", generation_id="g1", candidate_id="c1"
        )
        ref2 = derive_anonymous_talent_card_ref(
            key=key, stream_id="s2", generation_id="g1", candidate_id="c1"
        )
        assert ref1 != ref2

    def test_different_generation_different_ref(self):
        key = b"a" * 32
        ref1 = derive_anonymous_talent_card_ref(
            key=key, stream_id="s1", generation_id="g1", candidate_id="c1"
        )
        ref2 = derive_anonymous_talent_card_ref(
            key=key, stream_id="s1", generation_id="g2", candidate_id="c1"
        )
        assert ref1 != ref2

    def test_different_key_different_ref(self):
        ref1 = derive_anonymous_talent_card_ref(
            key=b"a" * 32, stream_id="s1", generation_id="g1", candidate_id="c1"
        )
        ref2 = derive_anonymous_talent_card_ref(
            key=b"b" * 32, stream_id="s1", generation_id="g1", candidate_id="c1"
        )
        assert ref1 != ref2

    def test_format(self):
        key = b"a" * 32
        ref = derive_anonymous_talent_card_ref(
            key=key, stream_id="s1", generation_id="g1", candidate_id="c1"
        )
        assert ref.startswith("ts-b8-card-v1:")
        assert len(ref) == len("ts-b8-card-v1:") + 64
        assert all(c in "0123456789abcdef" for c in ref.split(":")[1])

    def test_invalid_key_rejected(self):
        invalid_keys = [
            "string-key",
            None,
            b"short",
            b"a" * 31,
        ]
        for key in invalid_keys:
            with pytest.raises(ValueError):
                derive_anonymous_talent_card_ref(
                    key=key, stream_id="s1", generation_id="g1", candidate_id="c1"
                )

    def test_32_bytes_key_accepted(self):
        ref = derive_anonymous_talent_card_ref(
            key=b"a" * 32, stream_id="s1", generation_id="g1", candidate_id="c1"
        )
        assert ref.startswith("ts-b8-card-v1:")

    def test_no_cleartext_ids_in_ref(self):
        key = b"a" * 32
        ref = derive_anonymous_talent_card_ref(
            key=key, stream_id="stream-123", generation_id="gen-456", candidate_id="cand-789"
        )
        assert "stream-123" not in ref
        assert "gen-456" not in ref
        assert "cand-789" not in ref


class TestAdapterSuccess:
    @pytest.mark.asyncio
    async def test_exact_version_success(self):
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc(version=4, experience_years=8, seniority="senior")
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        facts = await adapter.build(candidate)

        assert isinstance(facts, AnonymousTalentFacts)
        assert facts.experience_years == 8
        assert facts.seniority == "senior"
        assert facts.professional_match_score == 75
        assert facts.match_evidence_coverage == 60
        assert facts.hard_eligibility_state == HardEligibilityState.ELIGIBLE
        assert facts.opportunity_fit_state == OpportunityFitState.COMPATIBLE
        assert facts.card_ref.startswith("ts-b8-card-v1:")

    @pytest.mark.asyncio
    async def test_experience_years_none_accepted(self):
        candidate = _make_candidate(candidate_profile_version=1)
        profile_doc = _make_profile_doc(version=1, experience_years=None, seniority=None)
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        facts = await adapter.build(candidate)
        assert facts.experience_years is None
        assert facts.seniority is None


class TestAdapterExactVersionFailClosed:
    @pytest.mark.asyncio
    async def test_profile_newer_fails(self):
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc(version=5, experience_years=8, seniority="senior")
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)

    @pytest.mark.asyncio
    async def test_profile_older_fails(self):
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc(version=3, experience_years=8, seniority="senior")
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)

    @pytest.mark.asyncio
    async def test_profile_missing_fails(self):
        candidate = _make_candidate()
        repo = FakeCandidateProfileRepository({})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)

    @pytest.mark.asyncio
    async def test_candidate_id_mismatch_fails(self):
        candidate = _make_candidate(candidate_id="candidate-1")
        profile_doc = _make_profile_doc(candidate_id="candidate-2", version=4)
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)

    @pytest.mark.asyncio
    async def test_malformed_version_none_fails(self):
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc(version=None)
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)

    @pytest.mark.asyncio
    async def test_malformed_version_string_fails(self):
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc()
        profile_doc["version"] = "4"
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)

    @pytest.mark.asyncio
    async def test_malformed_version_bool_fails(self):
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc()
        profile_doc["version"] = True
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)

    @pytest.mark.asyncio
    async def test_malformed_version_zero_fails(self):
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc(version=0)
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)

    @pytest.mark.asyncio
    async def test_malformed_experience_years_bool_fails(self):
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc(version=4, experience_years=True)
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)

    @pytest.mark.asyncio
    async def test_malformed_seniority_bool_fails(self):
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc(version=4, seniority=True)
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)


class TestAdapterMissingMatchFit:
    @pytest.mark.asyncio
    async def test_missing_match_summary_fails_without_repo_call(self):
        candidate = _make_candidate()
        candidate = StreamCandidate(
            stream_id=candidate.stream_id,
            stream_version=candidate.stream_version,
            requirement_version=candidate.requirement_version,
            generation_id=candidate.generation_id,
            candidate_id=candidate.candidate_id,
            role_dna_id=candidate.role_dna_id,
            role_dna_version=candidate.role_dna_version,
            opportunity_spec_id=candidate.opportunity_spec_id,
            opportunity_spec_version=candidate.opportunity_spec_version,
            computed_at=candidate.computed_at,
            discovery_evidence=candidate.discovery_evidence,
            professional_match_summary=None,
            opportunity_fit_summary=candidate.opportunity_fit_summary,
        )
        repo_called = False

        class TrackingRepo(FakeCandidateProfileRepository):
            async def get(self, candidate_id: str):
                nonlocal repo_called
                repo_called = True
                return _make_profile_doc()

        repo = TrackingRepo({})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)
        assert not repo_called, "Repository should not be called when Match is missing"

    @pytest.mark.asyncio
    async def test_missing_fit_summary_fails_without_repo_call(self):
        candidate = _make_candidate()
        candidate = StreamCandidate(
            stream_id=candidate.stream_id,
            stream_version=candidate.stream_version,
            requirement_version=candidate.requirement_version,
            generation_id=candidate.generation_id,
            candidate_id=candidate.candidate_id,
            role_dna_id=candidate.role_dna_id,
            role_dna_version=candidate.role_dna_version,
            opportunity_spec_id=candidate.opportunity_spec_id,
            opportunity_spec_version=candidate.opportunity_spec_version,
            computed_at=candidate.computed_at,
            discovery_evidence=candidate.discovery_evidence,
            professional_match_summary=candidate.professional_match_summary,
            opportunity_fit_summary=None,
        )
        repo_called = False

        class TrackingRepo(FakeCandidateProfileRepository):
            async def get(self, candidate_id: str):
                nonlocal repo_called
                repo_called = True
                return _make_profile_doc()

        repo = TrackingRepo({})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)
        assert not repo_called, "Repository should not be called when Fit is missing"


class TestAdapterB7Coherence:
    @pytest.mark.asyncio
    async def test_role_version_mismatch_fails(self):
        candidate = _make_candidate(role_dna_version=2, candidate_profile_version=4)
        profile_doc = _make_profile_doc(version=4)
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)

    @pytest.mark.asyncio
    async def test_opportunity_version_mismatch_fails(self):
        candidate = _make_candidate(opportunity_spec_version=2, candidate_profile_version=4)
        profile_doc = _make_profile_doc(version=4)
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentProjectionUnavailableError):
            await adapter.build(candidate)


class TestAdapterInputValidation:
    @pytest.mark.asyncio
    async def test_invalid_candidate_type_rejected(self):
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=FakeCandidateProfileRepository({}),
            card_ref_key=b"a" * 32,
        )
        with pytest.raises(AnonymousTalentAdapterError):
            await adapter.build("not a candidate")

    @pytest.mark.asyncio
    async def test_invalid_key_rejected_at_construction(self):
        with pytest.raises(ValueError):
            AnonymousTalentFactsAdapter(
                profile_repository=FakeCandidateProfileRepository({}),
                card_ref_key="not bytes",
            )

    @pytest.mark.asyncio
    async def test_short_key_rejected_at_construction(self):
        with pytest.raises(ValueError):
            AnonymousTalentFactsAdapter(
                profile_repository=FakeCandidateProfileRepository({}),
                card_ref_key=b"short",
            )


class TestDataMinimization:
    @pytest.mark.asyncio
    async def test_no_pii_free_text_transferred(self):
        sentinel = "SENTINEL_SHOULD_NOT_APPEAR"
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc(
            version=4,
            experience_years=8,
            seniority="senior",
            headline=sentinel,
            summary=sentinel,
            current_location=sentinel,
            employer=sentinel,
            experiences=[{"title": sentinel}],
            skills=[{"name": sentinel}],
            portfolio=[{"url": sentinel}],
        )
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        facts = await adapter.build(candidate)

        repr_str = repr(facts)
        assert sentinel not in repr_str
        assert facts.experience_years == 8
        assert facts.seniority == "senior"
        assert sentinel not in facts.card_ref


class TestAdapterErrorMessagesGeneric:
    @pytest.mark.asyncio
    async def test_error_messages_generic(self):
        candidate = _make_candidate(candidate_profile_version=4)
        profile_doc = _make_profile_doc(version=5)
        repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
        adapter = AnonymousTalentFactsAdapter(
            profile_repository=repo,
            card_ref_key=b"a" * 32,
        )
        try:
            await adapter.build(candidate)
        except AnonymousTalentProjectionUnavailableError as e:
            msg = str(e)
            assert "candidate" not in msg.lower()
            assert "stream" not in msg.lower()
            assert "version" not in msg.lower()
            assert "experience" not in msg.lower()
            assert "seniority" not in msg.lower()
            assert "email" not in msg.lower()
            assert "name" not in msg.lower()
            assert "profile" not in msg.lower()
            assert "employer" not in msg.lower()
            assert msg == "anonymous talent facts unavailable"


class TestFitStatesPreserved:
    @pytest.mark.asyncio
    async def test_hard_eligibility_states_preserved(self):
        for state in [HardEligibilityState.ELIGIBLE, HardEligibilityState.INELIGIBLE, HardEligibilityState.UNRESOLVED]:
            candidate = _make_candidate(hard_eligibility_state=state, candidate_profile_version=4)
            profile_doc = _make_profile_doc(version=4)
            repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
            adapter = AnonymousTalentFactsAdapter(
                profile_repository=repo,
                card_ref_key=b"a" * 32,
            )
            facts = await adapter.build(candidate)
            assert facts.hard_eligibility_state == state

    @pytest.mark.asyncio
    async def test_opportunity_fit_states_preserved(self):
        for state in [
            OpportunityFitState.COMPATIBLE,
            OpportunityFitState.INCOMPATIBLE,
            OpportunityFitState.UNRESOLVED,
            OpportunityFitState.NOT_APPLICABLE,
        ]:
            candidate = _make_candidate(opportunity_fit_state=state, candidate_profile_version=4)
            profile_doc = _make_profile_doc(version=4)
            repo = FakeCandidateProfileRepository({"candidate-1": profile_doc})
            adapter = AnonymousTalentFactsAdapter(
                profile_repository=repo,
                card_ref_key=b"a" * 32,
            )
            facts = await adapter.build(candidate)
            assert facts.opportunity_fit_state == state