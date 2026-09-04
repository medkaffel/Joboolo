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
        # Return all rows deliberately: domain revalidation must be authoritative.
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


def pref_doc(*, enabled=True, allow=True, ask=False, anonymous=False, excluded=(), current=None):
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
        "updated_at": NOW,
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


def grant_doc(*, candidate="c1", organization="org1", stream="stream1", scopes=("profile_preview",), document=None,
              issued_at=None, expires_at=None, revoked_at=None):
    doc = {
        "_id": "g1",
        "grant_id": "g1",
        "candidate_id": candidate,
        "grantee_organization_id": organization,
        "scopes": list(scopes),
        "stream_id": stream,
        "issued_at": NOW - timedelta(hours=1) if issued_at is None else issued_at,
        "consent_policy_version": "accepted-intro-v1",
    }
    if document is not None:
        doc["document_id"] = document
    if expires_at is not None:
        doc["expires_at"] = expires_at
    if revoked_at is not None:
        doc["revoked_at"] = revoked_at
    return doc


def seed(s, *, requesting="org1", hiring="org1", requesting_legacy="company1", hiring_legacy="company1"):
    s.repo.preferences["c1"] = pref_doc()
    s.repo.organizations[requesting] = org_doc(requesting, legacy=requesting_legacy)
    if hiring != requesting:
        s.repo.organizations[hiring] = org_doc(hiring, legacy=hiring_legacy)


def assert_reason(decision, reason):
    assert decision.reason_codes == (reason.value,)


def test_request_context_and_grant_rehydration_reject_bad_identifiers():
    with pytest.raises(ValueError):
        PermissionRequestContext(
            candidate_id=None,
            action=PermissionAction.REQUEST_INTRODUCTION,
            recruiting_actor=RecruitingActorContext(
                RecruiterUserId("r1"), OrganizationId("org1"), HiringCompanyId("org1"), None
            ),
            stream_id=TalentStreamId("stream1"),
        )
    bad = grant_doc(); bad["stream_id"] = None
    with pytest.raises(ValueError):
        grant_from_document(bad)


def test_request_context_requires_actor_and_exact_cv_document_contract():
    with pytest.raises(ValueError):
        PermissionRequestContext(CandidateId("c1"), PermissionAction.REQUEST_INTRODUCTION, None, TalentStreamId("s"))
    with pytest.raises(ValueError):
        context(PermissionAction.ACCESS_CV)
    with pytest.raises(ValueError):
        context(PermissionAction.REVEAL_IDENTITY, document="cv1")
    with pytest.raises(ValueError):
        PermissionRequestContext(
            CandidateId("c1"), PermissionAction.ACCESS_CV,
            RecruitingActorContext(RecruiterUserId("r1"), OrganizationId("org1"), HiringCompanyId("org1"), None),
            TalentStreamId("stream1"), document_id=123,
        )


@pytest.mark.asyncio
async def test_missing_preferences_denies_discovery_but_not_explicit_active_grant():
    s = service(); s.repo.organizations["org1"] = org_doc("org1")
    intro = await s.evaluate(context(), evaluated_at=NOW)
    assert not intro.allowed
    assert_reason(intro, PermissionReasonCode.CANDIDATE_PREFERENCES_NOT_FOUND)

    s.repo.grants = [grant_doc()]
    reveal = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert reveal.allowed
    assert_reason(reveal, PermissionReasonCode.ACTIVE_SCOPED_GRANT_GRANTED)


@pytest.mark.asyncio
async def test_present_malformed_preferences_block_intro_and_active_grant_fail_closed():
    s = service(); seed(s); s.repo.preferences["c1"]["discovery"]["enabled"] = "true"; s.repo.grants = [grant_doc()]
    for request in (context(), context(PermissionAction.REVEAL_PROFILE_PREVIEW)):
        decision = await s.evaluate(request, evaluated_at=NOW)
        assert not decision.allowed
        assert_reason(decision, PermissionReasonCode.CANDIDATE_PREFERENCES_INVALID)


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,allow,reason", [
    (False, False, PermissionReasonCode.DISCOVERY_DISABLED),
    (True, False, PermissionReasonCode.COMPATIBLE_OPPORTUNITIES_NOT_ALLOWED),
])
async def test_discovery_requires_explicit_current_authorization(enabled, allow, reason):
    s = service(); seed(s); s.repo.preferences["c1"] = pref_doc(enabled=enabled, allow=allow)
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, reason)


