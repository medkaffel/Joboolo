"""Internal TS-B1 command orchestration; no authorization or route wiring."""
from datetime import datetime, timezone
from hashlib import sha256
import json

from domains.shared.ids import TalentStreamId
from domains.shared.versioning import EntityVersion
from .stream_models import (
    StreamCommandHistoryEntry,
    StreamCommandKind,
    TalentStream,
    TalentStreamState,
    _validate_recruiting_actor,
    _validate_requirement,
    nonblank_identifier,
    positive_entity_version,
    utc_millisecond,
)
from .stream_repository import TalentStreamConflictError, TalentStreamRepository


class TalentStreamNotFoundError(LookupError):
    pass


def _canonical_timestamp(value):
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _digest(command):
    encoded = json.dumps(
        command, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return "sha256:" + sha256(encoded).hexdigest()


def create_command_fingerprint(stream_id, actor, requirement):
    nonblank_identifier(stream_id, "stream_id")
    _validate_recruiting_actor(actor)
    _validate_requirement(requirement)
    return _digest({
        "stream_id": str(stream_id),
        "command_kind": StreamCommandKind.CREATE.value,
        "recruiting_actor_context": {
            "recruiter_user_id": str(actor.recruiter_user_id),
            "requesting_organization_id": str(actor.requesting_organization_id),
            "hiring_company_id": str(actor.hiring_company_id),
            "mandate_id": None if actor.mandate_id is None else str(actor.mandate_id),
        },
        "requirement_snapshot": {
            "role_dna": {
                "role_dna_id": str(requirement.role_dna.role_dna_id),
                "version": int(requirement.role_dna.version),
            },
            "opportunity_spec": {
                "opportunity_spec_id": str(requirement.opportunity_spec.opportunity_spec_id),
                "version": int(requirement.opportunity_spec.version),
            },
            "requirement_version": int(requirement.requirement_version),
            "captured_at": _canonical_timestamp(requirement.captured_at),
        },
    })


def transition_command_fingerprint(stream_id, command_kind, expected_version):
    nonblank_identifier(stream_id, "stream_id")
    if command_kind not in (StreamCommandKind.ACTIVATE, StreamCommandKind.CLOSE):
        raise ValueError("unsupported Stream transition command")
    version = positive_entity_version(expected_version, "expected_version")
    return _digest({
        "stream_id": str(stream_id),
        "command_kind": command_kind.value,
        "expected_version": int(version),
    })


def _command_time(value):
    if value is None:
        generated = datetime.now(timezone.utc)
        value = generated.replace(microsecond=(generated.microsecond // 1000) * 1000)
    return utc_millisecond(value, "occurred_at")


def _replay(current, command_id, command_kind, fingerprint):
    matches = [entry for entry in current.history if entry.command_id == command_id]
    if not matches:
        return False
    entry = matches[0]
    if entry.command_kind is command_kind and entry.command_fingerprint == fingerprint:
        return True
    raise TalentStreamConflictError("Talent Stream command identity conflict")


class TalentStreamService:
    def __init__(self, db):
        self.repository = TalentStreamRepository(db)

    async def get(self, stream_id):
        stream_id = nonblank_identifier(stream_id, "stream_id")
        current = await self.repository.get(stream_id)
        if current is None:
            raise TalentStreamNotFoundError("Talent Stream not found")
        return current

    async def create(
        self,
        stream_id,
        recruiting_actor_context,
        requirement_snapshot,
        *,
        command_id,
        occurred_at=None,
    ):
        stream_id = TalentStreamId(nonblank_identifier(stream_id, "stream_id"))
        command_id = nonblank_identifier(command_id, "command_id")
        fingerprint = create_command_fingerprint(
            stream_id, recruiting_actor_context, requirement_snapshot,
        )
        now = _command_time(occurred_at)
        entry = StreamCommandHistoryEntry(
            command_id=command_id,
            command_fingerprint=fingerprint,
            command_kind=StreamCommandKind.CREATE,
            from_state=None,
            to_state=TalentStreamState.DRAFT,
            resulting_version=EntityVersion(1),
            occurred_at=now,
        )
        stream = TalentStream(
            stream_id=stream_id,
            version=EntityVersion(1),
            recruiting_actor_context=recruiting_actor_context,
            requirement_snapshot=requirement_snapshot,
            state=TalentStreamState.DRAFT,
            created_at=now,
            updated_at=now,
            history=(entry,),
        )
        return await self.repository.create(stream)

    async def activate(self, stream_id, *, command_id, expected_version, occurred_at=None):
        return await self._transition(
            stream_id,
            command_id=command_id,
            command_kind=StreamCommandKind.ACTIVATE,
            expected_version=expected_version,
            occurred_at=occurred_at,
        )

    async def close(self, stream_id, *, command_id, expected_version, occurred_at=None):
        return await self._transition(
            stream_id,
            command_id=command_id,
            command_kind=StreamCommandKind.CLOSE,
            expected_version=expected_version,
            occurred_at=occurred_at,
        )

    async def _transition(
        self,
        stream_id,
        *,
        command_id,
        command_kind,
        expected_version,
        occurred_at=None,
    ):
        stream_id = TalentStreamId(nonblank_identifier(stream_id, "stream_id"))
        command_id = nonblank_identifier(command_id, "command_id")
        version = positive_entity_version(expected_version, "expected_version")
        fingerprint = transition_command_fingerprint(stream_id, command_kind, version)
        now = _command_time(occurred_at)
        current = await self.repository.get(str(stream_id))
        if current is None:
            raise TalentStreamNotFoundError("Talent Stream not found")
        if _replay(current, command_id, command_kind, fingerprint):
            return current
        if current.version != version:
            raise TalentStreamConflictError("Talent Stream state or version conflict")
        if command_kind is StreamCommandKind.ACTIVATE:
            if current.state is not TalentStreamState.DRAFT:
                raise TalentStreamConflictError("Talent Stream state or version conflict")
            target = TalentStreamState.ACTIVE
        elif current.state in (TalentStreamState.DRAFT, TalentStreamState.ACTIVE):
            target = TalentStreamState.CLOSED
        else:
            raise TalentStreamConflictError("Talent Stream state or version conflict")
        entry = StreamCommandHistoryEntry(
            command_id=command_id,
            command_fingerprint=fingerprint,
            command_kind=command_kind,
            from_state=current.state,
            to_state=target,
            resulting_version=EntityVersion(int(version) + 1),
            occurred_at=now,
        )
        updated = await self.repository.transition(current, entry)
        if updated is not None:
            return updated
        latest = await self.repository.get(str(stream_id))
        if latest is not None and _replay(latest, command_id, command_kind, fingerprint):
            return latest
        raise TalentStreamConflictError("Talent Stream state or version conflict")
