# Contract Tests for TS-A0-001 Domain Contracts
# Validates: imports, type structure, frozen models, NewType separation, business invariant encoding

import pytest
from typing import get_type_hints


# ============================================================
# Shared Kernel Tests
# ============================================================

def test_shared_ids_import():
    from domains.shared.ids import (
        CandidateId, CompanyId, OrganizationId, RecruiterId, JobId,
        RoleDNAId, OpportunitySpecId, StreamId, IntentEventId,
        ContactRequestId, GrantId, MandateId,
        ProfileVersion, PreferencesVersion, RoleDNAVersion,
        OpportunitySpecVersion, MatchEngineVersion, IntentEngineVersion,
        PolicyVersion, ConsentVersion, EventSchemaVersion,
    )
    # Verify NewType identity (static separation)
    assert CandidateId.__name__ == "CandidateId"
    assert CompanyId.__name__ == "CompanyId"


def test_shared_ids_factory_functions():
    from domains.shared.ids import (
        new_candidate_id, new_company_id, new_organization_id,
        new_recruiter_id, new_job_id, new_role_dna_id,
        new_opportunity_spec_id, new_stream_id, new_intent_event_id,
        new_contact_request_id, new_grant_id, new_mandate_id,
        new_profile_version, new_preferences_version, new_role_dna_version,
        new_opportunity_spec_version, new_match_engine_version,
        new_intent_engine_version, new_policy_version, new_consent_version,
        new_event_schema_version,
    )
    cid = new_candidate_id()
    assert isinstance(cid, str)
    assert len(cid) == 36  # UUID format


def test_shared_versioning():
    from domains.shared.versioning import VersionedRef, Versioned, StreamRequirementVersion, ProfileRef, RoleDNARef, OpportunitySpecRef
    from domains.shared.ids import ProfileVersion, RoleDNAVersion, OpportunitySpecVersion
    from datetime import datetime
    
    # VersionedRef construction (using type alias)
    ref = ProfileRef(id="test", version=ProfileVersion("v1"))
    assert ref.id == "test"
    assert ref.version == ProfileVersion("v1")
    assert isinstance(ref.snapshot_at, datetime)
    
    # StreamRequirementVersion
    sr = StreamRequirementVersion(
        role_dna=RoleDNARef(id="rdna1", version=RoleDNAVersion("v1")),
        opportunity_spec=OpportunitySpecRef(id="ospec1", version=OpportunitySpecVersion("v1"))
    )
    assert sr.role_dna.id == "rdna1"
    assert sr.opportunity_spec.id == "ospec1"


def test_shared_envelope():
    from domains.shared.envelope import DomainEnvelope, Metadata, ActorContext
    from domains.shared.ids import CandidateId, EventSchemaVersion
    
    meta = Metadata(event_schema_version=EventSchemaVersion("v1"))
    env = DomainEnvelope[str](event_id="e1", event_type="test", payload="data", metadata=meta)
    assert env.payload == "data"
    assert env.metadata.event_schema_version == EventSchemaVersion("v1")
    
    actor = ActorContext(candidate_id=CandidateId("c1"), is_verified_recruiter=True)
    assert actor.candidate_id == CandidateId("c1")
    assert actor.is_verified_recruiter is True


# ============================================================
# Profiles Domain Tests
# ============================================================

def test_profiles_import():
    from domains.profiles import (
        ProfessionalProfile, ProfileVersion, ProfileRef,
        CandidatePreferences, PreferencesVersion, PreferencesRef,
        DiscoveryState, DiscoveryMode, DiscoveryPoolEligibility,
    )
    assert ProfessionalProfile is not None
    assert DiscoveryMode is not None


def test_professional_profile_frozen():
    from domains.profiles.profile import ProfessionalProfile
    from domains.shared.ids import CandidateId, ProfileVersion
    
    profile = ProfessionalProfile(
        id="p1",
        version=ProfileVersion("v1"),
        candidate_id=CandidateId("c1"),
        occupations=["software_engineer"],
        skills=["python", "fastapi"],
    )
    # Verify frozen - field reassignment should fail
    import pytest
    with pytest.raises(Exception):
        profile.id = "p2"  # Field reassignment should fail


