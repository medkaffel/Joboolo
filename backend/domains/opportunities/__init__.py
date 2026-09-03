# Opportunities Domain Contracts
# TS-A0-001: Domain Contracts & Business Invariants
# Owns: Opportunity Specification, Stream Requirement composition
# Freezes: RoleDNA + OpportunitySpec = StreamRequirement (TALENT_STREAM_SPEC.md §6)

from .opportunity_spec import (
    OpportunitySpecification,
    OpportunitySpecVersion,
    OpportunitySpecRef,
)
from .stream_requirement import (
    StreamRequirement,
    StreamRequirementInput,
    StreamRequirementUpdate,
)
from ..shared.versioning import StreamRequirementVersion

__all__ = [
    "OpportunitySpecification",
    "OpportunitySpecVersion",
    "OpportunitySpecRef",
    "StreamRequirement",
    "StreamRequirementVersion",
    "StreamRequirementInput",
    "StreamRequirementUpdate",
]