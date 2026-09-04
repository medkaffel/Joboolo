"""Current-state orchestration for TS-A9 candidate Permission decisions."""
from datetime import datetime, timezone
from typing import Optional

from domains.shared.ids import OrganizationId
from domains.shared.versioning import ConsentPolicyVersion, PolicyVersion
from domains.talent_stream.decisions import PermissionDecision
from domains.trust.organization_models import organization_from_document

from .engine import (
    evaluate_discovery_permission,
    evaluate_organization_exclusions,
    evaluate_scoped_grants,
    permission_decision,
)
from .models import (
    OrganizationPermissionIdentity,
    PermissionAction,
    PermissionReasonCode,
    PermissionRequestContext,
    candidate_permission_state_from_document,
    grant_from_document,
    require_aware_datetime,
)
from .repository import PermissionRepository


class PermissionService:
    def __init__(
        self,
        db,
        *,
        policy_version: PolicyVersion,
        consent_policy_version: ConsentPolicyVersion,
    ):
        if not isinstance(policy_version, str) or not policy_version.strip():
            raise ValueError("policy_version must not be blank")
        if not isinstance(consent_policy_version, str) or not consent_policy_version.strip():
            raise ValueError("consent_policy_version must not be blank")
        self.repo = PermissionRepository(db)
        self.policy_version = policy_version
        self.consent_policy_version = consent_policy_version

    def _deny(
        self,
        reason: PermissionReasonCode,
        evaluated_at: datetime,
        evidence_refs=(),
    ) -> PermissionDecision:
        return permission_decision(
            allowed=False,
            reason=reason,
            policy_version=self.policy_version,
            consent_policy_version=self.consent_policy_version,
            evaluated_at=evaluated_at,
            evidence_refs=evidence_refs,
        )

    async def _organization_identity(
        self, organization_id: str
    ) -> Optional[OrganizationPermissionIdentity]:
        document = await self.repo.get_organization(organization_id)
        if document is None:
            return None
        try:
            organization = organization_from_document(document)
        except (AttributeError, KeyError, TypeError, ValueError):
            return None
        if str(organization.organization_id) != organization_id:
            return None
        return OrganizationPermissionIdentity(
            organization_id=OrganizationId(organization_id),
            version=organization.version,
            legacy_company_id=organization.legacy_company_id,
        )

    async def evaluate(
        self,
        context: PermissionRequestContext,
        *,
        evaluated_at: Optional[datetime] = None,
    ) -> PermissionDecision:
        now = evaluated_at or datetime.now(timezone.utc)
        require_aware_datetime(now, "evaluated_at")

        preferences_document = await self.repo.get_candidate_preferences(str(context.candidate_id))
        if preferences_document is None:
            return self._deny(PermissionReasonCode.CANDIDATE_PREFERENCES_NOT_FOUND, now)
        try:
            state = candidate_permission_state_from_document(preferences_document)
        except (KeyError, TypeError, ValueError):
            return self._deny(PermissionReasonCode.CANDIDATE_PREFERENCES_INVALID, now)
        if str(state.candidate_id) != str(context.candidate_id):
            return self._deny(PermissionReasonCode.CANDIDATE_PREFERENCES_INVALID, now)

        requesting_id = str(context.recruiting_actor.requesting_organization_id)
        hiring_id = str(context.recruiting_actor.hiring_company_id)
        requesting = await self._organization_identity(requesting_id)
        if requesting is None:
            return self._deny(
                PermissionReasonCode.ORGANIZATION_EXCLUSION_CONTEXT_UNRESOLVED,
                now,
                (f"candidate_preferences:{state.preferences_id}:v{state.preferences_version}",),
            )
        if hiring_id == requesting_id:
            hiring = requesting
            organizations = (requesting,)
        else:
            hiring = await self._organization_identity(hiring_id)
            if hiring is None:
                return self._deny(
                    PermissionReasonCode.ORGANIZATION_EXCLUSION_CONTEXT_UNRESOLVED,
                    now,
                    (f"candidate_preferences:{state.preferences_id}:v{state.preferences_version}",),
                )
            organizations = (requesting, hiring)

        evidence = [f"candidate_preferences:{state.preferences_id}:v{state.preferences_version}"]
        evidence.extend(
            f"organization:{organization.organization_id}:v{organization.version}"
            for organization in organizations
        )
        exclusion_reason = evaluate_organization_exclusions(state, organizations)
        if exclusion_reason is not None:
            return self._deny(exclusion_reason, now, evidence)

        if context.action is PermissionAction.REQUEST_INTRODUCTION:
            return evaluate_discovery_permission(
                state,
                policy_version=self.policy_version,
                consent_policy_version=self.consent_policy_version,
                evaluated_at=now,
                evidence_refs=evidence,
            )

        required_scope = context.required_scope
        if required_scope is None:
            raise ValueError("unsupported Permission action")
        grant_documents = await self.repo.find_grants(
            str(context.candidate_id),
            requesting_id,
            str(context.stream_id),
            required_scope,
            None if context.document_id is None else str(context.document_id),
        )
        valid_grants = []
        for document in grant_documents:
            try:
                valid_grants.append(grant_from_document(document))
            except (KeyError, TypeError, ValueError):
                continue
        return evaluate_scoped_grants(
            context,
            valid_grants,
            policy_version=self.policy_version,
            consent_policy_version=self.consent_policy_version,
            evaluated_at=now,
            evidence_refs=evidence,
        )
