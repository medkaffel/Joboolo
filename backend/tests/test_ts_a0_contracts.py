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
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
)
from domains.shared.versioning import ConsentPolicyVersion, EngineVersion, EntityVersion, PolicyVersion
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
from domains.talent_stream.events import IntentKind, IntentOrigin, TalentIntentEvent
from domains.talent_stream.invariants import DATA_INVARIANTS, SEPARATION_INVARIANTS


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


def test_cv_scope_requires_specific_document():
    with pytest.raises(ValueError):
        GrantContract(
            grant_id=GrantId("grant-1"),
            candidate_id=CandidateId("candidate-1"),
            grantee_organization_id=OrganizationId("org-1"),
            scopes=(GrantScope.CV,),
            issued_at=datetime.utcnow(),
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


def test_policy_decisions_are_explainable_and_versioned():
    now = datetime.utcnow()
    trust = TrustDecision(False, ("RECRUITER_NOT_VERIFIED",), PolicyVersion("trust-v1"), now)
    permission = PermissionDecision(False, ("DISCOVERY_DISABLED",), PolicyVersion("permission-v1"), now)
    assert trust.allowed is False
    assert permission.allowed is False
    assert trust.reason_codes != permission.reason_codes


def test_intent_event_supports_declared_observed_and_inferred_origins():
    assert {origin.value for origin in IntentOrigin} == {"declared", "observed", "inferred"}
    event_fields = {field.name for field in fields(TalentIntentEvent)}
    assert "source_organization_id" in event_fields
    assert "source_campaign_id" in event_fields
    assert "billing_amount" not in event_fields
    assert "cpc" not in event_fields


def test_profile_and_preferences_are_separate_versioned_references():
    profile = CandidateProfileRef(CandidateProfileId("profile-1"), CandidateId("candidate-1"), EntityVersion(2))
    prefs = CandidatePreferencesRef(CandidatePreferencesId("prefs-1"), CandidateId("candidate-1"), EntityVersion(5))
    assert profile.candidate_id == prefs.candidate_id
    assert profile.version != prefs.version


def test_intent_kind_preserves_job_role_company_market_dimensions():
    assert {kind.value for kind in IntentKind} == {"job", "role", "company", "market"}
