# Intent Domain Contracts
# TS-A0-001: Domain Contracts & Business Invariants
# Owns: Intent event contracts/provenance, Job/Role/Company/Market Intent
# ARCHITECTURE.md §4: "intent — Owns intent event contracts/provenance, Job/Role/Company/Market Intent, recency/aggregation and intent-engine versioning. Discovery is NOT owned here."

from .events import (
    IntentEventType,
    IntentSourceType,
    IntentEvent,
    IntentEventProvenance,
    DeclaredIntentEvent,
    ObservedIntentEvent,
)
from .dimensions import (
    JobIntent,
    RoleIntent,
    CompanyIntent,
    MarketIntent,
)

__all__ = [
    "IntentEventType",
    "IntentSourceType",
    "IntentEvent",
    "IntentEventProvenance",
    "DeclaredIntentEvent",
    "ObservedIntentEvent",
    "JobIntent",
    "RoleIntent",
    "CompanyIntent",
    "MarketIntent",
]