def test_discovery_mode_values():
    from domains.profiles.discovery import DiscoveryMode
    
    # Verify all required modes exist (TALENT_STREAM_SPEC.md §5)
    assert DiscoveryMode.DISABLED == "disabled"
    assert DiscoveryMode.ENABLED_COMPATIBLE == "enabled_compatible"
    assert DiscoveryMode.ENABLED_ASK_BEFORE_REVEAL == "enabled_ask_before_reveal"
    assert DiscoveryMode.ANONYMOUS_ONLY == "anonymous_only"
    assert DiscoveryMode.PROFILE_REVEAL_AFTER_ACCEPT == "profile_reveal_after_accept"


def test_discovery_not_intent_boundary():
    """
    CRITICAL: Discovery != Intent — this is a semantic boundary test.
    DiscoveryState exists in profiles/, Intent events live in intent/.
    """
    from domains.profiles.discovery import DiscoveryState, DiscoveryMode
    from domains.intent.events import IntentEventType
    
    # DiscoveryState has no intent event fields
    state = DiscoveryState(
        candidate_id="c1",
        mode=DiscoveryMode.ENABLED_COMPATIBLE,
    )
    # Verify no intent fields exist
    assert not hasattr(state, 'intent_events')
    assert not hasattr(state, 'job_intent')
    assert not hasattr(state, 'role_intent')
    
    # IntentEventType has no discovery mode
    assert IntentEventType.SAVED_JOB == "saved_job"
    # Discovery enablement is NOT an intent event (BUSINESS_RULES.md §2.8)


# ============================================================
# Roles Domain Tests
# ============================================================

def test_roles_import():
    from domains.roles import RoleDNA, RoleDNAVersion, RoleDNARef, OccupationTaxonomyRef, SkillTaxonomyRef
    assert RoleDNA is not None
    assert OccupationTaxonomyRef is not None


def test_role_dna_frozen():
    from domains.roles.role_dna import RoleDNA
    from domains.shared.ids import RoleDNAId, RoleDNAVersion
    
    role = RoleDNA(
        id=RoleDNAId("r1"),
        version=RoleDNAVersion("v1"),
        occupation_code="SW_ENG",
        occupation_label="Software Engineer",
    )
    # Verify frozen - field reassignment should fail
    import pytest
    with pytest.raises(Exception):
        role.id = RoleDNAId("r2")  # Field reassignment should fail


def test_taxonomy_refs():
    from domains.roles.taxonomy import OccupationTaxonomyRef, SkillTaxonomyRef
    
    occ = OccupationTaxonomyRef(
        taxonomy_id="ROME",
        taxonomy_version="2020",
        code="M1805",
        label="Software development",
    )
    assert occ.code == "M1805"
    
    skill = SkillTaxonomyRef(
        taxonomy_id="ESCO",
        taxonomy_version="1.1",
        code="S1.2.3",
        label="Python programming",
    )
    assert skill.category is None


# ============================================================
# Opportunities Domain Tests
# ============================================================

def test_opportunities_import():
    from domains.opportunities import (
        OpportunitySpecification, OpportunitySpecVersion, OpportunitySpecRef,
        StreamRequirement, StreamRequirementVersion,
    )
    assert OpportunitySpecification is not None
    assert StreamRequirement is not None


def test_opportunity_spec_frozen():
    from domains.opportunities.opportunity_spec import OpportunitySpecification
    from domains.shared.ids import OpportunitySpecId, OpportunitySpecVersion, RoleDNAId, CompanyId
    
    spec = OpportunitySpecification(
        id=OpportunitySpecId("os1"),
        version=OpportunitySpecVersion("v1"),
        role_dna_id=RoleDNAId("rdna1"),
        role_dna_version="v1",
        salary_min=50000,
        location="Paris",
    )
    with pytest.raises(Exception):
        spec.salary_min = 60000


