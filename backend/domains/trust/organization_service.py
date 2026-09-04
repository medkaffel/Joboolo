"""Application service for canonical Organization identity and verification state."""
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from database import get_client
from domains.shared.ids import OrganizationId
from domains.shared.versioning import EntityVersion, PolicyVersion
from .organization_models import (
    Organization,
    OrganizationCreate,
    OrganizationIdentityRevision,
    OrganizationVerificationReasonCode,
    OrganizationVerificationState,
    OrganizationVerificationTransition,
    normalize_country,
    normalize_domain,
    normalize_nonempty,
    normalize_optional_text,
    organization_from_document,
    require_aware_datetime,
)
from .organization_repository import OrganizationRepository


class OrganizationConflictError(RuntimeError):
    pass


class OrganizationInputNotFoundError(LookupError):
    pass


_ALLOWED_TRANSITIONS = {
    OrganizationVerificationState.UNVERIFIED: {OrganizationVerificationState.PENDING},
    OrganizationVerificationState.PENDING: {
        OrganizationVerificationState.VERIFIED,
        OrganizationVerificationState.REJECTED,
    },
    OrganizationVerificationState.VERIFIED: {OrganizationVerificationState.SUSPENDED},
    OrganizationVerificationState.SUSPENDED: {
        OrganizationVerificationState.VERIFIED,
        OrganizationVerificationState.REJECTED,
    },
    OrganizationVerificationState.REJECTED: {OrganizationVerificationState.PENDING},
}

_SENSITIVE_IDENTITY_FIELDS = frozenset({
    "legal_name", "primary_domain", "registration_country", "registration_id"
})


def _command_time(value: Optional[datetime], field_name: str) -> datetime:
    current = value or datetime.now(timezone.utc)
    return require_aware_datetime(current, field_name)


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def _identity_changes(current: dict, revision: OrganizationIdentityRevision) -> dict:
    changes = {}
    if revision.legal_name is not None:
        changes["legal_name"] = normalize_nonempty(revision.legal_name, "legal_name")
    if revision.display_name is not None:
        changes["display_name"] = normalize_optional_text(revision.display_name)
    if revision.website_url is not None:
        changes["website_url"] = normalize_optional_text(revision.website_url)
    if revision.primary_domain is not None:
        changes["primary_domain"] = normalize_domain(revision.primary_domain)
    if revision.registration_country is not None:
        changes["registration_country"] = normalize_country(revision.registration_country)
        changes["registration_id"] = normalize_optional_text(revision.registration_id)
    if revision.legacy_company_id is not None:
        changes["legacy_company_id"] = normalize_optional_text(revision.legacy_company_id)
    for field in revision.clear_fields:
        changes[field] = None
    return {key: value for key, value in changes.items() if current.get(key) != value}


def _event_document(
    *,
    organization_id: str,
    organization_version: int,
    previous_state: OrganizationVerificationState,
    new_state: OrganizationVerificationState,
    reason_codes,
    evidence_refs,
    policy_version: PolicyVersion,
    actor_id: str,
    occurred_at: datetime,
) -> dict:
    return {
        "_id": f"organization_verification_event:{uuid4()}",
        "organization_id": organization_id,
        "organization_version": organization_version,
        "previous_state": previous_state.value,
        "new_state": new_state.value,
        "reason_codes": [_enum_value(value) for value in reason_codes],
        "evidence_refs": list(evidence_refs),
        "policy_version": str(policy_version),
        "actor_id": actor_id,
        "occurred_at": occurred_at,
        "created_at": occurred_at,
    }


