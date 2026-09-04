from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from domains.privacy.engine import (
    evaluate_audit_event_retention,
    evaluate_grant_privacy,
    evaluate_grant_retention,
)
from domains.privacy.models import (
    GrantRevocationCommand,
    GrantRevocationReasonCode,
    PrivacyAuditEvent,
    PrivacyDataCategory,
    PrivacyReasonCode,
    RetentionRule,
    RetentionTerminalAction,
    RevocationAuthority,
    grant_from_document,
)
from domains.privacy.service import (
    PrivacyLifecycleConflictError,
    PrivacyLifecycleEligibilityError,
    PrivacyLifecycleService,
)
from domains.shared.ids import CandidateId, GrantId, OrganizationId, TalentStreamId
from domains.shared.versioning import ConsentPolicyVersion, PolicyVersion
from domains.talent_stream.contracts import GrantContract, GrantScope
from domains.talent_stream.decisions import PermissionDecision, PrivacyDecision, TrustDecision

NOW = datetime(2026, 9, 5, 1, 0, tzinfo=timezone.utc)
POLICY = PolicyVersion("privacy-v1")


def grant_doc(*, grant_id="g1", candidate="c1", issued_at=None, expires_at=None, revoked_at=None, scopes=("profile_preview",)):
    doc = {
        "_id": grant_id,
        "grant_id": grant_id,
        "candidate_id": candidate,
        "grantee_organization_id": "org1",
        "scopes": list(scopes),
        "stream_id": "stream1",
        "issued_at": issued_at if issued_at is not None else NOW - timedelta(days=30),
        "consent_policy_version": "consent-v1",
    }
    if expires_at is not None:
        doc["expires_at"] = expires_at
    if revoked_at is not None:
        doc["revoked_at"] = revoked_at
    return doc


def candidate_command(*, command_id="cmd1", grant_id="g1", candidate="c1"):
    return GrantRevocationCommand(
        command_id=command_id,
        grant_id=GrantId(grant_id),
        candidate_id=CandidateId(candidate),
        authority=RevocationAuthority.CANDIDATE,
        reason_code=GrantRevocationReasonCode.CONSENT_WITHDRAWN,
        policy_version=POLICY,
        actor_id=candidate,
    )


class FakeSession:
    async def __aenter__(self):
        return self
    async def __aexit__(self, exc_type, exc, tb):
        return False
    def start_transaction(self):
        return self


class FakeClient:
    def __init__(self):
        self.session = FakeSession()
    async def start_session(self):
        return self.session


class FakeRepo:
    def __init__(self):
        self.grants = {}
        self.events = {}
        self.update_calls = 0
        self.insert_calls = 0
        self.update_session = None
        self.event_session = None
        self.force_update_conflict = False

    async def get_grant(self, grant_id, session=None):
        doc = self.grants.get(grant_id)
        return None if doc is None else dict(doc)

    async def get_event_by_command_id(self, command_id, session=None):
        doc = self.events.get(command_id)
        return None if doc is None else dict(doc)

    async def revoke_grant_if_unrevoked(self, grant_id, candidate_id, effective_at, changes, session=None):
        self.update_calls += 1
        self.update_session = session
        doc = self.grants.get(grant_id)
        if doc is None or doc.get("candidate_id") != candidate_id:
            return None
        revoked_at = doc.get("revoked_at")
        if self.force_update_conflict:
            return None
        if revoked_at is not None and revoked_at <= effective_at:
            return None
        doc.update(changes)
        return dict(doc)

    async def insert_event(self, document, session=None):
        self.insert_calls += 1
        self.event_session = session
        command_id = document["command_id"]
        if command_id in self.events:
            from pymongo.errors import DuplicateKeyError
            raise DuplicateKeyError("duplicate")
        self.events[command_id] = dict(document)
        return document


def service():
    db = SimpleNamespace(talent_stream_grants=None, talent_stream_privacy_events=None)
    client = FakeClient()
    svc = PrivacyLifecycleService(db, client_provider=lambda: client)
    svc.repo = FakeRepo()
    return svc, client


