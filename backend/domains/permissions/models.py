"""Strict TS-A9 permission request, candidate-state and scoped-grant contracts."""
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Tuple

from domains.shared.ids import (
    CandidateId,
    CandidatePreferencesId,
    DocumentId,
    GrantId,
    OrganizationId,
    TalentStreamId,
)
from domains.shared.versioning import ConsentPolicyVersion, EntityVersion
from domains.talent_stream.contracts import GrantContract, GrantScope, RecruitingActorContext


class PermissionAction(str, Enum):
    REQUEST_INTRODUCTION = "request_introduction"
    REVEAL_PROFILE_PREVIEW = "reveal_profile_preview"
    REVEAL_IDENTITY = "reveal_identity"
    REVEAL_CONTACT = "reveal_contact"
    ACCESS_CV = "access_cv"
    OPEN_MESSAGING = "open_messaging"


class PermissionReasonCode(str, Enum):
    DISCOVERY_PERMISSION_GRANTED = "discovery_permission_granted"
    ACTIVE_SCOPED_GRANT_GRANTED = "active_scoped_grant_granted"
    CANDIDATE_PREFERENCES_NOT_FOUND = "candidate_preferences_not_found"
    CANDIDATE_PREFERENCES_INVALID = "candidate_preferences_invalid"
    DISCOVERY_DISABLED = "discovery_disabled"
    COMPATIBLE_OPPORTUNITIES_NOT_ALLOWED = "compatible_opportunities_not_allowed"
    CANDIDATE_ORGANIZATION_EXCLUSION = "candidate_organization_exclusion"
    ORGANIZATION_EXCLUSION_CONTEXT_UNRESOLVED = "organization_exclusion_context_unresolved"
    ACTIVE_SCOPED_GRANT_REQUIRED = "active_scoped_grant_required"


_ACTION_SCOPE = {
    PermissionAction.REVEAL_PROFILE_PREVIEW: GrantScope.PROFILE_PREVIEW,
    PermissionAction.REVEAL_IDENTITY: GrantScope.IDENTITY,
    PermissionAction.REVEAL_CONTACT: GrantScope.CONTACT,
    PermissionAction.ACCESS_CV: GrantScope.CV,
    PermissionAction.OPEN_MESSAGING: GrantScope.MESSAGING,
}


def _nonblank(value: str, field_name: str) -> str:
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


