from datetime import datetime, timezone

import pytest

from domains.roles.models import RoleDNA, RoleDNARevision, RoleDNAStatus, RoleFactSource, RoleSkill
from domains.roles.repository import RoleDNARepository
from domains.shared.ids import RoleDNAId
from domains.shared.versioning import EntityVersion


def role(**kwargs):
    now = datetime.now(timezone.utc)
    data = dict(
        role_dna_id=RoleDNAId("role:software-engineer"),
        version=EntityVersion(1),
        status=RoleDNAStatus.DRAFT,
        canonical_title="Software Engineer",
        created_at=now,
        updated_at=now,
    )
    data.update(kwargs)
    return RoleDNA(**data)


def test_role_dna_excludes_opportunity_constraints():
    fields = RoleDNA.__dataclass_fields__
    for forbidden in ("salary_min", "salary_max", "location", "is_remote", "job_type", "contract_type"):
        assert forbidden not in fields


def test_role_dna_contains_no_candidate_permission_or_intent():
    fields = RoleDNA.__dataclass_fields__
    for forbidden in ("candidate_id", "preferences", "intent", "permission", "grant", "discovery"):
        assert forbidden not in fields


def test_suggested_role_requires_source_job_provenance():
    with pytest.raises(ValueError):
        role(provenance=RoleFactSource.SUGGESTED)


def test_normalized_skill_keeps_normalization_reference():
    with pytest.raises(ValueError):
        RoleSkill(label="Python", source=RoleFactSource.MANUAL, normalized_code="skill:python")


def test_role_dna_version_is_positive():
    with pytest.raises(ValueError):
        EntityVersion(0)


def test_revision_requires_explicit_version_provenance():
    revision = RoleDNARevision(
        version_provenance=RoleFactSource.MANUAL,
        canonical_title="Senior Software Engineer",
    )
    serialized = RoleDNARepository.serialize_revision(revision)
    assert serialized["version_provenance"] == "manual"
    assert serialized["canonical_title"] == "Senior Software Engineer"


def test_imported_or_suggested_revision_requires_provenance_ref():
    with pytest.raises(ValueError):
        RoleDNARevision(
            version_provenance=RoleFactSource.SUGGESTED,
            canonical_title="Software Engineer",
        )


def test_provenance_only_revision_has_no_business_change():
    revision = RoleDNARevision(version_provenance=RoleFactSource.MANUAL)
    serialized = RoleDNARepository.serialize_revision(revision)
    business = {
        key: value
        for key, value in serialized.items()
        if key not in {"version_provenance", "version_provenance_ref"}
    }
    assert business == {}
