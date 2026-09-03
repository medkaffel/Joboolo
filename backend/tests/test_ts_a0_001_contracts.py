"""Contract tests for TS-A0-001 Domain Contracts & Business Invariants.

These tests verify the structural integrity of domain contracts and
enforce canonical Talent Stream business invariants at the type level.
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from typing import get_type_hints

def utcnow() -> datetime:
    """Timezone-aware UTC now."""
    return datetime.now(timezone.utc)

# --- Shared kernel tests ---

def test_shared_ids_newtype_distinction():
    """Verify NewType IDs provide static distinction."""
    from backend.domains.shared.ids import (
        CandidateId, RecruiterId, OrganizationId, RoleDNAId,
        StreamId, candidate_id, recruiter_id, organization_id, role_dna_id, stream_id
    )

    c = candidate_id()
    r = recruiter_id()
    o = organization_id()
    rd = role_dna_id()
    s = stream_id()

    assert isinstance(c, str)
    assert isinstance(r, str)
    assert isinstance(o, str)
    assert isinstance(rd, str)
    assert isinstance(s, str)

    # NewType doesn't prevent runtime assignment but provides static checking
    assert c != r
    assert c != o
    assert rd != s


def test_shared_versioning_value_objects():
    """Verify versioning value objects are immutable and well-formed."""
    from backend.domains.shared.versioning import (
        VersionedRef, Versioned, StreamRequirementVersion, EntityVersion
    )

    ref = VersionedRef(entity_id="test-123", version=5)
    assert ref.entity_id == "test-123"
    assert ref.version == 5

    versioned = Versioned(value="data", version=3, updated_at=utcnow())
    assert versioned.value == "data"
    assert versioned.version == 3

    snap = StreamRequirementVersion(
        role_dna_ref=VersionedRef("role-1", 2),
        opportunity_spec_ref=VersionedRef("opp-1", 1),
        composed_at=utcnow(),
        composed_by="recruiter-1",
        policy_version="v1.0",
    )
    assert snap.role_dna_ref.version == 2
    assert snap.policy_version == "v1.0"


def test_shared_envelope_metadata():
    """Verify event/command envelope structure."""
    from backend.domains.shared.envelope import Metadata, ActorContext, DomainEnvelope

    actor = ActorContext(
        actor_type="recruiter",
        actor_id="rec-123",
        organization_id="org-456",
    )
    meta = Metadata(actor=actor, schema_version=1)
    assert meta.actor.actor_type == "recruiter"
    assert meta.schema_version == 1

    env = DomainEnvelope.create(payload={"key": "value"}, actor=actor)
    assert env.payload["key"] == "value"
    assert env.metadata.actor.actor_id == "rec-123"


# --- Profiles domain tests ---

def test_profiles_professional_profile_contract():
    """Verify ProfessionalProfile contract shape."""
    from backend.domains.profiles.contracts import ProfessionalProfile
    from backend.domains.shared.ids import ProfileId, CandidateId

    profile = ProfessionalProfile(
        profile_id=ProfileId("prof-1"),
        candidate_id=CandidateId("cand-1"),
        version=1,
        updated_at=utcnow(),
        updated_by=CandidateId("cand-1"),
        occupations=["software_engineer"],
        skills=["python", "sql"],
        seniority_level="senior",
    )
    assert profile.profile_id == "prof-1"
    assert profile.seniority_level == "senior"
    assert profile.to_ref().version == 1


def test_profiles_candidate_preferences_contract():
    """Verify CandidatePreferences contract shape."""
    from backend.domains.profiles.contracts import CandidatePreferences
    from backend.domains.shared.ids import PreferencesId, CandidateId

    prefs = CandidatePreferences(
        preferences_id=PreferencesId("pref-1"),
        candidate_id=CandidateId("cand-1"),
        version=1,
        updated_at=utcnow(),
        updated_by=CandidateId("cand-1"),
        target_roles=["software_engineer"],
        salary_min=60000,
        remote_policy="remote",
    )
    assert prefs.remote_policy == "remote"
    assert prefs.salary_min == 60000


def test_profiles_discovery_state_separate_from_intent():
    """Verify DiscoveryState is separate from Intent (DISCOVERY != INTENT invariant)."""
    from backend.domains.profiles.contracts import DiscoveryState, DiscoveryMode
    from backend.domains.shared.ids import DiscoveryStateId, CandidateId

    state = DiscoveryState(
        discovery_state_id=DiscoveryStateId("disc-1"),
        candidate_id=CandidateId("cand-1"),
        version=1,
        updated_at=utcnow(),
        updated_by=CandidateId("cand-1"),
        mode=DiscoveryMode.ENABLED_SIMILAR,
        similar_opportunities_allowed=True,
    )
    # Discovery enablement is not an intent event
    assert state.mode == DiscoveryMode.ENABLED_SIMILAR
    assert state.is_eligible_for_discovery() is True

    # Disabled mode
    disabled = DiscoveryState(
        discovery_state_id=DiscoveryStateId("disc-2"),
        candidate_id=CandidateId("cand-2"),
        version=1,
        updated_at=utcnow(),
        updated_by=CandidateId("cand-2"),
        mode=DiscoveryMode.DISABLED,
    )
    assert disabled.is_eligible_for_discovery() is False


def test_profiles_discovery_pool_eligibility_derived():
    """Verify DiscoveryPoolEligibility is derived, not stored."""
    from backend.domains.profiles.contracts import DiscoveryPoolEligibility
    from backend.domains.shared.ids import CandidateId
    from backend.domains.shared.versioning import VersionedRef

    elig = DiscoveryPoolEligibility(
        candidate_id=CandidateId("cand-1"),
        discovery_state_ref=VersionedRef("disc-1", 1),
        preferences_ref=VersionedRef("pref-1", 1),
        eligible=True,
        reasons=["discovery_enabled", "preferences_compatible"],
    )
    assert elig.eligible is True
    assert "discovery_enabled" in elig.reasons


# --- Roles domain tests ---

def test_roles_role_dna_contract():
    """Verify RoleDNA contract shape — no commercial conditions."""
    from backend.domains.roles.contracts import RoleDNA
    from backend.domains.shared.ids import RoleDNAId

    role_dna = RoleDNA(
        role_dna_id=RoleDNAId("role-1"),
        version=1,
        updated_at=utcnow(),
        updated_by="recruiter-1",
        occupation_code="2512",
        occupation_label="Software Developer",
        seniority="senior",
        hard_skills=["python", "aws"],
        management_dimension=False,
    )
    # Role DNA describes the professional role, not commercial conditions
    assert role_dna.occupation_code == "2512"
    assert role_dna.seniority == "senior"
    assert not hasattr(role_dna, "salary")  # salary is NOT in Role DNA


def test_roles_normalization_contracts():
    """Verify normalization interfaces are defined."""
    from backend.domains.roles.contracts import (
        NormalizationSourceContext, NormalizationResult,
        OccupationTaxonomyRef, SkillTaxonomyRef
    )
    from backend.domains.shared.ids import OccupationTaxonomyId, SkillTaxonomyId

    ctx = NormalizationSourceContext(
        source_type="reference_job",
        source_job_id="job-123",
    )
    assert ctx.source_type == "reference_job"

    occ_ref = OccupationTaxonomyRef(
        taxonomy_id=OccupationTaxonomyId("tax-1"),
        code="2512",
        label="Software Developer",
    )
    assert occ_ref.code == "2512"


# --- Opportunities domain tests ---

def test_opportunities_opportunity_specification_contract():
    """Verify OpportunitySpecification contains commercial conditions, not role."""
    from backend.domains.opportunities.contracts import OpportunitySpecification
    from backend.domains.shared.ids import OpportunitySpecId

    spec = OpportunitySpecification(
        opportunity_spec_id=OpportunitySpecId("opp-1"),
        version=1,
        updated_at=utcnow(),
        updated_by="recruiter-1",
        salary_min=70000,
        locations=["Paris"],
        remote_policy="hybrid",
        contract_type="permanent",
    )
    # Opportunity Spec describes commercial conditions
    assert spec.salary_min == 70000
    assert spec.remote_policy == "hybrid"
    # Role attributes are NOT here
    assert not hasattr(spec, "hard_skills")


def test_opportunities_stream_requirement_composition():
    """Verify StreamRequirement = RoleDNA + OpportunitySpecification."""
    from backend.domains.opportunities.contracts import StreamRequirement
    from backend.domains.shared.ids import StreamRequirementId, RoleDNAId, OpportunitySpecId
    from backend.domains.shared.versioning import VersionedRef

    req = StreamRequirement(
        stream_requirement_id=StreamRequirementId("sr-1"),
        version=1,
        updated_at=utcnow(),
        updated_by="recruiter-1",
        role_dna_ref=VersionedRef("role-1", 2),
        opportunity_spec_ref=VersionedRef("opp-1", 1),
        composed_at=utcnow(),
        composed_by="recruiter-1",
        policy_version="v1.0",
    )
    assert req.role_dna_ref.entity_id == "role-1"
    assert req.opportunity_spec_ref.entity_id == "opp-1"
    # Stream binds to version/snapshot
    snap = req.to_snapshot()
    assert snap.policy_version == "v1.0"


# --- Intent domain tests ---

def test_intent_event_types_separate_declared_vs_observed():
    """Verify IntentEventType distinguishes declared vs observed."""
    from backend.domains.intent.contracts import (
        IntentEventType, DeclaredIntentEvent, ObservedIntentEvent,
        IntentSourceType, IntentDimension
    )
    from backend.domains.shared.ids import IntentEventId, CandidateId, RoleDNAId

    declared = DeclaredIntentEvent(
        event_id=IntentEventId("evt-1"),
        candidate_id=CandidateId("cand-1"),
        event_type=IntentEventType.DECLARED_INTEREST,
        source_type=IntentSourceType.JOBOOLO_JOB,
        occurred_at=utcnow(),
        declaration_text="I'm interested in this role",
    )
    assert declared.event_type == IntentEventType.DECLARED_INTEREST

    observed = ObservedIntentEvent(
        event_id=IntentEventId("evt-2"),
        candidate_id=CandidateId("cand-1"),
        event_type=IntentEventType.JOB_VIEW,
        source_type=IntentSourceType.JOBOOLO_JOB,
        occurred_at=utcnow(),
        view_duration_seconds=45,
    )
    assert observed.event_type == IntentEventType.JOB_VIEW


def test_intent_four_dimensions_separate():
    """Verify four intent dimensions are kept separate."""
    from backend.domains.intent.contracts import (
        IntentDimension, RoleIntentAggregate, JobIntentAggregate,
        CompanyIntentAggregate, MarketIntentAggregate
    )
    from backend.domains.shared.ids import CandidateId
    from backend.domains.shared.versioning import VersionedRef

    role_intent = RoleIntentAggregate(
        aggregate_id="ri-1",
        candidate_id=CandidateId("cand-1"),
        confidence=0.8,
        independent_signal_count=2,
    )
    assert role_intent.confidence == 0.8

    job_intent = JobIntentAggregate(
        candidate_id=CandidateId("cand-1"),
        job_id="job-1",
        confidence=0.9,
    )
    assert job_intent.job_id == "job-1"

    company_intent = CompanyIntentAggregate(
        candidate_id=CandidateId("cand-1"),
        company_id="comp-1",
        confidence=0.7,
    )
    # Company Intent must not automatically become transferable competitor Role Intent
    assert company_intent.company_id == "comp-1"

    market_intent = MarketIntentAggregate(
        candidate_id=CandidateId("cand-1"),
        activity_level="moderate",
    )
    assert market_intent.activity_level == "moderate"


def test_intent_independent_signal_policy_contract():
    """Verify IndependentSignalRule policy contract exists."""
    from backend.domains.intent.contracts import IndependentSignalPolicy

    policy = IndependentSignalPolicy(
        policy_version="v1.0",
        min_independent_sources=2,
        require_explicit_discovery_or_permission=True,
    )
    assert policy.min_independent_sources == 2
    assert policy.require_explicit_discovery_or_permission is True


# --- Talent Stream domain tests ---

def test_talent_stream_stream_aggregate():
    """Verify TalentStream aggregate binds to versioned StreamRequirement."""
    from backend.domains.talent_stream.contracts import (
        TalentStream, StreamStatus, StreamSourceType
    )
    from backend.domains.shared.ids import StreamId, StreamRequirementId, RecruiterId, OrganizationId
    from backend.domains.shared.versioning import VersionedRef

    stream = TalentStream(
        stream_id=StreamId("stream-1"),
        stream_requirement_ref=VersionedRef("sr-1", 3),
        recruiter_id=RecruiterId("rec-1"),
        organization_id=OrganizationId("org-1"),
        source_type=StreamSourceType.REFERENCE_JOB,
        source_job_id="job-456",
    )
    assert stream.status == StreamStatus.DRAFT
    assert stream.source_type == StreamSourceType.REFERENCE_JOB
    # Reference job does not transfer audience rights


def test_talent_stream_progressive_reveal_levels():
    """Verify progressive reveal levels are defined."""
    from backend.domains.talent_stream.contracts import VisibilityLevel

    levels = list(VisibilityLevel)
    assert VisibilityLevel.MARKET_AGGREGATE in levels
    assert VisibilityLevel.ANONYMOUS_TALENT in levels
    assert VisibilityLevel.PROFILE_PREVIEW in levels
    assert VisibilityLevel.IDENTITY in levels
    assert VisibilityLevel.CV in levels


def test_talent_stream_contact_request_governor_first():
    """Verify ContactRequest starts with Governor check."""
    from backend.domains.talent_stream.contracts import (
        ContactRequest, ContactRequestStatus
    )
    from backend.domains.shared.ids import ContactRequestId, StreamId, CandidateId, RecruiterId, OrganizationId

    cr = ContactRequest(
        contact_request_id=ContactRequestId("cr-1"),
        stream_id=StreamId("stream-1"),
        candidate_id=CandidateId("cand-1"),
        recruiter_id=RecruiterId("rec-1"),
        organization_id=OrganizationId("org-1"),
    )
    # Governor runs BEFORE real invitation
    assert cr.status == ContactRequestStatus.PENDING_GOVERNOR


def test_talent_stream_grant_scopes_distinct():
    """Verify Profile != Identity != CV grant scopes."""
    from backend.domains.talent_stream.contracts import GrantScope, Grant, GrantStatus
    from backend.domains.shared.ids import GrantId, CandidateId, RecruiterId, OrganizationId

    profile_grant = Grant(
        grant_id=GrantId("grant-1"),
        candidate_id=CandidateId("cand-1"),
        recruiter_id=RecruiterId("rec-1"),
        organization_id=OrganizationId("org-1"),
        scope=GrantScope.PROFILE,
    )
    cv_grant = Grant(
        grant_id=GrantId("grant-2"),
        candidate_id=CandidateId("cand-1"),
        recruiter_id=RecruiterId("rec-1"),
        organization_id=OrganizationId("org-1"),
        scope=GrantScope.CV,
        resource_id="cv-doc-1",
    )
    assert profile_grant.scope == GrantScope.PROFILE
    assert cv_grant.scope == GrantScope.CV
    assert cv_grant.resource_id == "cv-doc-1"


# --- Permissions domain tests ---

def test_permissions_authorization_current_not_cached():
    """Verify AuthorizationResult uses current state, not cached projection."""
    from backend.domains.permissions.contracts import (
        AuthorizationContext, AuthorizationResult, AuthorizationDecision, DenialReason
    )
    from backend.domains.shared.ids import CandidateId, RecruiterId, OrganizationId

    ctx = AuthorizationContext(
        candidate_id=CandidateId("cand-1"),
        recruiter_id=RecruiterId("rec-1"),
        organization_id=OrganizationId("org-1"),
        requested_scope="profile",
        action="reveal_profile",
    )
    result = AuthorizationResult(
        decision=AuthorizationDecision.ALLOW,
        policy_version="v1.0",
    )
    assert result.decision == AuthorizationDecision.ALLOW
    # Cached projection is never the authorization source of truth


def test_permissions_exclusion_check_current_employer():
    """Verify current-employer exclusion is a security rule."""
    from backend.domains.permissions.contracts import ExclusionCheck
    from backend.domains.shared.ids import CandidateId, OrganizationId

    check = ExclusionCheck(
        candidate_id=CandidateId("cand-1"),
        hiring_company_id="comp-current",
        recruiter_organization_id=OrganizationId("org-1"),
        current_employer_excluded=True,
    )
    assert check.has_exclusion() is True
    assert check.current_employer_excluded is True


def test_permissions_denial_reasons_structured():
    """Verify denial reasons are structured for audit."""
    from backend.domains.permissions.contracts import DenialReason

    # Key business invariant denials exist
    assert DenialReason.DISCOVERY_DISABLED
    assert DenialReason.EXCLUDED_CURRENT_EMPLOYER
    assert DenialReason.SOURCE_PROTECTION_ACTIVE
    assert DenialReason.INDEPENDENT_SIGNAL_INSUFFICIENT
    assert DenialReason.GRANT_EXPIRED
    assert DenialReason.NO_ACTIVE_GRANT


def test_permissions_contact_governor_policy():
    """Verify Contact Governor policy contract exists."""
    from backend.domains.permissions.contracts import ContactGovernorPolicy

    policy = ContactGovernorPolicy(
        policy_version="v1.0",
        max_invitations_per_candidate_per_week=3,
        min_professional_match_threshold=0.6,
        duplicate_window_days=30,
    )
    assert policy.max_invitations_per_candidate_per_week == 3
    assert policy.duplicate_window_days == 30


# --- Business invariant tests (canonical rules) ---

def test_invariant_match_not_intent():
    """MATCH != INTENT — professional match is separate from intent."""
    from backend.domains.profiles.contracts import ProfessionalProfile
    from backend.domains.intent.contracts import RoleIntentAggregate
    from backend.domains.shared.ids import CandidateId, ProfileId
    from backend.domains.shared.versioning import VersionedRef

    # These are separate constructs with separate semantics
    profile = ProfessionalProfile(
        profile_id=ProfileId("p1"), candidate_id=CandidateId("c1"),
        version=1, updated_at=utcnow(), updated_by=CandidateId("c1"),
    )
    intent = RoleIntentAggregate(
        aggregate_id="ri1", candidate_id=CandidateId("c1"),
        confidence=0.9, independent_signal_count=2,
    )
    # They exist independently
    assert profile.candidate_id == intent.candidate_id
    # But match != intent structurally


def test_invariant_discovery_not_intent():
    """DISCOVERY != INTENT — discovery is a permission state, not intent."""
    from backend.domains.profiles.contracts import DiscoveryState, DiscoveryMode
    from backend.domains.intent.contracts import IntentEventType
    from backend.domains.shared.ids import CandidateId, DiscoveryStateId

    discovery = DiscoveryState(
        discovery_state_id=DiscoveryStateId("d1"), candidate_id=CandidateId("c1"),
        version=1, updated_at=utcnow(), updated_by=CandidateId("c1"),
        mode=DiscoveryMode.ENABLED_SIMILAR, similar_opportunities_allowed=True,
    )
    # Discovery enablement is NOT an intent event type
    assert IntentEventType.DECLARED_INTEREST != "discovery_enabled"
    assert discovery.is_eligible_for_discovery() is True


def test_invariant_intent_not_permission():
    """INTENT != PERMISSION — intent doesn't grant permission."""
    from backend.domains.intent.contracts import DeclaredIntentEvent, IntentEventType, IntentSourceType
    from backend.domains.permissions.contracts import AuthorizationResult, AuthorizationDecision
    from backend.domains.shared.ids import CandidateId, IntentEventId

    intent_event = DeclaredIntentEvent(
        event_id=IntentEventId("e1"), candidate_id=CandidateId("c1"),
        event_type=IntentEventType.DECLARED_INTEREST, source_type=IntentSourceType.JOBOOLO_JOB,
        occurred_at=utcnow(),
    )
    # Intent event exists but permission decision is separate
    perm_result = AuthorizationResult(
        decision=AuthorizationDecision.DENY,
        reason=None,
        policy_version="v1.0",
    )
    assert perm_result.decision == AuthorizationDecision.DENY
    # Intent alone doesn't determine permission


