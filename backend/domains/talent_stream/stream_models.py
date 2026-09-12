"""Pure TS-B1 Talent Stream aggregate and lifecycle contracts.

These immutable models record only Stream identity, the exact A0 requirement
and recruiting-actor context, and the bounded B1 lifecycle.  They do not grant
Trust or Permission and contain no candidate, reveal, contact or CV state.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

from bson.int64 import Int64

from domains.shared.ids import TalentStreamId
from domains.shared.versioning import EntityVersion, SchemaVersion
from domains.talent_stream.contracts import (
    OpportunitySpecificationRef,
    RecruitingActorContext,
    RoleDNARef,
    StreamRequirementSnapshot,
)


TALENT_STREAM_SCHEMA_VERSION = "talent-stream-v1"
MAX_TALENT_STREAM_HISTORY_ENTRIES = 3


class TalentStreamState(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class StreamCommandKind(str, Enum):
    CREATE = "create"
    ACTIVATE = "activate"
    CLOSE = "close"


def nonblank_identifier(value: str, field_name: str) -> str:
    """Validate an A0 opaque identifier without changing its representation."""
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be a nonblank string")
    return value


def positive_entity_version(value: int, field_name: str) -> EntityVersion:
    """Normalize Python/BSON integers while rejecting bool and invalid versions."""
    if isinstance(value, bool) or not isinstance(value, (int, Int64)) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return EntityVersion(int(value))


def utc_millisecond(value: datetime, field_name: str) -> datetime:
    """Require an aware instant and normalize it to BSON-compatible UTC."""
    if type(value) is not datetime or value.tzinfo is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")
    try:
        if value.utcoffset() is None:
            raise ValueError
        normalized = value.astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a valid UTC datetime") from None
    if normalized.microsecond % 1000:
        raise ValueError(f"{field_name} must use BSON millisecond precision")
    return normalized


def _validate_recruiting_actor(context: RecruitingActorContext) -> None:
    if type(context) is not RecruitingActorContext:
        raise ValueError("invalid recruiting actor context")
    nonblank_identifier(context.recruiter_user_id, "recruiter_user_id")
    nonblank_identifier(context.requesting_organization_id, "requesting_organization_id")
    nonblank_identifier(context.hiring_company_id, "hiring_company_id")
    if context.mandate_id is not None:
        nonblank_identifier(context.mandate_id, "mandate_id")


def _validate_requirement(snapshot: StreamRequirementSnapshot) -> None:
    if type(snapshot) is not StreamRequirementSnapshot:
        raise ValueError("invalid Stream requirement snapshot")
    if type(snapshot.role_dna) is not RoleDNARef:
        raise ValueError("invalid Role DNA reference")
    if type(snapshot.opportunity_spec) is not OpportunitySpecificationRef:
        raise ValueError("invalid Opportunity Specification reference")
    nonblank_identifier(snapshot.role_dna.role_dna_id, "role_dna_id")
    positive_entity_version(snapshot.role_dna.version, "role_dna.version")
    nonblank_identifier(
        snapshot.opportunity_spec.opportunity_spec_id,
        "opportunity_spec_id",
    )
    positive_entity_version(
        snapshot.opportunity_spec.version,
        "opportunity_spec.version",
    )
    positive_entity_version(snapshot.requirement_version, "requirement_version")
    utc_millisecond(snapshot.captured_at, "requirement.captured_at")
    if snapshot.captured_at.utcoffset() != timedelta(0):
        raise ValueError("requirement.captured_at must be UTC")


@dataclass(frozen=True, slots=True, repr=False)
class StreamCommandHistoryEntry:
    """Minimal evidence for one applied B1 command, never a generic audit event."""

    command_id: str
    command_fingerprint: str
    command_kind: StreamCommandKind
    from_state: TalentStreamState | None
    to_state: TalentStreamState
    resulting_version: EntityVersion
    occurred_at: datetime

    def __post_init__(self) -> None:
        nonblank_identifier(self.command_id, "command_id")
        nonblank_identifier(self.command_fingerprint, "command_fingerprint")
        if type(self.command_kind) is not StreamCommandKind:
            raise ValueError("unsupported Stream command kind")
        if self.from_state is not None and type(self.from_state) is not TalentStreamState:
            raise ValueError("unsupported prior Stream state")
        if type(self.to_state) is not TalentStreamState:
            raise ValueError("unsupported resulting Stream state")
        object.__setattr__(
            self,
            "resulting_version",
            positive_entity_version(self.resulting_version, "resulting_version"),
        )
        object.__setattr__(
            self,
            "occurred_at",
            utc_millisecond(self.occurred_at, "occurred_at"),
        )


_LEGAL_TRANSITIONS = {
    StreamCommandKind.CREATE: (None, TalentStreamState.DRAFT),
    StreamCommandKind.ACTIVATE: (TalentStreamState.DRAFT, TalentStreamState.ACTIVE),
    StreamCommandKind.CLOSE: None,
}


@dataclass(frozen=True, slots=True, repr=False)
class TalentStream:
    """Authoritative, single-document B1 aggregate snapshot."""

    stream_id: TalentStreamId
    version: EntityVersion
    recruiting_actor_context: RecruitingActorContext
    requirement_snapshot: StreamRequirementSnapshot
    state: TalentStreamState
    created_at: datetime
    updated_at: datetime
    history: tuple[StreamCommandHistoryEntry, ...]
    schema_version: SchemaVersion = SchemaVersion(TALENT_STREAM_SCHEMA_VERSION)

    def __post_init__(self) -> None:
        nonblank_identifier(self.stream_id, "stream_id")
        if type(self.schema_version) is not str or self.schema_version != TALENT_STREAM_SCHEMA_VERSION:
            raise ValueError("unsupported Talent Stream schema version")
        object.__setattr__(
            self,
            "version",
            positive_entity_version(self.version, "version"),
        )
        _validate_recruiting_actor(self.recruiting_actor_context)
        _validate_requirement(self.requirement_snapshot)
        if type(self.state) is not TalentStreamState:
            raise ValueError("unsupported Talent Stream state")
        created_at = utc_millisecond(self.created_at, "created_at")
        updated_at = utc_millisecond(self.updated_at, "updated_at")
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        if updated_at < created_at:
            raise ValueError("updated_at cannot predate created_at")
        if self.requirement_snapshot.captured_at > created_at:
            raise ValueError("requirement snapshot cannot postdate Stream creation")
        if type(self.history) is not tuple:
            raise ValueError("Stream history must be an immutable tuple")
        if not 1 <= len(self.history) <= MAX_TALENT_STREAM_HISTORY_ENTRIES:
            raise ValueError("Stream history is outside B1 bounds")
        if any(type(entry) is not StreamCommandHistoryEntry for entry in self.history):
            raise ValueError("invalid Stream history entry")
        if len({entry.command_id for entry in self.history}) != len(self.history):
            raise ValueError("Stream command IDs must be unique")

        previous_state = None
        previous_at = created_at
        for position, entry in enumerate(self.history, start=1):
            if entry.resulting_version != position:
                raise ValueError("Stream history versions must be contiguous")
            if entry.occurred_at < previous_at:
                raise ValueError("Stream history timestamps must be monotonic")
            expected = _LEGAL_TRANSITIONS[entry.command_kind]
            if entry.command_kind is StreamCommandKind.CLOSE:
                legal_close = (
                    (TalentStreamState.DRAFT, TalentStreamState.CLOSED),
                    (TalentStreamState.ACTIVE, TalentStreamState.CLOSED),
                )
                if (entry.from_state, entry.to_state) not in legal_close:
                    raise ValueError("illegal Stream close transition")
            elif (entry.from_state, entry.to_state) != expected:
                raise ValueError("illegal Stream lifecycle transition")
            if entry.from_state is not previous_state:
                raise ValueError("discontinuous Stream history")
            previous_state = entry.to_state
            previous_at = entry.occurred_at

        first, last = self.history[0], self.history[-1]
        if first.command_kind is not StreamCommandKind.CREATE or first.occurred_at != created_at:
            raise ValueError("Stream history must begin with creation")
        if self.version != len(self.history):
            raise ValueError("aggregate version must match Stream history")
        if self.state is not last.to_state:
            raise ValueError("aggregate state must match Stream history")
        if updated_at != last.occurred_at:
            raise ValueError("updated_at must match the latest Stream command")