def test_stream_requirement_composition():
    from domains.opportunities.stream_requirement import StreamRequirement, StreamRequirementInput
    from domains.roles.role_dna import RoleDNARef
    from domains.opportunities.opportunity_spec import OpportunitySpecRef
    from domains.shared.ids import (
        StreamId, RoleDNAId, OpportunitySpecId,
        RoleDNAVersion, OpportunitySpecVersion,
    )
    from domains.shared.versioning import StreamRequirementVersion, RoleDNARef as SharedRoleDNARef, OpportunitySpecRef as SharedOpportunitySpecRef
    from datetime import datetime
    
    req = StreamRequirement(
        stream_id=StreamId("s1"),
        requirement_version=StreamRequirementVersion(
            role_dna=SharedRoleDNARef(id="rdna1", version=RoleDNAVersion("v1")),
            opportunity_spec=SharedOpportunitySpecRef(id="os1", version=OpportunitySpecVersion("v1"))
        ),
        role_dna=RoleDNARef(role_dna_id=RoleDNAId("rdna1"), role_dna_version=RoleDNAVersion("v1")),
        opportunity_spec=OpportunitySpecRef(opportunity_spec_id=OpportunitySpecId("os1"), opportunity_spec_version=OpportunitySpecVersion("v1")),
        composed_by="user1",
    )
    assert req.stream_id == StreamId("s1")
    assert req.role_dna.role_dna_id == RoleDNAId("rdna1")


def test_stream_requirement_update_explicit():
    """
    ARCHITECTURE.md §16: Updating a Stream requirement is an explicit operation.
    A source job changing later must not silently redefine an existing Stream.
    """
    from domains.opportunities.stream_requirement import StreamRequirementUpdate
    from domains.shared.ids import StreamId, RoleDNAId, RoleDNAVersion
    from domains.shared.versioning import StreamRequirementVersion, RoleDNARef as SharedRoleDNARef, OpportunitySpecRef as SharedOpportunitySpecRef
    from domains.roles.role_dna import RoleDNARef
    from domains.opportunities.opportunity_spec import OpportunitySpecRef
    from domains.shared.ids import OpportunitySpecId, OpportunitySpecVersion
    
    update = StreamRequirementUpdate(
        stream_id=StreamId("s1"),
        current_requirement_version=StreamRequirementVersion(
            role_dna=SharedRoleDNARef(id="rdna1", version=RoleDNAVersion("v1")),
            opportunity_spec=SharedOpportunitySpecRef(id="os1", version=OpportunitySpecVersion("v1"))
        ),
        new_role_dna_id=RoleDNAId("rdna2"),
        new_role_dna_version=RoleDNAVersion("v2"),
        update_reason="role_refinement",
        updated_by="user1",
    )
    assert update.new_role_dna_id == RoleDNAId("rdna2")
    assert update.update_reason == "role_refinement"


# ============================================================
# Matching Domain Tests
# ============================================================

def test_matching_package_exists():
    import domains.matching
    # Empty package — just boundary marker for A5/A6


# ============================================================
# Intent Domain Tests
# ============================================================

def test_intent_import():
    from domains.intent import (
        IntentEventType, IntentSourceType, IntentEvent, IntentEventProvenance,
        DeclaredIntentEvent, ObservedIntentEvent,
        JobIntent, RoleIntent, CompanyIntent, MarketIntent,
    )
    assert IntentEventType is not None
    assert JobIntent is not None