def event_doc(command, occurred_at=NOW):
    return {
        "_id": f"privacy_event:{command.command_id}",
        "command_id": command.command_id,
        "grant_id": str(command.grant_id),
        "candidate_id": str(command.candidate_id),
        "authority": command.authority.value,
        "reason_code": command.reason_code.value,
        "policy_version": str(command.policy_version),
        "actor_id": command.actor_id,
        "occurred_at": occurred_at,
    }


@pytest.mark.parametrize("state,expected_allowed,expected_reason", [
    ("active", True, PrivacyReasonCode.GRANT_PRIVACY_ACTIVE),
    ("future", False, PrivacyReasonCode.GRANT_NOT_YET_ACTIVE),
    ("expired", False, PrivacyReasonCode.GRANT_EXPIRED),
    ("revoked", False, PrivacyReasonCode.GRANT_REVOKED),
])
def test_current_grant_privacy_states(state, expected_allowed, expected_reason):
    kwargs = {}
    if state == "future": kwargs["issued_at"] = NOW + timedelta(hours=1)
    if state == "expired": kwargs["expires_at"] = NOW - timedelta(minutes=1)
    if state == "revoked": kwargs["revoked_at"] = NOW - timedelta(minutes=1)
    decision = evaluate_grant_privacy(grant_from_document(grant_doc(**kwargs)), policy_version=POLICY, evaluated_at=NOW)
    assert isinstance(decision, PrivacyDecision)
    assert not isinstance(decision, (PermissionDecision, TrustDecision))
    assert decision.allowed is expected_allowed
    assert decision.reason_codes == (expected_reason.value,)


def test_privacy_uses_earliest_terminal_reason_when_expired_then_revoked():
    grant = grant_from_document(grant_doc(
        expires_at=NOW - timedelta(hours=2),
        revoked_at=NOW - timedelta(hours=1),
    ))
    decision = evaluate_grant_privacy(grant, policy_version=POLICY, evaluated_at=NOW)
    assert decision.reason_codes == (PrivacyReasonCode.GRANT_EXPIRED.value,)


def test_revocation_command_candidate_authority_is_self_scoped_and_reason_scoped():
    with pytest.raises(ValueError):
        GrantRevocationCommand("cmd", GrantId("g"), CandidateId("c1"), RevocationAuthority.CANDIDATE,
                               GrantRevocationReasonCode.CONSENT_WITHDRAWN, POLICY, "other")
    with pytest.raises(ValueError):
        GrantRevocationCommand("cmd", GrantId("g"), CandidateId("c1"), RevocationAuthority.CANDIDATE,
                               GrantRevocationReasonCode.POLICY_INVALIDATED, POLICY, "c1")


@pytest.mark.asyncio
async def test_first_revoke_updates_grant_and_writes_exactly_one_event_in_same_session():
    svc, client = service(); svc.repo.grants["g1"] = grant_doc()
    result = await svc.revoke_grant(candidate_command(), now=NOW)
    assert result.revoked_at == NOW
    assert svc.repo.update_calls == 1
    assert svc.repo.insert_calls == 1
    assert svc.repo.update_session is client.session
    assert svc.repo.event_session is client.session
    stored = svc.repo.grants["g1"]
    assert stored["revocation_command_id"] == "cmd1"
    assert stored["revocation_reason_code"] == "consent_withdrawn"
    assert "cmd1" in svc.repo.events


@pytest.mark.asyncio
async def test_same_command_retry_is_idempotent_and_keeps_original_timestamp():
    svc, _ = service(); svc.repo.grants["g1"] = grant_doc()
    first = await svc.revoke_grant(candidate_command(), now=NOW)
    second = await svc.revoke_grant(candidate_command(), now=NOW + timedelta(hours=1))
    assert second.revoked_at == first.revoked_at == NOW
    assert svc.repo.update_calls == 1
    assert svc.repo.insert_calls == 1




