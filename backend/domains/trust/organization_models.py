"""Canonical Organization identity and verification contracts for TS-A7."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import FrozenSet, Optional, Tuple

from domains.shared.ids import OrganizationId
from domains.shared.versioning import EntityVersion, PolicyVersion


class OrganizationVerificationState(str, Enum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class OrganizationVerificationReasonCode(str, Enum):
    VERIFICATION_REQUESTED = "verification_requested"
    LEGAL_IDENTITY_CONFIRMED = "legal_identity_confirmed"
    DOMAIN_OWNERSHIP_CONFIRMED = "domain_ownership_confirmed"
    MANUAL_REVIEW_APPROVED = "manual_review_approved"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    IDENTITY_MISMATCH = "identity_mismatch"
    POLICY_VIOLATION = "policy_violation"
    SUSPICIOUS_ACTIVITY = "suspicious_activity"
    MANUAL_SUSPENSION = "manual_suspension"
    REVERIFICATION_APPROVED = "reverification_approved"
    IDENTITY_CHANGED_REVERIFICATION_REQUIRED = "identity_changed_reverification_required"


_ALLOWED_REASON_CODES_BY_STATE = {
    OrganizationVerificationState.PENDING: {
        OrganizationVerificationReasonCode.VERIFICATION_REQUESTED,
    },
    OrganizationVerificationState.VERIFIED: {
        OrganizationVerificationReasonCode.LEGAL_IDENTITY_CONFIRMED,
        OrganizationVerificationReasonCode.DOMAIN_OWNERSHIP_CONFIRMED,
        OrganizationVerificationReasonCode.MANUAL_REVIEW_APPROVED,
        OrganizationVerificationReasonCode.REVERIFICATION_APPROVED,
    },
    OrganizationVerificationState.REJECTED: {
        OrganizationVerificationReasonCode.EVIDENCE_INSUFFICIENT,
        OrganizationVerificationReasonCode.IDENTITY_MISMATCH,
        OrganizationVerificationReasonCode.POLICY_VIOLATION,
    },
    OrganizationVerificationState.SUSPENDED: {
        OrganizationVerificationReasonCode.POLICY_VIOLATION,
        OrganizationVerificationReasonCode.SUSPICIOUS_ACTIVITY,
        OrganizationVerificationReasonCode.MANUAL_SUSPENSION,
    },
}


def normalize_nonempty(value: str, field_name: str) -> str:
    normalized = " ".join((value or "").strip().split())
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized


def normalize_optional_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


def normalize_domain(value: Optional[str]) -> Optional[str]:
    value = normalize_optional_text(value)
    if value is None:
        return None
    domain = value.casefold().rstrip(".")
    if any(token in domain for token in ("://", "/", "@", " ")) or "." not in domain:
        raise ValueError("primary_domain must be a bare DNS domain")
    return domain


def normalize_country(value: Optional[str]) -> Optional[str]:
    value = normalize_optional_text(value)
    return None if value is None else value.upper()


def require_aware_datetime(value: datetime, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


def storage_datetime_utc(value: datetime, field_name: str) -> datetime:
    """Rehydrate a BSON datetime as aware UTC.

    PyMongo decodes BSON datetimes as naive UTC by default. Naive values are
    therefore accepted only at this persistence boundary and explicitly tagged
    UTC before entering strict domain contracts.
    """
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_evidence_refs(values: Tuple[str, ...]) -> Tuple[str, ...]:
    normalized = tuple(normalize_nonempty(value, "verification_evidence_ref") for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("verification evidence refs must be unique")
    return normalized


def _normalize_reason_codes(values) -> Tuple[OrganizationVerificationReasonCode, ...]:
    normalized = tuple(OrganizationVerificationReasonCode(value) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("verification reason codes must be unique")
    return normalized


def _validate_decision_metadata(
    *,
    state: OrganizationVerificationState,
    policy_version: Optional[PolicyVersion],
    reason_codes: Tuple[OrganizationVerificationReasonCode, ...],
    evidence_refs: Tuple[str, ...],
    actor_id: Optional[str],
    decided_at: Optional[datetime],
    created_at: datetime,
    updated_at: datetime,
) -> None:
    if policy_version is None or not str(policy_version).strip():
        raise ValueError("verification decision requires policy version")
    normalize_nonempty(actor_id or "", "verification_actor_id")
    if decided_at is None:
        raise ValueError("verification decision requires decided_at")
    require_aware_datetime(decided_at, "verification_decided_at")
    if decided_at < created_at or decided_at > updated_at:
        raise ValueError("verification_decided_at must be within organization lifetime")
    if not reason_codes:
        raise ValueError("verification decision requires reason codes")

    if state is OrganizationVerificationState.UNVERIFIED:
        if reason_codes != (
            OrganizationVerificationReasonCode.IDENTITY_CHANGED_REVERIFICATION_REQUIRED,
        ):
            raise ValueError("audited UNVERIFIED state requires identity-change re-verification reason")
        if evidence_refs:
            raise ValueError("identity-change reset to UNVERIFIED must not retain verification evidence")
        return

    allowed = _ALLOWED_REASON_CODES_BY_STATE[state]
    if any(reason not in allowed for reason in reason_codes):
        raise ValueError(f"reason codes are inconsistent with verification state {state.value}")
    if state is OrganizationVerificationState.VERIFIED and not evidence_refs:
        raise ValueError("VERIFIED organization requires verification evidence")


@dataclass(frozen=True)
class Organization:
    organization_id: OrganizationId
    version: EntityVersion
    legal_name: str
    verification_state: OrganizationVerificationState
    created_at: datetime
    updated_at: datetime
    display_name: Optional[str] = None
    website_url: Optional[str] = None
    primary_domain: Optional[str] = None
    registration_country: Optional[str] = None
    registration_id: Optional[str] = None
    legacy_company_id: Optional[str] = None
    verification_policy_version: Optional[PolicyVersion] = None
    verification_reason_codes: Tuple[OrganizationVerificationReasonCode, ...] = ()
    verification_evidence_refs: Tuple[str, ...] = ()
    verification_actor_id: Optional[str] = None
    verification_decided_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if not str(self.organization_id).strip():
            raise ValueError("organization_id must not be blank")
        if int(self.version) < 1:
            raise ValueError("organization version must be >= 1")
        state = OrganizationVerificationState(self.verification_state)
        object.__setattr__(self, "verification_state", state)
        object.__setattr__(self, "legal_name", normalize_nonempty(self.legal_name, "legal_name"))
        object.__setattr__(self, "display_name", normalize_optional_text(self.display_name))
        object.__setattr__(self, "website_url", normalize_optional_text(self.website_url))
        object.__setattr__(self, "primary_domain", normalize_domain(self.primary_domain))
        object.__setattr__(self, "registration_country", normalize_country(self.registration_country))
        object.__setattr__(self, "registration_id", normalize_optional_text(self.registration_id))
        object.__setattr__(self, "legacy_company_id", normalize_optional_text(self.legacy_company_id))
        if (self.registration_country is None) != (self.registration_id is None):
            raise ValueError("registration_country and registration_id must be provided together")

        require_aware_datetime(self.created_at, "created_at")
        require_aware_datetime(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot predate created_at")

        reasons = _normalize_reason_codes(self.verification_reason_codes)
        evidence = _normalize_evidence_refs(tuple(self.verification_evidence_refs))
        object.__setattr__(self, "verification_reason_codes", reasons)
        object.__setattr__(self, "verification_evidence_refs", evidence)

        has_decision_metadata = any((
            self.verification_policy_version is not None,
            bool(reasons),
            bool(evidence),
            self.verification_actor_id is not None,
            self.verification_decided_at is not None,
        ))
        if state is OrganizationVerificationState.UNVERIFIED and not has_decision_metadata:
            return

        _validate_decision_metadata(
            state=state,
            policy_version=self.verification_policy_version,
            reason_codes=reasons,
            evidence_refs=evidence,
            actor_id=self.verification_actor_id,
            decided_at=self.verification_decided_at,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


@dataclass(frozen=True)
class OrganizationCreate:
    organization_id: OrganizationId
    legal_name: str
    display_name: Optional[str] = None
    website_url: Optional[str] = None
    primary_domain: Optional[str] = None
    registration_country: Optional[str] = None
    registration_id: Optional[str] = None
    legacy_company_id: Optional[str] = None

    def to_identity(self) -> dict:
        organization_id = str(self.organization_id)
        if not organization_id.strip():
            raise ValueError("organization_id must not be blank")
        registration_country = normalize_country(self.registration_country)
        registration_id = normalize_optional_text(self.registration_id)
        if (registration_country is None) != (registration_id is None):
            raise ValueError("registration_country and registration_id must be provided together")
        return {
            "legal_name": normalize_nonempty(self.legal_name, "legal_name"),
            "display_name": normalize_optional_text(self.display_name),
            "website_url": normalize_optional_text(self.website_url),
            "primary_domain": normalize_domain(self.primary_domain),
            "registration_country": registration_country,
            "registration_id": registration_id,
            "legacy_company_id": normalize_optional_text(self.legacy_company_id),
        }


_CLEARABLE_IDENTITY_FIELDS = frozenset({
    "display_name", "website_url", "primary_domain", "registration_country", "registration_id"
})


@dataclass(frozen=True)
class OrganizationIdentityRevision:
    legal_name: Optional[str] = None
    display_name: Optional[str] = None
    website_url: Optional[str] = None
    primary_domain: Optional[str] = None
    registration_country: Optional[str] = None
    registration_id: Optional[str] = None
    legacy_company_id: Optional[str] = None
    clear_fields: FrozenSet[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        for field_name in (
            "legal_name", "display_name", "website_url", "primary_domain",
            "registration_country", "registration_id", "legacy_company_id",
        ):
            value = getattr(self, field_name)
            if value is not None and normalize_optional_text(value) is None:
                raise ValueError(f"{field_name} must not be blank when provided; use clear_fields when clearable")
        unknown = set(self.clear_fields) - _CLEARABLE_IDENTITY_FIELDS
        if unknown:
            raise ValueError(f"identity fields cannot be cleared: {', '.join(sorted(unknown))}")
        provided_registration = (self.registration_country is not None, self.registration_id is not None)
        clear_registration = (
            "registration_country" in self.clear_fields,
            "registration_id" in self.clear_fields,
        )
        if provided_registration[0] != provided_registration[1]:
            raise ValueError("registration_country and registration_id must be revised together")
        if clear_registration[0] != clear_registration[1]:
            raise ValueError("registration_country and registration_id must be cleared together")
        if any(provided_registration) and any(clear_registration):
            raise ValueError("registration identity cannot be set and cleared together")


@dataclass(frozen=True)
class OrganizationVerificationTransition:
    new_state: OrganizationVerificationState
    reason_codes: Tuple[OrganizationVerificationReasonCode, ...]
    evidence_refs: Tuple[str, ...]
    policy_version: PolicyVersion
    actor_id: str

    def __post_init__(self) -> None:
        state = OrganizationVerificationState(self.new_state)
        object.__setattr__(self, "new_state", state)
        if state is OrganizationVerificationState.UNVERIFIED:
            raise ValueError("UNVERIFIED is reached by identity reset, not a verification decision")
        reasons = _normalize_reason_codes(self.reason_codes)
        evidence = _normalize_evidence_refs(tuple(self.evidence_refs))
        object.__setattr__(self, "reason_codes", reasons)
        object.__setattr__(self, "evidence_refs", evidence)
        if not reasons:
            raise ValueError("verification transition requires reason codes")
        allowed_reasons = _ALLOWED_REASON_CODES_BY_STATE[state]
        if any(reason not in allowed_reasons for reason in reasons):
            raise ValueError(f"reason codes are inconsistent with verification state {state.value}")
        normalize_nonempty(self.actor_id, "actor_id")
        if not str(self.policy_version).strip():
            raise ValueError("verification transition requires policy_version")
        if state is OrganizationVerificationState.VERIFIED and not evidence:
            raise ValueError("VERIFIED requires at least one evidence reference")


def organization_from_document(doc: dict) -> Organization:
    """Strictly rehydrate one current Organization document.

    The Mongo `_id` and canonical `organization_id` must match. BSON datetime
    values are normalized from PyMongo's default naive-UTC representation at
    this persistence boundary before entering strict domain contracts.
    """
    if not isinstance(doc, dict):
        raise ValueError("organization document must be a mapping")
    required = (
        "_id", "organization_id", "version", "legal_name", "verification_state",
        "created_at", "updated_at",
    )
    missing = [field_name for field_name in required if field_name not in doc]
    if missing:
        raise ValueError(f"organization document missing required fields: {', '.join(missing)}")
    if doc["_id"] != doc["organization_id"]:
        raise ValueError("organization document identity mismatch")
    decided_at = doc.get("verification_decided_at")
    return Organization(
        organization_id=OrganizationId(doc["organization_id"]),
        version=EntityVersion(int(doc["version"])),
        legal_name=doc["legal_name"],
        verification_state=OrganizationVerificationState(doc["verification_state"]),
        created_at=storage_datetime_utc(doc["created_at"], "created_at"),
        updated_at=storage_datetime_utc(doc["updated_at"], "updated_at"),
        display_name=doc.get("display_name"),
        website_url=doc.get("website_url"),
        primary_domain=doc.get("primary_domain"),
        registration_country=doc.get("registration_country"),
        registration_id=doc.get("registration_id"),
        legacy_company_id=doc.get("legacy_company_id"),
        verification_policy_version=(
            None if doc.get("verification_policy_version") is None
            else PolicyVersion(doc["verification_policy_version"])
        ),
        verification_reason_codes=tuple(
            OrganizationVerificationReasonCode(value)
            for value in doc.get("verification_reason_codes", [])
        ),
        verification_evidence_refs=tuple(doc.get("verification_evidence_refs", [])),
        verification_actor_id=doc.get("verification_actor_id"),
        verification_decided_at=(
            None if decided_at is None
            else storage_datetime_utc(decided_at, "verification_decided_at")
        ),
    )
