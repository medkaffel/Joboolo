"""Transactional TS-A8 services and current Recruiter/Organization Trust evaluation."""
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pymongo.errors import DuplicateKeyError

from database import get_client
from domains.shared.ids import HiringCompanyId, MandateId, MembershipId, OrganizationId, RecruiterUserId
from domains.shared.versioning import EntityVersion, PolicyVersion
from domains.talent_stream.contracts import RecruitingActorContext
from domains.talent_stream.decisions import TrustDecision
from .organization_models import (
    Organization,
    OrganizationVerificationState,
    organization_from_document,
    require_aware_datetime,
    storage_datetime_utc,
)
from .recruiting_models import (
    MandateCreate, MandateReasonCode, MandateState, MandateTransition,
    MembershipCreate, MembershipReasonCode, MembershipRole, MembershipState, MembershipTransition,
    OrganizationMembership, RecruiterVerification, RecruiterVerificationCreate,
    RecruiterVerificationReasonCode, RecruiterVerificationState, RecruiterVerificationTransition,
    RecruitingMandate, RecruitingTrustReasonCode, RecruitingTrustSubjectType,
)
from .recruiting_repository import RecruitingTrustRepository


class RecruitingTrustConflictError(RuntimeError): pass
class RecruitingTrustInputNotFoundError(LookupError): pass
class RecruitingTrustEligibilityError(RuntimeError): pass

