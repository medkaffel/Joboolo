"""A12 G0 only: pure contracts, no storage, network or producer integration."""
from dataclasses import FrozenInstanceError, fields, replace
from enum import Enum
import json
from pathlib import Path
import subprocess
import sys

import pytest

from domains.shared.reason_codes import ReasonCodeRef, qualify_reason_code
from domains.talent_stream.audit import AuditEvidenceRef, AuditEvidenceSourceKind
from domains.matching.models import MatchReasonCode
from domains.matching.opportunity_fit_models import OpportunityFitReasonCode
from domains.trust.organization_models import OrganizationVerificationReasonCode
from domains.trust.recruiting_models import (
    MembershipReasonCode, RecruiterVerificationReasonCode, MandateReasonCode,
    RecruitingTrustReasonCode,
)
from domains.permissions.models import PermissionReasonCode
from domains.privacy.models import GrantRevocationReasonCode, PrivacyReasonCode


VOCABULARIES = (
    ("matching.professional", MatchReasonCode),
    ("matching.opportunity_fit", OpportunityFitReasonCode),
    ("trust.organization_verification", OrganizationVerificationReasonCode),
    ("trust.membership", MembershipReasonCode),
    ("trust.recruiter_verification", RecruiterVerificationReasonCode),
    ("trust.mandate", MandateReasonCode),
    ("trust.recruiting", RecruitingTrustReasonCode),
    ("permissions.authorization", PermissionReasonCode),
    ("privacy.revocation", GrantRevocationReasonCode),
    ("privacy.lifecycle", PrivacyReasonCode),
)


@pytest.mark.parametrize("namespace,vocabulary", VOCABULARIES)
def test_qualifies_every_existing_enum_member_without_changing_vocabulary(namespace, vocabulary):
    before = tuple((m.name, m.value) for m in vocabulary)
    for member in vocabulary:
        ref = qualify_reason_code(namespace, member)
        assert ref == ReasonCodeRef(namespace, member.value)
        assert ref.code is member.value
    assert tuple((m.name, m.value) for m in vocabulary) == before


def test_overlapping_domain_codes_are_distinct():
    first = qualify_reason_code("matching.professional", MatchReasonCode.EXPLICIT_MISMATCH)
    second = qualify_reason_code("matching.opportunity_fit", OpportunityFitReasonCode.EXPLICIT_MISMATCH)
    assert first.code == second.code and first != second
    assert qualify_reason_code("trust.membership", MembershipReasonCode.MANUAL_REVIEW_APPROVED) != qualify_reason_code(
        "trust.mandate", MandateReasonCode.MANUAL_REVIEW_APPROVED)


@pytest.mark.parametrize("field", ["namespace", "code"])
@pytest.mark.parametrize("bad", [None, True, 1, [], {}, "", " ", "a b", " a", "a ", "A", "a\n", "a/b", "a@b", "a__b", "_a", "a_"])
def test_invalid_reason_tokens_fail_without_coercion(field, bad):
    values = dict(namespace="trust.membership", code="manual_review_approved")
    values[field] = bad
    with pytest.raises(ValueError):
        ReasonCodeRef(**values)


@pytest.mark.parametrize("bad", [".trust", "trust.", "trust..membership", "trust._membership", "trust.member_"])
def test_namespace_segments_are_strict(bad):
    with pytest.raises(ValueError):
        ReasonCodeRef(bad, "approved")


def test_shared_contract_is_syntactic_and_has_no_global_registry():
    assert ReasonCodeRef("other_domain.reasons", "domain_owned_code").namespace == "other_domain.reasons"
    with pytest.raises(ValueError):
        ReasonCodeRef("trust", "nested.code")


@pytest.mark.parametrize("bad", ["approved", 1, None, MatchReasonCode, {"value": "approved"}])
def test_helper_requires_an_actual_enum_member(bad):
    with pytest.raises(ValueError):
        qualify_reason_code("trust", bad)


def test_helper_rejects_nonstring_and_malformed_enum_values():
    class Invalid(Enum):
        NUMBER = 1
        TEXT = "human readable explanation"
    for member in Invalid:
        with pytest.raises(ValueError):
            qualify_reason_code("trust", member)


def evidence(**changes):
    values = dict(source_kind=AuditEvidenceSourceKind.PRIVACY_REVOCATION,
                  source_event_id="privacy_event:synthetic-command-1",
                  retention_category="privacy_audit_event",
                  retention_purpose="revocation_evidence",
                  retention_policy_version="retention-policy-v1")
    values.update(changes)
    return AuditEvidenceRef(**values)


