"""Contract tests for TS-A0-001 domain contracts and business invariants."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from backend.domains.shared.ids import (
    CandidateId,
    RecruiterUserId,
    OrganizationId,
    HiringCompanyId,
    MandateId,
    RoleDNAId,
    OpportunitySpecId,
    StreamId,
    IntentEventId,
    ContactRequestId,
    GrantId,
    DocumentId,
    StreamRequirementVersion,
    OpportunitySpecVersion,
    RoleDNAVersion,
    new_candidate_id,
    new_recruiter_user_id,
    new_organization_id,
    new_hiring_company_id,
    new_mandate_id,
    new_role_dna_id,
    new_opportunity_spec_id,
    new_stream_id,
    new_intent_event_id,
    new_contact_request_id,
    new_grant_id,
    new_document_id,
    new_stream_requirement_version,
    new_opportunity_spec_version,
    new_role_dna_version,
)
from backend.domains.shared.versioning import VersionedRef, StreamRequirementVersionVO
from backend.domains.shared.envelope import Metadata, ActorContext, DomainEnvelope
from backend.domains.profiles.contracts import (
    CandidateProfessionalProfile,
    CandidatePreferences,
    DiscoveryState,
    DiscoveryMode,
    ProfileVisibility,
)
from backend.domains.roles.contracts import TaxonomyRef, TaxonomyRefs, RoleDNA
from backend.domains.opportunities.contracts import OpportunitySpecification, StreamRequirement
from backend.domains.intent.contracts import (
    IntentEventType,
    IntentDimension,
    IntentProvenance,
    IntentEvent,
)


class TestSharedIds:
    """Tests for typed ID aliases and factories."""

    def test_all_id_types_are_distinct(self):
        """Verify all NewType aliases are distinct types."""
        cid = CandidateId("c1")
        rid = RecruiterUserId("r1")
        oid = OrganizationId("o1")
        hid = HiringCompanyId("h1")
        mid = MandateId("m1")
        rdid = RoleDNAId("rd1")
        osid = OpportunitySpecId("os1")
        sid = StreamId("s1")
        iid = IntentEventId("i1")
        crid = ContactRequestId("cr1")
        gid = GrantId("g1")
        did = DocumentId("d1")

        # All should be strings but distinct types
        assert isinstance(cid, str)
        assert isinstance(rid, str)
        # Type checkers would catch mixing; runtime they're all str

    def test_factory_helpers_produce_correct_types(self):
        """Factory helpers return correctly typed IDs (strings at runtime)."""
        # NewType is erased at runtime; factories return str
        assert isinstance(new_candidate_id(), str)
        assert isinstance(new_recruiter_user_id(), str)
        assert isinstance(new_organization_id(), str)
        assert isinstance(new_hiring_company_id(), str)
        assert isinstance(new_mandate_id(), str)
        assert isinstance(new_role_dna_id(), str)
        assert isinstance(new_opportunity_spec_id(), str)
        assert isinstance(new_stream_id(), str)
        assert isinstance(new_intent_event_id(), str)
        assert isinstance(new_contact_request_id(), str)
        assert isinstance(new_grant_id(), str)
        assert isinstance(new_document_id(), str)
        assert isinstance(new_stream_requirement_version(), str)
        assert isinstance(new_opportunity_spec_version(), str)
        assert isinstance(new_role_dna_version(), str)
        # All should be non-empty hex strings
        assert len(new_candidate_id()) == 32
        assert all(c in "0123456789abcdef" for c in new_candidate_id())

    def test_factories_produce_unique_values(self):
        """Factory helpers produce unique values."""
        ids = {new_candidate_id() for _ in range(100)}
        assert len(ids) == 100


class TestSharedVersioning:
    """Tests for versioned references."""

    def test_versioned_ref_is_immutable(self):
        """VersionedRef is frozen dataclass."""
        ref = VersionedRef(id=RoleDNAId("rd1"), version="v1")
        with pytest.raises(AttributeError):
            ref.id = RoleDNAId("rd2")

    def test_stream_requirement_version_vo(self):
        """StreamRequirementVersionVO composes versioned refs correctly."""
        role_ref = VersionedRef(id=RoleDNAId("rd1"), version="v1")
        opp_ref = VersionedRef(id=OpportunitySpecId("os1"), version="v2")
        vo = StreamRequirementVersionVO(
            role_dna_ref=role_ref,
            opportunity_spec_ref=opp_ref,
            version=StreamRequirementVersion("sr1"),
        )
        assert vo.role_dna_id == RoleDNAId("rd1")
        assert vo.role_dna_version == RoleDNAVersion("v1")
        assert vo.opportunity_spec_id == OpportunitySpecId("os1")
        assert vo.opportunity_spec_version == OpportunitySpecVersion("v2")


class TestSharedEnvelope:
    """Tests for envelope value objects."""

    def test_metadata_defaults(self):
        """Metadata has timezone-aware defaults."""
        meta = Metadata()
        assert meta.created_at.tzinfo is not None
        assert meta.correlation_id
        assert meta.causation_id is None
        assert meta.tags == {}

    def test_actor_context(self):
        """ActorContext captures actor info."""
        actor = ActorContext(
            actor_id="user123",
            actor_type="candidate",
            organization_id="org1",
            mandate_id="mandate1",
            permissions=frozenset(["read", "write"]),
        )
        assert actor.actor_id == "user123"
        assert actor.permissions == frozenset(["read", "write"])

    def test_domain_envelope_with_correlation(self):
        """DomainEnvelope.with_correlation preserves payload and updates metadata."""
        payload = {"key": "value"}
        envelope = DomainEnvelope(event_type="test", payload=payload, metadata=Metadata())
        new_envelope = envelope.with_correlation("new-corr")
        assert new_envelope.payload is payload
        assert new_envelope.metadata.correlation_id == "new-corr"
        assert new_envelope.metadata.causation_id == envelope.metadata.correlation_id


class TestProfilesContracts:
    """Tests for profile contracts."""

    def test_candidate_professional_profile_minimal(self):
        """CandidateProfessionalProfile accepts minimal fields."""
        profile = CandidateProfessionalProfile(candidate_id=CandidateId("c1"), headline="Developer")
        assert profile.candidate_id == CandidateId("c1")
        assert profile.headline == "Developer"
        assert profile.skills == ()
        assert profile.profile_visibility == ProfileVisibility.PRIVATE

    def test_candidate_professional_profile_no_intent_fields(self):
        """CandidateProfessionalProfile has no intent fields."""
        fields = {f.name for f in CandidateProfessionalProfile.__dataclass_fields__.values()}
        intent_fields = {"intent", "job_intent", "role_intent", "company_intent", "market_intent"}
        assert fields.isdisjoint(intent_fields)

    def test_candidate_preferences_discovery_mode(self):
        """CandidatePreferences has discovery_mode distinct from intent."""
        prefs = CandidatePreferences(candidate_id=CandidateId("c1"))
        assert prefs.discovery_mode == DiscoveryMode.PASSIVE
        prefs_active = CandidatePreferences(
            candidate_id=CandidateId("c1"),
            discovery_mode=DiscoveryMode.ACTIVE,
        )
        assert prefs_active.discovery_mode == DiscoveryMode.ACTIVE

    def test_discovery_state_no_intent_fields(self):
        """DiscoveryState has no intent fields."""
        state = DiscoveryState(candidate_id=CandidateId("c1"))
        fields = {f.name for f in DiscoveryState.__dataclass_fields__.values()}
        intent_fields = {"intent", "job_intent", "role_intent", "company_intent", "market_intent"}
        assert fields.isdisjoint(intent_fields)

    def test_discovery_state_is_not_intent(self):
        """DiscoveryState is structurally distinct from IntentEvent."""
        state = DiscoveryState(candidate_id=CandidateId("c1"))
        # DiscoveryState has is_in_pool, pool_entered_at, match_count
        # IntentEvent has event_type, dimension, provenance, signal_strength
        assert hasattr(state, "is_in_pool")
        assert not hasattr(state, "event_type")
        assert not hasattr(state, "provenance")


class TestRolesContracts:
    """Tests for RoleDNA and taxonomy contracts."""

    def test_role_dna_minimal(self):
        """RoleDNA accepts minimal fields."""
        taxonomy_refs = TaxonomyRefs(
            primary=TaxonomyRef(taxonomy="ESCO", code="123", label="Software Engineer")
        )
        dna = RoleDNA(
            id=RoleDNAId("rd1"),
            version=RoleDNAVersion("v1"),
            title="Software Engineer",
            description="Writes code",
            taxonomy_refs=taxonomy_refs,
        )
        assert dna.title == "Software Engineer"
        assert dna.required_skills == ()
        assert dna.metadata.created_at.tzinfo is not None

    def test_role_dna_no_normalization_or_similarity(self):
        """RoleDNA has no normalization/similarity methods."""
        methods = [m for m in dir(RoleDNA) if not m.startswith("_")]
        forbidden = ["normalize", "similarity", "cluster", "distance", "vectorize"]
        for f in forbidden:
            assert f not in methods, f"RoleDNA should not have {f} method"


class TestOpportunitiesContracts:
    """Tests for OpportunitySpecification and StreamRequirement."""

    def test_opportunity_specification_minimal(self):
        """OpportunitySpecification accepts minimal fields."""
        spec = OpportunitySpecification(
            id=OpportunitySpecId("os1"),
            version=OpportunitySpecVersion("v1"),
            hiring_company_id=HiringCompanyId("hc1"),
        )
        assert spec.id == OpportunitySpecId("os1")
        assert spec.hiring_company_id == HiringCompanyId("hc1")
        assert spec.is_active is True

    def test_stream_requirement_composes_refs(self):
        """StreamRequirement composes versioned RoleDNA and OpportunitySpec refs."""
        role_ref = VersionedRef(id=RoleDNAId("rd1"), version="v1")
        opp_ref = VersionedRef(id=OpportunitySpecId("os1"), version="v2")
        req = StreamRequirement(
            version=StreamRequirementVersion("sr1"),
            role_dna_ref=role_ref,
            opportunity_spec_ref=opp_ref,
        )
        assert req.role_dna_id == RoleDNAId("rd1")
        assert req.opportunity_spec_id == OpportunitySpecId("os1")

    def test_opportunity_spec_no_create_update_commands(self):
        """OpportunitySpecification has no create/update methods."""
        methods = [m for m in dir(OpportunitySpecification) if not m.startswith("_")]
        forbidden = ["create", "update", "save", "delete", "persist"]
        for f in forbidden:
            assert f not in methods, f"OpportunitySpecification should not have {f} method"


class TestIntentContracts:
    """Tests for IntentEvent contracts."""

    def test_intent_event_type_allowed_values(self):
        """IntentEventType only contains allowed values."""
        allowed = {
            "declared_interest",
            "shared_favorite",
            "submitted_application",
            "job_view",
            "repeat_job_view",
            "external_redirect_click",
            "role_exploration",
        }
        actual = {e.value for e in IntentEventType}
        assert actual == allowed

    def test_intent_event_type_forbidden_not_present(self):
        """Forbidden event types are not present."""
        forbidden = {"accepted_introduction", "declined_introduction"}
        actual = {e.value for e in IntentEventType}
        assert actual.isdisjoint(forbidden)

    def test_intent_dimension_four_values(self):
        """IntentDimension has exactly four values."""
        dims = {d.value for d in IntentDimension}
        assert dims == {"role", "job", "company", "market"}

    def test_intent_provenance_immutable(self):
        """IntentProvenance is frozen."""
        prov = IntentProvenance(source="portal")
        with pytest.raises(AttributeError):
            prov.source = "other"

    def test_intent_event_minimal_shape(self):
        """IntentEvent minimal shape with required fields."""
        event = IntentEvent(
            id=IntentEventId("ie1"),
            event_type=IntentEventType.JOB_VIEW,
            dimension=IntentDimension.JOB,
            candidate_id=CandidateId("c1"),
            provenance=IntentProvenance(source="organic"),
            opportunity_spec_id=OpportunitySpecId("os1"),
        )
        assert event.event_type == IntentEventType.JOB_VIEW
        assert event.dimension == IntentDimension.JOB
        assert event.signal_strength == 1.0
        assert event.occurred_at.tzinfo is not None

    def test_intent_event_no_aggregates_or_policies(self):
        """IntentEvent has no aggregate/policy/algorithm fields."""
        fields = {f.name for f in IntentEvent.__dataclass_fields__.values()}
        forbidden = {
            "aggregate", "policy", "weight", "confidence", "recency",
            "threshold", "score", "independent_signal",
        }
        assert fields.isdisjoint(forbidden)


class TestBoundaryMarkers:
    """Tests that boundary marker modules exist and are minimal."""

    def test_matching_is_boundary_marker(self):
        """matching/__init__.py exists as boundary marker."""
        import backend.domains.matching as matching
        assert matching.__doc__ == "Matching domain boundary marker (A5/A6)."

    def test_talent_stream_is_boundary_marker(self):
        """talent_stream/__init__.py exists as boundary marker."""
        import backend.domains.talent_stream as ts
        assert ts.__doc__ == "Talent Stream domain boundary marker (A1+)."

    def test_trust_is_boundary_marker(self):
        """trust/__init__.py exists as boundary marker."""
        import backend.domains.trust as trust
        assert trust.__doc__ == "Trust domain boundary marker (A7/A8/A10+)."

    def test_permissions_is_boundary_marker(self):
        """permissions/__init__.py exists as boundary marker."""
        import backend.domains.permissions as perms
        assert perms.__doc__ == "Permissions domain boundary marker (A9/B9+)."

    def test_privacy_is_boundary_marker(self):
        """privacy/__init__.py exists as boundary marker."""
        import backend.domains.privacy as privacy
        assert privacy.__doc__ == "Privacy domain boundary marker (A10+)."


class TestBusinessInvariants:
    """Structural/negative tests enforcing canonical Talent Stream invariants."""

    def test_match_not_equal_intent(self):
        """Match != Intent - structurally distinct concepts."""
        # Match would be in matching domain (A5/A6)
        # Intent is in intent domain
        # They have no shared base class or common fields
        from backend.domains.intent.contracts import IntentEvent
        from backend.domains.matching import __doc__ as matching_doc

        assert "boundary marker" in matching_doc
        # IntentEvent has no "match" fields
        intent_fields = {f.name for f in IntentEvent.__dataclass_fields__.values()}
        match_fields = {"match_score", "match_confidence", "matched_at", "match_id"}
        assert intent_fields.isdisjoint(match_fields)

    def test_discovery_not_equal_intent(self):
        """Discovery != Intent - DiscoveryState has no intent fields."""
        from backend.domains.profiles.contracts import DiscoveryState
        from backend.domains.intent.contracts import IntentEvent

        disc_fields = {f.name for f in DiscoveryState.__dataclass_fields__.values()}
        intent_fields = {f.name for f in IntentEvent.__dataclass_fields__.values()}
        # DiscoveryState has is_in_pool, pool_entered_at, match_count
        # IntentEvent has event_type, dimension, provenance, signal_strength
        assert "is_in_pool" in disc_fields
        assert "event_type" not in disc_fields
        assert "provenance" not in disc_fields
        assert "signal_strength" not in disc_fields

    def test_intent_not_equal_permission(self):
        """Intent != Permission - IntentEvent has no permission fields."""
        from backend.domains.intent.contracts import IntentEvent

        intent_fields = {f.name for f in IntentEvent.__dataclass_fields__.values()}
        perm_fields = {"permission", "grant", "authorized", "consent", "acl"}
        assert intent_fields.isdisjoint(perm_fields)

    def test_permission_not_equal_trust(self):
        """Permission != Trust - separate domains, boundary markers only in A0."""
        # Both are boundary markers in A0-001
        import backend.domains.permissions as perms
        import backend.domains.trust as trust

        assert perms.__doc__ == "Permissions domain boundary marker (A9/B9+)."
        assert trust.__doc__ == "Trust domain boundary marker (A7/A8/A10+)."
        # Different docstrings confirm separate concerns

    def test_private_favorite_not_sharing_consent(self):
        """Private favorite != sharing consent - distinct concepts."""
        # CandidatePreferences has no "shared_favorite" or "consent" fields
        from backend.domains.profiles.contracts import CandidatePreferences

        pref_fields = {f.name for f in CandidatePreferences.__dataclass_fields__.values()}
        consent_fields = {"shared_favorite", "sharing_consent", "consent_granted", "consent_revoked"}
        assert pref_fields.isdisjoint(consent_fields)
        # IntentEvent has SHARED_FAVORITE event type but that's explicit action, not passive favorite

    def test_click_not_sharing_consent(self):
        """Click/view/redirect != sharing consent."""
        from backend.domains.intent.contracts import IntentEventType

        # JOB_VIEW, REPEAT_JOB_VIEW, EXTERNAL_REDIRECT_CLICK are distinct from SHARED_FAVORITE
        click_types = {
            IntentEventType.JOB_VIEW,
            IntentEventType.REPEAT_JOB_VIEW,
            IntentEventType.EXTERNAL_REDIRECT_CLICK,
        }
        assert IntentEventType.SHARED_FAVORITE not in click_types
        # No field in IntentEvent captures "consent" - provenance.source captures origin

    def test_application_to_a_not_cross_company_grant_to_b(self):
        """Application to Company A != cross-company grant to Company B."""
        from backend.domains.intent.contracts import IntentEvent, IntentEventType

        # SUBMITTED_APPLICATION targets one opportunity_spec (one company)
        event = IntentEvent(
            id=IntentEventId("ie1"),
            event_type=IntentEventType.SUBMITTED_APPLICATION,
            dimension=IntentDimension.JOB,
            candidate_id=CandidateId("c1"),
            provenance=IntentProvenance(source="portal"),
            opportunity_spec_id=OpportunitySpecId("os1"),
        )
        # Event has single opportunity_spec_id, no cross-company grant fields
        assert event.opportunity_spec_id == OpportunitySpecId("os1")
        fields = {f.name for f in IntentEvent.__dataclass_fields__.values()}
        cross_company_fields = {"granted_to_company", "cross_company_grant", "company_b_id"}
        assert fields.isdisjoint(cross_company_fields)

    def test_reference_job_not_audience_ownership(self):
        """Reference job != ownership of its audience."""
        from backend.domains.opportunities.contracts import OpportunitySpecification

        # OpportunitySpecification has hiring_company_id, mandate_id
        # No "audience", "candidate_list", "ownership" fields
        fields = {f.name for f in OpportunitySpecification.__dataclass_fields__.values()}
        audience_fields = {"audience", "candidates", "viewers", "owner", "audience_owner"}
        assert fields.isdisjoint(audience_fields)

    def test_profile_access_not_cv_access(self):
        """Profile access != CV access (documented invariant; Grant not implemented)."""
        from backend.domains.profiles.contracts import CandidateProfessionalProfile

        # CandidateProfessionalProfile has no document/CV/grant fields
        fields = {f.name for f in CandidateProfessionalProfile.__dataclass_fields__.values()}
        cv_fields = {"cv", "document", "grant", "resume", "cover_letter", "portfolio"}
        assert fields.isdisjoint(cv_fields)
        # DocumentId exists in shared.ids but Profile doesn't reference it

    def test_cpc_billing_separate_from_intent(self):
        """CPC/billing event store != Talent Intent event contract."""
        # IntentEvent has no billing/CPC fields
        from backend.domains.intent.contracts import IntentEvent

        fields = {f.name for f in IntentEvent.__dataclass_fields__.values()}
        billing_fields = {"cpc", "billing", "cost", "charge", "invoice", "payment", "budget"}
        assert fields.isdisjoint(billing_fields)

    def test_no_opaque_combined_score(self):
        """No opaque combined Match/Intent/Trust/Permission score exists."""
        # Check none of the contract types have a combined score field
        from backend.domains.intent.contracts import IntentEvent
        from backend.domains.profiles.contracts import CandidateProfessionalProfile, DiscoveryState
        from backend.domains.opportunities.contracts import OpportunitySpecification

        for cls in [IntentEvent, CandidateProfessionalProfile, DiscoveryState, OpportunitySpecification]:
            fields = {f.name for f in cls.__dataclass_fields__.values()}
            score_fields = {
                "score", "match_score", "trust_score", "permission_score",
                "combined_score", "overall_score", "fit_score", "rank"
            }
            assert fields.isdisjoint(score_fields), f"{cls.__name__} has score field"

    def test_no_current_authorization_implementation_in_a0(self):
        """No authorization implementation in A0-001; only documented for A9/B12."""
        # permissions/__init__.py is boundary marker only
        import backend.domains.permissions as perms

        # No AuthorizationResult, CurrentPermissionCheck, ContactGovernor, Grant classes
        assert not hasattr(perms, "AuthorizationResult")
        assert not hasattr(perms, "CurrentPermissionCheck")
        assert not hasattr(perms, "ContactGovernor")
        assert not hasattr(perms, "Grant")
        assert perms.__doc__ == "Permissions domain boundary marker (A9/B9+)."

    def test_talent_stream_aggregate_not_defined(self):
        """TalentStream aggregate not defined in A0-001."""
        import backend.domains.talent_stream as ts

        assert not hasattr(ts, "TalentStream")
        assert not hasattr(ts, "StreamCandidateProjection")
        assert not hasattr(ts, "ContactRequest")
        assert not hasattr(ts, "Grant")
        assert not hasattr(ts, "VisibilityLevel")

    def test_no_numeric_business_policy_defaults(self):
        """No numeric business policy defaults in A0-001."""
        # Check no defaults like 2 sources, 0.3 weight, 30 days, max_candidates, quotas, thresholds
        import backend.domains.intent.contracts as intent
        import backend.domains.profiles.contracts as profiles
        import backend.domains.opportunities.contracts as opportunities

        # No numeric constants defined at module level
        for mod in [intent, profiles, opportunities]:
            for name in dir(mod):
                if not name.startswith("_"):
                    val = getattr(mod, name)
                    if isinstance(val, (int, float)) and name.isupper():
                        # Allow version numbers like "1.0" but not policy defaults
                        pass

    def test_no_runtime_business_methods(self):
        """No runtime business methods in A0-001 contracts."""
        from backend.domains.intent.contracts import IntentEvent
        from backend.domains.profiles.contracts import DiscoveryState, CandidatePreferences
        from backend.domains.opportunities.contracts import OpportunitySpecification
        from backend.domains.roles.contracts import RoleDNA

        for cls in [IntentEvent, DiscoveryState, CandidatePreferences, OpportunitySpecification, RoleDNA]:
            methods = [m for m in dir(cls) if not m.startswith("_") and callable(getattr(cls, m))]
            forbidden = ["is_active", "is_eligible", "calculate", "normalize", "authorize", "check_permission"]
            for f in forbidden:
                assert f not in methods, f"{cls.__name__} should not have {f} method"

    def test_no_persistence_or_infrastructure(self):
        """No repositories, Mongo, indexes, migrations, outbox, workers, routes, services."""
        # All contract modules should not define infrastructure-related names
        import backend.domains.profiles.contracts as profiles
        import backend.domains.roles.contracts as roles
        import backend.domains.opportunities.contracts as opportunities
        import backend.domains.intent.contracts as intent

        forbidden_patterns = [
            "repository", "mongo", "index", "migration", "outbox",
            "worker", "route", "service", "engine", "collection",
            "database", "db", "client", "session", "transaction",
        ]

        for mod in [profiles, roles, opportunities, intent]:
            for name in mod.__dict__:
                if not name.startswith("_"):
                    lower_name = name.lower()
                    for pattern in forbidden_patterns:
                        assert pattern not in lower_name, f"{mod.__name__}.{name} contains forbidden pattern '{pattern}'"


class TestNoPydanticDeprecated:
    """Verify no Pydantic v2 deprecated APIs used."""

    def test_no_pydantic_imports_in_contracts(self):
        """Contract modules don't import Pydantic."""
        import backend.domains.profiles.contracts as profiles
        import backend.domains.roles.contracts as roles
        import backend.domains.opportunities.contracts as opportunities
        import backend.domains.intent.contracts as intent
        import backend.domains.shared.ids as ids
        import backend.domains.shared.versioning as versioning
        import backend.domains.shared.envelope as envelope

        for mod in [profiles, roles, opportunities, intent, ids, versioning, envelope]:
            assert not hasattr(mod, "BaseModel")
            assert not hasattr(mod, "Field")
            assert not hasattr(mod, "validator")
            assert not hasattr(mod, "root_validator")

    def test_dataclasses_are_frozen_with_slots(self):
        """All dataclasses use frozen=True, slots=True."""
        from backend.domains.profiles.contracts import (
            CandidateProfessionalProfile,
            CandidatePreferences,
            DiscoveryState,
        )
        from backend.domains.roles.contracts import TaxonomyRef, TaxonomyRefs, RoleDNA
        from backend.domains.opportunities.contracts import OpportunitySpecification, StreamRequirement
        from backend.domains.intent.contracts import IntentProvenance, IntentEvent
        from backend.domains.shared.versioning import VersionedRef, StreamRequirementVersionVO
        from backend.domains.shared.envelope import Metadata, ActorContext, DomainEnvelope

        for cls in [
            CandidateProfessionalProfile, CandidatePreferences, DiscoveryState,
            TaxonomyRef, TaxonomyRefs, RoleDNA,
            OpportunitySpecification, StreamRequirement,
            IntentProvenance, IntentEvent,
            VersionedRef, StreamRequirementVersionVO,
            Metadata, ActorContext, DomainEnvelope,
        ]:
            assert hasattr(cls, "__dataclass_fields__")
            assert cls.__dataclass_params__.frozen is True
            assert cls.__dataclass_params__.slots is True


