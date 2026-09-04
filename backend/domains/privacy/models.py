"""Strict TS-A10 privacy lifecycle contracts and persistence rehydration."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Tuple

from domains.shared.ids import CandidateId, DocumentId, GrantId, OrganizationId, TalentStreamId
from domains.shared.versioning import ConsentPolicyVersion, PolicyVersion
from domains.talent_stream.contracts import GrantContract, GrantScope


class PrivacyDataCategory(str, Enum):
    TALENT_STREAM_GRANT = "talent_stream_grant"
    PRIVACY_AUDIT_EVENT = "privacy_audit_event"


class RetentionTerminalAction(str, Enum):
    DELETE = "delete"
    ANONYMIZE = "anonymize"


class RevocationAuthority(str, Enum):
    CANDIDATE = "candidate"
    PRIVACY_ADMIN = "privacy_admin"
    SYSTEM_POLICY = "system_policy"


class GrantRevocationReasonCode(str, Enum):
    CONSENT_WITHDRAWN = "consent_withdrawn"
    PRIVACY_REQUEST = "privacy_request"
    POLICY_INVALIDATED = "policy_invalidated"
    SECURITY_RESPONSE = "security_response"
    ADMIN_CORRECTION = "admin_correction"


class PrivacyReasonCode(str, Enum):
    GRANT_PRIVACY_ACTIVE = "grant_privacy_active"
    GRANT_NOT_YET_ACTIVE = "grant_not_yet_active"
    GRANT_EXPIRED = "grant_expired"
    GRANT_REVOKED = "grant_revoked"
    IDENTIFIABLE_RETENTION_ACTIVE = "identifiable_retention_active"
    IDENTIFIABLE_RETENTION_EXPIRED = "identifiable_retention_expired"
    IDENTIFIABLE_RETENTION_NOT_DUE = "identifiable_retention_not_due"


_ALLOWED_REASONS_BY_AUTHORITY = {
    RevocationAuthority.CANDIDATE: {GrantRevocationReasonCode.CONSENT_WITHDRAWN},
    RevocationAuthority.PRIVACY_ADMIN: {
        GrantRevocationReasonCode.PRIVACY_REQUEST,
        GrantRevocationReasonCode.SECURITY_RESPONSE,
        GrantRevocationReasonCode.ADMIN_CORRECTION,
    },
    RevocationAuthority.SYSTEM_POLICY: {GrantRevocationReasonCode.POLICY_INVALIDATED},
}


def nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = " ".join(value.strip().split())
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def storage_datetime_utc(value: datetime, field_name: str) -> datetime:
    """Normalize PyMongo's default naive-UTC BSON datetime at persistence boundary."""
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class GrantRevocationCommand:
    command_id: str
    grant_id: GrantId
    candidate_id: CandidateId
    authority: RevocationAuthority
    reason_code: GrantRevocationReasonCode
    policy_version: PolicyVersion
    actor_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_id", nonblank(self.command_id, "command_id"))
        nonblank(self.grant_id, "grant_id")
        nonblank(self.candidate_id, "candidate_id")
        authority = RevocationAuthority(self.authority)
        reason = GrantRevocationReasonCode(self.reason_code)
        object.__setattr__(self, "authority", authority)
        object.__setattr__(self, "reason_code", reason)
        if reason not in _ALLOWED_REASONS_BY_AUTHORITY[authority]:
            raise ValueError("revocation reason is inconsistent with authority")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version must not be blank")
        actor = nonblank(self.actor_id, "actor_id")
        object.__setattr__(self, "actor_id", actor)
        if authority is RevocationAuthority.CANDIDATE and actor != str(self.candidate_id):
            raise ValueError("candidate revocation authority must be self-scoped")


@dataclass(frozen=True)
class PrivacyAuditEvent:
    command_id: str
    grant_id: GrantId
    candidate_id: CandidateId
    authority: RevocationAuthority
    reason_code: GrantRevocationReasonCode
    policy_version: PolicyVersion
    actor_id: str
    occurred_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_id", nonblank(self.command_id, "command_id"))
        nonblank(self.grant_id, "grant_id")
        nonblank(self.candidate_id, "candidate_id")
        object.__setattr__(self, "authority", RevocationAuthority(self.authority))
        object.__setattr__(self, "reason_code", GrantRevocationReasonCode(self.reason_code))
        if self.reason_code not in _ALLOWED_REASONS_BY_AUTHORITY[self.authority]:
            raise ValueError("event reason is inconsistent with authority")
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version must not be blank")
        actor = nonblank(self.actor_id, "actor_id")
        object.__setattr__(self, "actor_id", actor)
        if self.authority is RevocationAuthority.CANDIDATE and actor != str(self.candidate_id):
            raise ValueError("candidate privacy event must be self-scoped")
        require_aware_datetime(self.occurred_at, "occurred_at")


