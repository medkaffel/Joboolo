"""Canonical Organization identity and verification contracts for TS-A7."""
from dataclasses import dataclass, field
from datetime import datetime
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
        object.__setattr__(self, "legal_name", normalize_nonempty(self.legal_name, "legal_name"))
        object.__setattr__(self, "display_name", normalize_optional_text(self.display_name))
        object.__setattr__(self, "website_url", normalize_optional_text(self.website_url))
        object.__setattr__(self, "primary_domain", normalize_domain(self.primary_domain))
        object.__setattr__(self, "registration_country", normalize_country(self.registration_country))
        object.__setattr__(self, "registration_id", normalize_optional_text(self.registration_id))
        object.__setattr__(self, "legacy_company_id", normalize_optional_text(self.legacy_company_id))
        if (self.registration_country is None) != (self.registration_id is None):
            raise ValueError("registration_country and registration_id must be provided together")
        if self.verification_state is OrganizationVerificationState.UNVERIFIED:
            return
        if self.verification_policy_version is None or self.verification_actor_id is None or self.verification_decided_at is None:
            raise ValueError("non-unverified organization requires latest verification decision metadata")
        if not self.verification_reason_codes:
            raise ValueError("non-unverified organization requires verification reason codes")
        if self.verification_state is OrganizationVerificationState.VERIFIED and not self.verification_evidence_refs:
            raise ValueError("VERIFIED organization requires verification evidence")


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
        organization = Organization(
            organization_id=self.organization_id,
            version=EntityVersion(1),
            legal_name=self.legal_name,
            verification_state=OrganizationVerificationState.UNVERIFIED,
            created_at=datetime.min,
            updated_at=datetime.min,
            display_name=self.display_name,
            website_url=self.website_url,
            primary_domain=self.primary_domain,
            registration_country=self.registration_country,
            registration_id=self.registration_id,
            legacy_company_id=self.legacy_company_id,
        )
        return {
            "legal_name": organization.legal_name,
            "display_name": organization.display_name,
            "website_url": organization.website_url,
            "primary_domain": organization.primary_domain,
            "registration_country": organization.registration_country,
            "registration_id": organization.registration_id,
            "legacy_company_id": organization.legacy_company_id,
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
        if self.new_state is OrganizationVerificationState.UNVERIFIED:
            raise ValueError("UNVERIFIED is reached by identity reset, not a verification decision")
        if not self.reason_codes:
            raise ValueError("verification transition requires reason codes")
        allowed_reasons = _ALLOWED_REASON_CODES_BY_STATE[self.new_state]
        invalid_reasons = [reason for reason in self.reason_codes if reason not in allowed_reasons]
        if invalid_reasons:
            raise ValueError(
                f"reason codes are inconsistent with verification state {self.new_state.value}"
            )
        if not normalize_optional_text(self.actor_id):
            raise ValueError("verification transition requires actor_id")
        if not str(self.policy_version).strip():
            raise ValueError("verification transition requires policy_version")
        if any(normalize_optional_text(value) is None for value in self.evidence_refs):
            raise ValueError("evidence references must not be blank")
        if self.new_state is OrganizationVerificationState.VERIFIED and not self.evidence_refs:
            raise ValueError("VERIFIED requires at least one evidence reference")