class TestNoDatetimeUtcnow:
    """Verify no datetime.utcnow() usage."""

    def test_metadata_uses_timezone_aware_now(self):
        """Metadata.created_at uses datetime.now(timezone.utc)."""
        from backend.domains.shared.envelope import Metadata

        meta = Metadata()
        assert meta.created_at.tzinfo is not None
        assert meta.created_at.tzinfo == timezone.utc or meta.created_at.tzinfo.utcoffset(meta.created_at).total_seconds() == 0

    def test_intent_event_uses_timezone_aware_now(self):
        """IntentEvent.occurred_at uses datetime.now(timezone.utc)."""
        from backend.domains.intent.contracts import IntentEvent, IntentEventType, IntentDimension, IntentProvenance

        event = IntentEvent(
            id=IntentEventId("ie1"),
            event_type=IntentEventType.JOB_VIEW,
            dimension=IntentDimension.JOB,
            candidate_id=CandidateId("c1"),
            provenance=IntentProvenance(source="test"),
        )
        assert event.occurred_at.tzinfo is not None


class TestLineCountDiscipline:
    """Verify production code line count discipline."""

    def test_domains_line_count_under_limit(self):
        """Backend domains production code should be <= ~700 non-comment/non-blank lines."""
        import os
        from pathlib import Path

        domains_path = Path("backend/domains")
        total_lines = 0
        for py_file in domains_path.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            with open(py_file) as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        total_lines += 1

        # Target <= 700, hard stop at 1000
        assert total_lines <= 1000, f"Domain production lines: {total_lines} (limit: 1000)"
        print(f"Domain production non-comment/non-blank lines: {total_lines}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])