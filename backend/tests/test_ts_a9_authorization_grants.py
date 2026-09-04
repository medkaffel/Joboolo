from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from domains.permissions.models import (
    PermissionAction,
    PermissionReasonCode,
    PermissionRequestContext,
    grant_from_document,
)
from domains.permissions.service import PermissionService
from domains.shared.ids import (
    CandidateId,
    DocumentId,
    HiringCompanyId,
    OrganizationId,
    RecruiterUserId,
    TalentStreamId,
)
from domains.shared.versioning import ConsentPolicyVersion, PolicyVersion
from domains.talent_stream.contracts import RecruitingActorContext

NOW = datetime(2026, 9, 5, 0, 30, tzinfo=timezone.utc)
POLICY = PolicyVersion("permission-v1")
CONSENT = ConsentPolicyVersion("candidate-discovery-policy-v1")


class FakeRepo:
    def __init__(self):
        self.preferences = {}
        self.organizations = {}
        self.grants = []

    async def get_candidate_preferences(self, candidate_id):
        return self.preferences.get(candidate_id)

    async def get_organization(self, organization_id):
        return self.organizations.get(organization_id)

    async def find_grants(self, candidate_id, organization_id, stream_id, required_scope, document_id=None):
        # Deliberately return all grants so service/engine revalidation is tested,
        # not merely the fake query behavior.
        return list(self.grants)


def service():
    db = SimpleNamespace(candidate_preferences=None, organizations=None, talent_stream_grants=None)
    instance = PermissionService(db, policy_version=POLICY, consent_policy_version=CONSENT)
    instance.repo = FakeRepo()
    return instance


def context(action=PermissionAction.REQUEST_INTRODUCTION, *, requesting="org1", hiring="org1", document=None):
    return PermissionRequestContext(
        candidate_id=CandidateId("c1"),
        action=action,
        recruiting_actor=RecruitingActorContext(
            recruiter_user_id=RecruiterUserId("r1"),
            requesting_organization_id=OrganizationId(requesting),
            hiring_company_id=HiringCompanyId(hiring),
            mandate_id=None,
        ),
        stream_id=TalentStreamId("stream1"),
        document_id=None if document is None else DocumentId(document),
    )


def pref_doc(*, enabled=True, allow=True, ask=False, anonymous=False, excluded=(), current=None, updated_at=NOW):
    return {
        "_id": "candidate_preferences:c1",
        "candidate_id": "c1",
        "version": 3,
        "search_state": "paused",
        "discovery": {
            "enabled": enabled,
            "allow_compatible_opportunities": allow,
            "ask_before_reveal": ask,
            "anonymous_only": anonymous,
        },
        "excluded_company_ids": list(excluded),
        "current_employer_company_id": current,
        "updated_at": updated_at,
    }


def org_doc(org_id, *, legacy="company1", malformed=False):
    doc = {
        "_id": org_id,
        "organization_id": org_id,
        "version": 2,
        "legal_name": f"Organization {org_id}",
        "verification_state": "unverified",
        "created_at": NOW - timedelta(days=2),
        "updated_at": NOW - timedelta(days=1),
        "legacy_company_id": legacy,
        "verification_policy_version": None,
        "verification_reason_codes": [],
        "verification_evidence_refs": [],
        "verification_actor_id": None,
        "verification_decided_at": None,
    }
    if malformed:
        doc["organization_id"] = "different-org"
    return doc


def grant_doc(
    *,
    grant_id="g1",
    candidate="c1",
    organization="org1",
    stream="stream1",
    scopes=("profile_preview",),
    document=None,
    issued_at=None,
    expires_at=None,
    revoked_at=None,
    consent="accepted-intro-v1",
):
    issued_at = NOW - timedelta(hours=1) if issued_at is None else issued_at
    doc = {
        "_id": grant_id,
        "grant_id": grant_id,
        "candidate_id": candidate,
        "grantee_organization_id": organization,
        "scopes": list(scopes),
        "stream_id": stream,
        "issued_at": issued_at,
        "consent_policy_version": consent,
    }
    if document is not None:
        doc["document_id"] = document
    if expires_at is not None:
        doc["expires_at"] = expires_at
    if revoked_at is not None:
        doc["revoked_at"] = revoked_at
    return doc


def seed_base(s, *, requesting="org1", hiring="org1", requesting_legacy="company1", hiring_legacy="company1"):
    s.repo.preferences["c1"] = pref_doc()
    s.repo.organizations[requesting] = org_doc(requesting, legacy=requesting_legacy)
    if hiring != requesting:
        s.repo.organizations[hiring] = org_doc(hiring, legacy=hiring_legacy)


