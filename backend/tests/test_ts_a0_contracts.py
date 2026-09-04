from dataclasses import fields
from datetime import datetime, timedelta

import pytest

from domains.shared.ids import (
    CandidateId,
    CandidatePreferencesId,
    CandidateProfileId,
    DocumentId,
    GrantId,
    HiringCompanyId,
    IntentEventId,
    IntentEventType,
    IntentSourceType,
    OpportunitySpecId,
    OrganizationId,
    PseudonymousCandidateId,
    RecruiterUserId,
    RoleDNAId,
)
from domains.shared.versioning import (
    ConsentPolicyVersion,
    EngineVersion,
    EntityVersion,
    PolicyVersion,
    SchemaVersion,
)
from domains.talent_stream.contracts import (
    CandidatePreferencesRef,
    CandidateProfileRef,
    DiscoveryState,
    GrantContract,
    GrantScope,
    OpportunityFitRef,
    OpportunitySpecificationRef,
    ProfessionalMatchRef,
    RecruitingActorContext,
    RoleDNARef,
    StreamRequirementSnapshot,
)
from domains.talent_stream.decisions import PermissionDecision, TrustDecision
from domains.talent_stream.events import IntentKind, IntentOrigin, IntentSubject, TalentIntentEvent
from domains.talent_stream.invariants import (
    ALL_INVARIANTS,
    AUTHORIZATION_INVARIANTS,
    CROSS_OFFER_INVARIANTS,
    DATA_INVARIANTS,
    PRIVACY_INVARIANTS,
    SEPARATION_INVARIANTS,
)


def test_entity_version_rejects_zero_and_negative_values():
    with pytest.raises(ValueError):
        EntityVersion(0)
    with pytest.raises(ValueError):
        EntityVersion(-1)
    assert EntityVersion(1) == 1


def test_discovery_state_is_explicit_composable_and_distinct_from_intent():
    state = DiscoveryState(
        candidate_id=CandidateId("candidate-1"),
        enabled=True,
        allow_compatible_opportunities=True,
        ask_before_reveal=True,
        anonymous_only=True,
        preferences_version=EntityVersion(2),
        updated_at=datetime.utcnow(),
    )
    assert state.enabled is True
    assert state.allow_compatible_opportunities is True
    assert state.ask_before_reveal is True
    assert state.anonymous_only is True
    assert "intent" not in {field.name for field in fields(DiscoveryState)}
    assert "discovery_is_not_intent" in SEPARATION_INVARIANTS
    assert "paused_search_can_coexist_with_enabled_discovery" in SEPARATION_INVARIANTS


def test_disabled_discovery_cannot_enable_subcontrols():
    with pytest.raises(ValueError):
        DiscoveryState(
            candidate_id=CandidateId("candidate-1"),
            enabled=False,
            allow_compatible_opportunities=True,
            ask_before_reveal=False,
            anonymous_only=False,
            preferences_version=EntityVersion(1),
            updated_at=datetime.utcnow(),
        )


def test_role_dna_and_opportunity_spec_versions_are_pinned_separately():
    snapshot = StreamRequirementSnapshot(
        role_dna=RoleDNARef(RoleDNAId("role-1"), EntityVersion(3)),
        opportunity_spec=OpportunitySpecificationRef(OpportunitySpecId("opp-1"), EntityVersion(7)),
        requirement_version=EntityVersion(4),
        captured_at=datetime.utcnow(),
    )
    assert snapshot.role_dna.version == 3
    assert snapshot.opportunity_spec.version == 7
    assert snapshot.role_dna.version != snapshot.opportunity_spec.version


def test_professional_match_contract_has_no_permission_or_intent_fields():
    names = {field.name for field in fields(ProfessionalMatchRef)}
    assert "permission" not in names
    assert "intent" not in names
    assert "opportunity_fit" not in names


def test_opportunity_fit_depends_on_preferences_not_profile_contract():
    fit = OpportunityFitRef(
        candidate_id=CandidateId("candidate-1"),
        opportunity_spec=OpportunitySpecificationRef(OpportunitySpecId("opp-1"), EntityVersion(1)),
        candidate_preferences_version=EntityVersion(9),
        engine_version=EngineVersion("fit-v1"),
        computed_at=datetime.utcnow(),
    )
    assert fit.candidate_preferences_version == 9
    assert "candidate_profile_version" not in {field.name for field in fields(OpportunityFitRef)}


def test_grant_scopes_keep_cv_distinct_and_expiry_denies_immediately():
    now = datetime.utcnow()
    grant = GrantContract(
        grant_id=GrantId("grant-1"),
        candidate_id=CandidateId("candidate-1"),
        grantee_organization_id=OrganizationId("org-1"),
        scopes=(GrantScope.PROFILE_PREVIEW, GrantScope.CV),
        document_id=DocumentId("cv-1"),
        issued_at=now - timedelta(days=2),
        expires_at=now - timedelta(seconds=1),
        consent_policy_version=ConsentPolicyVersion("consent-v1"),
    )
    assert GrantScope.PROFILE_PREVIEW != GrantScope.CV
    assert grant.is_active_at(now) is False
    assert "ttl_cleanup_is_not_authorization" in DATA_INVARIANTS


def test_grant_requires_scope_and_cv_requires_specific_document():
    now = datetime.utcnow()
    with pytest.raises(ValueError):
        GrantContract(
            grant_id=GrantId("grant-empty"),
            candidate_id=CandidateId("candidate-1"),
            grantee_organization_id=OrganizationId("org-1"),
            scopes=(),
            issued_at=now,
            consent_policy_version=ConsentPolicyVersion("consent-v1"),
        )
    with pytest.raises(ValueError):
        GrantContract(
            grant_id=GrantId("grant-cv"),
            candidate_id=CandidateId("candidate-1"),
            grantee_organization_id=OrganizationId("org-1"),
            scopes=(GrantScope.CV,),
            issued_at=now,
            consent_policy_version=ConsentPolicyVersion("consent-v1"),
        )