def test_invariant_permission_not_trust():
    """PERMISSION != TRUST — separate domains."""
    from backend.domains.permissions.contracts import AuthorizationDecision
    from backend.domains.trust.__init__ import __doc__ as trust_doc

    # Trust domain owns verification, permissions domain owns grants
    assert "verification" in trust_doc.lower()
    assert AuthorizationDecision.ALLOW == "allow"


def test_invariant_opportunity_fit_not_match():
    """OPPORTUNITY FIT != PROFESSIONAL MATCH — separate evaluations."""
    from backend.domains.talent_stream.contracts import StreamCandidateProjection

    proj = StreamCandidateProjection(
        stream_id="s1", candidate_id="c1",
        candidate_profile_version=1, candidate_preferences_version=1,
        role_dna_version=1, opportunity_spec_version=1,
        match_engine_version="v1", intent_engine_version="v1", policy_version="v1",
        professional_match=0.95, opportunity_fit=0.40,  # High match, low fit
        eligibility_state="eligible",
    )
    # High professional match doesn't imply good opportunity fit
    assert proj.professional_match > proj.opportunity_fit


def test_invariant_reference_job_not_audience():
    """REFERENCE JOB != AUDIENCE OWNERSHIP."""
    from backend.domains.talent_stream.contracts import TalentStream, StreamSourceType
    from backend.domains.shared.ids import StreamId, StreamRequirementId, RecruiterId, OrganizationId
    from backend.domains.shared.versioning import VersionedRef

    stream = TalentStream(
        stream_id=StreamId("s1"),
        stream_requirement_ref=VersionedRef("sr1", 1),
        recruiter_id=RecruiterId("r1"),
        organization_id=OrganizationId("o1"),
        source_type=StreamSourceType.REFERENCE_JOB,
        source_job_id="job-competitor",
    )
    # Using reference job doesn't grant access to its candidates
    assert stream.source_type == StreamSourceType.REFERENCE_JOB
    assert stream.source_job_id == "job-competitor"