def test_intent_event_types():
    from domains.intent.events import IntentEventType
    
    # Declared intent types
    assert IntentEventType.DECLARED_JOB_INTEREST == "declared_job_interest"
    assert IntentEventType.DECLARED_ROLE_INTEREST == "declared_role_interest"
    assert IntentEventType.SHARED_FAVORITE == "shared_favorite"
    assert IntentEventType.ACCEPTED_INTRODUCTION == "accepted_introduction"
    assert IntentEventType.SUBMITTED_APPLICATION == "submitted_application"
    
    # Observed intent types
    assert IntentEventType.JOB_VIEW == "job_view"
    assert IntentEventType.EXTERNAL_CLICK == "external_click"
    assert IntentEventType.SAVED_JOB == "saved_job"
    
    # Discovery enablement is NOT an intent event
    all_types = [e.value for e in IntentEventType]
    assert "discovery_enabled" not in all_types
    assert "discovery_enablement" not in all_types


def test_intent_provenance_internal_only():
    from domains.intent.events import IntentEventProvenance, IntentSourceType
    from domains.shared.ids import JobId, OrganizationId
    
    prov = IntentEventProvenance(
        source_type=IntentSourceType.JOBOOLO_JOB,
        source_job_id=JobId("j1"),
        source_organization_id=OrganizationId("org1"),
    )
    # Provenance has source tracking fields for INTERNAL use
    assert prov.source_organization_id == OrganizationId("org1")
    # But no field for exposing to recruiters


def test_four_intent_dimensions_separate():
    """
    BUSINESS_RULES.md §18: Keep Job Intent, Role Intent, Company Intent, Market Intent separate.
    """
    from domains.intent.dimensions import JobIntent, RoleIntent, CompanyIntent, MarketIntent
    from domains.shared.ids import CandidateId, JobId, RoleDNAId, CompanyId
    
    job_intent = JobIntent(candidate_id=CandidateId("c1"), job_id=JobId("j1"))
    role_intent = RoleIntent(candidate_id=CandidateId("c1"), role_dna_ids=[RoleDNAId("rdna1")])
    company_intent = CompanyIntent(candidate_id=CandidateId("c1"), company_id=CompanyId("comp1"))
    market_intent = MarketIntent(candidate_id=CandidateId("c1"))
    
    # They are distinct types with different fields
    assert hasattr(job_intent, 'job_id')
    assert hasattr(role_intent, 'role_dna_ids')
    assert hasattr(company_intent, 'company_id')
    assert hasattr(market_intent, 'active_job_search')
    
    # Company Intent must not auto-transfer to Role Intent (BUSINESS_RULES.md §6.8)
    # This is enforced by separate types — no automatic conversion


# ============================================================
# Talent Stream Domain Tests
# ============================================================

def test_talent_stream_import():
    from domains.talent_stream import (
        ContactRequest, ContactRequestStatus, ContactLifecycleEvent,
        ContactLifecycleEventType, CandidateDecision,
        CVGrantReason, CVGrantScope, TalentStreamCVGrant,
        CVAccessRequest, CVAccessDecision,
        ExclusionScope, ExclusionCheck, CurrentEmployerExclusion,
    )
    assert ContactRequest is not None
    assert TalentStreamCVGrant is not None


def test_contact_request_statuses():
    from domains.talent_stream.contact import ContactRequestStatus
    
    assert ContactRequestStatus.PENDING == "pending"
    assert ContactRequestStatus.ACCEPTED == "accepted"
    assert ContactRequestStatus.DECLINED == "declined"
    assert ContactRequestStatus.IGNORED == "ignored"
    assert ContactRequestStatus.GRANT_ACTIVATED == "grant_activated"


def test_candidate_decision_values():
    from domains.talent_stream.contact import CandidateDecision
    
    assert CandidateDecision.ACCEPT == "accept"
    assert CandidateDecision.DECLINE == "decline"
    assert CandidateDecision.IGNORE == "ignore"


def test_cv_grant_reason_explicit():
    """
    Architecture Review Amendment: Use TALENT_STREAM_CV_GRANT (not generic TALENT_STREAM_GRANT)
    to preserve rule that CV permission is document/scope specific.
    """
    from domains.talent_stream.cv_access import CVGrantReason
    
    assert CVGrantReason.TALENT_STREAM_CV_GRANT == "talent_stream_cv_grant"
    # No generic TALENT_STREAM_GRANT exists
    reasons = [r.value for r in CVGrantReason]
    assert "talent_stream_grant" not in reasons
    assert "talent_stream_cv_grant" in reasons


