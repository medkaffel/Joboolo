# Shared Kernel — Generic primitives for Talent Stream domains
# TS-A0-001: Domain Contracts & Business Invariants
# No business semantics here — cross-cutting primitives only

from .ids import (
    CandidateId,
    CompanyId,
    OrganizationId,
    RecruiterId,
    JobId,
    RoleDNAId,
    OpportunitySpecId,
    StreamId,
    IntentEventId,
    ContactRequestId,
    GrantId,
    MandateId,
    ProfileVersion,
    PreferencesVersion,
    RoleDNAVersion,
    OpportunitySpecVersion,
    MatchEngineVersion,
    IntentEngineVersion,
    PolicyVersion,
    ConsentVersion,
    EventSchemaVersion,
)
from .versioning import VersionedRef, Versioned
from .envelope import DomainEnvelope, Metadata

__all__ = [
    # IDs
    "CandidateId",
    "CompanyId",
    "OrganizationId",
    "RecruiterId",
    "JobId",
    "RoleDNAId",
    "OpportunitySpecId",
    "StreamId",
    "IntentEventId",
    "ContactRequestId",
    "GrantId",
    "MandateId",
    # Version types
    "ProfileVersion",
    "PreferencesVersion",
    "RoleDNAVersion",
    "OpportunitySpecVersion",
    "MatchEngineVersion",
    "IntentEngineVersion",
    "PolicyVersion",
    "ConsentVersion",
    "EventSchemaVersion",
    # Versioning
    "VersionedRef",
    "Versioned",
    # Envelope
    "DomainEnvelope",
    "Metadata",
]