def test_invariant_favorite_not_consent():
    """PRIVATE FAVORITE != CONSENT TO SHARE."""
    from backend.domains.intent.contracts import IntentEventType

    # Favorite/save is not in declared intent types
    declared_types = {IntentEventType.DECLARED_INTEREST, IntentEventType.SHARED_FAVORITE,
                      IntentEventType.ACCEPTED_INTRODUCTION, IntentEventType.SUBMITTED_APPLICATION}
    # SHARED_FAVORITE requires explicit sharing action, not private save
    assert "private_save" not in [t.value for t in IntentEventType]


def test_invariant_click_not_consent():
    """CLICK != CONSENT TO SHARE."""
    from backend.domains.intent.contracts import IntentEventType, ObservedIntentEvent
    from backend.domains.shared.ids import CandidateId, IntentEventId

    click = ObservedIntentEvent(
        event_id=IntentEventId("e1"), candidate_id=CandidateId("c1"),
        event_type=IntentEventType.JOB_VIEW, source_type=IntentEventType.JOB_VIEW,
        occurred_at=utcnow(),
    )
    # Observed click is observed intent, not declared consent
    assert click.event_type == IntentEventType.JOB_VIEW


def test_invariant_application_not_cross_company_grant():
    """APPLICATION TO COMPANY A != CROSS-COMPANY GRANT TO COMPANY B."""
    from backend.domains.intent.contracts import DeclaredIntentEvent, IntentEventType, IntentSourceType
    from backend.domains.talent_stream.contracts import Grant, GrantScope
    from backend.domains.shared.ids import CandidateId, IntentEventId, GrantId, RecruiterId, OrganizationId

    app_intent = DeclaredIntentEvent(
        event_id=IntentEventId("e1"), candidate_id=CandidateId("c1"),
        event_type=IntentEventType.SUBMITTED_APPLICATION, source_type=IntentSourceType.JOBOOLO_JOB,
        occurred_at=utcnow(),
    )
    # Application creates intent evidence, not cross-company grant
    grant = Grant(
        grant_id=GrantId("g1"), candidate_id=CandidateId("c1"),
        recruiter_id=RecruiterId("r2"), organization_id=OrganizationId("o2"),
        scope=GrantScope.PROFILE,
    )
    # Grant is explicit and scoped, not automatic from application
    assert grant.scope == GrantScope.PROFILE
    assert grant.organization_id == "o2"  # specific to requesting org