@pytest.mark.asyncio
async def test_idempotent_retry_fails_closed_if_event_and_grant_metadata_diverge():
    svc, _ = service(); svc.repo.grants["g1"] = grant_doc()
    await svc.revoke_grant(candidate_command(), now=NOW)
    svc.repo.grants["g1"]["revocation_actor_id"] = "tampered"
    with pytest.raises(PrivacyLifecycleConflictError):
        await svc.revoke_grant(candidate_command(), now=NOW + timedelta(minutes=1))

@pytest.mark.asyncio
async def test_command_id_reuse_with_different_payload_conflicts():
    svc, _ = service(); svc.repo.grants["g1"] = grant_doc()
    original = candidate_command()
    await svc.revoke_grant(original, now=NOW)
    changed = GrantRevocationCommand(
        command_id="cmd1", grant_id=GrantId("g1"), candidate_id=CandidateId("c1"),
        authority=RevocationAuthority.PRIVACY_ADMIN,
        reason_code=GrantRevocationReasonCode.ADMIN_CORRECTION,
        policy_version=POLICY, actor_id="admin1",
    )
    with pytest.raises(PrivacyLifecycleConflictError):
        await svc.revoke_grant(changed, now=NOW + timedelta(minutes=1))


@pytest.mark.asyncio
async def test_wrong_candidate_cannot_revoke_another_candidates_grant():
    svc, _ = service(); svc.repo.grants["g1"] = grant_doc(candidate="c2")
    with pytest.raises(PrivacyLifecycleEligibilityError):
        await svc.revoke_grant(candidate_command(candidate="c1"), now=NOW)
    assert svc.repo.update_calls == 0
    assert svc.repo.insert_calls == 0


@pytest.mark.asyncio
async def test_future_issued_grant_cannot_be_revoked_with_preissue_timestamp():
    svc, _ = service(); svc.repo.grants["g1"] = grant_doc(issued_at=NOW + timedelta(hours=1))
    with pytest.raises(PrivacyLifecycleConflictError):
        await svc.revoke_grant(candidate_command(), now=NOW)
    assert svc.repo.insert_calls == 0


@pytest.mark.asyncio
async def test_already_revoked_grant_keeps_original_revoked_at_without_new_event():
    original = NOW - timedelta(hours=1)
    svc, _ = service(); svc.repo.grants["g1"] = grant_doc(revoked_at=original)
    result = await svc.revoke_grant(candidate_command(command_id="new-command"), now=NOW)
    assert result.revoked_at == original
    assert svc.repo.update_calls == 0
    assert svc.repo.insert_calls == 0


@pytest.mark.asyncio
async def test_future_scheduled_revocation_can_be_replaced_by_immediate_candidate_revocation():
    scheduled = NOW + timedelta(hours=2)
    svc, _ = service(); svc.repo.grants["g1"] = grant_doc(revoked_at=scheduled)
    result = await svc.revoke_grant(candidate_command(command_id="revoke-now"), now=NOW)
    assert result.revoked_at == NOW
    assert svc.repo.update_calls == 1
    assert svc.repo.insert_calls == 1
    assert svc.repo.grants["g1"]["revocation_command_id"] == "revoke-now"


@pytest.mark.asyncio
async def test_concurrent_update_failure_with_only_future_revocation_fails_closed():
    scheduled = NOW + timedelta(hours=2)
    svc, _ = service(); svc.repo.grants["g1"] = grant_doc(revoked_at=scheduled)
    svc.repo.force_update_conflict = True
    with pytest.raises(PrivacyLifecycleConflictError):
        await svc.revoke_grant(candidate_command(command_id="revoke-now"), now=NOW)
    assert svc.repo.insert_calls == 0


@pytest.mark.asyncio
async def test_malformed_grant_fails_closed_before_mutation():
    svc, _ = service(); bad = grant_doc(); bad["scopes"] = [] ; svc.repo.grants["g1"] = bad
    with pytest.raises(PrivacyLifecycleEligibilityError):
        await svc.revoke_grant(candidate_command(), now=NOW)
    assert svc.repo.update_calls == 0
    assert svc.repo.insert_calls == 0