class OrganizationService:
    def __init__(self, db):
        self.db = db
        self.repo = OrganizationRepository(db)

    async def get(self, organization_id: OrganizationId) -> Organization:
        document = await self.repo.get(str(organization_id))
        if document is None:
            raise OrganizationInputNotFoundError("Organization not found")
        return organization_from_document(document)

    async def create(self, command: OrganizationCreate, *, created_at: Optional[datetime] = None) -> Organization:
        identity = command.to_identity()
        if identity["legacy_company_id"] is not None:
            if not await self.repo.legacy_company_exists(identity["legacy_company_id"]):
                raise OrganizationInputNotFoundError("legacy company mapping target not found")
        now = _command_time(created_at, "created_at")
        document = {
            "_id": str(command.organization_id),
            "organization_id": str(command.organization_id),
            "version": 1,
            **identity,
            "verification_state": OrganizationVerificationState.UNVERIFIED.value,
            "verification_policy_version": None,
            "verification_reason_codes": [],
            "verification_evidence_refs": [],
            "verification_actor_id": None,
            "verification_decided_at": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            await self.repo.insert(document)
        except DuplicateKeyError as exc:
            raise OrganizationConflictError("Organization identity already exists") from exc
        return organization_from_document(document)

    async def revise_identity(
        self,
        organization_id: OrganizationId,
        expected_version: EntityVersion,
        revision: OrganizationIdentityRevision,
        *,
        actor_id: str,
        policy_version: PolicyVersion,
        occurred_at: Optional[datetime] = None,
    ) -> Organization:
        actor_id = normalize_nonempty(actor_id, "actor_id")
        if not str(policy_version).strip():
            raise ValueError("policy_version must not be blank")
        client = get_client()
        if client is None:
            raise RuntimeError("Mongo client unavailable")
        now = _command_time(occurred_at, "occurred_at")
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    current = await self.repo.get(str(organization_id), session=session)
                    if current is None:
                        raise OrganizationInputNotFoundError("Organization not found")
                    if int(current["version"]) != int(expected_version):
                        raise OrganizationConflictError(
                            f"organization version mismatch: expected {int(expected_version)}, current {current['version']}"
                        )
                    current_org = organization_from_document(current)
                    changes = _identity_changes(current, revision)
                    if not changes:
                        raise ValueError("Organization identity revision requires a business change")

                    current_legacy = current_org.legacy_company_id
                    requested_legacy = changes.get("legacy_company_id")
                    if current_legacy is not None and requested_legacy is not None and requested_legacy != current_legacy:
                        raise ValueError("legacy_company_id is immutable once attached")
                    if requested_legacy is not None and current_legacy is None:
                        if not await self.repo.legacy_company_exists(requested_legacy, session=session):
                            raise OrganizationInputNotFoundError("legacy company mapping target not found")

                    previous_state = current_org.verification_state
                    sensitive_changed = bool(_SENSITIVE_IDENTITY_FIELDS & set(changes))
                    event = None
                    if sensitive_changed and previous_state is not OrganizationVerificationState.UNVERIFIED:
                        changes.update({
                            "verification_state": OrganizationVerificationState.UNVERIFIED.value,
                            "verification_policy_version": str(policy_version),
                            "verification_reason_codes": [
                                OrganizationVerificationReasonCode.IDENTITY_CHANGED_REVERIFICATION_REQUIRED.value
                            ],
                            "verification_evidence_refs": [],
                            "verification_actor_id": actor_id,
                            "verification_decided_at": now,
                        })
                        event = _event_document(
                            organization_id=str(organization_id),
                            organization_version=int(expected_version) + 1,
                            previous_state=previous_state,
                            new_state=OrganizationVerificationState.UNVERIFIED,
                            reason_codes=(
                                OrganizationVerificationReasonCode.IDENTITY_CHANGED_REVERIFICATION_REQUIRED,
                            ),
                            evidence_refs=(),
                            policy_version=policy_version,
                            actor_id=actor_id,
                            occurred_at=now,
                        )
                    changes["updated_at"] = now
                    updated = await self.repo.update_with_version(
                        str(organization_id), int(expected_version), changes, session=session
                    )
                    if updated is None:
                        raise OrganizationConflictError("Organization changed concurrently")
                    if event is not None:
                        await self.repo.insert_event(event, session=session)
                    return organization_from_document(updated)
        except DuplicateKeyError as exc:
            raise OrganizationConflictError("Organization identity conflicts with an existing organization") from exc

    async def transition_verification(
        self,
        organization_id: OrganizationId,
        expected_version: EntityVersion,
        transition: OrganizationVerificationTransition,
        *,
        occurred_at: Optional[datetime] = None,
    ) -> Organization:
        client = get_client()
        if client is None:
            raise RuntimeError("Mongo client unavailable")
        now = _command_time(occurred_at, "occurred_at")
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    current = await self.repo.get(str(organization_id), session=session)
                    if current is None:
                        raise OrganizationInputNotFoundError("Organization not found")
                    if int(current["version"]) != int(expected_version):
                        raise OrganizationConflictError(
                            f"organization version mismatch: expected {int(expected_version)}, current {current['version']}"
                        )
                    current_org = organization_from_document(current)
                    previous_state = current_org.verification_state
                    if transition.new_state not in _ALLOWED_TRANSITIONS[previous_state]:
                        raise ValueError(
                            f"invalid organization verification transition: {previous_state.value} -> {transition.new_state.value}"
                        )
                    next_version = int(expected_version) + 1
                    changes = {
                        "verification_state": transition.new_state.value,
                        "verification_policy_version": str(transition.policy_version),
                        "verification_reason_codes": [value.value for value in transition.reason_codes],
                        "verification_evidence_refs": list(transition.evidence_refs),
                        "verification_actor_id": transition.actor_id,
                        "verification_decided_at": now,
                        "updated_at": now,
                    }
                    updated = await self.repo.update_with_version(
                        str(organization_id), int(expected_version), changes, session=session
                    )
                    if updated is None:
                        raise OrganizationConflictError("Organization changed concurrently")
                    await self.repo.insert_event(
                        _event_document(
                            organization_id=str(organization_id),
                            organization_version=next_version,
                            previous_state=previous_state,
                            new_state=transition.new_state,
                            reason_codes=transition.reason_codes,
                            evidence_refs=transition.evidence_refs,
                            policy_version=transition.policy_version,
                            actor_id=transition.actor_id,
                            occurred_at=now,
                        ),
                        session=session,
                    )
                    return organization_from_document(updated)
        except DuplicateKeyError as exc:
            raise OrganizationConflictError("Organization verification transition conflicts; retry") from exc