@pytest.mark.asyncio
async def test_paused_search_discovery_allows_intro_but_ask_anonymous_never_reveal():
    s = service(); seed(s); s.repo.preferences["c1"] = pref_doc(ask=True, anonymous=True)
    intro = await s.evaluate(context(), evaluated_at=NOW)
    identity = await s.evaluate(context(PermissionAction.REVEAL_IDENTITY), evaluated_at=NOW)
    assert intro.allowed
    assert_reason(intro, PermissionReasonCode.DISCOVERY_PERMISSION_GRANTED)
    assert not identity.allowed
    assert_reason(identity, PermissionReasonCode.ACTIVE_SCOPED_GRANT_REQUIRED)


@pytest.mark.asyncio
@pytest.mark.parametrize("requesting,hiring,requesting_legacy,hiring_legacy,excluded,current", [
    ("org1", "org1", "company1", "company1", ("org1",), None),
    ("agency", "client", "agency-co", "client-co", ("client-co",), None),
    ("agency", "client", "agency-co", "client-co", ("agency-co",), None),
    ("agency", "client", "agency-co", "client-co", (), "client-co"),
])
async def test_requesting_hiring_current_employer_and_company_exclusions_block(
    requesting, hiring, requesting_legacy, hiring_legacy, excluded, current
):
    s = service(); seed(s, requesting=requesting, hiring=hiring, requesting_legacy=requesting_legacy, hiring_legacy=hiring_legacy)
    s.repo.preferences["c1"] = pref_doc(excluded=excluded, current=current)
    decision = await s.evaluate(context(requesting=requesting, hiring=hiring), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_ORGANIZATION_EXCLUSION)
    assert "employer" not in decision.reason_codes[0]


@pytest.mark.asyncio
async def test_exclusion_namespace_ambiguity_fails_closed_only_when_exclusions_exist():
    s = service(); seed(s, requesting_legacy=None)
    s.repo.preferences["c1"] = pref_doc(excluded=("legacy-x",))
    blocked = await s.evaluate(context(), evaluated_at=NOW)
    assert not blocked.allowed
    assert_reason(blocked, PermissionReasonCode.ORGANIZATION_EXCLUSION_CONTEXT_UNRESOLVED)

    s.repo.preferences["c1"] = pref_doc()
    allowed = await s.evaluate(context(), evaluated_at=NOW)
    assert allowed.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["missing", "identity", "scalar"])
async def test_missing_or_malformed_organization_fails_closed(mutation):
    s = service(); seed(s)
    if mutation == "missing":
        del s.repo.organizations["org1"]
    elif mutation == "identity":
        s.repo.organizations["org1"] = org_doc("org1", malformed=True)
    else:
        s.repo.organizations["org1"]["legal_name"] = 123
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.ORGANIZATION_EXCLUSION_CONTEXT_UNRESOLVED)


@pytest.mark.asyncio
async def test_unverified_organization_does_not_merge_permission_with_trust():
    s = service(); seed(s)  # org fixture is structurally valid but UNVERIFIED
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert decision.allowed
    assert_reason(decision, PermissionReasonCode.DISCOVERY_PERMISSION_GRANTED)


@pytest.mark.asyncio
async def test_profile_grant_is_scope_specific_and_discovery_disable_does_not_revoke_it():
    s = service(); seed(s); s.repo.preferences["c1"] = pref_doc(enabled=False, allow=False); s.repo.grants = [grant_doc()]
    profile = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    identity = await s.evaluate(context(PermissionAction.REVEAL_IDENTITY), evaluated_at=NOW)
    assert profile.allowed
    assert not identity.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("patch", [
    {"candidate_id": "other"},
    {"grantee_organization_id": "other-org"},
    {"stream_id": "other-stream"},
    {"scopes": ["contact"]},
])
async def test_wrong_candidate_org_stream_or_scope_never_authorizes(patch):
    s = service(); seed(s); grant = grant_doc(); grant.update(patch); s.repo.grants = [grant]
    decision = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.ACTIVE_SCOPED_GRANT_REQUIRED)