def test_engine_rejects_naive_grant_business_timestamps_even_outside_persistence():
    grant = GrantContract(
        grant_id=GrantId("g-naive"), candidate_id=CandidateId("c1"),
        grantee_organization_id=OrganizationId("org1"), scopes=(GrantScope.PROFILE_PREVIEW,),
        issued_at=datetime(2026, 9, 1, 12, 0),
        consent_policy_version=ConsentPolicyVersion("consent-v1"),
        stream_id=TalentStreamId("stream1"),
    )
    with pytest.raises(ValueError):
        evaluate_grant_privacy(grant, policy_version=POLICY, evaluated_at=NOW)

def test_bson_naive_utc_is_normalized_only_at_persistence_boundary():
    naive = datetime(2026, 9, 4, 22, 0)
    grant = grant_from_document(grant_doc(issued_at=naive))
    assert grant.issued_at.tzinfo == timezone.utc
    with pytest.raises(ValueError):
        evaluate_grant_privacy(grant, policy_version=POLICY, evaluated_at=datetime(2026, 9, 5, 1, 0))


def grant_rule(hours=24, action=RetentionTerminalAction.ANONYMIZE):
    return RetentionRule(
        PrivacyDataCategory.TALENT_STREAM_GRANT,
        "grant_lifecycle",
        timedelta(hours=hours),
        action,
        PolicyVersion("retention-grant-v1"),
    )


def audit_rule(hours=72, action=RetentionTerminalAction.DELETE):
    return RetentionRule(
        PrivacyDataCategory.PRIVACY_AUDIT_EVENT,
        "privacy_audit",
        timedelta(hours=hours),
        action,
        PolicyVersion("retention-audit-v1"),
    )


def test_retention_duration_is_injected_and_changes_deadline():
    grant = grant_from_document(grant_doc(revoked_at=NOW - timedelta(hours=1)))
    short = evaluate_grant_retention(grant, grant_rule(hours=2), evaluated_at=NOW)
    long = evaluate_grant_retention(grant, grant_rule(hours=10), evaluated_at=NOW)
    assert short.retention_until != long.retention_until
    assert short.retention_until == grant.revoked_at + timedelta(hours=2)
    assert short.policy_version == "retention-grant-v1"
    assert short.category is PrivacyDataCategory.TALENT_STREAM_GRANT
    assert short.purpose == "grant_lifecycle"
    assert short.evaluated_at == NOW


def test_revoked_grant_retention_anchors_at_revocation():
    revoked = NOW - timedelta(hours=5)
    grant = grant_from_document(grant_doc(revoked_at=revoked))
    result = evaluate_grant_retention(grant, grant_rule(hours=24), evaluated_at=NOW)
    assert result.retention_until == revoked + timedelta(hours=24)
    assert result.action_due is None


def test_expired_grant_retention_anchors_at_expiry():
    expiry = NOW - timedelta(hours=5)
    grant = grant_from_document(grant_doc(expires_at=expiry))
    result = evaluate_grant_retention(grant, grant_rule(hours=24), evaluated_at=NOW)
    assert result.retention_until == expiry + timedelta(hours=24)


def test_if_expired_then_revoked_retention_uses_earliest_terminal_point():
    expiry = NOW - timedelta(hours=10)
    revoked = NOW - timedelta(hours=2)
    grant = grant_from_document(grant_doc(expires_at=expiry, revoked_at=revoked))
    result = evaluate_grant_retention(grant, grant_rule(hours=24), evaluated_at=NOW)
    assert result.retention_until == expiry + timedelta(hours=24)


def test_active_nonexpiring_grant_has_no_terminal_retention_deadline():
    grant = grant_from_document(grant_doc())
    result = evaluate_grant_retention(grant, grant_rule(), evaluated_at=NOW)
    assert result.retention_until is None
    assert result.action_due is None
    assert result.reason_code is PrivacyReasonCode.IDENTIFIABLE_RETENTION_NOT_DUE


