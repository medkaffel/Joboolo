"""Transactional TS-A10 grant revocation and current privacy evaluation."""
from datetime import datetime, timezone
from typing import Optional

from pymongo.errors import DuplicateKeyError

from database import get_client
from domains.shared.ids import GrantId
from domains.shared.versioning import PolicyVersion
from domains.talent_stream.contracts import GrantContract
from domains.talent_stream.decisions import PrivacyDecision

from .engine import evaluate_grant_privacy
from .models import (
    GrantRevocationCommand,
    PrivacyAuditEvent,
    grant_from_document,
    privacy_event_from_document,
    require_aware_datetime,
)
from .repository import PrivacyRepository


class PrivacyLifecycleConflictError(RuntimeError):
    pass


class PrivacyLifecycleNotFoundError(LookupError):
    pass


class PrivacyLifecycleEligibilityError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _event_document(command: GrantRevocationCommand, occurred_at: datetime) -> dict:
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


def _event_matches_command(event: PrivacyAuditEvent, command: GrantRevocationCommand) -> bool:
    return (
        event.command_id == command.command_id
        and str(event.grant_id) == str(command.grant_id)
        and str(event.candidate_id) == str(command.candidate_id)
        and event.authority is command.authority
        and event.reason_code is command.reason_code
        and str(event.policy_version) == str(command.policy_version)
        and event.actor_id == command.actor_id
    )


def _grant_document_matches_command(doc: dict, event: PrivacyAuditEvent, command: GrantRevocationCommand) -> bool:
    if doc.get("revocation_command_id") != command.command_id:
        return False
    if doc.get("revocation_policy_version") != str(command.policy_version):
        return False
    if doc.get("revocation_reason_code") != command.reason_code.value:
        return False
    if doc.get("revocation_authority") != command.authority.value:
        return False
    if doc.get("revocation_actor_id") != command.actor_id:
        return False
    try:
        revoked_at = grant_from_document(doc).revoked_at
    except (KeyError, TypeError, ValueError):
        return False
    return revoked_at is not None and revoked_at == event.occurred_at