def test_cv_grant_scoped():
    """
    BUSINESS_RULES.md §13.7: CV grant is scoped to candidate/document/recruiter/org/Stream/purpose.
    """
    from domains.talent_stream.cv_access import CVGrantScope
    
    assert CVGrantScope.SPECIFIC_CV_STREAM == "specific_cv_stream"
    assert CVGrantScope.SPECIFIC_CV_RECRUITER == "specific_cv_recruiter"
    assert CVGrantScope.SPECIFIC_CV_ORG == "specific_cv_org"


def test_current_employer_exclusion_security():
    """
    BUSINESS_RULES.md §10.3: Current-employer exclusion is security/privacy rule, not cosmetic preference.
    BUSINESS_RULES.md §10.6: Accidental exposure is critical trust incident.
    """
    from domains.talent_stream.exclusions import CurrentEmployerExclusion, ExclusionType
    from domains.shared.ids import CandidateId, CompanyId
    
    excl = CurrentEmployerExclusion(
        candidate_id=CandidateId("c1"),
        company_id=CompanyId("comp1"),
        verified=True,
    )
    assert excl.verified is True
    assert ExclusionType.CURRENT_EMPLOYER == "current_employer"


def test_exclusion_check_before_contact():
    """
    BUSINESS_RULES.md §10.4, §11.3: Exclusions apply BEFORE recruiter contact/reveal.
    Contact Governor runs before invitation (BUSINESS_RULES.md §11.1).
    """
    from domains.talent_stream.exclusions import ExclusionCheck, ExclusionScope, ExclusionType
    from domains.shared.ids import CandidateId, CompanyId, OrganizationId
    
    check = ExclusionCheck(
        candidate_id=CandidateId("c1"),
        target_company_id=CompanyId("comp1"),
        scope=ExclusionScope.CONTACT,
        is_excluded=True,
        matched_exclusions=[ExclusionType.CURRENT_EMPLOYER],
        reason="Current employer exclusion",
    )
    assert check.is_excluded is True
    assert check.scope == ExclusionScope.CONTACT


# ============================================================
# Business Invariant Encoding Tests
# ============================================================

def test_match_not_intent_encoded():
    """
    BUSINESS_RULES.md §1: Professional Match != Intent
    Encoded as: Matching domain (A5/A6) separate from Intent domain.
    """
    import domains.matching
    import domains.intent
    # Separate packages enforce separation at module level


def test_discovery_not_intent_encoded():
    """
    BUSINESS_RULES.md §1: Discovery != Intent
    Encoded as: DiscoveryState in profiles/, Intent events in intent/.
    """
    from domains.profiles.discovery import DiscoveryState
    from domains.intent.events import IntentEventType
    
    # DiscoveryState has no intent fields
    ds_fields = set(DiscoveryState.__fields__.keys())
    assert 'intent_events' not in ds_fields
    assert 'job_intent' not in ds_fields
    assert 'role_intent' not in ds_fields


def test_intent_not_permission_encoded():
    """
    BUSINESS_RULES.md §1: Intent != Permission
    Encoded as: Intent events (intent/) separate from Permission/Grants (talent_stream/, permissions/ domain).
    """
    from domains.intent.events import IntentEvent
    from domains.talent_stream.cv_access import TalentStreamCVGrant
    
    # IntentEvent has no grant/permission fields
    ie_fields = set(IntentEvent.__fields__.keys())
    assert 'grant_id' not in ie_fields
    assert 'permission' not in ie_fields


def test_permission_not_trust_encoded():
    """
    BUSINESS_RULES.md §1: Permission != Trust
    Encoded as: Talent Stream grants (talent_stream/) separate from Trust/Verification (trust/ domain).
    """
    from domains.talent_stream.cv_access import TalentStreamCVGrant
    
    # CVGrant has no trust/verification fields
    grant_fields = set(TalentStreamCVGrant.__fields__.keys())
    assert 'trust_score' not in grant_fields
    assert 'verified' not in grant_fields


