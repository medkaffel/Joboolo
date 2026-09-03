# Roles Domain Contracts
# TS-A0-001: Domain Contracts & Business Invariants
# Owns: Role DNA, Occupation/Skill Taxonomy, Role Normalization
# Freezes RoleDNA identity/version for A3/A5/C1

from .role_dna import (
    RoleDNA,
    RoleDNAVersion,
    RoleDNARef,
)
from .taxonomy import (
    OccupationTaxonomyRef,
    SkillTaxonomyRef,
)

__all__ = [
    "RoleDNA",
    "RoleDNAVersion",
    "RoleDNARef",
    "OccupationTaxonomyRef",
    "SkillTaxonomyRef",
]