def test_grant_rejects_invalid_temporal_bounds():
    now = datetime.utcnow()
    with pytest.raises(ValueError):
        GrantContract(
            grant_id=GrantId("grant-expiry"),
            candidate_id=CandidateId("candidate-1"),
            grantee_organization_id=OrganizationId("org-1"),
            scopes=(GrantScope.CONTACT,),
            issued_at=now,
            expires_at=now,
            consent_policy_version=ConsentPolicyVersion("consent-v1"),
        )


def test_recruiter_context_distinguishes_requesting_org_hiring_company_and_mandate():
    ctx = RecruitingActorContext(
        recruiter_user_id=RecruiterUserId("user-1"),
        requesting_organization_id=OrganizationId("agency-1"),
        hiring_company_id=HiringCompanyId("company-1"),
        mandate_id=None,
    )
    assert ctx.requesting_organization_id != ctx.hiring_company_id


def test_policy_decisions_are_explainable_and_permission_versions_consent():
    now = datetime.utcnow()
    trust = TrustDecision(
        allowed=False,
        reason_codes=("RECRUITER_NOT_VERIFIED",),
        policy_version=PolicyVersion("trust-v1"),
        evaluated_at=now,
    )
    permission = PermissionDecision(
        allowed=False,
        reason_codes=("DISCOVERY_DISABLED",),
        policy_version=PolicyVersion("permission-v1"),
        consent_policy_version=ConsentPolicyVersion("consent-v2"),
        evaluated_at=now,
    )
    assert trust.allowed is False
    assert permission.allowed is False
    assert permission.consent_policy_version == "consent-v2"
    assert trust.reason_codes != permission.reason_codes


def test_policy_decision_requires_reason_code():
    with pytest.raises(ValueError):
        TrustDecision(
            allowed=True,
            reason_codes=(),
            policy_version=PolicyVersion("trust-v1"),
            evaluated_at=datetime.utcnow(),
        )


def test_intent_subject_requires_exactly_one_identity_form():
    direct = IntentSubject(candidate_id=CandidateId("candidate-1"))
    pseudo = IntentSubject(pseudonymous_id=PseudonymousCandidateId("pseudo-1"))
    assert direct.candidate_id is not None
    assert pseudo.pseudonymous_id is not None
    with pytest.raises(ValueError):
        IntentSubject()
    with pytest.raises(ValueError):
        IntentSubject(
            candidate_id=CandidateId("candidate-1"),
            pseudonymous_id=PseudonymousCandidateId("pseudo-1"),
        )


def test_intent_event_supports_pseudonymous_subject_and_governed_origins():
    now = datetime.utcnow()
    event = TalentIntentEvent(
        event_id=IntentEventId("event-1"),
        schema_version=SchemaVersion("intent-event-v1"),
        subject=IntentSubject(pseudonymous_id=PseudonymousCandidateId("pseudo-1")),
        intent_kind=IntentKind.ROLE,
        origin=IntentOrigin.INFERRED,
        event_type=IntentEventType("role_interest_inferred"),
        occurred_at=now,
        created_at=now,
        source_type=IntentSourceType("internal_aggregate"),
    )
    assert event.subject.pseudonymous_id == "pseudo-1"
    assert {origin.value for origin in IntentOrigin} == {"declared", "observed", "inferred"}
    event_fields = {field.name for field in fields(TalentIntentEvent)}
    assert "source_organization_id" in event_fields
    assert "source_campaign_id" in event_fields
    assert "billing_amount" not in event_fields
    assert "cpc" not in event_fields
    assert "candidate_id" not in event_fields


def test_profile_and_preferences_are_separate_versioned_references():
    profile = CandidateProfileRef(CandidateProfileId("profile-1"), CandidateId("candidate-1"), EntityVersion(2))
    prefs = CandidatePreferencesRef(CandidatePreferencesId("prefs-1"), CandidateId("candidate-1"), EntityVersion(5))
    assert profile.candidate_id == prefs.candidate_id
    assert profile.version != prefs.version


def test_intent_kind_preserves_job_role_company_market_dimensions():
    assert {kind.value for kind in IntentKind} == {"job", "role", "company", "market"}
    assert "company_intent_is_distinct_from_role_intent" in SEPARATION_INVARIANTS


def test_mandatory_cross_company_and_interest_invariants_are_frozen():
    required = {
        "application_to_company_a_is_not_authorization_for_company_b",
        "absence_of_observed_intent_is_not_absence_of_potential_interest",
        "company_intent_is_distinct_from_role_intent",
        "company_intent_is_not_automatically_competitive_signal",
        "discovery_pool_supports_opt_in_without_recent_activity",
        "specific_company_exclusions_apply_before_exposure",
    }
    assert required.issubset(set(ALL_INVARIANTS))


def test_privacy_source_protection_and_anti_opaque_score_invariants_are_frozen():
    assert "anonymous_talent_requires_anti_reidentification_policy" in PRIVACY_INVARIANTS
    assert "no_precise_competitor_activity_exposure" in CROSS_OFFER_INVARIANTS
    assert "match_intent_trust_permission_must_not_be_merged_into_opaque_score" in DATA_INVARIANTS
    assert "no_broad_recruiter_cv_acl_bypass" in AUTHORIZATION_INVARIANTS


def test_all_invariants_are_unique():
    assert len(ALL_INVARIANTS) == len(set(ALL_INVARIANTS))