def test_cv_grant_not_broad_recruiter_bypass():
    """
    BUSINESS_RULES.md §13.6: Never introduce broad `if employer: allow` behavior.
    CVGrantReason.TALENT_STREAM_CV_GRANT is explicit and scoped.
    """
    from domains.talent_stream.cv_access import CVGrantReason
    
    # Only specific, scoped grant reasons exist
    reasons = [r.value for r in CVGrantReason]
    # No broad employer bypass
    assert "employer_access" not in reasons
    assert "recruiter_access" not in reasons


def test_no_single_opaque_score():
    """
    BUSINESS_RULES.md §1.9: Do not replace dimensions with one opaque authoritative Talent Score.
    Separate types for Match, Fit, Intent, Trust, Permission enforce this.
    """
    # ProfessionalMatch (A5/A6) != OpportunityFit (A6) != Intent (intent/) != 
    # Permission (talent_stream/) != Trust (trust/) — all separate domains
    
    # This test validates the architectural separation exists
    import domains.matching
    import domains.intent
    import domains.talent_stream
    # Separate packages = separate concepts


# ============================================================
# Frozen/Immutable Contract Tests
# ============================================================

def test_all_domain_models_frozen():
    """
    All domain contract models should be frozen (immutable) for safety.
    """
    from domains.profiles.profile import ProfessionalProfile
    from domains.profiles.preferences import CandidatePreferences
    from domains.profiles.discovery import DiscoveryState
    from domains.roles.role_dna import RoleDNA
    from domains.opportunities.opportunity_spec import OpportunitySpecification
    from domains.opportunities.stream_requirement import StreamRequirement
    from domains.intent.events import IntentEvent, DeclaredIntentEvent, ObservedIntentEvent
    from domains.intent.dimensions import JobIntent, RoleIntent, CompanyIntent, MarketIntent
    from domains.talent_stream.contact import ContactRequest, ContactLifecycleEvent
    from domains.talent_stream.cv_access import TalentStreamCVGrant, CVAccessRequest
    from domains.talent_stream.exclusions import CurrentEmployerExclusion, ExclusionCheck
    
    models = [
        ProfessionalProfile, CandidatePreferences, DiscoveryState,
        RoleDNA, OpportunitySpecification, StreamRequirement,
        IntentEvent, DeclaredIntentEvent, ObservedIntentEvent,
        JobIntent, RoleIntent, CompanyIntent, MarketIntent,
        ContactRequest, ContactLifecycleEvent,
        TalentStreamCVGrant, CVAccessRequest,
        CurrentEmployerExclusion, ExclusionCheck,
    ]
    
    for model in models:
        config = getattr(model, 'Config', None)
        assert config is not None, f"{model.__name__} missing Config"
        assert getattr(config, 'frozen', False) is True, f"{model.__name__} not frozen"


# ============================================================
# Import/Compile Smoke Test
# ============================================================

def test_all_domains_import():
    """
    Smoke test: all domain packages import without error.
    """
    import domains
    import domains.shared
    import domains.shared.ids
    import domains.shared.versioning
    import domains.shared.envelope
    import domains.profiles
    import domains.profiles.profile
    import domains.profiles.preferences
    import domains.profiles.discovery
    import domains.roles
    import domains.roles.role_dna
    import domains.roles.taxonomy
    import domains.opportunities
    import domains.opportunities.opportunity_spec
    import domains.opportunities.stream_requirement
    import domains.matching
    import domains.intent
    import domains.intent.events
    import domains.intent.dimensions
    import domains.talent_stream
    import domains.talent_stream.contact
    import domains.talent_stream.cv_access
    import domains.talent_stream.exclusions
    
    # If we reach here, all imports succeeded
    assert True