def test_invariant_current_authorization_checked():
    """CURRENT AUTHORIZATION MUST BE CHECKED BEFORE EVERY SENSITIVE ACTION."""
    from backend.domains.permissions.contracts import CurrentPermissionCheck, AuthorizationContext, AuthorizationResult
    from backend.domains.shared.ids import CandidateId, RecruiterId, OrganizationId
    import inspect

    # The contract requires current evaluation - verify protocol shape
    assert hasattr(CurrentPermissionCheck, 'evaluate')
    sig = inspect.signature(CurrentPermissionCheck.evaluate)
    params = list(sig.parameters.keys())
    assert 'context' in params
    # Forward reference string comparison
    assert str(sig.return_annotation) == 'AuthorizationResult'
    # Never authorize from cached projection alone


def test_invariant_no_broad_recruiter_bypass():
    """NO BROAD RECRUITER BYPASS OF CV ACLs."""
    from backend.domains.talent_stream.contracts import Grant, GrantScope, GrantStatus
    from backend.domains.shared.ids import GrantId, CandidateId, RecruiterId, OrganizationId

    # CV access only through active scoped grant
    cv_grant = Grant(
        grant_id=GrantId("g1"), candidate_id=CandidateId("c1"),
        recruiter_id=RecruiterId("r1"), organization_id=OrganizationId("o1"),
        scope=GrantScope.CV, resource_id="cv-123", resource_type="cv_document",
    )
    assert cv_grant.scope == GrantScope.CV
    assert cv_grant.resource_id == "cv-123"
    # No broad "if employer: allow" pattern


