"""Version contracts shared by Talent Stream bounded contexts."""
from typing import NewType


class EntityVersion(int):
    """Strictly positive entity version with int-compatible runtime semantics."""

    def __new__(cls, value: int) -> "EntityVersion":
        if value < 1:
            raise ValueError("entity version must be >= 1")
        return int.__new__(cls, value)


SchemaVersion = NewType("SchemaVersion", str)
EngineVersion = NewType("EngineVersion", str)
PolicyVersion = NewType("PolicyVersion", str)
ConsentPolicyVersion = NewType("ConsentPolicyVersion", str)
