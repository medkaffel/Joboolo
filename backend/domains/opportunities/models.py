"""Opportunity-specific constraints for Talent Stream (TS-A4).

Role DNA owns stable professional role facts. This module owns only constraints
of one concrete recruiting opportunity. Unknown source data stays unspecified.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import FrozenSet, Optional, Tuple

from domains.shared.ids import JobId, OpportunitySpecId
from domains.shared.versioning import EntityVersion


class OpportunitySpecStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class OpportunityFactSource(str, Enum):
    MANUAL = "manual"
    INTERNAL_JOB = "internal_job"
    IMPORTED = "imported"
    SUGGESTED = "suggested"


class CompensationBasis(str, Enum):
    ANNUAL = "annual"
    MONTHLY = "monthly"
    DAILY = "daily"
    HOURLY = "hourly"


class WorkArrangement(str, Enum):
    ONSITE = "onsite"
    HYBRID = "hybrid"
    REMOTE = "remote"


@dataclass(frozen=True)
class CompensationConstraint:
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    currency: str = "EUR"
    basis: Optional[CompensationBasis] = None

    def __post_init__(self) -> None:
        if self.minimum is not None and self.minimum < 0:
            raise ValueError("minimum compensation cannot be negative")
        if self.maximum is not None and self.maximum < 0:
            raise ValueError("maximum compensation cannot be negative")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.maximum < self.minimum
        ):
            raise ValueError("maximum compensation cannot be below minimum")
        if (self.minimum is not None or self.maximum is not None) and not self.currency.strip():
            raise ValueError("compensation currency is required when an amount is set")


@dataclass(frozen=True)
class LocationConstraint:
    locations: Tuple[str, ...] = ()
    radius_km: Optional[int] = None

    def __post_init__(self) -> None:
        if any(not location.strip() for location in self.locations):
            raise ValueError("location entries cannot be empty")
        if self.radius_km is not None and self.radius_km < 0:
            raise ValueError("radius_km cannot be negative")
        if self.radius_km is not None and not self.locations:
            raise ValueError("radius_km requires at least one target location")


@dataclass(frozen=True)
class OpportunitySpecification:
    opportunity_spec_id: OpportunitySpecId
    version: EntityVersion
    status: OpportunitySpecStatus
    created_at: datetime
    updated_at: datetime

    compensation: Optional[CompensationConstraint] = None
    location: Optional[LocationConstraint] = None
    work_arrangement: Optional[WorkArrangement] = None
    contract_types: Tuple[str, ...] = ()
    schedule: Optional[str] = None
    target_start: Optional[str] = None
    industry_constraints: Tuple[str, ...] = ()
    company_constraints: Tuple[str, ...] = ()
    must_have_requirements: Tuple[str, ...] = ()
    nice_to_have_requirements: Tuple[str, ...] = ()

    provenance: OpportunityFactSource = OpportunityFactSource.MANUAL
    source_job_id: Optional[JobId] = None
    source_ref: Optional[str] = None
    version_provenance: Optional[OpportunityFactSource] = None
    version_provenance_ref: Optional[str] = None

    def __post_init__(self) -> None:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot predate created_at")
        if self.provenance is OpportunityFactSource.INTERNAL_JOB and self.source_job_id is None:
            raise ValueError("internal-job Opportunity Specification requires source_job_id")
        if self.provenance in {
            OpportunityFactSource.IMPORTED,
            OpportunityFactSource.SUGGESTED,
        } and not self.source_ref:
            raise ValueError("imported/suggested Opportunity Specification requires source_ref")
        if self.version_provenance in {
            OpportunityFactSource.INTERNAL_JOB,
            OpportunityFactSource.IMPORTED,
            OpportunityFactSource.SUGGESTED,
        } and not self.version_provenance_ref:
            raise ValueError("non-manual Opportunity Specification version requires provenance ref")
        for values in (
            self.contract_types,
            self.industry_constraints,
            self.company_constraints,
            self.must_have_requirements,
            self.nice_to_have_requirements,
        ):
            if any(not value.strip() for value in values):
                raise ValueError("opportunity constraint entries cannot be empty")


@dataclass(frozen=True)
class OpportunitySpecRevision:
    version_provenance: OpportunityFactSource
    version_provenance_ref: Optional[str] = None

    status: Optional[OpportunitySpecStatus] = None
    compensation: Optional[CompensationConstraint] = None
    location: Optional[LocationConstraint] = None
    work_arrangement: Optional[WorkArrangement] = None
    contract_types: Optional[Tuple[str, ...]] = None
    schedule: Optional[str] = None
    target_start: Optional[str] = None
    industry_constraints: Optional[Tuple[str, ...]] = None
    company_constraints: Optional[Tuple[str, ...]] = None
    must_have_requirements: Optional[Tuple[str, ...]] = None
    nice_to_have_requirements: Optional[Tuple[str, ...]] = None
    clear_fields: FrozenSet[str] = frozenset()

    def __post_init__(self) -> None:
        if self.version_provenance in {
            OpportunityFactSource.INTERNAL_JOB,
            OpportunityFactSource.IMPORTED,
            OpportunityFactSource.SUGGESTED,
        } and not self.version_provenance_ref:
            raise ValueError("non-manual revision requires version_provenance_ref")
        clearable = {
            "compensation",
            "location",
            "work_arrangement",
            "schedule",
            "target_start",
        }
        if not self.clear_fields.issubset(clearable):
            raise ValueError("clear_fields contains a non-clearable opportunity field")
        for field_name in (
            "contract_types",
            "industry_constraints",
            "company_constraints",
            "must_have_requirements",
            "nice_to_have_requirements",
        ):
            values = getattr(self, field_name)
            if values is not None and any(not value.strip() for value in values):
                raise ValueError("opportunity constraint entries cannot be empty")