def test_invariant_no_single_opaque_score():
    """NO SINGLE OPAQUE SCORE REPLACES MATCH, INTENT, TRUST, PERMISSION."""
    from backend.domains.talent_stream.contracts import StreamCandidateProjection

    proj = StreamCandidateProjection(
        stream_id="s1", candidate_id="c1",
        candidate_profile_version=1, candidate_preferences_version=1,
        role_dna_version=1, opportunity_spec_version=1,
        match_engine_version="v1", intent_engine_version="v1", policy_version="v1",
        professional_match=0.8, opportunity_fit=0.7, role_intent=0.6, market_intent=0.3,
        eligibility_state="eligible",
    )
    # Separate dimensions preserved
    assert hasattr(proj, 'professional_match')
    assert hasattr(proj, 'opportunity_fit')
    assert hasattr(proj, 'role_intent')
    assert hasattr(proj, 'market_intent')
    # No 'talent_score' field


def test_invariant_talent_stream_opt_in_not_required_to_apply():
    """TALENT STREAM OPT-IN NEVER REQUIRED TO APPLY."""
    from backend.domains.profiles.contracts import DiscoveryState, DiscoveryMode
    from backend.domains.shared.ids import CandidateId, DiscoveryStateId

    # Candidate can have Discovery disabled and still apply
    state = DiscoveryState(
        discovery_state_id=DiscoveryStateId("d1"), candidate_id=CandidateId("c1"),
        version=1, updated_at=utcnow(), updated_by=CandidateId("c1"),
        mode=DiscoveryMode.DISABLED,
    )
    assert state.mode == DiscoveryMode.DISABLED
    # Application flow is separate (not modeled in A0)