@pytest.mark.asyncio
async def test_cv_requires_exact_document_and_does_not_imply_profile():
    s = service(); seed(s); s.repo.grants = [grant_doc(scopes=("cv",), document="cv1")]
    exact = await s.evaluate(context(PermissionAction.ACCESS_CV, document="cv1"), evaluated_at=NOW)
    wrong = await s.evaluate(context(PermissionAction.ACCESS_CV, document="cv2"), evaluated_at=NOW)
    profile = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert exact.allowed
    assert not wrong.allowed
    assert not profile.allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("grant", [
    grant_doc(expires_at=NOW),
    grant_doc(revoked_at=NOW),
    grant_doc(issued_at=NOW + timedelta(seconds=1)),
])
async def test_expired_revoked_or_future_grant_denies_immediately(grant):
    s = service(); seed(s); s.repo.grants = [grant]
    decision = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.ACTIVE_SCOPED_GRANT_REQUIRED)


@pytest.mark.asyncio
async def test_new_current_exclusion_overrides_existing_active_grant():
    s = service(); seed(s); s.repo.preferences["c1"] = pref_doc(excluded=("company1",)); s.repo.grants = [grant_doc()]
    decision = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_ORGANIZATION_EXCLUSION)


def test_bson_naive_datetimes_normalize_to_utc_only_at_rehydration_boundary():
    grant = grant_from_document(grant_doc(
        issued_at=(NOW - timedelta(hours=1)).replace(tzinfo=None),
        expires_at=(NOW + timedelta(hours=1)).replace(tzinfo=None),
    ))
    assert grant.issued_at.tzinfo is timezone.utc
    assert grant.expires_at.tzinfo is timezone.utc
    assert grant.is_active_at(NOW)


@pytest.mark.asyncio
async def test_malformed_grant_is_ignored_and_preferences_identity_is_strict():
    s = service(); seed(s)
    bad = grant_doc(); bad["_id"] = "mismatch"; s.repo.grants = [bad]
    decision = await s.evaluate(context(PermissionAction.REVEAL_PROFILE_PREVIEW), evaluated_at=NOW)
    assert not decision.allowed

    s.repo.preferences["c1"]["_id"] = "wrong-pref-id"
    decision = await s.evaluate(context(), evaluated_at=NOW)
    assert not decision.allowed
    assert_reason(decision, PermissionReasonCode.CANDIDATE_PREFERENCES_INVALID)


def test_policy_consent_and_evaluation_time_are_strict():
    db = SimpleNamespace(candidate_preferences=None, organizations=None, talent_stream_grants=None)
    for policy, consent in (("", CONSENT), (POLICY, ""), (None, CONSENT), (POLICY, None)):
        with pytest.raises(ValueError):
            PermissionService(db, policy_version=policy, consent_policy_version=consent)


@pytest.mark.asyncio
async def test_evaluated_at_must_be_timezone_aware():
    s = service(); seed(s)
    with pytest.raises(ValueError):
        await s.evaluate(context(), evaluated_at=NOW.replace(tzinfo=None))


def test_a9_has_no_trust_intent_match_click_favorite_or_application_authority():
    root = Path(__file__).parents[1]
    service_source = (root / "domains" / "permissions" / "service.py").read_text()
    repository_source = (root / "domains" / "permissions" / "repository.py").read_text()
    forbidden = (
        "RecruitingTrustService", "evaluate_recruiting_actor_trust", "talent_intent",
        "professional_match", "opportunity_fit", "favorites", "saved_jobs", "clicks", "applications",
    )
    assert all(token not in service_source for token in forbidden)
    assert all(name in repository_source for name in ("candidate_preferences", "organizations", "talent_stream_grants"))
    assert all(name not in repository_source for name in ("users", "recruiter_verifications", "recruiting_mandates"))


def test_migration_preflight_is_strict_and_has_no_ttl_or_backfill():
    source = (Path(__file__).parents[1] / "scripts" / "migrate_ts_a9_permission_indexes.py").read_text()
    required = (
        '"$type": "array"', '"$type": "date"', '"document_id": ""', '"$setUnion"',
        '"$lte": ["$expires_at", "$issued_at"]', '"$lt": ["$revoked_at", "$issued_at"]',
        "candidate_id", "grantee_organization_id", "stream_id", "document_id", "no grant backfill",
    )
    assert all(token in source for token in required)
    assert "expireAfterSeconds" not in source
    assert "TTL" in source