def assert_reason(decision, reason):
    assert decision.reason_codes == (reason.value,)



def test_non_string_or_none_identifiers_fail_closed_in_request_and_rehydration():
    with pytest.raises(ValueError):
        PermissionRequestContext(
            candidate_id=None,
            action=PermissionAction.REQUEST_INTRODUCTION,
            recruiting_actor=RecruitingActorContext(
                recruiter_user_id=RecruiterUserId("r1"),
                requesting_organization_id=OrganizationId("org1"),
                hiring_company_id=HiringCompanyId("org1"),
                mandate_id=None,
            ),
            stream_id=TalentStreamId("stream1"),
        )
    bad = grant_doc()
    bad["stream_id"] = None
    with pytest.raises(ValueError):
        grant_from_document(bad)


@pytest.mark.asyncio
async def test_non_string_candidate_preferences_identity_fails_closed():
    s = service(); seed_base(s)
    s.repo.preferences["c1"]["candidate_id"] = None
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_PREFERENCES_INVALID)


def test_request_context_requires_real_recruiting_actor():
    with pytest.raises(ValueError):
        PermissionRequestContext(
            candidate_id=CandidateId("c1"),
            action=PermissionAction.REQUEST_INTRODUCTION,
            recruiting_actor=None,
            stream_id=TalentStreamId("stream1"),
        )

def test_cv_request_requires_exact_document_id_and_non_cv_rejects_document_id():
    with pytest.raises(ValueError):
        context(PermissionAction.ACCESS_CV)
    with pytest.raises(ValueError):
        context(PermissionAction.REVEAL_IDENTITY, document="cv1")


@pytest.mark.asyncio
async def test_missing_preferences_denies_introduction():
    s = service()
    s.repo.organizations["org1"] = org_doc("org1")
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_PREFERENCES_NOT_FOUND)


@pytest.mark.asyncio
async def test_disabled_discovery_denies_introduction():
    s = service(); seed_base(s)
    s.repo.preferences["c1"] = pref_doc(enabled=False, allow=False)
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.DISCOVERY_DISABLED)


@pytest.mark.asyncio
async def test_compatible_opportunities_must_be_explicitly_allowed():
    s = service(); seed_base(s)
    s.repo.preferences["c1"] = pref_doc(enabled=True, allow=False)
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.COMPATIBLE_OPPORTUNITIES_NOT_ALLOWED)


@pytest.mark.asyncio
async def test_paused_search_with_enabled_discovery_can_allow_introduction():
    s = service(); seed_base(s)
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert decision.allowed
    assert_reason(decision, PermissionReasonCode.DISCOVERY_PERMISSION_GRANTED)


@pytest.mark.asyncio
async def test_ask_before_reveal_and_anonymous_only_do_not_block_intro_but_never_grant_reveal():
    s = service(); seed_base(s)
    s.repo.preferences["c1"] = pref_doc(ask=True, anonymous=True)
    intro = await s.evaluate(context(), evaluated_at=NOW)
    reveal = await s.evaluate(context(PermissionAction.REVEAL_IDENTITY), evaluated_at=NOW)
    assert intro.allowed
    assert not reveal.allowed
    assert_reason(reveal, PermissionReasonCode.ACTIVE_SCOPED_GRANT_REQUIRED)


@pytest.mark.asyncio
async def test_selected_company_exclusion_blocks_requesting_organization_by_canonical_id():
    s = service(); seed_base(s)
    s.repo.preferences["c1"] = pref_doc(excluded=("org1",))
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_ORGANIZATION_EXCLUSION)


@pytest.mark.asyncio
async def test_selected_company_exclusion_blocks_hiring_company_by_legacy_mapping():
    s = service(); seed_base(s, requesting="agency", hiring="client", requesting_legacy="agency-co", hiring_legacy="client-co")
    s.repo.preferences["c1"] = pref_doc(excluded=("client-co",))
    decision = await s.evaluate(context(requesting="agency", hiring="client"), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_ORGANIZATION_EXCLUSION)


@pytest.mark.asyncio
async def test_current_employer_exclusion_blocks_hiring_company_without_specific_reason_leak():
    s = service(); seed_base(s, requesting="agency", hiring="client", requesting_legacy="agency-co", hiring_legacy="client-co")
    s.repo.preferences["c1"] = pref_doc(current="client-co")
    decision = await s.evaluate(context(requesting="agency", hiring="client"), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_ORGANIZATION_EXCLUSION)
    assert "current" not in decision.reason_codes[0]
    assert "employer" not in decision.reason_codes[0]