_MEMBERSHIP_TRANSITIONS = {
    MembershipState.PENDING: {MembershipState.ACTIVE, MembershipState.REVOKED},
    MembershipState.ACTIVE: {MembershipState.SUSPENDED, MembershipState.REVOKED},
    MembershipState.SUSPENDED: {MembershipState.ACTIVE, MembershipState.REVOKED},
    MembershipState.REVOKED: set(),
}
_RECRUITER_TRANSITIONS = {
    RecruiterVerificationState.UNVERIFIED: {RecruiterVerificationState.PENDING},
    RecruiterVerificationState.PENDING: {RecruiterVerificationState.VERIFIED, RecruiterVerificationState.REJECTED},
    RecruiterVerificationState.VERIFIED: {RecruiterVerificationState.SUSPENDED},
    RecruiterVerificationState.SUSPENDED: {RecruiterVerificationState.VERIFIED, RecruiterVerificationState.REJECTED},
    RecruiterVerificationState.REJECTED: {RecruiterVerificationState.PENDING},
}
_MANDATE_TRANSITIONS = {
    MandateState.PENDING: {MandateState.ACTIVE, MandateState.REJECTED, MandateState.REVOKED},
    MandateState.ACTIVE: {MandateState.SUSPENDED, MandateState.REVOKED},
    MandateState.SUSPENDED: {MandateState.ACTIVE, MandateState.REVOKED},
    MandateState.REJECTED: {MandateState.PENDING},
    MandateState.REVOKED: set(),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _command_time(value: Optional[datetime], field_name: str) -> datetime:
    return require_aware_datetime(value or _utcnow(), field_name)


def _values(values):
    return [value.value if hasattr(value, "value") else value for value in values]


def _event(subject_type, subject_id, subject_version, previous_state, new_state, reason_codes, evidence_refs, policy_version, actor_id, occurred_at):
    return {
        "_id": f"trust_event:{uuid4()}", "subject_type": subject_type.value,
        "subject_id": subject_id, "subject_version": int(subject_version),
        "previous_state": None if previous_state is None else previous_state.value,
        "new_state": new_state.value, "reason_codes": _values(reason_codes),
        "evidence_refs": list(evidence_refs), "policy_version": str(policy_version),
        "actor_id": actor_id, "occurred_at": occurred_at,
    }


def _membership(doc):
    if doc.get("_id") != doc.get("membership_id"):
        raise ValueError("membership identity mismatch")
    return OrganizationMembership(
        membership_id=MembershipId(doc["membership_id"]),
        recruiter_user_id=RecruiterUserId(doc["recruiter_user_id"]),
        organization_id=OrganizationId(doc["organization_id"]),
        version=EntityVersion(int(doc["version"])),
        role=MembershipRole(doc["role"]),
        state=MembershipState(doc["state"]),
        policy_version=PolicyVersion(doc["policy_version"]),
        reason_codes=tuple(MembershipReasonCode(v) for v in doc["reason_codes"]),
        evidence_refs=tuple(doc.get("evidence_refs", [])),
        actor_id=doc["actor_id"],
        decided_at=storage_datetime_utc(doc["decided_at"], "membership.decided_at"),
        created_at=storage_datetime_utc(doc["created_at"], "membership.created_at"),
        updated_at=storage_datetime_utc(doc["updated_at"], "membership.updated_at"),
    )


def _verification(doc):
    if doc.get("_id") != doc.get("recruiter_user_id"):
        raise ValueError("recruiter verification identity mismatch")
    return RecruiterVerification(
        recruiter_user_id=RecruiterUserId(doc["recruiter_user_id"]),
        version=EntityVersion(int(doc["version"])),
        state=RecruiterVerificationState(doc["state"]),
        policy_version=PolicyVersion(doc["policy_version"]),
        reason_codes=tuple(RecruiterVerificationReasonCode(v) for v in doc["reason_codes"]),
        evidence_refs=tuple(doc.get("evidence_refs", [])),
        actor_id=doc["actor_id"],
        decided_at=storage_datetime_utc(doc["decided_at"], "recruiter_verification.decided_at"),
        created_at=storage_datetime_utc(doc["created_at"], "recruiter_verification.created_at"),
        updated_at=storage_datetime_utc(doc["updated_at"], "recruiter_verification.updated_at"),
    )


def _mandate(doc):
    if doc.get("_id") != doc.get("mandate_id"):
        raise ValueError("mandate identity mismatch")
    return RecruitingMandate(
        mandate_id=MandateId(doc["mandate_id"]),
        requesting_organization_id=OrganizationId(doc["requesting_organization_id"]),
        hiring_company_id=HiringCompanyId(doc["hiring_company_id"]),
        version=EntityVersion(int(doc["version"])),
        state=MandateState(doc["state"]),
        valid_from=storage_datetime_utc(doc["valid_from"], "mandate.valid_from"),
        valid_until=storage_datetime_utc(doc["valid_until"], "mandate.valid_until"),
        policy_version=PolicyVersion(doc["policy_version"]),
        reason_codes=tuple(MandateReasonCode(v) for v in doc["reason_codes"]),
        evidence_refs=tuple(doc.get("evidence_refs", [])),
        actor_id=doc["actor_id"],
        decided_at=storage_datetime_utc(doc["decided_at"], "mandate.decided_at"),
        created_at=storage_datetime_utc(doc["created_at"], "mandate.created_at"),
        updated_at=storage_datetime_utc(doc["updated_at"], "mandate.updated_at"),
    )


def _valid_organization(doc, expected_id: str) -> Optional[Organization]:
    if doc is None:
        return None
    try:
        organization = organization_from_document(doc)
    except (KeyError, TypeError, ValueError):
        return None
    if str(organization.organization_id) != expected_id:
        return None
    return organization


class RecruitingTrustService:
    def __init__(self, db, *, client_provider=get_client):
        self.repo = RecruitingTrustRepository(db)
        self.client_provider = client_provider

    def _client(self):
        client = self.client_provider()
        if client is None:
            raise RuntimeError("Mongo client unavailable")
        return client

    async def _eligible_user(self, recruiter_user_id: str, session=None):
        user = await self.repo.get_user(recruiter_user_id, session=session)
        if user is None:
            raise RecruitingTrustInputNotFoundError("Recruiter user not found")
        if user.get("is_active") is not True:
            raise RecruitingTrustEligibilityError("Recruiter user is inactive or incomplete")
        if user.get("user_type") != "employer":
            raise RecruitingTrustEligibilityError("Recruiter user type is unsupported")
        return user

    async def _organization(self, organization_id: str, session=None) -> Organization:
        doc = await self.repo.get_organization(organization_id, session=session)
        if doc is None:
            raise RecruitingTrustInputNotFoundError("Organization not found")
        organization = _valid_organization(doc, organization_id)
        if organization is None:
            raise RecruitingTrustEligibilityError("Organization record is invalid")
        return organization

    async def create_membership(self, command: MembershipCreate, *, now: Optional[datetime]=None) -> OrganizationMembership:
        now = _command_time(now, "now")
        client = self._client()
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    await self._eligible_user(str(command.recruiter_user_id), session=session)
                    await self._organization(str(command.organization_id), session=session)
                    doc = {"_id": str(command.membership_id), "membership_id": str(command.membership_id),
                           "recruiter_user_id": str(command.recruiter_user_id), "organization_id": str(command.organization_id),
                           "version": 1, "role": command.role.value, "state": MembershipState.PENDING.value,
                           "policy_version": str(command.policy_version), "reason_codes": [MembershipReasonCode.MEMBERSHIP_REQUESTED.value],
                           "evidence_refs": list(command.evidence_refs), "actor_id": command.actor_id, "decided_at": now,
                           "created_at": now, "updated_at": now}
                    await self.repo.insert_membership(doc, session=session)
                    await self.repo.insert_event(_event(RecruitingTrustSubjectType.MEMBERSHIP, str(command.membership_id), 1, None, MembershipState.PENDING,
                                                        (MembershipReasonCode.MEMBERSHIP_REQUESTED,), command.evidence_refs, command.policy_version, command.actor_id, now), session=session)
                    return _membership(doc)
        except DuplicateKeyError as exc:
            raise RecruitingTrustConflictError("Membership already exists") from exc

    async def transition_membership(self, membership_id: MembershipId, expected_version: EntityVersion, transition: MembershipTransition, *, now: Optional[datetime]=None) -> OrganizationMembership:
        now = _command_time(now, "now")
        client = self._client()
        async with await client.start_session() as session:
            async with session.start_transaction():
                current = await self.repo.get_membership(str(membership_id), session=session)
                if current is None:
                    raise RecruitingTrustInputNotFoundError("Membership not found")
                current_obj = _membership(current)
                state = current_obj.state
                if transition.new_state not in _MEMBERSHIP_TRANSITIONS[state]:
                    raise ValueError(f"invalid membership transition {state.value}->{transition.new_state.value}")
                changes = {"state": transition.new_state.value, "policy_version": str(transition.policy_version), "reason_codes": _values(transition.reason_codes),
                           "evidence_refs": list(transition.evidence_refs), "actor_id": transition.actor_id, "decided_at": now, "updated_at": now}
                updated = await self.repo.update_membership(str(membership_id), int(expected_version), changes, session=session)
                if updated is None:
                    raise RecruitingTrustConflictError("Membership version conflict")
                await self.repo.insert_event(_event(RecruitingTrustSubjectType.MEMBERSHIP, str(membership_id), int(expected_version)+1, state, transition.new_state,
                                                    transition.reason_codes, transition.evidence_refs, transition.policy_version, transition.actor_id, now), session=session)
                return _membership(updated)

    async def create_recruiter_verification(self, command: RecruiterVerificationCreate, *, now: Optional[datetime]=None) -> RecruiterVerification:
        now = _command_time(now, "now")
        client = self._client()
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    await self._eligible_user(str(command.recruiter_user_id), session=session)
                    doc = {"_id": str(command.recruiter_user_id), "recruiter_user_id": str(command.recruiter_user_id), "version": 1,
                           "state": RecruiterVerificationState.UNVERIFIED.value, "policy_version": str(command.policy_version),
                           "reason_codes": [RecruiterVerificationReasonCode.RECORD_CREATED.value], "evidence_refs": [], "actor_id": command.actor_id,
                           "decided_at": now, "created_at": now, "updated_at": now}
                    await self.repo.insert_recruiter_verification(doc, session=session)
                    await self.repo.insert_event(_event(RecruitingTrustSubjectType.RECRUITER_VERIFICATION, str(command.recruiter_user_id), 1, None,
                                                        RecruiterVerificationState.UNVERIFIED, (RecruiterVerificationReasonCode.RECORD_CREATED,), (),
                                                        command.policy_version, command.actor_id, now), session=session)
                    return _verification(doc)
        except DuplicateKeyError as exc:
            raise RecruitingTrustConflictError("Recruiter verification already exists") from exc

    async def transition_recruiter_verification(self, recruiter_user_id: RecruiterUserId, expected_version: EntityVersion, transition: RecruiterVerificationTransition, *, now: Optional[datetime]=None) -> RecruiterVerification:
        now = _command_time(now, "now")
        client = self._client()
        async with await client.start_session() as session:
            async with session.start_transaction():
                current = await self.repo.get_recruiter_verification(str(recruiter_user_id), session=session)
                if current is None:
                    raise RecruitingTrustInputNotFoundError("Recruiter verification not found")
                current_obj = _verification(current)
                state = current_obj.state
                if transition.new_state not in _RECRUITER_TRANSITIONS[state]:
                    raise ValueError(f"invalid recruiter verification transition {state.value}->{transition.new_state.value}")
                changes = {"state": transition.new_state.value, "policy_version": str(transition.policy_version), "reason_codes": _values(transition.reason_codes),
                           "evidence_refs": list(transition.evidence_refs), "actor_id": transition.actor_id, "decided_at": now, "updated_at": now}
                updated = await self.repo.update_recruiter_verification(str(recruiter_user_id), int(expected_version), changes, session=session)
                if updated is None:
                    raise RecruitingTrustConflictError("Recruiter verification version conflict")
                await self.repo.insert_event(_event(RecruitingTrustSubjectType.RECRUITER_VERIFICATION, str(recruiter_user_id), int(expected_version)+1, state,
                                                    transition.new_state, transition.reason_codes, transition.evidence_refs, transition.policy_version, transition.actor_id, now), session=session)
                return _verification(updated)

    async def create_mandate(self, command: MandateCreate, *, now: Optional[datetime]=None) -> RecruitingMandate:
        now = _command_time(now, "now")
        client = self._client()
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    await self._organization(str(command.requesting_organization_id), session=session)
                    await self._organization(str(command.hiring_company_id), session=session)
                    doc = {"_id": str(command.mandate_id), "mandate_id": str(command.mandate_id),
                           "requesting_organization_id": str(command.requesting_organization_id), "hiring_company_id": str(command.hiring_company_id),
                           "version": 1, "state": MandateState.PENDING.value, "valid_from": command.valid_from, "valid_until": command.valid_until,
                           "policy_version": str(command.policy_version), "reason_codes": [MandateReasonCode.MANDATE_SUBMITTED.value],
                           "evidence_refs": list(command.evidence_refs), "actor_id": command.actor_id, "decided_at": now, "created_at": now, "updated_at": now}
                    await self.repo.insert_mandate(doc, session=session)
                    await self.repo.insert_event(_event(RecruitingTrustSubjectType.MANDATE, str(command.mandate_id), 1, None, MandateState.PENDING,
                                                        (MandateReasonCode.MANDATE_SUBMITTED,), command.evidence_refs, command.policy_version, command.actor_id, now), session=session)
                    return _mandate(doc)
        except DuplicateKeyError as exc:
            raise RecruitingTrustConflictError("Mandate already exists") from exc

    async def transition_mandate(self, mandate_id: MandateId, expected_version: EntityVersion, transition: MandateTransition, *, now: Optional[datetime]=None) -> RecruitingMandate:
        now = _command_time(now, "now")
        client = self._client()
        async with await client.start_session() as session:
            async with session.start_transaction():
                current = await self.repo.get_mandate(str(mandate_id), session=session)
                if current is None:
                    raise RecruitingTrustInputNotFoundError("Mandate not found")
                current_obj = _mandate(current)
                state = current_obj.state
                if transition.new_state not in _MANDATE_TRANSITIONS[state]:
                    raise ValueError(f"invalid mandate transition {state.value}->{transition.new_state.value}")
                if transition.new_state is MandateState.ACTIVE:
                    requesting = await self._organization(str(current_obj.requesting_organization_id), session=session)
                    hiring = await self._organization(str(current_obj.hiring_company_id), session=session)
                    if requesting.verification_state is not OrganizationVerificationState.VERIFIED or hiring.verification_state is not OrganizationVerificationState.VERIFIED:
                        raise RecruitingTrustEligibilityError("Both mandate organizations must be VERIFIED before activation")
                    if current_obj.valid_until <= now:
                        raise RecruitingTrustEligibilityError("Expired mandate cannot be activated")
                changes = {"state": transition.new_state.value, "policy_version": str(transition.policy_version), "reason_codes": _values(transition.reason_codes),
                           "evidence_refs": list(transition.evidence_refs), "actor_id": transition.actor_id, "decided_at": now, "updated_at": now}
                updated = await self.repo.update_mandate(str(mandate_id), int(expected_version), changes, session=session)
                if updated is None:
                    raise RecruitingTrustConflictError("Mandate version conflict")
                await self.repo.insert_event(_event(RecruitingTrustSubjectType.MANDATE, str(mandate_id), int(expected_version)+1, state, transition.new_state,
                                                    transition.reason_codes, transition.evidence_refs, transition.policy_version, transition.actor_id, now), session=session)
                return _mandate(updated)

    def _decision(self, allowed: bool, reason: RecruitingTrustReasonCode, policy_version: PolicyVersion, evaluated_at: datetime, evidence=()):
        if not str(policy_version).strip():
            raise ValueError("policy_version must not be blank")
        return TrustDecision(allowed=allowed, reason_codes=(reason.value,), policy_version=policy_version, evaluated_at=evaluated_at, evidence_refs=tuple(evidence))

    async def evaluate_recruiting_actor_trust(self, context: RecruitingActorContext, *, policy_version: PolicyVersion, evaluated_at: Optional[datetime]=None) -> TrustDecision:
        now = _command_time(evaluated_at, "evaluated_at")
        if not str(policy_version).strip():
            raise ValueError("policy_version must not be blank")
        recruiter = str(context.recruiter_user_id)
        requesting_id = str(context.requesting_organization_id)
        hiring_id = str(context.hiring_company_id)

        user = await self.repo.get_user(recruiter)
        if user is None:
            return self._decision(False, RecruitingTrustReasonCode.RECRUITER_USER_NOT_FOUND, policy_version, now)
        if user.get("is_active") is not True:
            return self._decision(False, RecruitingTrustReasonCode.RECRUITER_USER_INACTIVE, policy_version, now)
        if user.get("user_type") != "employer":
            return self._decision(False, RecruitingTrustReasonCode.RECRUITER_USER_TYPE_UNSUPPORTED, policy_version, now)

        requesting_doc = await self.repo.get_organization(requesting_id)
        requesting = _valid_organization(requesting_doc, requesting_id)
        if requesting is None or requesting.verification_state is not OrganizationVerificationState.VERIFIED:
            return self._decision(False, RecruitingTrustReasonCode.REQUESTING_ORGANIZATION_NOT_VERIFIED, policy_version, now)

        membership_doc = await self.repo.get_membership_by_pair(recruiter, requesting_id)
        try:
            membership = None if membership_doc is None else _membership(membership_doc)
        except (KeyError, TypeError, ValueError):
            membership = None
        if membership is None or membership.state is not MembershipState.ACTIVE:
            return self._decision(False, RecruitingTrustReasonCode.MEMBERSHIP_NOT_ACTIVE, policy_version, now)

        verification_doc = await self.repo.get_recruiter_verification(recruiter)
        try:
            verification = None if verification_doc is None else _verification(verification_doc)
        except (KeyError, TypeError, ValueError):
            verification = None
        if verification is None or verification.state is not RecruiterVerificationState.VERIFIED:
            return self._decision(False, RecruitingTrustReasonCode.RECRUITER_NOT_VERIFIED, policy_version, now)

        hiring_doc = await self.repo.get_organization(hiring_id)
        hiring = _valid_organization(hiring_doc, hiring_id)
        if hiring is None or hiring.verification_state is not OrganizationVerificationState.VERIFIED:
            return self._decision(False, RecruitingTrustReasonCode.HIRING_COMPANY_NOT_VERIFIED, policy_version, now)

        evidence = [
            f"organization:{requesting_id}:v{requesting.version}",
            f"membership:{membership.membership_id}:v{membership.version}",
            f"recruiter_verification:{recruiter}:v{verification.version}",
        ]
        if hiring_id != requesting_id:
            evidence.append(f"organization:{hiring_id}:v{hiring.version}")

        if requesting_id == hiring_id:
            return self._decision(True, RecruitingTrustReasonCode.RECRUITING_ACTOR_TRUSTED, policy_version, now, evidence)
        if context.mandate_id is None:
            return self._decision(False, RecruitingTrustReasonCode.MANDATE_REQUIRED, policy_version, now, evidence)

        mandate_doc = await self.repo.get_mandate(str(context.mandate_id))
        if mandate_doc is None:
            return self._decision(False, RecruitingTrustReasonCode.MANDATE_NOT_FOUND, policy_version, now, evidence)
        try:
            mandate = _mandate(mandate_doc)
        except (KeyError, TypeError, ValueError):
            return self._decision(False, RecruitingTrustReasonCode.MANDATE_NOT_ACTIVE, policy_version, now, evidence)
        if str(mandate.requesting_organization_id) != requesting_id or str(mandate.hiring_company_id) != hiring_id:
            return self._decision(False, RecruitingTrustReasonCode.MANDATE_PARTIES_MISMATCH, policy_version, now, evidence)
        if mandate.state is not MandateState.ACTIVE:
            return self._decision(False, RecruitingTrustReasonCode.MANDATE_NOT_ACTIVE, policy_version, now, evidence)
        if now < mandate.valid_from:
            return self._decision(False, RecruitingTrustReasonCode.MANDATE_NOT_YET_VALID, policy_version, now, evidence)
        if now >= mandate.valid_until:
            return self._decision(False, RecruitingTrustReasonCode.MANDATE_EXPIRED, policy_version, now, evidence)
        return self._decision(True, RecruitingTrustReasonCode.RECRUITING_ACTOR_TRUSTED, policy_version, now, evidence + [f"mandate:{mandate.mandate_id}:v{mandate.version}"])