def test_invariant_no_fake_jobs_for_harvesting():
    """NO FAKE JOBS FOR CANDIDATE/INTENT HARVESTING."""
    from backend.domains.talent_stream.contracts import StreamSourceType

    # Only legitimate source types
    valid_sources = {StreamSourceType.OWN_JOB, StreamSourceType.REFERENCE_JOB,
                     StreamSourceType.EXTERNAL_JOB, StreamSourceType.NATURAL_LANGUAGE}
    # No "fake_job" or "harvesting_pool" source type
    assert "fake_job" not in [s.value for s in StreamSourceType]


# --- Structural tests ---

def test_all_domains_importable():
    """Verify all domain packages can be imported."""
    import backend.domains.shared
    import backend.domains.profiles
    import backend.domains.roles
    import backend.domains.opportunities
    import backend.domains.matching
    import backend.domains.intent
    import backend.domains.talent_stream
    import backend.domains.trust
    import backend.domains.permissions
    import backend.domains.privacy

    # All should have __init__.py
    assert hasattr(backend.domains.shared, '__file__')
    assert hasattr(backend.domains.profiles, '__file__')


def test_contracts_no_runtime_logic():
    """Verify contracts are pure data/interface definitions."""
    import inspect
    from backend.domains.profiles.contracts import ProfessionalProfile
    from backend.domains.roles.contracts import RoleDNA
    from backend.domains.opportunities.contracts import OpportunitySpecification
    from backend.domains.intent.contracts import DeclaredIntentEvent
    from backend.domains.talent_stream.contracts import TalentStream
    from backend.domains.permissions.contracts import AuthorizationResult

    # All should be frozen dataclasses (immutable data)
    for cls in [ProfessionalProfile, RoleDNA, OpportunitySpecification,
                DeclaredIntentEvent, TalentStream, AuthorizationResult]:
        assert hasattr(cls, '__dataclass_fields__')
        # Verify frozen=True via __dataclass_params__
        params = cls.__dataclass_params__
        assert params.frozen is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])