@pytest.mark.asyncio
async def test_agency_requesting_organization_can_itself_be_excluded():
    s = service(); seed_base(s, requesting="agency", hiring="client", requesting_legacy="agency-co", hiring_legacy="client-co")
    s.repo.preferences["c1"] = pref_doc(excluded=("agency-co",))
    decision = await s.evaluate(context(requesting="agency", hiring="client"), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_ORGANIZATION_EXCLUSION)


@pytest.mark.asyncio
async def test_exclusion_namespace_ambiguity_fails_closed_when_legacy_bridge_missing():
    s = service(); seed_base(s, requesting_legacy=None)
    s.repo.preferences["c1"] = pref_doc(excluded=("some-legacy-company",))
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.ORGANIZATION_EXCLUSION_CONTEXT_UNRESOLVED)


@pytest.mark.asyncio
async def test_missing_legacy_bridge_is_not_blocking_when_candidate_has_no_exclusions():
    s = service(); seed_base(s, requesting_legacy=None)
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert decision.allowed


@pytest.mark.asyncio
async def test_missing_or_malformed_organization_fails_closed():
    s = service(); seed_base(s)
    del s.repo.organizations["org1"]
    missing = await s.evaluate(context(), evaluated_at=NOW)
    assert not missing.allowed
    assert_reason(missing, PermissionReasonCode.ORGANIZATION_EXCLUSION_CONTEXT_UNRESOLVED)

    s.repo.organizations["org1"] = org_doc("org1", malformed=True)
    malformed = await s.evaluate(context(), evaluated_at=NOW)
    assert not malformed.allowed
    assert_reason(malformed, PermissionReasonCode.ORGANIZATION_EXCLUSION_CONTEXT_UNRESOLVED)



@pytest.mark.asyncio
async def test_malformed_organization_scalar_type_denies_instead_of_crashing():
    s = service(); seed_base(s)
    s.repo.organizations["org1"]["legal_name"] = 123
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.ORGANIZATION_EXCLUSION_CONTEXT_UNRESOLVED)

@pytest.mark.asyncio
async def test_structurally_valid_but_unverified_organization_does_not_turn_permission_into_trust():
    s = service(); seed_base(s)
    # org_doc is intentionally UNVERIFIED. Permission can be ALLOW while Trust remains a separate gate.
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert decision.allowed
    assert_reason(decision, PermissionReasonCode.DISCOVERY_PERMISSION_GRANTED)


@pytest.mark.asyncio
async def test_active_profile_grant_allows_only_requested_profile_scope():
    s = service(); seed_base(s)
    s.repo.preferences["c1"] = pref_doc(enabled=False, allow=False)
    s.repo.grants = [grant_doc(scopes=("profile_preview",))]
    profile = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    identity = await s.evaluate(context(PermissionAction.REVEAL_IDENTITY), evaluated_at=NOW)
    assert profile.allowed
    assert_reason(profile, PermissionReasonCode.ACTIVE_SCOPED_GRANT_GRANTED)
    assert not identity.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [
    {"candidate_id": "other"},
    {"grantee_organization_id": "other-org"},
    {"stream_id": "other-stream"},
    {"scopes": ["contact"]},
])
async def test_wrong_grant_candidate_org_stream_or_scope_denies(patch):
    s = service(); seed_base(s)
    grant = grant_doc()
    grant.update(patch)
    s.repo.grants = [grant]
    decision = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.ACTIVE_SCOPED_GRANT_REQUIRED)


@pytest.mark.asyncio
async def test_exact_cv_document_grant_allows_cv_only():
    s = service(); seed_base(s)
    s.repo.grants = [grant_doc(scopes=("cv",), document="cv1")]
    allowed = await s.evaluate(context(PermissionAction.ACCESS_CV, document="cv1"), evaluated_at=NOW)
    wrong_doc = await s.evaluate(context(PermissionAction.ACCESS_CV, document="cv2"), evaluated_at=NOW)
    profile = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert allowed.allowed
    assert not wrong_doc.allowed
    assert not profile.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("grant", [
    grant_doc(expires_at=NOW),
    grant_doc(revoked_at=NOW),
    grant_doc(issued_at=NOW + timedelta(seconds=1)),
])
async def test_expired_revoked_or_future_grant_denies_immediately(grant):
    s = service(); seed_base(s)
    s.repo.grants = [grant]
    decision = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.ACTIVE_SCOPED_GRANT_REQUIRED)


@pytest.mark.asyncio
async def test_disabling_discovery_does_not_silently_revoke_existing_scoped_grant():
    s = service(); seed_base(s)
    s.repo.preferences["c1"] = pref_doc(enabled=False, allow=False)
    s.repo.grants = [grant_doc()]
    decision = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert decision.allowed


