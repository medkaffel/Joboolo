"""Recruiter membership, verification and mandate contracts for TS-A8."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple

from domains.shared.ids import HiringCompanyId, MandateId, MembershipId, OrganizationId, RecruiterUserId
from domains.shared.versioning import EntityVersion, PolicyVersion


def _text(value: str, field: str) -> str:
    normalized = " ".join((value or "").strip().split())
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized


def _aware(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value


def _refs(values: Tuple[str, ...]) -> Tuple[str, ...]:
    out = tuple(_text(value, "evidence_ref") for value in values)
    if len(set(out)) != len(out):
        raise ValueError("evidence refs must be unique")
    return out


class MembershipRole(str, Enum):
    RECRUITER = "recruiter"
    ORG_ADMIN = "org_admin"


class MembershipState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class MembershipReasonCode(str, Enum):
    MEMBERSHIP_REQUESTED = "membership_requested"
    RELATION_CONFIRMED = "relation_confirmed"
    MANUAL_REVIEW_APPROVED = "manual_review_approved"
    RELATION_SUSPENDED = "relation_suspended"
    RELATION_ENDED = "relation_ended"
    POLICY_VIOLATION = "policy_violation"
    MANUAL_REVOKE = "manual_revoke"


_MEMBERSHIP_REASONS = {
    MembershipState.PENDING: {MembershipReasonCode.MEMBERSHIP_REQUESTED},
    MembershipState.ACTIVE: {MembershipReasonCode.RELATION_CONFIRMED, MembershipReasonCode.MANUAL_REVIEW_APPROVED},
    MembershipState.SUSPENDED: {MembershipReasonCode.RELATION_SUSPENDED, MembershipReasonCode.POLICY_VIOLATION},
    MembershipState.REVOKED: {MembershipReasonCode.RELATION_ENDED, MembershipReasonCode.POLICY_VIOLATION, MembershipReasonCode.MANUAL_REVOKE},
}


class RecruiterVerificationState(str, Enum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class RecruiterVerificationReasonCode(str, Enum):
    RECORD_CREATED = "record_created"
    VERIFICATION_REQUESTED = "verification_requested"
    IDENTITY_CONFIRMED = "identity_confirmed"
    MANUAL_REVIEW_APPROVED = "manual_review_approved"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    IDENTITY_MISMATCH = "identity_mismatch"
    POLICY_VIOLATION = "policy_violation"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    MANUAL_SUSPENSION = "manual_suspension"
    REVERIFICATION_APPROVED = "reverification_approved"


_RECRUITER_REASONS = {
    RecruiterVerificationState.UNVERIFIED: {RecruiterVerificationReasonCode.RECORD_CREATED},
    RecruiterVerificationState.PENDING: {RecruiterVerificationReasonCode.VERIFICATION_REQUESTED},
    RecruiterVerificationState.VERIFIED: {RecruiterVerificationReasonCode.IDENTITY_CONFIRMED, RecruiterVerificationReasonCode.MANUAL_REVIEW_APPROVED, RecruiterVerificationReasonCode.REVERIFICATION_APPROVED},
    RecruiterVerificationState.REJECTED: {RecruiterVerificationReasonCode.EVIDENCE_INSUFFICIENT, RecruiterVerificationReasonCode.IDENTITY_MISMATCH, RecruiterVerificationReasonCode.POLICY_VIOLATION},
    RecruiterVerificationState.SUSPENDED: {RecruiterVerificationReasonCode.SUSPICIOUS_ACTIVITY, RecruiterVerificationReasonCode.POLICY_VIOLATION, RecruiterVerificationReasonCode.MANUAL_SUSPENSION},
}


class MandateState(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REJECTED = "rejected"
    REVOKED = "revoked"


class MandateReasonCode(str, Enum):
    MANDATE_SUBMITTED = "mandate_submitted"
    MANDATE_CONFIRMED = "mandate_confirmed"
    MANUAL_REVIEW_APPROVED = "manual_review_approved"
    MANDATE_SUSPENDED = "mandate_suspended"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    PARTIES_MISMATCH = "parties_mismatch"
    POLICY_VIOLATION = "policy_violation"
    MANDATE_REVOKED = "mandate_revoked"
    RELATION_ENDED = "relation_ended"
    REACTIVATED = "reactivated"


_MANDATE_REASONS = {
    MandateState.PENDING: {MandateReasonCode.MANDATE_SUBMITTED},
    MandateState.ACTIVE: {MandateReasonCode.MANDATE_CONFIRMED, MandateReasonCode.MANUAL_REVIEW_APPROVED, MandateReasonCode.REACTIVATED},
    MandateState.SUSPENDED: {MandateReasonCode.MANDATE_SUSPENDED, MandateReasonCode.POLICY_VIOLATION},
    MandateState.REJECTED: {MandateReasonCode.EVIDENCE_INSUFFICIENT, MandateReasonCode.PARTIES_MISMATCH, MandateReasonCode.POLICY_VIOLATION},
    MandateState.REVOKED: {MandateReasonCode.MANDATE_REVOKED, MandateReasonCode.RELATION_ENDED, MandateReasonCode.POLICY_VIOLATION},
}


class RecruitingTrustSubjectType(str, Enum):
    MEMBERSHIP = "membership"
    RECRUITER_VERIFICATION = "recruiter_verification"
    MANDATE = "mandate"


class RecruitingTrustReasonCode(str, Enum):
    RECRUITER_USER_NOT_FOUND = "recruiter_user_not_found"
    RECRUITER_USER_INACTIVE = "recruiter_user_inactive"
    RECRUITER_USER_TYPE_UNSUPPORTED = "recruiter_user_type_unsupported"
    REQUESTING_ORGANIZATION_NOT_VERIFIED = "requesting_organization_not_verified"
    MEMBERSHIP_NOT_ACTIVE = "membership_not_active"
    RECRUITER_NOT_VERIFIED = "recruiter_not_verified"
    HIRING_COMPANY_NOT_VERIFIED = "hiring_company_not_verified"
    MANDATE_REQUIRED = "mandate_required"
    MANDATE_NOT_FOUND = "mandate_not_found"
    MANDATE_PARTIES_MISMATCH = "mandate_parties_mismatch"
    MANDATE_NOT_ACTIVE = "mandate_not_active"
    MANDATE_NOT_YET_VALID = "mandate_not_yet_valid"
    MANDATE_EXPIRED = "mandate_expired"
    RECRUITING_ACTOR_TRUSTED = "recruiting_actor_trusted"


def _decision_metadata(state, reasons, evidence, policy_version, actor_id, decided_at, allowed_reasons, *, evidence_required=False):
    reasons = tuple(reasons)
    evidence = _refs(tuple(evidence))
    if not reasons:
        raise ValueError("decision requires reason codes")
    if any(reason not in allowed_reasons[state] for reason in reasons):
        raise ValueError(f"reason codes are inconsistent with state {state.value}")
    if not str(policy_version).strip():
        raise ValueError("policy_version is required")
    _text(actor_id, "actor_id")
    if decided_at is None:
        raise ValueError("decided_at is required")
    _aware(decided_at, "decided_at")
    if evidence_required and not evidence:
        raise ValueError(f"{state.value} requires evidence")
    return reasons, evidence


@dataclass(frozen=True)
class OrganizationMembership:
    membership_id: MembershipId
    recruiter_user_id: RecruiterUserId
    organization_id: OrganizationId
    version: EntityVersion
    role: MembershipRole
    state: MembershipState
    policy_version: PolicyVersion
    reason_codes: Tuple[MembershipReasonCode, ...]
    evidence_refs: Tuple[str, ...]
    actor_id: str
    decided_at: datetime
    created_at: datetime
    updated_at: datetime

    def __post_init__(self):
        _aware(self.created_at, "created_at"); _aware(self.updated_at, "updated_at")
        reasons, evidence = _decision_metadata(self.state, self.reason_codes, self.evidence_refs, self.policy_version, self.actor_id, self.decided_at, _MEMBERSHIP_REASONS, evidence_required=self.state is MembershipState.ACTIVE)
        object.__setattr__(self, "reason_codes", reasons); object.__setattr__(self, "evidence_refs", evidence)


@dataclass(frozen=True)
class MembershipCreate:
    membership_id: MembershipId
    recruiter_user_id: RecruiterUserId
    organization_id: OrganizationId
    role: MembershipRole
    policy_version: PolicyVersion
    actor_id: str
    evidence_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MembershipTransition:
    new_state: MembershipState
    reason_codes: Tuple[MembershipReasonCode, ...]
    evidence_refs: Tuple[str, ...]
    policy_version: PolicyVersion
    actor_id: str

    def __post_init__(self):
        _decision_metadata(self.new_state, self.reason_codes, self.evidence_refs, self.policy_version, self.actor_id, datetime.min.replace(tzinfo=timezone.utc), _MEMBERSHIP_REASONS, evidence_required=self.new_state is MembershipState.ACTIVE)


@dataclass(frozen=True)
class RecruiterVerification:
    recruiter_user_id: RecruiterUserId
    version: EntityVersion
    state: RecruiterVerificationState
    policy_version: PolicyVersion
    reason_codes: Tuple[RecruiterVerificationReasonCode, ...]
    evidence_refs: Tuple[str, ...]
    actor_id: str
    decided_at: datetime
    created_at: datetime
    updated_at: datetime

    def __post_init__(self):
        _aware(self.created_at, "created_at"); _aware(self.updated_at, "updated_at")
        reasons, evidence = _decision_metadata(self.state, self.reason_codes, self.evidence_refs, self.policy_version, self.actor_id, self.decided_at, _RECRUITER_REASONS, evidence_required=self.state is RecruiterVerificationState.VERIFIED)
        object.__setattr__(self, "reason_codes", reasons); object.__setattr__(self, "evidence_refs", evidence)


@dataclass(frozen=True)
class RecruiterVerificationCreate:
    recruiter_user_id: RecruiterUserId
    policy_version: PolicyVersion
    actor_id: str


@dataclass(frozen=True)
class RecruiterVerificationTransition:
    new_state: RecruiterVerificationState
    reason_codes: Tuple[RecruiterVerificationReasonCode, ...]
    evidence_refs: Tuple[str, ...]
    policy_version: PolicyVersion
    actor_id: str

    def __post_init__(self):
        _decision_metadata(self.new_state, self.reason_codes, self.evidence_refs, self.policy_version, self.actor_id, datetime.min.replace(tzinfo=timezone.utc), _RECRUITER_REASONS, evidence_required=self.new_state is RecruiterVerificationState.VERIFIED)


@dataclass(frozen=True)
class RecruitingMandate:
    mandate_id: MandateId
    requesting_organization_id: OrganizationId
    hiring_company_id: HiringCompanyId
    version: EntityVersion
    state: MandateState
    valid_from: datetime
    valid_until: datetime
    policy_version: PolicyVersion
    reason_codes: Tuple[MandateReasonCode, ...]
    evidence_refs: Tuple[str, ...]
    actor_id: str
    decided_at: datetime
    created_at: datetime
    updated_at: datetime

    def __post_init__(self):
        _aware(self.created_at, "created_at"); _aware(self.updated_at, "updated_at"); _aware(self.valid_from, "valid_from"); _aware(self.valid_until, "valid_until")
        if str(self.requesting_organization_id) == str(self.hiring_company_id):
            raise ValueError("self-mandate is not valid")
        if self.valid_until <= self.valid_from:
            raise ValueError("mandate valid_until must be after valid_from")
        reasons, evidence = _decision_metadata(self.state, self.reason_codes, self.evidence_refs, self.policy_version, self.actor_id, self.decided_at, _MANDATE_REASONS, evidence_required=self.state is MandateState.ACTIVE)
        object.__setattr__(self, "reason_codes", reasons); object.__setattr__(self, "evidence_refs", evidence)

    def is_temporally_valid_at(self, now: datetime) -> bool:
        return self.valid_from <= now < self.valid_until


@dataclass(frozen=True)
class MandateCreate:
    mandate_id: MandateId
    requesting_organization_id: OrganizationId
    hiring_company_id: HiringCompanyId
    valid_from: datetime
    valid_until: datetime
    policy_version: PolicyVersion
    actor_id: str
    evidence_refs: Tuple[str, ...] = ()

    def __post_init__(self):
        _aware(self.valid_from, "valid_from"); _aware(self.valid_until, "valid_until")
        if str(self.requesting_organization_id) == str(self.hiring_company_id):
            raise ValueError("self-mandate is not valid")
        if self.valid_until <= self.valid_from:
            raise ValueError("mandate valid_until must be after valid_from")


@dataclass(frozen=True)
class MandateTransition:
    new_state: MandateState
    reason_codes: Tuple[MandateReasonCode, ...]
    evidence_refs: Tuple[str, ...]
    policy_version: PolicyVersion
    actor_id: str

    def __post_init__(self):
        _decision_metadata(self.new_state, self.reason_codes, self.evidence_refs, self.policy_version, self.actor_id, datetime.min.replace(tzinfo=timezone.utc), _MANDATE_REASONS, evidence_required=self.new_state is MandateState.ACTIVE)
