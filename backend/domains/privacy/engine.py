"""Deterministic TS-A10 privacy lifecycle and retention policy engine."""
from datetime import datetime
from typing import Iterable, Optional

from domains.shared.versioning import PolicyVersion
from domains.talent_stream.contracts import GrantContract
from domains.talent_stream.decisions import PrivacyDecision

from .models import (
    PrivacyAuditEvent,
    PrivacyDataCategory,
    PrivacyReasonCode,
    RetentionEvaluation,
    RetentionRule,
    require_aware_datetime,
)


def _policy_version(value: PolicyVersion) -> PolicyVersion:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("policy_version must not be blank")
    return value


def privacy_decision(*, allowed: bool, reason: PrivacyReasonCode, policy_version: PolicyVersion,
                     evaluated_at: datetime, evidence_refs: Iterable[str] = ()) -> PrivacyDecision:
    require_aware_datetime(evaluated_at, "evaluated_at")
    return PrivacyDecision(
        allowed=allowed,
        reason_codes=(reason.value,),
        policy_version=_policy_version(policy_version),
        evaluated_at=evaluated_at,
        evidence_refs=tuple(evidence_refs),
    )


def _validate_grant_times(grant: GrantContract) -> None:
    require_aware_datetime(grant.issued_at, "grant.issued_at")
    if grant.expires_at is not None:
        require_aware_datetime(grant.expires_at, "grant.expires_at")
    if grant.revoked_at is not None:
        require_aware_datetime(grant.revoked_at, "grant.revoked_at")


def evaluate_grant_privacy(grant: GrantContract, *, policy_version: PolicyVersion,
                           evaluated_at: datetime) -> PrivacyDecision:
    require_aware_datetime(evaluated_at, "evaluated_at")
    _validate_grant_times(grant)
    evidence = (f"grant:{grant.grant_id}",)
    if evaluated_at < grant.issued_at:
        return privacy_decision(allowed=False, reason=PrivacyReasonCode.GRANT_NOT_YET_ACTIVE,
                                policy_version=policy_version, evaluated_at=evaluated_at, evidence_refs=evidence)
    terminal = []
    if grant.revoked_at is not None and grant.revoked_at <= evaluated_at:
        terminal.append((grant.revoked_at, PrivacyReasonCode.GRANT_REVOKED))
    if grant.expires_at is not None and grant.expires_at <= evaluated_at:
        terminal.append((grant.expires_at, PrivacyReasonCode.GRANT_EXPIRED))
    if terminal:
        _, reason = min(terminal, key=lambda item: item[0])
        return privacy_decision(allowed=False, reason=reason,
                                policy_version=policy_version, evaluated_at=evaluated_at, evidence_refs=evidence)
    return privacy_decision(allowed=True, reason=PrivacyReasonCode.GRANT_PRIVACY_ACTIVE,
                            policy_version=policy_version, evaluated_at=evaluated_at, evidence_refs=evidence)


def _terminal_anchor(grant: GrantContract, evaluated_at: datetime) -> Optional[datetime]:
    """Return the earliest effective terminal time, never a later event that prolongs retention."""
    candidates = []
    if grant.revoked_at is not None and grant.revoked_at <= evaluated_at:
        candidates.append(grant.revoked_at)
    if grant.expires_at is not None and grant.expires_at <= evaluated_at:
        candidates.append(grant.expires_at)
    return min(candidates) if candidates else None


def _retention_result(anchor: Optional[datetime], rule: RetentionRule, evaluated_at: datetime) -> RetentionEvaluation:
    require_aware_datetime(evaluated_at, "evaluated_at")
    common = dict(
        category=rule.category,
        purpose=rule.purpose,
        policy_version=rule.policy_version,
        evaluated_at=evaluated_at,
    )
    if anchor is None:
        return RetentionEvaluation(
            **common,
            retention_until=None,
            action_due=None,
            reason_code=PrivacyReasonCode.IDENTIFIABLE_RETENTION_NOT_DUE,
        )
    retention_until = anchor + rule.retain_for
    if evaluated_at < retention_until:
        return RetentionEvaluation(
            **common,
            retention_until=retention_until,
            action_due=None,
            reason_code=PrivacyReasonCode.IDENTIFIABLE_RETENTION_ACTIVE,
        )
    return RetentionEvaluation(
        **common,
        retention_until=retention_until,
        action_due=rule.terminal_action,
        reason_code=PrivacyReasonCode.IDENTIFIABLE_RETENTION_EXPIRED,
    )


def evaluate_grant_retention(grant: GrantContract, rule: RetentionRule, *, evaluated_at: datetime) -> RetentionEvaluation:
    if rule.category is not PrivacyDataCategory.TALENT_STREAM_GRANT:
        raise ValueError("grant retention requires TALENT_STREAM_GRANT rule")
    require_aware_datetime(evaluated_at, "evaluated_at")
    _validate_grant_times(grant)
    return _retention_result(_terminal_anchor(grant, evaluated_at), rule, evaluated_at)


def evaluate_audit_event_retention(event: PrivacyAuditEvent, rule: RetentionRule, *, evaluated_at: datetime) -> RetentionEvaluation:
    if rule.category is not PrivacyDataCategory.PRIVACY_AUDIT_EVENT:
        raise ValueError("audit retention requires PRIVACY_AUDIT_EVENT rule")
    require_aware_datetime(evaluated_at, "evaluated_at")
    if event.occurred_at > evaluated_at:
        raise ValueError("privacy audit event cannot occur in the future")
    return _retention_result(event.occurred_at, rule, evaluated_at)
