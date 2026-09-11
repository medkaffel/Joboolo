"""Internal, non-persistent references to existing domain audit evidence.

No resolver, writer or authorization decision lives here. A reference does not
prove source existence. Governance metadata is descriptive: it neither extends
source retention nor creates access rights. Source events retain their own
actors, timestamps, reasons and evidence; none are copied into this contract.
"""
from dataclasses import dataclass
from enum import Enum
import re


class AuditEvidenceSourceKind(str, Enum):
    ORGANIZATION_VERIFICATION = "organization_verification"
    MEMBERSHIP = "membership"
    RECRUITER_VERIFICATION = "recruiter_verification"
    MANDATE = "mandate"
    PRIVACY_REVOCATION = "privacy_revocation"


def _identifier(value: str, field: str) -> None:
    # Opaque internal identifiers only. Syntax validation is not a PII detector
    # or proof that the source exists; callers must supply canonical IDs.
    if type(value) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]*", value) is None:
        raise ValueError(f"{field} must be a nonempty internal identifier")


@dataclass(frozen=True, slots=True)
class AuditEvidenceRef:
    source_kind: AuditEvidenceSourceKind
    source_event_id: str
    retention_category: str
    retention_purpose: str
    retention_policy_version: str
    schema_version: str = "audit-evidence-ref-v1"

    def __post_init__(self) -> None:
        if type(self.source_kind) is not AuditEvidenceSourceKind:
            raise ValueError("source_kind must be an AuditEvidenceSourceKind member")
        _identifier(self.source_event_id, "source_event_id")
        for field in ("retention_category", "retention_purpose"):
            value = getattr(self, field)
            if type(value) is not str or re.fullmatch(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*", value) is None:
                raise ValueError(f"{field} must be a nonempty descriptive token")
        _identifier(self.retention_policy_version, "retention_policy_version")
        if type(self.schema_version) is not str or self.schema_version != "audit-evidence-ref-v1":
            raise ValueError("unsupported audit evidence reference schema")

    @property
    def evidence_identity(self) -> tuple[AuditEvidenceSourceKind, str]:
        """Stable source identity, independent of descriptive governance metadata."""
        return self.source_kind, self.source_event_id
