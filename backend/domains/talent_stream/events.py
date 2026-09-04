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
    CampaignId,
    CandidateId,
    CausationId,
    CorrelationId,
    IdempotencyKey,
    IntentEventId,
    IntentEventType,
    IntentSourceType,
    JobId,
    OrganizationId,
    PseudonymousCandidateId,
    RoleDNAId,
)
from domains.shared.versioning import ConsentPolicyVersion, PolicyVersion, SchemaVersion


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
class IntentSubject:
    """Exactly one internal subject identity form must be present."""

    candidate_id: Optional[CandidateId] = None
    pseudonymous_id: Optional[PseudonymousCandidateId] = None

    def __post_init__(self) -> None:
        if (self.candidate_id is None) == (self.pseudonymous_id is None):
            raise ValueError("intent subject requires exactly one identity form")


@dataclass(frozen=True)
class ConsentContextRef:
    consent_policy_version: ConsentPolicyVersion
    context_ref: str


@dataclass(frozen=True)
class PrivacyContextRef:
    policy_version: PolicyVersion
    context_ref: str


@dataclass(frozen=True)
class TalentIntentEvent:
    """Governed intent evidence.

    Declared, observed and inferred describe evidence origin only. None of these
    origins is sharing consent or Permission authority, and inferred evidence is
    never treated as a candidate declaration.
    """

    event_id: IntentEventId
    schema_version: SchemaVersion
    subject: IntentSubject
    intent_kind: IntentKind
    origin: IntentOrigin
    event_type: IntentEventType
    occurred_at: datetime
    created_at: datetime
    source_type: IntentSourceType
    idempotency_key: Optional[IdempotencyKey] = None
    job_id: Optional[JobId] = None
    role_dna_id: Optional[RoleDNAId] = None
    source_organization_id: Optional[OrganizationId] = None
    source_campaign_id: Optional[CampaignId] = None
    consent_context: Optional[ConsentContextRef] = None
    privacy_context: Optional[PrivacyContextRef] = None
    retention_until: Optional[datetime] = None
    correlation_id: Optional[CorrelationId] = None
    causation_id: Optional[CausationId] = None

    def __post_init__(self) -> None:
        if self.created_at < self.occurred_at:
            raise ValueError("intent event creation cannot predate occurrence")
        if self.retention_until is not None and self.retention_until <= self.occurred_at:
            raise ValueError("retention_until must be after event occurrence")