def test_closed_sources_cover_only_existing_a7_a8_a10_evidence():
    assert {m.value for m in AuditEvidenceSourceKind} == {
        "organization_verification", "membership", "recruiter_verification", "mandate", "privacy_revocation"}
    for member in AuditEvidenceSourceKind:
        assert evidence(source_kind=member).source_kind is member


@pytest.mark.parametrize("bad", [None, 1, True, "membership", "talent_intent_events", "admin", "source_protection", "contact_governor", {}])
def test_source_kind_requires_a_closed_enum_member(bad):
    with pytest.raises(ValueError):
        evidence(source_kind=bad)


@pytest.mark.parametrize("field", ["source_event_id", "retention_category", "retention_purpose", "retention_policy_version", "schema_version"])
@pytest.mark.parametrize("bad", [None, 1, True, {}, [], "", " ", " a", "a ", "a\n", "user@example.invalid", "https://example.invalid/cv", "raw text"])
def test_reference_metadata_is_strict(field, bad):
    with pytest.raises(ValueError):
        evidence(**{field: bad})


@pytest.mark.parametrize("field", ["retention_category", "retention_purpose"])
@pytest.mark.parametrize("bad", ["UPPER", "a.b", "a-b", "a__b", "_a", "a_"])
def test_governance_labels_are_machine_tokens(field, bad):
    with pytest.raises(ValueError):
        evidence(**{field: bad})


def test_identity_and_full_equality_have_explicit_different_meanings():
    first = evidence()
    assert first == evidence()
    changed = replace(first, retention_policy_version="retention-policy-v2")
    assert changed != first
    assert changed.evidence_identity == first.evidence_identity
    assert replace(first, source_event_id="privacy_event:other").evidence_identity != first.evidence_identity
    assert replace(first, source_kind=AuditEvidenceSourceKind.MANDATE).evidence_identity != first.evidence_identity
    with pytest.raises(ValueError):
        evidence(schema_version="audit-evidence-ref-v2")


def test_contracts_are_frozen_and_cannot_acquire_payload_fields():
    for ref, field in [(ReasonCodeRef("trust", "approved"), "code"), (evidence(), "source_event_id")]:
        with pytest.raises(FrozenInstanceError):
            setattr(ref, field, "changed")
        with pytest.raises((AttributeError, TypeError)):
            setattr(ref, "payload", {"email": "synthetic@example.invalid"})


def test_minimal_reference_has_no_copied_evidence_access_or_retention_deadline():
    assert {f.name for f in fields(AuditEvidenceRef)} == {
        "source_kind", "source_event_id", "schema_version", "retention_category",
        "retention_purpose", "retention_policy_version"}
    for field in ("actor_id", "occurred_at", "reason_codes", "evidence_refs", "payload", "cv",
                  "email", "phone", "allowed", "expires_at", "retention_until", "ttl"):
        with pytest.raises(TypeError):
            evidence(**{field: "forbidden"})
    # Construction is not existence verification, nor a grant or retention rule.
    assert evidence(source_event_id="nonexistent-synthetic-source").source_event_id == "nonexistent-synthetic-source"


def test_fresh_imports_and_construction_are_pure_and_process_independent():
    script = '''
import sys
sys.dont_write_bytecode = True
import json
def guard(event, args):
    if event.startswith(("socket.", "subprocess.")) or event in ("os.system", "os.urandom"):
        raise AssertionError("external side effect")
sys.addaudithook(guard)
from domains.shared.reason_codes import ReasonCodeRef
from domains.talent_stream.audit import AuditEvidenceRef, AuditEvidenceSourceKind
assert not any(name.split('.')[0] in {"motor", "pymongo", "database", "requests", "httpx", "fastapi", "uuid"} for name in sys.modules)
assert not any(name.startswith(("domains.trust", "domains.permissions", "domains.privacy", "domains.matching", "domains.intent")) for name in sys.modules)
r = ReasonCodeRef("trust.membership", "manual_review_approved")
a = AuditEvidenceRef(AuditEvidenceSourceKind.MEMBERSHIP, "trust_event:synthetic", "trust_audit", "transition_evidence", "retention-v1")
print(json.dumps([r.namespace, r.code, a.evidence_identity, a.schema_version]))
'''
    outputs = [subprocess.check_output([sys.executable, "-B", "-c", script],
                cwd=Path(__file__).resolve().parents[1], text=True) for _ in range(2)]
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])[2] == ["membership", "trust_event:synthetic"]
