"""Explainable policy-decision contracts for Talent Stream safety gates."""
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple

from domains.shared.versioning import ConsentPolicyVersion, PolicyVersion


@dataclass(frozen=True, kw_only=True)
class PolicyDecision:
    allowed: bool
    reason_codes: Tuple[str, ...]
    policy_version: PolicyVersion
    evaluated_at: datetime
    evidence_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason_codes:
            raise ValueError("policy decision requires at least one reason code")


@dataclass(frozen=True, kw_only=True)
class TrustDecision(PolicyDecision):
    pass


@dataclass(frozen=True, kw_only=True)
class PermissionDecision(PolicyDecision):
    consent_policy_version: ConsentPolicyVersion


@dataclass(frozen=True, kw_only=True)
class SourceProtectionDecision(PolicyDecision):
    pass


@dataclass(frozen=True, kw_only=True)
class ContactGovernorDecision(PolicyDecision):
    pass


@dataclass(frozen=True, kw_only=True)
class PrivacyDecision(PolicyDecision):
    pass