@dataclass(frozen=True)
class RetentionRule:
    category: PrivacyDataCategory
    purpose: str
    retain_for: timedelta
    terminal_action: RetentionTerminalAction
    policy_version: PolicyVersion

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", PrivacyDataCategory(self.category))
        object.__setattr__(self, "purpose", nonblank(self.purpose, "purpose"))
        if not isinstance(self.retain_for, timedelta) or self.retain_for <= timedelta(0):
            raise ValueError("retain_for must be a positive timedelta")
        object.__setattr__(self, "terminal_action", RetentionTerminalAction(self.terminal_action))
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version must not be blank")


@dataclass(frozen=True)
class RetentionEvaluation:
    category: PrivacyDataCategory
    purpose: str
    policy_version: PolicyVersion
    evaluated_at: datetime
    retention_until: Optional[datetime]
    action_due: Optional[RetentionTerminalAction]
    reason_code: PrivacyReasonCode

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", PrivacyDataCategory(self.category))
        object.__setattr__(self, "purpose", nonblank(self.purpose, "purpose"))
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ValueError("policy_version must not be blank")
        require_aware_datetime(self.evaluated_at, "evaluated_at")
        if self.retention_until is not None:
            require_aware_datetime(self.retention_until, "retention_until")
        object.__setattr__(self, "reason_code", PrivacyReasonCode(self.reason_code))
        if self.action_due is not None:
            object.__setattr__(self, "action_due", RetentionTerminalAction(self.action_due))
        if self.reason_code is PrivacyReasonCode.IDENTIFIABLE_RETENTION_EXPIRED:
            if self.retention_until is None or self.action_due is None:
                raise ValueError("expired retention requires deadline and action")
        elif self.action_due is not None:
            raise ValueError("action_due is only valid for expired retention")


def grant_from_document(doc: dict) -> GrantContract:
    """Strict A10 persistence-boundary rehydration of an A0 Talent Stream grant."""
    if not isinstance(doc, dict):
        raise ValueError("grant document must be a mapping")
    required = (
        "_id", "grant_id", "candidate_id", "grantee_organization_id", "scopes",
        "stream_id", "issued_at", "consent_policy_version",
    )
    missing = [name for name in required if name not in doc]
    if missing:
        raise ValueError(f"grant document missing required fields: {', '.join(missing)}")
    grant_id = nonblank(doc["grant_id"], "grant_id")
    if doc["_id"] != grant_id:
        raise ValueError("grant document identity mismatch")
    scopes_raw = doc["scopes"]
    if not isinstance(scopes_raw, (list, tuple)):
        raise ValueError("grant scopes must be a list")
    scopes = tuple(GrantScope(value) for value in scopes_raw)
    expires_at = doc.get("expires_at")
    revoked_at = doc.get("revoked_at")
    return GrantContract(
        grant_id=GrantId(grant_id),
        candidate_id=CandidateId(nonblank(doc["candidate_id"], "candidate_id")),
        grantee_organization_id=OrganizationId(nonblank(doc["grantee_organization_id"], "grantee_organization_id")),
        scopes=scopes,
        issued_at=storage_datetime_utc(doc["issued_at"], "grant.issued_at"),
        consent_policy_version=ConsentPolicyVersion(nonblank(doc["consent_policy_version"], "consent_policy_version")),
        stream_id=TalentStreamId(nonblank(doc["stream_id"], "stream_id")),
        document_id=(None if doc.get("document_id") is None else DocumentId(nonblank(doc["document_id"], "document_id"))),
        expires_at=(None if expires_at is None else storage_datetime_utc(expires_at, "grant.expires_at")),
        revoked_at=(None if revoked_at is None else storage_datetime_utc(revoked_at, "grant.revoked_at")),
    )


def privacy_event_from_document(doc: dict) -> PrivacyAuditEvent:
    if not isinstance(doc, dict):
        raise ValueError("privacy event document must be a mapping")
    required = (
        "_id", "command_id", "grant_id", "candidate_id", "authority", "reason_code",
        "policy_version", "actor_id", "occurred_at",
    )
    missing = [name for name in required if name not in doc]
    if missing:
        raise ValueError(f"privacy event document missing required fields: {', '.join(missing)}")
    command_id = nonblank(doc["command_id"], "command_id")
    if doc["_id"] != f"privacy_event:{command_id}":
        raise ValueError("privacy event identity mismatch")
    return PrivacyAuditEvent(
        command_id=command_id,
        grant_id=GrantId(nonblank(doc["grant_id"], "grant_id")),
        candidate_id=CandidateId(nonblank(doc["candidate_id"], "candidate_id")),
        authority=RevocationAuthority(doc["authority"]),
        reason_code=GrantRevocationReasonCode(doc["reason_code"]),
        policy_version=PolicyVersion(nonblank(doc["policy_version"], "policy_version")),
        actor_id=nonblank(doc["actor_id"], "actor_id"),
        occurred_at=storage_datetime_utc(doc["occurred_at"], "privacy_event.occurred_at"),
    )
