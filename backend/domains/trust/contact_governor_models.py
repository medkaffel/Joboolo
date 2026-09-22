"""Trust-owned contracts for the Contact Governor safety gate.

These contracts deliberately contain only derived classifications needed to
decide whether a recruiter invitation may be reserved.  They are not Match or
Opportunity Fit domain models, and they do not grant contact, identity, CV, or
messaging access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Optional, Protocol, Tuple

from domains.shared.ids import (
    CandidateId,
    IdempotencyKey,
    OpportunitySpecId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import PolicyVersion
from domains.talent_stream.contracts import RecruitingActorContext
from domains.talent_stream.decisions import PermissionDecision, TrustDecision


class ContactGovernorReasonCode(str, Enum):
    """Closed, recruiter-safe reason vocabulary for B9."""

    ALLOWED = "allowed"
    ALLOWED_IDEMPOTENT_REPLAY = "allowed_idempotent_replay"
    TRUST_DENIED = "trust_denied"
    PERMISSION_DENIED = "permission_denied"
    CANDIDATE_FACTS_MISSING = "candidate_facts_missing"
    CANDIDATE_FACTS_STALE = "candidate_facts_stale"
    PROFESSIONAL_MATCH_MISSING = "professional_match_missing"
    HARD_ELIGIBILITY_INELIGIBLE = "hard_eligibility_ineligible"
    HARD_ELIGIBILITY_UNRESOLVED = "hard_eligibility_unresolved"
    OPPORTUNITY_FIT_MISSING = "opportunity_fit_missing"
    OPPORTUNITY_FIT_INCOMPATIBLE = "opportunity_fit_incompatible"
    OPPORTUNITY_FIT_UNRESOLVED = "opportunity_fit_unresolved"
    PROFESSIONAL_MATCH_BELOW_THRESHOLD = "professional_match_below_threshold"
    DUPLICATE_CONTACT = "duplicate_contact"
    FREQUENCY_CAP_REACHED = "frequency_cap_reached"
    COMPANY_COOLING_ACTIVE = "company_cooling_active"
    ACTIVE_RESERVATION_LIMIT_REACHED = "active_reservation_limit_reached"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    GOVERNOR_UNAVAILABLE = "governor_unavailable"


class GovernorFactsStatus(str, Enum):
    CURRENT = "current"
    MISSING = "missing"
    STALE = "stale"


class GovernorMatchClassification(str, Enum):
    """Governor input derived by an adapter from the authoritative Match result."""

    PRESENT = "present"
    MISSING = "missing"


class GovernorEligibilityClassification(str, Enum):
    """Governor input derived from the authoritative hard-eligibility result."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    UNRESOLVED = "unresolved"


class GovernorFitClassification(str, Enum):
    """Governor input derived by an adapter from authoritative Opportunity Fit."""

    COMPATIBLE = "compatible"
    NOT_APPLICABLE = "not_applicable"
    INCOMPATIBLE = "incompatible"
    UNRESOLVED = "unresolved"
    MISSING = "missing"


class GovernorFrequencyScope(str, Enum):
    CANDIDATE_GLOBAL = "candidate_global"
    RECRUITER_CANDIDATE = "recruiter_candidate"
    REQUESTING_ORGANIZATION_CANDIDATE = "requesting_organization_candidate"
    HIRING_COMPANY_CANDIDATE = "hiring_company_candidate"


class GovernorDuplicateScope(str, Enum):
    STREAM_CANDIDATE_RECRUITER = "stream_candidate_recruiter"
    STREAM_CANDIDATE_REQUESTING_ORGANIZATION = "stream_candidate_requesting_organization"
    STREAM_CANDIDATE_HIRING_COMPANY = "stream_candidate_hiring_company"


class GovernorCompanyCoolingScope(str, Enum):
    REQUESTING_ORGANIZATION_CANDIDATE = "requesting_organization_candidate"
    HIRING_COMPANY_CANDIDATE = "hiring_company_candidate"