def test_retention_expiry_produces_due_action_without_deleting_anything():
    grant = grant_from_document(grant_doc(revoked_at=NOW - timedelta(days=2)))
    result = evaluate_grant_retention(grant, grant_rule(hours=1, action=RetentionTerminalAction.ANONYMIZE), evaluated_at=NOW)
    assert result.reason_code is PrivacyReasonCode.IDENTIFIABLE_RETENTION_EXPIRED
    assert result.action_due is RetentionTerminalAction.ANONYMIZE


def test_audit_event_retention_is_independent_from_grant_retention():
    command = candidate_command()
    event = PrivacyAuditEvent(
        command.command_id, command.grant_id, command.candidate_id, command.authority,
        command.reason_code, command.policy_version, command.actor_id, NOW - timedelta(hours=5),
    )
    grant_result = evaluate_grant_retention(
        grant_from_document(grant_doc(revoked_at=NOW - timedelta(hours=5))),
        grant_rule(hours=2), evaluated_at=NOW,
    )
    audit_result = evaluate_audit_event_retention(event, audit_rule(hours=20), evaluated_at=NOW)
    assert grant_result.action_due is RetentionTerminalAction.ANONYMIZE
    assert audit_result.action_due is None
    assert audit_result.retention_until == event.occurred_at + timedelta(hours=20)




def test_future_audit_event_is_rejected_by_retention_evaluation():
    command = candidate_command()
    event = PrivacyAuditEvent(
        command.command_id, command.grant_id, command.candidate_id, command.authority,
        command.reason_code, command.policy_version, command.actor_id, NOW + timedelta(hours=1),
    )
    with pytest.raises(ValueError):
        evaluate_audit_event_retention(event, audit_rule(), evaluated_at=NOW)

def test_retention_rule_requires_positive_duration_and_correct_category():
    with pytest.raises(ValueError):
        RetentionRule(PrivacyDataCategory.TALENT_STREAM_GRANT, "x", timedelta(0), RetentionTerminalAction.DELETE, POLICY)
    grant = grant_from_document(grant_doc(revoked_at=NOW))
    with pytest.raises(ValueError):
        evaluate_grant_retention(grant, audit_rule(), evaluated_at=NOW)


def test_architecture_separation_no_permission_trust_intent_match_imports_or_physical_cleanup():
    root = Path(__file__).parents[1]
    source = "\n".join((root / "domains" / "privacy" / name).read_text() for name in ("models.py", "engine.py", "repository.py", "service.py"))
    forbidden = (
        "domains.permissions", "recruiting_service", "domains.matching", "domains.intent",
        "delete_one", "delete_many", "drop(", "anonymize_record",
    )
    assert all(token not in source for token in forbidden)


def test_migration_is_explicit_non_ttl_no_backfill_and_has_unique_command_protection():
    root = Path(__file__).parents[1]
    source = (root / "scripts" / "migrate_ts_a10_privacy_indexes.py").read_text()
    lowered = source.lower()
    assert "unique=true" in lowered
    assert "command_id" in lowered
    assert "revoked_at" in lowered
    assert "incomplete ts-a10 grant revocation metadata" in lowered
    assert "authority/reason mismatch" in lowered
    assert "expireafterseconds" not in lowered
    assert "ttl" in lowered
    assert "no ttl" in lowered
    assert "backfill" in lowered
    assert "no ttl, deletion, anonymization, or backfill" in lowered
    assert "ts_a9_grant_expiry" not in source


def test_only_authorized_a10_files_exist_in_privacy_context_and_no_existing_a9_file_was_rewritten():
    root = Path(__file__).parents[1]
    privacy_files = sorted(p.name for p in (root / "domains" / "privacy").glob("*.py"))
    assert privacy_files == ["__init__.py", "engine.py", "models.py", "repository.py", "service.py"]
    assert (root / "domains" / "permissions" / "service.py").exists()
