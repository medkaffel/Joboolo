"""Intent/provenance event envelope contracts for TS-A0-001.

Billing/CPC events are deliberately not represented here. Talent Stream intent
has its own governed event contract even when internal provenance references a
job, organization, or campaign.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from domains.shared.ids import (
    CandidateId,
    CausationId,
    CorrelationId,
    IdempotencyKey,
    IntentEventId,
    OrganizationId,
    RoleDNAId,
)
from domains.shared.versioning import SchemaVersion


class IntentKind(str, Enum):
    JOB = "job"
    ROLE = "role"
    COMPANY = "company"
    MARKET = "market"


class IntentOrigin(str, Enum):
    DECLARED = "declared"
    OBSERVED = "observed"
    INFERRED = "inferred"


@dataclass(frozen=True)
class TalentIntentEvent:
    event_id: IntentEventId
    schema_version: SchemaVersion
    candidate_id: CandidateId
    intent_kind: IntentKind
    origin: IntentOrigin
    event_type: str
    occurred_at: datetime
    created_at: datetime
    source_type: str
    idempotency_key: Optional[IdempotencyKey] = None
    job_id: Optional[str] = None
    role_dna_id: Optional[RoleDNAId] = None
    source_organization_id: Optional[OrganizationId] = None
    source_campaign_id: Optional[str] = None
    consent_context: Optional[str] = None
    privacy_context: Optional[str] = None
    retention_until: Optional[datetime] = None
    correlation_id: Optional[CorrelationId] = None
    causation_id: Optional[CausationId] = None
