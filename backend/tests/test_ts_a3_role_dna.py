from datetime import datetime, timezone

import pytest

from domains.roles.models import RoleDNA, RoleDNAStatus, RoleFactSource, RoleSkill
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
