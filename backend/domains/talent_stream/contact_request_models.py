"""Pure TS-B10 contact-request contracts and deterministic identities.

B10 consumes the identity recorded by B9; it does not re-evaluate Trust,
Permission, Match, Fit, or the B7 projection.  A valid B8 card reference proves
only keyed lineage to a candidate/stream/generation tuple.  It does not prove
that a particular recruiter was historically shown the card, when it was
shown, or that the recruiter is currently authorized.

This module performs no I/O and publishes nothing.  The A14 envelope builder
only freezes the future durable handoff contract for B10 orchestration.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import hmac
import json
import re
from typing import Protocol

from async_outbox.models import JobEnvelope, JobReference, RetryPolicy
from domains.shared.ids import (
    CandidateId,
    ContactRequestId,
    HiringCompanyId,
    IdempotencyKey,
    MandateId,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import SchemaVersion
from domains.talent_stream.anonymous_talent_adapter import (
    derive_anonymous_talent_card_ref,
)
from domains.talent_stream.contracts import RecruitingActorContext
from domains.trust.contact_governor_models import (
    ContactGovernorRequest,
    GovernorReservationState,
    derive_request_fingerprint as derive_governor_request_fingerprint,
    derive_reservation_id as derive_governor_reservation_id,
    require_governor_time,
)


CONTACT_REQUEST_SCHEMA_VERSION = "talent-stream-contact-request-v1"
CONTACT_REQUEST_AGGREGATE_VERSION = 1
CONTACT_REQUEST_ID_PREFIX = "ts-b10-request-v1"
CONTACT_REQUEST_FINGERPRINT_PREFIX = "ts-b10-command-v1"
CONTACT_REQUEST_HANDOFF_JOB_ID_PREFIX = "ts-b10-handoff-v1"
CONTACT_REQUEST_HANDOFF_JOB_TYPE = "talent_stream_contact_request_created"
CONTACT_REQUEST_HANDOFF_PAYLOAD_SCHEMA_VERSION = (
    "talent-stream-contact-request-created-v1"
)
CONTACT_REQUEST_HANDOFF_REFERENCE_TYPE = "talent_stream_contact_request"

_B8_CARD_REF = re.compile(r"^ts-b8-card-v1:[0-9a-f]{64}$")
_B9_RESERVATION_ID = re.compile(r"^ts-b9-reservation-v1:[0-9a-f]{64}$")
_B9_REQUEST_FINGERPRINT = re.compile(r"^ts-b9-request-v1:[0-9a-f]{64}$")
_B10_REQUEST_ID = re.compile(r"^ts-b10-request-v1-[0-9a-f]{64}$")
_B10_COMMAND_FINGERPRINT = re.compile(
    r"^ts-b10-command-v1:[0-9a-f]{64}$"
)
_B10_HANDOFF_JOB_ID = re.compile(r"^ts-b10-handoff-v1-[0-9a-f]{64}$")


def _nonblank(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")
    return value


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be an integer >= 1")
    return value


def _pattern(value: object, pattern: re.Pattern[str], field: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(f"invalid {field}")
    return value


def _validate_actor(actor: object) -> RecruitingActorContext:
    if type(actor) is not RecruitingActorContext:
        raise ValueError("recruiting_actor must be a RecruitingActorContext")
    _nonblank(actor.recruiter_user_id, "recruiting_actor.recruiter_user_id")
    _nonblank(
        actor.requesting_organization_id,
        "recruiting_actor.requesting_organization_id",
    )
    _nonblank(actor.hiring_company_id, "recruiting_actor.hiring_company_id")
    if actor.mandate_id is not None:
        _nonblank(actor.mandate_id, "recruiting_actor.mandate_id")
    return actor


class ContactRequestState(str, Enum):
    """B10 owns only durable creation; candidate lifecycle begins in B11."""

    CREATED = "created"


class ContactRequestCreateOutcome(str, Enum):
    CREATED = "created"
    IDEMPOTENT_REPLAY = "idempotent_replay"


@dataclass(frozen=True, slots=True, repr=False)
class CreateContactRequestCommand:
    """Caller input bound to the already-authorized B9 reservation identity."""

    idempotency_key: IdempotencyKey
    reservation_id: str
    governor_request_fingerprint: str
    anonymous_card_ref: str
    recruiting_actor: RecruitingActorContext

    def __post_init__(self) -> None:
        _nonblank(self.idempotency_key, "idempotency_key")
        _pattern(self.reservation_id, _B9_RESERVATION_ID, "reservation_id")
        _pattern(
            self.governor_request_fingerprint,
            _B9_REQUEST_FINGERPRINT,
            "governor_request_fingerprint",
        )
        _pattern(self.anonymous_card_ref, _B8_CARD_REF, "anonymous_card_ref")
        _validate_actor(self.recruiting_actor)


class GovernorReservationBinding(Protocol):
    """Narrow structural view B10.2 will obtain through the strict B9 port."""

    reservation_id: str
    request_fingerprint: str
    idempotency_key: str
    candidate_id: str
    stream_id: str
    generation_id: str
    projection_state_version: int
    stream_version: int
    requirement_version: int
    role_dna_id: str
    role_dna_version: int
    opportunity_spec_id: str
    opportunity_spec_version: int
    recruiter_user_id: str
    requesting_organization_id: str
    hiring_company_id: str
    mandate_id: str | None
    policy_version: str
    activity_at: datetime
    expires_at: datetime
    status: GovernorReservationState
    contact_request_id: str | None


def derive_contact_request_id(
    command: CreateContactRequestCommand,
) -> ContactRequestId:
    """Derive identity from the same B9 key and minimum actor scope."""

    if type(command) is not CreateContactRequestCommand:
        raise ValueError("command must be CreateContactRequestCommand")
    actor = command.recruiting_actor
    canonical = json.dumps(
        [
            "ts-b10-contact-request-v1",
            str(actor.recruiter_user_id),
            str(actor.requesting_organization_id),
            str(command.idempotency_key),
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return ContactRequestId(f"{CONTACT_REQUEST_ID_PREFIX}-{digest}")


def derive_contact_request_fingerprint(
    command: CreateContactRequestCommand,
) -> str:
    """Fingerprint every material caller field and no clock-derived value."""

    if type(command) is not CreateContactRequestCommand:
        raise ValueError("command must be CreateContactRequestCommand")
    actor = command.recruiting_actor
    canonical = json.dumps(
        {
            "anonymous_card_ref": command.anonymous_card_ref,
            "governor_request_fingerprint": command.governor_request_fingerprint,
            "hiring_company_id": str(actor.hiring_company_id),
            "idempotency_key": str(command.idempotency_key),
            "mandate_id": (
                None if actor.mandate_id is None else str(actor.mandate_id)
            ),
            "recruiter_user_id": str(actor.recruiter_user_id),
            "requesting_organization_id": str(
                actor.requesting_organization_id
            ),
            "reservation_id": command.reservation_id,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return f"{CONTACT_REQUEST_FINGERPRINT_PREFIX}:{digest}"


def derive_contact_request_handoff_job_id(
    contact_request_id: ContactRequestId,
) -> str:
    """Return an A14 opaque-token-compatible deterministic job identity."""

    request_id = _pattern(
        contact_request_id,
        _B10_REQUEST_ID,
        "contact_request_id",
    )
    canonical = json.dumps(
        [CONTACT_REQUEST_HANDOFF_JOB_ID_PREFIX, request_id],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return f"{CONTACT_REQUEST_HANDOFF_JOB_ID_PREFIX}-{digest}"


def _governor_request_from_binding(
    binding: GovernorReservationBinding,
) -> ContactGovernorRequest:
    try:
        actor = RecruitingActorContext(
            recruiter_user_id=RecruiterUserId(binding.recruiter_user_id),
            requesting_organization_id=OrganizationId(
                binding.requesting_organization_id
            ),
            hiring_company_id=HiringCompanyId(binding.hiring_company_id),
            mandate_id=(
                None
                if binding.mandate_id is None
                else MandateId(binding.mandate_id)
            ),
        )
        return ContactGovernorRequest(
            idempotency_key=IdempotencyKey(binding.idempotency_key),
            candidate_id=CandidateId(binding.candidate_id),
            stream_id=TalentStreamId(binding.stream_id),
            generation_id=binding.generation_id,
            projection_state_version=binding.projection_state_version,
            stream_version=binding.stream_version,
            requirement_version=binding.requirement_version,
            role_dna_id=RoleDNAId(binding.role_dna_id),
            role_dna_version=binding.role_dna_version,
            opportunity_spec_id=OpportunitySpecId(binding.opportunity_spec_id),
            opportunity_spec_version=binding.opportunity_spec_version,
            recruiting_actor=actor,
        )
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ValueError("invalid governor reservation binding") from None


def validate_governor_reservation_binding(
    command: CreateContactRequestCommand,
    binding: GovernorReservationBinding,
) -> ContactGovernorRequest:
    """Validate exact B9 identity, subject snapshot, state, and full actor."""

    if type(command) is not CreateContactRequestCommand:
        raise ValueError("command must be CreateContactRequestCommand")
    request = _governor_request_from_binding(binding)
    try:
        activity_at = require_governor_time(binding.activity_at, "activity_at")
        expires_at = require_governor_time(binding.expires_at, "expires_at")
        _nonblank(binding.policy_version, "policy_version")
        if binding.status is not GovernorReservationState.RESERVED:
            raise ValueError("governor reservation is not available")
        if binding.contact_request_id is not None:
            raise ValueError("governor reservation is already bound")
        if expires_at <= activity_at:
            raise ValueError("invalid governor reservation lease")
        if binding.reservation_id != derive_governor_reservation_id(request):
            raise ValueError("governor reservation identity mismatch")
        expected_fingerprint = derive_governor_request_fingerprint(request)
        if binding.request_fingerprint != expected_fingerprint:
            raise ValueError("governor request fingerprint mismatch")
        if command.reservation_id != binding.reservation_id:
            raise ValueError("command reservation identity mismatch")
        if command.governor_request_fingerprint != binding.request_fingerprint:
            raise ValueError("command governor fingerprint mismatch")
        if str(command.idempotency_key) != binding.idempotency_key:
            raise ValueError("command must reuse the governor idempotency key")
        if command.recruiting_actor != request.recruiting_actor:
            raise ValueError("command recruiting actor mismatch")
    except (AttributeError, TypeError, ValueError, OverflowError) as error:
        if isinstance(error, ValueError):
            raise
        raise ValueError("invalid governor reservation binding") from None
    return request


def verify_anonymous_card_lineage(
    command: CreateContactRequestCommand,
    binding: GovernorReservationBinding,
    *,
    card_ref_key: bytes,
) -> None:
    """Verify B8 HMAC lineage only, never historical recruiter exposure.

    The reference binds candidate, stream, and generation using B8's key.  It
    contains no recruiter, delivery, or time claim and grants no permission.
    """

    request = validate_governor_reservation_binding(command, binding)
    expected = derive_anonymous_talent_card_ref(
        key=card_ref_key,
        stream_id=str(request.stream_id),
        generation_id=request.generation_id,
        candidate_id=str(request.candidate_id),
    )
    if not hmac.compare_digest(command.anonymous_card_ref, expected):
        raise ValueError("anonymous card lineage mismatch")


@dataclass(frozen=True, slots=True, repr=False)
class ContactRequest:
    """Internal authoritative B10 aggregate; it reveals or sends nothing."""

    contact_request_id: ContactRequestId
    command_fingerprint: str
    idempotency_key: IdempotencyKey
    reservation_id: str
    governor_request_fingerprint: str
    governor_policy_version: str
    anonymous_card_ref: str
    candidate_id: CandidateId
    stream_id: TalentStreamId
    generation_id: str
    projection_state_version: int
    stream_version: int
    requirement_version: int
    role_dna_id: RoleDNAId
    role_dna_version: int
    opportunity_spec_id: OpportunitySpecId
    opportunity_spec_version: int
    recruiting_actor: RecruitingActorContext
    reservation_activity_at: datetime
    reservation_expires_at: datetime
    created_at: datetime
    handoff_job_id: str
    state: ContactRequestState = ContactRequestState.CREATED
    version: int = CONTACT_REQUEST_AGGREGATE_VERSION
    schema_version: SchemaVersion = SchemaVersion(CONTACT_REQUEST_SCHEMA_VERSION)

    def __post_init__(self) -> None:
        _pattern(self.contact_request_id, _B10_REQUEST_ID, "contact_request_id")
        _pattern(
            self.command_fingerprint,
            _B10_COMMAND_FINGERPRINT,
            "command_fingerprint",
        )
        _nonblank(self.idempotency_key, "idempotency_key")
        _pattern(self.reservation_id, _B9_RESERVATION_ID, "reservation_id")
        _pattern(
            self.governor_request_fingerprint,
            _B9_REQUEST_FINGERPRINT,
            "governor_request_fingerprint",
        )
        _nonblank(self.governor_policy_version, "governor_policy_version")
        _pattern(self.anonymous_card_ref, _B8_CARD_REF, "anonymous_card_ref")
        _nonblank(self.candidate_id, "candidate_id")
        _nonblank(self.stream_id, "stream_id")
        _nonblank(self.generation_id, "generation_id")
        for field in (
            "projection_state_version",
            "stream_version",
            "requirement_version",
            "role_dna_version",
            "opportunity_spec_version",
        ):
            _positive_int(getattr(self, field), field)
        _nonblank(self.role_dna_id, "role_dna_id")
        _nonblank(self.opportunity_spec_id, "opportunity_spec_id")
        _validate_actor(self.recruiting_actor)
        activity_at = require_governor_time(
            self.reservation_activity_at,
            "reservation_activity_at",
        )
        expires_at = require_governor_time(
            self.reservation_expires_at,
            "reservation_expires_at",
        )
        created_at = require_governor_time(self.created_at, "created_at")
        object.__setattr__(self, "reservation_activity_at", activity_at)
        object.__setattr__(self, "reservation_expires_at", expires_at)
        object.__setattr__(self, "created_at", created_at)
        if not activity_at <= created_at < expires_at:
            raise ValueError("created_at must be inside the governor lease")
        _pattern(self.handoff_job_id, _B10_HANDOFF_JOB_ID, "handoff_job_id")
        if type(self.state) is not ContactRequestState:
            raise ValueError("state must be ContactRequestState.CREATED")
        if self.state is not ContactRequestState.CREATED:
            raise ValueError("unsupported contact request state")
        if type(self.version) is not int or self.version != 1:
            raise ValueError("unsupported contact request aggregate version")
        if (
            type(self.schema_version) is not str
            or self.schema_version != CONTACT_REQUEST_SCHEMA_VERSION
        ):
            raise ValueError("unsupported contact request schema version")

        command = CreateContactRequestCommand(
            idempotency_key=self.idempotency_key,
            reservation_id=self.reservation_id,
            governor_request_fingerprint=self.governor_request_fingerprint,
            anonymous_card_ref=self.anonymous_card_ref,
            recruiting_actor=self.recruiting_actor,
        )
        if self.contact_request_id != derive_contact_request_id(command):
            raise ValueError("contact_request_id is not canonical")
        if self.command_fingerprint != derive_contact_request_fingerprint(command):
            raise ValueError("command_fingerprint is not canonical")
        if self.handoff_job_id != derive_contact_request_handoff_job_id(
            self.contact_request_id
        ):
            raise ValueError("handoff_job_id is not canonical")

        governor_request = ContactGovernorRequest(
            idempotency_key=self.idempotency_key,
            candidate_id=self.candidate_id,
            stream_id=self.stream_id,
            generation_id=self.generation_id,
            projection_state_version=self.projection_state_version,
            stream_version=self.stream_version,
            requirement_version=self.requirement_version,
            role_dna_id=self.role_dna_id,
            role_dna_version=self.role_dna_version,
            opportunity_spec_id=self.opportunity_spec_id,
            opportunity_spec_version=self.opportunity_spec_version,
            recruiting_actor=self.recruiting_actor,
        )
        if self.reservation_id != derive_governor_reservation_id(
            governor_request
        ):
            raise ValueError("aggregate governor reservation identity mismatch")
        if self.governor_request_fingerprint != derive_governor_request_fingerprint(
            governor_request
        ):
            raise ValueError("aggregate governor request fingerprint mismatch")


def create_contact_request(
    command: CreateContactRequestCommand,
    binding: GovernorReservationBinding,
    *,
    card_ref_key: bytes,
    created_at: datetime,
) -> ContactRequest:
    """Create an in-memory aggregate after exact B8/B9 binding checks."""

    verify_anonymous_card_lineage(
        command,
        binding,
        card_ref_key=card_ref_key,
    )
    created_at = require_governor_time(created_at, "created_at")
    activity_at = require_governor_time(binding.activity_at, "activity_at")
    expires_at = require_governor_time(binding.expires_at, "expires_at")
    if not activity_at <= created_at < expires_at:
        raise ValueError("created_at must be inside the governor lease")
    request_id = derive_contact_request_id(command)
    return ContactRequest(
        contact_request_id=request_id,
        command_fingerprint=derive_contact_request_fingerprint(command),
        idempotency_key=command.idempotency_key,
        reservation_id=binding.reservation_id,
        governor_request_fingerprint=binding.request_fingerprint,
        governor_policy_version=binding.policy_version,
        anonymous_card_ref=command.anonymous_card_ref,
        candidate_id=CandidateId(binding.candidate_id),
        stream_id=TalentStreamId(binding.stream_id),
        generation_id=binding.generation_id,
        projection_state_version=binding.projection_state_version,
        stream_version=binding.stream_version,
        requirement_version=binding.requirement_version,
        role_dna_id=RoleDNAId(binding.role_dna_id),
        role_dna_version=binding.role_dna_version,
        opportunity_spec_id=OpportunitySpecId(binding.opportunity_spec_id),
        opportunity_spec_version=binding.opportunity_spec_version,
        recruiting_actor=command.recruiting_actor,
        reservation_activity_at=activity_at,
        reservation_expires_at=expires_at,
        created_at=created_at,
        handoff_job_id=derive_contact_request_handoff_job_id(request_id),
    )


@dataclass(frozen=True, slots=True, repr=False)
class CreateContactRequestResult:
    """Recruiter-safe result; internal candidate and opportunity IDs stay hidden."""

    contact_request_id: ContactRequestId
    state: ContactRequestState
    outcome: ContactRequestCreateOutcome
    created_at: datetime

    def __post_init__(self) -> None:
        _pattern(self.contact_request_id, _B10_REQUEST_ID, "contact_request_id")
        if type(self.state) is not ContactRequestState:
            raise ValueError("invalid contact request state")
        if self.state is not ContactRequestState.CREATED:
            raise ValueError("unsupported contact request state")
        if type(self.outcome) is not ContactRequestCreateOutcome:
            raise ValueError("invalid contact request outcome")
        object.__setattr__(
            self,
            "created_at",
            require_governor_time(self.created_at, "created_at"),
        )

    @classmethod
    def from_contact_request(
        cls,
        request: ContactRequest,
        *,
        outcome: ContactRequestCreateOutcome,
    ) -> "CreateContactRequestResult":
        if type(request) is not ContactRequest:
            raise ValueError("request must be ContactRequest")
        return cls(
            contact_request_id=request.contact_request_id,
            state=request.state,
            outcome=outcome,
            created_at=request.created_at,
        )


def build_contact_request_handoff_envelope(
    request: ContactRequest,
    *,
    retry_policy: RetryPolicy,
) -> JobEnvelope:
    """Build, but never publish, the exact future B11 A14 handoff."""

    if type(request) is not ContactRequest:
        raise ValueError("request must be ContactRequest")
    if type(retry_policy) is not RetryPolicy:
        raise ValueError("retry_policy must be explicitly provided")
    return JobEnvelope(
        job_id=request.handoff_job_id,
        job_type=CONTACT_REQUEST_HANDOFF_JOB_TYPE,
        idempotency_key=IdempotencyKey(str(request.contact_request_id)),
        payload_schema_version=SchemaVersion(
            CONTACT_REQUEST_HANDOFF_PAYLOAD_SCHEMA_VERSION
        ),
        reference=JobReference(
            reference_type=CONTACT_REQUEST_HANDOFF_REFERENCE_TYPE,
            reference_id=str(request.contact_request_id),
            reference_version=request.version,
        ),
        retry_policy=retry_policy,
        created_at=request.created_at,
        initial_available_at=request.created_at,
    )


__all__ = [
    "CONTACT_REQUEST_SCHEMA_VERSION",
    "CONTACT_REQUEST_AGGREGATE_VERSION",
    "CONTACT_REQUEST_ID_PREFIX",
    "CONTACT_REQUEST_FINGERPRINT_PREFIX",
    "CONTACT_REQUEST_HANDOFF_JOB_ID_PREFIX",
    "CONTACT_REQUEST_HANDOFF_JOB_TYPE",
    "CONTACT_REQUEST_HANDOFF_PAYLOAD_SCHEMA_VERSION",
    "CONTACT_REQUEST_HANDOFF_REFERENCE_TYPE",
    "ContactRequestState",
    "ContactRequestCreateOutcome",
    "CreateContactRequestCommand",
    "GovernorReservationBinding",
    "ContactRequest",
    "CreateContactRequestResult",
    "derive_contact_request_id",
    "derive_contact_request_fingerprint",
    "derive_contact_request_handoff_job_id",
    "validate_governor_reservation_binding",
    "verify_anonymous_card_lineage",
    "create_contact_request",
    "build_contact_request_handoff_envelope",
]
