"""Intent domain contracts: Intent event types, provenance, and dimension definitions."""
from backend.domains.intent.contracts import (
    IntentEventType,
    IntentSourceType,
    IntentDimension,
    IntentEventBase,
    DeclaredIntentEvent,
    ObservedIntentEvent,
    IntentEvent,
    IntentEnvelope,
    RoleIntentSignal,
    RoleIntentAggregate,
    JobIntentAggregate,
    CompanyIntentAggregate,
    MarketIntentAggregate,
    IndependentSignalPolicy,
)

__all__ = [
    "IntentEventType",
    "IntentSourceType",
    "IntentDimension",
    "IntentEventBase",
    "DeclaredIntentEvent",
    "ObservedIntentEvent",
    "IntentEvent",
    "IntentEnvelope",
    "RoleIntentSignal",
    "RoleIntentAggregate",
    "JobIntentAggregate",
    "CompanyIntentAggregate",
    "MarketIntentAggregate",
    "IndependentSignalPolicy",
]