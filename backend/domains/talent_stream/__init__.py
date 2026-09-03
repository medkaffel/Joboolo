# Talent Stream Domain Contracts
# TS-A0-001: Domain Contracts & Business Invariants
# Owns: Stream aggregate/lifecycle, contact-request orchestration, introduction lifecycle
# Consumes policy outcomes; must not redefine Match, Trust, Permission locally (ARCHITECTURE.md §4)

from .contact import (
    ContactRequest,
    ContactRequestStatus,
    ContactLifecycleEvent,
    ContactLifecycleEventType,
    CandidateDecision,
)
from .cv_access import (
    CVGrantReason,
    CVGrantScope,
    TalentStreamCVGrant,
    CVAccessRequest,
    CVAccessDecision,
)
from .exclusions import (
    ExclusionScope,
    ExclusionCheck,
    CurrentEmployerExclusion,
)

__all__ = [
    "ContactRequest",
    "ContactRequestStatus",
    "ContactLifecycleEvent",
    "ContactLifecycleEventType",
    "CandidateDecision",
    "CVGrantReason",
    "CVGrantScope",
    "TalentStreamCVGrant",
    "CVAccessRequest",
    "CVAccessDecision",
    "ExclusionScope",
    "ExclusionCheck",
    "CurrentEmployerExclusion",
]