def _strict_bool(value, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _string_tuple(values, field_name: str) -> Tuple[str, ...]:
    if not isinstance(values, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    return tuple(_nonblank(value, field_name) for value in values)


@dataclass(frozen=True)
class PermissionRequestContext:
    candidate_id: CandidateId
    action: PermissionAction
    recruiting_actor: RecruitingActorContext
    stream_id: TalentStreamId
    document_id: Optional[DocumentId] = None

    def __post_init__(self) -> None:
        if not isinstance(self.recruiting_actor, RecruitingActorContext):
            raise ValueError("recruiting_actor must be a RecruitingActorContext")
        _nonblank(self.candidate_id, "candidate_id")
        _nonblank(self.stream_id, "stream_id")
        _nonblank(self.recruiting_actor.recruiter_user_id, "recruiter_user_id")
        _nonblank(self.recruiting_actor.requesting_organization_id, "requesting_organization_id")
        _nonblank(self.recruiting_actor.hiring_company_id, "hiring_company_id")
        action = PermissionAction(self.action)
        object.__setattr__(self, "action", action)
        if action is PermissionAction.ACCESS_CV:
            if self.document_id is None:
                raise ValueError("CV access requires a specific document_id")
            _nonblank(self.document_id, "document_id")
        elif self.document_id is not None:
            raise ValueError("document_id is only valid for CV access")

    @property
    def required_scope(self) -> Optional[GrantScope]:
        return _ACTION_SCOPE.get(self.action)


@dataclass(frozen=True)
class CandidatePermissionState:
    preferences_id: CandidatePreferencesId
    candidate_id: CandidateId
    preferences_version: EntityVersion
    discovery_enabled: bool
    allow_compatible_opportunities: bool
    ask_before_reveal: bool
    anonymous_only: bool
    excluded_company_ids: Tuple[str, ...]
    current_employer_company_id: Optional[str]
    updated_at: datetime

    def __post_init__(self) -> None:
        _nonblank(self.preferences_id, "preferences_id")
        _nonblank(self.candidate_id, "candidate_id")
        object.__setattr__(self, "preferences_version", EntityVersion(int(self.preferences_version)))
        object.__setattr__(self, "discovery_enabled", _strict_bool(self.discovery_enabled, "discovery_enabled"))
        object.__setattr__(
            self,
            "allow_compatible_opportunities",
            _strict_bool(self.allow_compatible_opportunities, "allow_compatible_opportunities"),
        )
        object.__setattr__(self, "ask_before_reveal", _strict_bool(self.ask_before_reveal, "ask_before_reveal"))
        object.__setattr__(self, "anonymous_only", _strict_bool(self.anonymous_only, "anonymous_only"))
        require_aware_datetime(self.updated_at, "updated_at")
        if self.current_employer_company_id is not None:
            object.__setattr__(
                self,
                "current_employer_company_id",
                _nonblank(self.current_employer_company_id, "current_employer_company_id"),
            )
        for value in self.excluded_company_ids:
            _nonblank(value, "excluded_company_id")
        if not self.discovery_enabled and (
            self.allow_compatible_opportunities or self.ask_before_reveal or self.anonymous_only
        ):
            raise ValueError("disabled discovery cannot enable discovery sub-controls")

    @property
    def exclusion_ids(self) -> frozenset[str]:
        values = set(self.excluded_company_ids)
        if self.current_employer_company_id is not None:
            values.add(self.current_employer_company_id)
        return frozenset(values)


@dataclass(frozen=True)
class OrganizationPermissionIdentity:
    organization_id: OrganizationId
    version: EntityVersion
    legacy_company_id: Optional[str] = None

    def __post_init__(self) -> None:
        _nonblank(self.organization_id, "organization_id")
        object.__setattr__(self, "version", EntityVersion(int(self.version)))
        if self.legacy_company_id is not None:
            object.__setattr__(
                self,
                "legacy_company_id",
                _nonblank(self.legacy_company_id, "legacy_company_id"),
            )

    @property
    def comparison_ids(self) -> frozenset[str]:
        values = {str(self.organization_id)}
        if self.legacy_company_id is not None:
            values.add(self.legacy_company_id)
        return frozenset(values)


def candidate_permission_state_from_document(doc: dict) -> CandidatePermissionState:
    if not isinstance(doc, dict):
        raise ValueError("candidate preferences document must be a mapping")
    required = ("_id", "candidate_id", "version", "discovery", "excluded_company_ids", "updated_at")
    missing = [field_name for field_name in required if field_name not in doc]
    if missing:
        raise ValueError(f"candidate preferences document missing required fields: {', '.join(missing)}")
    discovery = doc["discovery"]
    if not isinstance(discovery, dict):
        raise ValueError("discovery must be a mapping")
    discovery_required = (
        "enabled",
        "allow_compatible_opportunities",
        "ask_before_reveal",
        "anonymous_only",
    )
    missing_discovery = [field_name for field_name in discovery_required if field_name not in discovery]
    if missing_discovery:
        raise ValueError(f"discovery missing required fields: {', '.join(missing_discovery)}")
    preferences_id = _nonblank(doc["_id"], "preferences_id")
    candidate_id = _nonblank(doc["candidate_id"], "candidate_id")
    if preferences_id != f"candidate_preferences:{candidate_id}":
        raise ValueError("candidate preferences identity mismatch")
    return CandidatePermissionState(
        preferences_id=CandidatePreferencesId(preferences_id),
        candidate_id=CandidateId(candidate_id),
        preferences_version=EntityVersion(int(doc["version"])),
        discovery_enabled=_strict_bool(discovery["enabled"], "discovery.enabled"),
        allow_compatible_opportunities=_strict_bool(
            discovery["allow_compatible_opportunities"], "discovery.allow_compatible_opportunities"
        ),
        ask_before_reveal=_strict_bool(discovery["ask_before_reveal"], "discovery.ask_before_reveal"),
        anonymous_only=_strict_bool(discovery["anonymous_only"], "discovery.anonymous_only"),
        excluded_company_ids=_string_tuple(doc["excluded_company_ids"], "excluded_company_ids"),
        current_employer_company_id=(
            None
            if doc.get("current_employer_company_id") is None
            else _nonblank(doc["current_employer_company_id"], "current_employer_company_id")
        ),
        updated_at=storage_datetime_utc(doc["updated_at"], "candidate_preferences.updated_at"),
    )


def grant_from_document(doc: dict) -> GrantContract:
    if not isinstance(doc, dict):
        raise ValueError("grant document must be a mapping")
    required = (
        "_id",
        "grant_id",
        "candidate_id",
        "grantee_organization_id",
        "scopes",
        "stream_id",
        "issued_at",
        "consent_policy_version",
    )
    missing = [field_name for field_name in required if field_name not in doc]
    if missing:
        raise ValueError(f"grant document missing required fields: {', '.join(missing)}")
    if doc["_id"] != doc["grant_id"]:
        raise ValueError("grant document identity mismatch")
    stream_id = _nonblank(doc["stream_id"], "stream_id")
    consent_policy_version = _nonblank(doc["consent_policy_version"], "consent_policy_version")
    scopes_raw = doc["scopes"]
    if not isinstance(scopes_raw, (list, tuple)):
        raise ValueError("grant scopes must be a list")
    scopes = tuple(GrantScope(value) for value in scopes_raw)
    expires_at = doc.get("expires_at")
    revoked_at = doc.get("revoked_at")
    return GrantContract(
        grant_id=GrantId(_nonblank(doc["grant_id"], "grant_id")),
        candidate_id=CandidateId(_nonblank(doc["candidate_id"], "candidate_id")),
        grantee_organization_id=OrganizationId(
            _nonblank(doc["grantee_organization_id"], "grantee_organization_id")
        ),
        scopes=scopes,
        issued_at=storage_datetime_utc(doc["issued_at"], "grant.issued_at"),
        consent_policy_version=ConsentPolicyVersion(consent_policy_version),
        stream_id=TalentStreamId(stream_id),
        document_id=(
            None
            if doc.get("document_id") is None
            else DocumentId(_nonblank(doc["document_id"], "document_id"))
        ),
        expires_at=(
            None if expires_at is None else storage_datetime_utc(expires_at, "grant.expires_at")
        ),
        revoked_at=(
            None if revoked_at is None else storage_datetime_utc(revoked_at, "grant.revoked_at")
        ),
    )
