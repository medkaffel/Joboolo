"""Pure qualification of domain-owned reasons; no vocabulary registry.

Validation checks syntax only, never membership in a domain vocabulary. Callers
own the namespace-to-domain association. Existing enum values remain unchanged.
"""
from dataclasses import dataclass
from enum import Enum
import re


def _token(value: str, field: str, pattern: str) -> None:
    if type(value) is not str or re.fullmatch(pattern, value) is None:
        raise ValueError(f"{field} must be a nonempty canonical token")


@dataclass(frozen=True, slots=True)
class ReasonCodeRef:
    """Identity is the complete (namespace, code) pair, not code alone."""

    namespace: str
    code: str

    def __post_init__(self) -> None:
        _token(self.namespace, "namespace", r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*(?:\.[a-z][a-z0-9]*(?:_[a-z0-9]+)*)*")
        _token(self.code, "code", r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")


def qualify_reason_code(namespace: str, member: Enum) -> ReasonCodeRef:
    """Qualify an actual string-valued Enum member without normalizing its value."""
    if not isinstance(member, Enum) or type(member.value) is not str:
        raise ValueError("reason must be a string-valued Enum member")
    return ReasonCodeRef(namespace=namespace, code=member.value)