class PrivacyLifecycleService:
    def __init__(self, db, *, client_provider=get_client):
        self.repo = PrivacyRepository(db)
        self.client_provider = client_provider

    def _client(self):
        client = self.client_provider()
        if client is None:
            raise RuntimeError("Mongo client unavailable")
        return client

    async def evaluate_grant(self, grant_id: GrantId, *, policy_version: PolicyVersion,
                             evaluated_at: Optional[datetime] = None) -> PrivacyDecision:
        now = evaluated_at or _utcnow()
        require_aware_datetime(now, "evaluated_at")
        doc = await self.repo.get_grant(str(grant_id))
        if doc is None:
            raise PrivacyLifecycleNotFoundError("Grant not found")
        try:
            grant = grant_from_document(doc)
        except (KeyError, TypeError, ValueError) as exc:
            raise PrivacyLifecycleEligibilityError("Grant record is invalid") from exc
        return evaluate_grant_privacy(grant, policy_version=policy_version, evaluated_at=now)

    async def _recover_idempotent(self, command: GrantRevocationCommand) -> GrantContract:
        event_doc = await self.repo.get_event_by_command_id(command.command_id)
        if event_doc is None:
            raise PrivacyLifecycleConflictError("Revocation command conflict")
        try:
            event = privacy_event_from_document(event_doc)
        except (KeyError, TypeError, ValueError) as exc:
            raise PrivacyLifecycleConflictError("Stored privacy event is invalid") from exc
        if not _event_matches_command(event, command):
            raise PrivacyLifecycleConflictError("command_id already used with different payload")
        grant_doc = await self.repo.get_grant(str(command.grant_id))
        if grant_doc is None:
            raise PrivacyLifecycleConflictError("Revoked grant no longer exists")
        try:
            grant = grant_from_document(grant_doc)
        except (KeyError, TypeError, ValueError) as exc:
            raise PrivacyLifecycleConflictError("Revoked grant record is invalid") from exc
        if str(grant.candidate_id) != str(command.candidate_id) or grant.revoked_at is None:
            raise PrivacyLifecycleConflictError("Idempotency record is inconsistent with grant state")
        if not _grant_document_matches_command(grant_doc, event, command):
            raise PrivacyLifecycleConflictError("Idempotency metadata is inconsistent with grant state")
        return grant

    async def revoke_grant(self, command: GrantRevocationCommand, *, now: Optional[datetime] = None) -> GrantContract:
        now = now or _utcnow()
        require_aware_datetime(now, "now")
        client = self._client()
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    existing_event_doc = await self.repo.get_event_by_command_id(command.command_id, session=session)
                    if existing_event_doc is not None:
                        try:
                            event = privacy_event_from_document(existing_event_doc)
                        except (KeyError, TypeError, ValueError) as exc:
                            raise PrivacyLifecycleConflictError("Stored privacy event is invalid") from exc
                        if not _event_matches_command(event, command):
                            raise PrivacyLifecycleConflictError("command_id already used with different payload")
                        grant_doc = await self.repo.get_grant(str(command.grant_id), session=session)
                        if grant_doc is None:
                            raise PrivacyLifecycleConflictError("Revoked grant no longer exists")
                        try:
                            grant = grant_from_document(grant_doc)
                        except (KeyError, TypeError, ValueError) as exc:
                            raise PrivacyLifecycleConflictError("Revoked grant record is invalid") from exc
                        if str(grant.candidate_id) != str(command.candidate_id) or grant.revoked_at is None:
                            raise PrivacyLifecycleConflictError("Idempotency record is inconsistent with grant state")
                        if not _grant_document_matches_command(grant_doc, event, command):
                            raise PrivacyLifecycleConflictError("Idempotency metadata is inconsistent with grant state")
                        return grant

                    grant_doc = await self.repo.get_grant(str(command.grant_id), session=session)
                    if grant_doc is None:
                        raise PrivacyLifecycleNotFoundError("Grant not found")
                    try:
                        grant = grant_from_document(grant_doc)
                    except (KeyError, TypeError, ValueError) as exc:
                        raise PrivacyLifecycleEligibilityError("Grant record is invalid") from exc
                    if str(grant.candidate_id) != str(command.candidate_id):
                        raise PrivacyLifecycleEligibilityError("Grant does not belong to candidate")
                    if grant.revoked_at is not None and grant.revoked_at <= now:
                        return grant
                    if now < grant.issued_at:
                        raise PrivacyLifecycleConflictError("Grant cannot be revoked before issuance")

                    changes = {
                        "revoked_at": now,
                        "revocation_policy_version": str(command.policy_version),
                        "revocation_reason_code": command.reason_code.value,
                        "revocation_authority": command.authority.value,
                        "revocation_actor_id": command.actor_id,
                        "revocation_command_id": command.command_id,
                        "privacy_updated_at": now,
                    }
                    updated_doc = await self.repo.revoke_grant_if_unrevoked(
                        str(command.grant_id), str(command.candidate_id), now, changes, session=session
                    )
                    if updated_doc is None:
                        current_doc = await self.repo.get_grant(str(command.grant_id), session=session)
                        if current_doc is None:
                            raise PrivacyLifecycleConflictError("Grant disappeared during revocation")
                        try:
                            current = grant_from_document(current_doc)
                        except (KeyError, TypeError, ValueError) as exc:
                            raise PrivacyLifecycleConflictError("Concurrent grant state is invalid") from exc
                        if current.revoked_at is not None and current.revoked_at <= now:
                            return current
                        raise PrivacyLifecycleConflictError("Concurrent grant revocation conflict")
                    await self.repo.insert_event(_event_document(command, now), session=session)
                    return grant_from_document(updated_doc)
        except DuplicateKeyError:
            return await self._recover_idempotent(command)
