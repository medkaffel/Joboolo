"""Deterministic candidate Permission policy for TS-A9."""
from datetime import datetime
from typing import Iterable, Optional, Sequence

from domains.shared.versioning import ConsentPolicyVersion, PolicyVersion
from domains.talent_stream.contracts import GrantContract, GrantScope
from domains.talent_stream.decisions import PermissionDecision

from .models import (
    CandidatePermissionState,
    OrganizationPermissionIdentity,
    PermissionAction,
    PermissionReasonCode,
    PermissionRequestContext,
    require_aware_datetime,
)


def _require_version(value, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def permission_decision(
    *,
    allowed: bool,
    reason: PermissionReasonCode,
    policy_version: PolicyVersion,
    consent_policy_version: ConsentPolicyVersion,
    evaluated_at: datetime,
    evidence_refs: Iterable[str] = (),
) -> PermissionDecision:
    _require_version(policy_version, "policy_version")
    _require_version(consent_policy_version, "consent_policy_version")
    require_aware_datetime(evaluated_at, "evaluated_at")
    return PermissionDecision(
        allowed=allowed,
        reason_codes=(reason.value,),
        policy_version=policy_version,
        consent_policy_version=consent_policy_version,
        evaluated_at=evaluated_at,
        evidence_refs=tuple(evidence_refs),
    )


def evaluate_organization_exclusions(
    state: CandidatePermissionState,
    organizations: Sequence[OrganizationPermissionIdentity],
) -> Optional[PermissionReasonCode]:
    exclusions = state.exclusion_ids
    if not exclusions:
        return None
    for organization in organizations:
        if exclusions & organization.comparison_ids:
            return PermissionReasonCode.CANDIDATE_ORGANIZATION_EXCLUSION
    # A2 company IDs have no namespace. If an exclusion exists and an organization
    # has no legacy bridge, a non-match cannot prove that the organization is safe.
    if any(organization.legacy_company_id is None for organization in organizations):
        return PermissionReasonCode.ORGANIZATION_EXCLUSION_CONTEXT_UNRESOLVED
    return None


def evaluate_discovery_permission(
    state: CandidatePermissionState,
    *,
    policy_version: PolicyVersion,
    consent_policy_version: ConsentPolicyVersion,
    evaluated_at: datetime,
    evidence_refs: Iterable[str] = (),
) -> PermissionDecision:
    if not state.discovery_enabled:
        return permission_decision(
            allowed=False,
            reason=PermissionReasonCode.DISCOVERY_DISABLED,
            policy_version=policy_version,
            consent_policy_version=consent_policy_version,
            evaluated_at=evaluated_at,
            evidence_refs=evidence_refs,
        )
    if not state.allow_compatible_opportunities:
        return permission_decision(
            allowed=False,
            reason=PermissionReasonCode.COMPATIBLE_OPPORTUNITIES_NOT_ALLOWED,
            policy_version=policy_version,
            consent_policy_version=consent_policy_version,
            evaluated_at=evaluated_at,
            evidence_refs=evidence_refs,
        )
    return permission_decision(
        allowed=True,
        reason=PermissionReasonCode.DISCOVERY_PERMISSION_GRANTED,
        policy_version=policy_version,
        consent_policy_version=consent_policy_version,
        evaluated_at=evaluated_at,
        evidence_refs=evidence_refs,
    )


def evaluate_scoped_grants(
    context: PermissionRequestContext,
    grants: Sequence[GrantContract],
    *,
    policy_version: PolicyVersion,
    consent_policy_version: ConsentPolicyVersion,
    evaluated_at: datetime,
    evidence_refs: Iterable[str] = (),
) -> PermissionDecision:
    required_scope = context.required_scope
    if context.action is PermissionAction.REQUEST_INTRODUCTION or required_scope is None:
        raise ValueError("scoped-grant evaluation requires a grant-backed Permission action")
    base_evidence = tuple(evidence_refs)
    for grant in grants:
        if str(grant.candidate_id) != str(context.candidate_id):
            continue
        if str(grant.grantee_organization_id) != str(context.recruiting_actor.requesting_organization_id):
            continue
        if grant.stream_id is None or str(grant.stream_id) != str(context.stream_id):
            continue
        if required_scope not in grant.scopes:
            continue
        if required_scope is GrantScope.CV and (
            grant.document_id is None or str(grant.document_id) != str(context.document_id)
        ):
            continue
        if not grant.is_active_at(evaluated_at):
            continue
        return permission_decision(
            allowed=True,
            reason=PermissionReasonCode.ACTIVE_SCOPED_GRANT_GRANTED,
            policy_version=policy_version,
            consent_policy_version=grant.consent_policy_version,
            evaluated_at=evaluated_at,
            evidence_refs=base_evidence + (f"grant:{grant.grant_id}",),
        )
    return permission_decision(
        allowed=False,
        reason=PermissionReasonCode.ACTIVE_SCOPED_GRANT_REQUIRED,
        policy_version=policy_version,
        consent_policy_version=consent_policy_version,
        evaluated_at=evaluated_at,
        evidence_refs=base_evidence,
    )