def _nonblank(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be a non-blank string")
    return value


def _positive_int(value: object, field: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{field} must be an integer >= 1")
    return value


def _strict_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return value


def _score(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError(f"{field} must be an integer between 0 and 100")
    return value


def _positive_duration(value: object, field: str) -> timedelta:
    if type(value) is not timedelta or value <= timedelta(0):
        raise ValueError(f"{field} must be a positive timedelta")
    if value % timedelta(milliseconds=1):
        raise ValueError(f"{field} must be an exact whole number of milliseconds")
    return value


def require_governor_time(value: object, field: str) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be an aware datetime")
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond % 1000:
        raise ValueError(f"{field} must have millisecond precision")
    return normalized


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


@dataclass(frozen=True, slots=True, repr=False)
class ContactGovernorRequest:
    """Strict command identity; policy selection is intentionally absent."""

    idempotency_key: IdempotencyKey
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

    def __post_init__(self) -> None:
        _nonblank(self.idempotency_key, "idempotency_key")
        _nonblank(self.candidate_id, "candidate_id")
        _nonblank(self.stream_id, "stream_id")
        _nonblank(self.generation_id, "generation_id")
        _positive_int(self.projection_state_version, "projection_state_version")
        _positive_int(self.stream_version, "stream_version")
        _positive_int(self.requirement_version, "requirement_version")
        _nonblank(self.role_dna_id, "role_dna_id")
        _positive_int(self.role_dna_version, "role_dna_version")
        _nonblank(self.opportunity_spec_id, "opportunity_spec_id")
        _positive_int(self.opportunity_spec_version, "opportunity_spec_version")
        _validate_actor(self.recruiting_actor)


@dataclass(frozen=True, slots=True)
class GovernorFrequencyCap:
    scope: GovernorFrequencyScope
    maximum_activity_count: int
    window: timedelta

    def __post_init__(self) -> None:
        if type(self.scope) is not GovernorFrequencyScope:
            raise ValueError("frequency cap scope must be GovernorFrequencyScope")
        _positive_int(self.maximum_activity_count, "maximum_activity_count")
        _positive_duration(self.window, "frequency cap window")


@dataclass(frozen=True, slots=True)
class FrequencyCapPolicy:
    enabled: bool
    caps: Optional[Tuple[GovernorFrequencyCap, ...]]

    def __post_init__(self) -> None:
        _strict_bool(self.enabled, "frequency cap policy enabled")
        if not self.enabled:
            if self.caps is not None:
                raise ValueError("disabled frequency cap policy must not define caps")
            return
        if type(self.caps) is not tuple or not self.caps:
            raise ValueError("enabled frequency cap policy requires a non-empty caps tuple")
        seen = set()
        for cap in self.caps:
            if type(cap) is not GovernorFrequencyCap:
                raise ValueError("frequency cap policy requires GovernorFrequencyCap values")
            key = (cap.scope, cap.window)
            if key in seen:
                raise ValueError("frequency cap policy must not duplicate a scope/window")
            seen.add(key)


@dataclass(frozen=True, slots=True)
class DuplicateProtectionPolicy:
    enabled: bool
    scope: Optional[GovernorDuplicateScope]
    window: Optional[timedelta]

    def __post_init__(self) -> None:
        _strict_bool(self.enabled, "duplicate protection policy enabled")
        if not self.enabled:
            if self.scope is not None or self.window is not None:
                raise ValueError(
                    "disabled duplicate protection policy must not define scope or window"
                )
            return
        if type(self.scope) is not GovernorDuplicateScope:
            raise ValueError("enabled duplicate protection policy requires a scope")
        _positive_duration(self.window, "duplicate protection window")


@dataclass(frozen=True, slots=True)
class CompanyCoolingPolicy:
    enabled: bool
    scope: Optional[GovernorCompanyCoolingScope]
    period: Optional[timedelta]

    def __post_init__(self) -> None:
        _strict_bool(self.enabled, "company cooling policy enabled")
        if not self.enabled:
            if self.scope is not None or self.period is not None:
                raise ValueError(
                    "disabled company cooling policy must not define scope or period"
                )
            return
        if type(self.scope) is not GovernorCompanyCoolingScope:
            raise ValueError("enabled company cooling policy requires a scope")
        _positive_duration(self.period, "company cooling period")


@dataclass(frozen=True, slots=True)
class ActiveReservationLimitPolicy:
    enabled: bool
    maximum_active_reservations: Optional[int]

    def __post_init__(self) -> None:
        _strict_bool(self.enabled, "active reservation limit policy enabled")
        if not self.enabled:
            if self.maximum_active_reservations is not None:
                raise ValueError(
                    "disabled active reservation limit policy must not define a maximum"
                )
            return
        _positive_int(
            self.maximum_active_reservations,
            "maximum_active_reservations",
        )


@dataclass(frozen=True, slots=True)
class ContactGovernorPolicyV1:
    """Complete injected B9 v1 policy; every value is explicit and required."""

    policy_version: PolicyVersion
    minimum_professional_match_score: int
    frequency_cap_policy: FrequencyCapPolicy
    duplicate_protection_policy: DuplicateProtectionPolicy
    company_cooling_policy: CompanyCoolingPolicy
    active_reservation_limit_policy: ActiveReservationLimitPolicy
    reservation_lease: timedelta

    def __post_init__(self) -> None:
        _nonblank(self.policy_version, "policy_version")
        _score(
            self.minimum_professional_match_score,
            "minimum_professional_match_score",
        )
        if type(self.frequency_cap_policy) is not FrequencyCapPolicy:
            raise ValueError("frequency_cap_policy must be FrequencyCapPolicy")
        if type(self.duplicate_protection_policy) is not DuplicateProtectionPolicy:
            raise ValueError(
                "duplicate_protection_policy must be DuplicateProtectionPolicy"
            )
        if type(self.company_cooling_policy) is not CompanyCoolingPolicy:
            raise ValueError("company_cooling_policy must be CompanyCoolingPolicy")
        if type(self.active_reservation_limit_policy) is not ActiveReservationLimitPolicy:
            raise ValueError(
                "active_reservation_limit_policy must be ActiveReservationLimitPolicy"
            )
        _positive_duration(self.reservation_lease, "reservation_lease")


@dataclass(frozen=True, slots=True, repr=False)
class GovernorCandidateFacts:
    """Current, derived gating facts bound to one exact B7 projection input."""

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
    match_classification: GovernorMatchClassification
    professional_match_score: Optional[int]
    eligibility_classification: GovernorEligibilityClassification
    fit_classification: GovernorFitClassification

    def __post_init__(self) -> None:
        _nonblank(self.candidate_id, "candidate_id")
        _nonblank(self.stream_id, "stream_id")
        _nonblank(self.generation_id, "generation_id")
        _positive_int(self.projection_state_version, "projection_state_version")
        _positive_int(self.stream_version, "stream_version")
        _positive_int(self.requirement_version, "requirement_version")
        _nonblank(self.role_dna_id, "role_dna_id")
        _positive_int(self.role_dna_version, "role_dna_version")
        _nonblank(self.opportunity_spec_id, "opportunity_spec_id")
        _positive_int(self.opportunity_spec_version, "opportunity_spec_version")
        if type(self.match_classification) is not GovernorMatchClassification:
            raise ValueError("match_classification must be GovernorMatchClassification")
        if self.match_classification is GovernorMatchClassification.PRESENT:
            _score(self.professional_match_score, "professional_match_score")
        elif self.professional_match_score is not None:
            raise ValueError("missing Match must not carry a score")
        if type(self.eligibility_classification) is not GovernorEligibilityClassification:
            raise ValueError(
                "eligibility_classification must be GovernorEligibilityClassification"
            )
        if type(self.fit_classification) is not GovernorFitClassification:
            raise ValueError("fit_classification must be GovernorFitClassification")

    def matches(self, request: ContactGovernorRequest) -> bool:
        return (
            self.candidate_id == request.candidate_id
            and self.stream_id == request.stream_id
            and self.generation_id == request.generation_id
            and self.projection_state_version == request.projection_state_version
            and self.stream_version == request.stream_version
            and self.requirement_version == request.requirement_version
            and self.role_dna_id == request.role_dna_id
            and self.role_dna_version == request.role_dna_version
            and self.opportunity_spec_id == request.opportunity_spec_id
            and self.opportunity_spec_version == request.opportunity_spec_version
        )


@dataclass(frozen=True, slots=True, repr=False)
class GovernorFactsReadResult:
    status: GovernorFactsStatus
    facts: Optional[GovernorCandidateFacts]

    def __post_init__(self) -> None:
        if type(self.status) is not GovernorFactsStatus:
            raise ValueError("status must be GovernorFactsStatus")
        if self.status is GovernorFactsStatus.CURRENT:
            if type(self.facts) is not GovernorCandidateFacts:
                raise ValueError("current facts result requires GovernorCandidateFacts")
        elif self.facts is not None:
            raise ValueError("missing or stale facts result must not carry facts")


def reservation_actor_scope(request: ContactGovernorRequest) -> Tuple[str, str]:
    """Minimum B9 actor scope: recruiter user plus requesting organization."""

    return (
        str(request.recruiting_actor.recruiter_user_id),
        str(request.recruiting_actor.requesting_organization_id),
    )


def derive_reservation_id(request: ContactGovernorRequest) -> str:
    actor_scope = reservation_actor_scope(request)
    canonical = json.dumps(
        ["ts-b9-reservation-v1", *actor_scope, str(request.idempotency_key)],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return f"ts-b9-reservation-v1:{sha256(canonical.encode('utf-8')).hexdigest()}"


def derive_request_fingerprint(request: ContactGovernorRequest) -> str:
    """Fingerprint payload separately from the scoped idempotency identity."""

    actor = request.recruiting_actor
    canonical = json.dumps(
        {
            "candidate_id": str(request.candidate_id),
            "generation_id": request.generation_id,
            "hiring_company_id": str(actor.hiring_company_id),
            "mandate_id": None if actor.mandate_id is None else str(actor.mandate_id),
            "opportunity_spec_id": str(request.opportunity_spec_id),
            "opportunity_spec_version": request.opportunity_spec_version,
            "projection_state_version": request.projection_state_version,
            "recruiter_user_id": str(actor.recruiter_user_id),
            "requesting_organization_id": str(actor.requesting_organization_id),
            "requirement_version": request.requirement_version,
            "role_dna_id": str(request.role_dna_id),
            "role_dna_version": request.role_dna_version,
            "stream_id": str(request.stream_id),
            "stream_version": request.stream_version,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"ts-b9-request-v1:{sha256(canonical.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True, slots=True, repr=False)
class GovernorReservationCommand:
    """Atomic ledger input.

    A later implementation must count active, non-expired ``reserved`` entries
    provisionally and ``consumed`` entries as activity. ``released`` entries and
    expired unconsumed reservations do not count. The activity timestamp is the
    immutable reservation creation timestamp.
    """

    request: ContactGovernorRequest
    policy: ContactGovernorPolicyV1
    evaluated_at: datetime
    reservation_id: str
    request_fingerprint: str
    reservation_expires_at: datetime

    def __post_init__(self) -> None:
        if type(self.request) is not ContactGovernorRequest:
            raise ValueError("request must be ContactGovernorRequest")
        if type(self.policy) is not ContactGovernorPolicyV1:
            raise ValueError("policy must be ContactGovernorPolicyV1")
        evaluated_at = require_governor_time(self.evaluated_at, "evaluated_at")
        expires_at = require_governor_time(
            self.reservation_expires_at,
            "reservation_expires_at",
        )
        if self.reservation_id != derive_reservation_id(self.request):
            raise ValueError("reservation_id must use the canonical actor-scoped identity")
        if self.request_fingerprint != derive_request_fingerprint(self.request):
            raise ValueError("request_fingerprint must use the canonical request payload")
        if expires_at != evaluated_at + self.policy.reservation_lease:
            raise ValueError("reservation expiry must equal evaluated_at plus policy lease")


class GovernorReservationOutcome(str, Enum):
    RESERVED = "reserved"
    IDEMPOTENT_REPLAY = "idempotent_replay"
    DUPLICATE = "duplicate"
    FREQUENCY_CAP_REACHED = "frequency_cap_reached"
    COMPANY_COOLING_ACTIVE = "company_cooling_active"
    ACTIVE_RESERVATION_LIMIT_REACHED = "active_reservation_limit_reached"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"


class GovernorReservationState(str, Enum):
    """Closed lifecycle vocabulary for the future ledger implementation."""

    RESERVED = "reserved"
    CONSUMED = "consumed"
    RELEASED = "released"


@dataclass(frozen=True, slots=True, repr=False)
class GovernorReservationResult:
    outcome: GovernorReservationOutcome
    reservation_id: Optional[str] = None
    reservation_expires_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if type(self.outcome) is not GovernorReservationOutcome:
            raise ValueError("outcome must be GovernorReservationOutcome")
        allowed = self.outcome in {
            GovernorReservationOutcome.RESERVED,
            GovernorReservationOutcome.IDEMPOTENT_REPLAY,
        }
        if allowed:
            _nonblank(self.reservation_id, "reservation_id")
            require_governor_time(
                self.reservation_expires_at,
                "reservation_expires_at",
            )
        elif self.reservation_id is not None or self.reservation_expires_at is not None:
            raise ValueError("denied reservation result must not expose reservation data")


class CurrentRecruitingTrustEvaluator(Protocol):
    async def evaluate_current_trust(
        self,
        recruiting_actor: RecruitingActorContext,
        *,
        evaluated_at: datetime,
    ) -> TrustDecision: ...


class IntroductionPermissionEvaluator(Protocol):
    async def evaluate_introduction_permission(
        self,
        *,
        candidate_id: CandidateId,
        stream_id: TalentStreamId,
        recruiting_actor: RecruitingActorContext,
        evaluated_at: datetime,
    ) -> PermissionDecision: ...


class CurrentGovernorFactsReader(Protocol):
    async def read_current_governor_facts(
        self,
        request: ContactGovernorRequest,
    ) -> GovernorFactsReadResult: ...


class ContactGovernorReservationLedger(Protocol):
    """Atomic reservation boundary for B9.2.

    ``reserve`` owns one atomic check-and-create critical section for
    deduplication, frequency, cooling, and active-reservation limits. Active,
    non-expired ``reserved`` entries count provisionally; ``consumed`` entries
    count as activity; ``released`` entries and expired unconsumed reservations
    do not count. The activity timestamp is immutable from reservation creation.
    Reservation identity is actor scope plus idempotency key; the independent
    request fingerprint must reject reuse of that scoped key for a different
    request. ``consume`` uses only its caller-owned ``evaluated_at`` and never
    reads a wall clock. That time must satisfy the governor's timezone-aware,
    whole-millisecond contract. A reserved entry may be consumed only before
    its lease expiry; equality is expired. Re-consuming with the same contact
    request is idempotent even after the former lease expires, while a different
    contact request conflicts. Released entries cannot be consumed. Releasing
    an already released entry is idempotent, and consumed entries cannot be
    released. A supplied session remains opaque to this core contract and must
    participate in its caller-owned transaction.
    """

    async def reserve(
        self,
        command: GovernorReservationCommand,
    ) -> GovernorReservationResult: ...

    async def consume(
        self,
        reservation_id: str,
        contact_request_id: str,
        *,
        evaluated_at: datetime,
        session=None,
    ) -> None: ...

    async def release(
        self,
        reservation_id: str,
        *,
        session=None,
    ) -> None: ...
