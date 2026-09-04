"""Version contracts shared by Talent Stream bounded contexts."""
from typing import NewType

EntityVersion = NewType("EntityVersion", int)
SchemaVersion = NewType("SchemaVersion", str)
EngineVersion = NewType("EngineVersion", str)
PolicyVersion = NewType("PolicyVersion", str)
ConsentPolicyVersion = NewType("ConsentPolicyVersion", str)


def validate_entity_version(version: int) -> int:
    """Require strictly positive entity versions."""
    if version < 1:
        raise ValueError("entity version must be >= 1")
    return version
