"""Opportunity Specification bounded context (TS-A4)."""

from .models import (
    CompensationBasis,
    CompensationConstraint,
    LocationConstraint,
    OpportunityFactSource,
    OpportunitySpecRevision,
    OpportunitySpecStatus,
    OpportunitySpecification,
    WorkArrangement,
)
from .service import OpportunitySpecConflictError, OpportunitySpecService

__all__ = [
    "CompensationBasis",
    "CompensationConstraint",
    "LocationConstraint",
    "OpportunityFactSource",
    "OpportunitySpecRevision",
    "OpportunitySpecStatus",
    "OpportunitySpecification",
    "WorkArrangement",
    "OpportunitySpecConflictError",
    "OpportunitySpecService",
]
