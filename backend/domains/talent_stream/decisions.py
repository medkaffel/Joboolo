"""Explainable policy-decision contracts for Talent Stream safety gates."""
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple

from domains.shared.versioning import PolicyVersion


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason_codes: Tuple[str, ...]
    policy_version: PolicyVersion
    evaluated_at: datetime
    evidence_refs: Tuple[str, ...] = ()


@dataclass(frozen=True)
class TrustDecision(PolicyDecision):
    pass


@dataclass(frozen=True)
class PermissionDecision(PolicyDecision):
    pass


@dataclass(frozen=True)
class SourceProtectionDecision(PolicyDecision):
    pass


@dataclass(frozen=True)
class ContactGovernorDecision(PolicyDecision):
    pass


@dataclass(frozen=True)
class PrivacyDecision(PolicyDecision):
    pass