@pytest.mark.asyncio
async def test_new_exclusion_blocks_even_an_otherwise_active_grant():
    s = service(); seed_base(s)
    s.repo.preferences["c1"] = pref_doc(excluded=("company1",))
    s.repo.grants = [grant_doc()]
    decision = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_ORGANIZATION_EXCLUSION)


def test_naive_bson_grant_datetimes_are_normalized_to_utc_at_rehydration_boundary():
    naive = NOW.replace(tzinfo=None)
    grant = grant_from_document(grant_doc(issued_at=naive, expires_at=(NOW + timedelta(hours=1)).replace(tzinfo=None)))
    assert grant.issued_at.tzinfo is timezone.utc
    assert grant.expires_at.tzinfo is timezone.utc
    assert grant.is_active_at(NOW)


@pytest.mark.asyncio
async def test_malformed_preferences_fail_closed():
    s = service(); seed_base(s)
    s.repo.preferences["c1"]["discovery"]["enabled"] = "true"
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_PREFERENCES_INVALID)


@pytest.mark.asyncio
async def test_malformed_grant_is_ignored_and_cannot_authorize():
    s = service(); seed_base(s)
    bad = grant_doc()
    bad["_id"] = "mismatch"
    s.repo.grants = [bad]
    decision = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert not decision.allowed


def test_policy_and_consent_versions_must_be_nonblank_strings():
    db = SimpleNamespace(candidate_preferences=None, organizations=None, talent_stream_grants=None)
    with pytest.raises(ValueError):
        PermissionService(db, policy_version=PolicyVersion(""), consent_policy_version=CONSENT)
    with pytest.raises(ValueError):
        PermissionService(db, policy_version=POLICY, consent_policy_version=ConsentPolicyVersion(""))
    with pytest.raises(ValueError):
        PermissionService(db, policy_version=None, consent_policy_version=CONSENT)
    with pytest.raises(ValueError):
        PermissionService(db, policy_version=POLICY, consent_policy_version=None)



@pytest.mark.asyncio
async def test_candidate_preferences_id_must_match_a2_deterministic_identity():
    s = service(); seed_base(s)
    s.repo.preferences["c1"]["_id"] = "unexpected-preferences-id"
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_PREFERENCES_INVALID)


def test_cv_document_id_must_be_a_string():
    with pytest.raises(ValueError):
        PermissionRequestContext(
            candidate_id=CandidateId("c1"),
            action=PermissionAction.ACCESS_CV,
            recruiting_actor=RecruitingActorContext(
                recruiter_user_id=RecruiterUserId("r1"),
                requesting_organization_id=OrganizationId("org1"),
                hiring_company_id=HiringCompanyId("org1"),
                mandate_id=None,
            ),
            stream_id=TalentStreamId("stream1"),
            document_id=123,
        )

@pytest.mark.asyncio
async def test_evaluated_at_must_be_timezone_aware():
    s = service(); seed_base(s)
    with pytest.raises(ValueError):
        await s.evaluate(context(), evaluated_at=NOW.replace(tzinfo=None))


def test_a9_service_has_no_trust_intent_match_click_favorite_or_application_authority():
    source = (Path(__file__).parents[1] / "domains" / "permissions" / "service.py").read_text()
    forbidden = (
        "RecruitingTrustService",
        "evaluate_recruiting_actor_trust",
        "talent_intent",
        "professional_match",
        "opportunity_fit",
        "favorites",
        "saved_jobs",
        "clicks",
        "applications",
    )
    assert all(token not in source for token in forbidden)


def test_a9_repository_reads_only_preferences_organizations_and_grants():
    source = (Path(__file__).parents[1] / "domains" / "permissions" / "repository.py").read_text()
    assert "candidate_preferences" in source
    assert "organizations" in source
    assert "talent_stream_grants" in source
    assert "users" not in source
    assert "recruiter_verifications" not in source
    assert "recruiting_mandates" not in source


def test_migration_has_explicit_indexes_no_ttl_and_no_backfill():
    source = (Path(__file__).parents[1] / "scripts" / "migrate_ts_a9_permission_indexes.py").read_text()
    assert "talent_stream_grants" in source
    assert "grant_id" in source
    assert '"$type": "array"' in source
    assert '"$type": "date"' in source
    assert "candidate_id" in source
    assert "grantee_organization_id" in source
    assert "stream_id" in source
    assert "document_id" in source
    assert "expireAfterSeconds" not in source
    assert "TTL" in source
    assert "no grant backfill" in source
