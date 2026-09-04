from datetime import datetime, timezone

import pytest

from domains.opportunities.models import (
    CompensationConstraint,
    LocationConstraint,
    OpportunityFactSource,
    OpportunitySpecRevision,
    OpportunitySpecStatus,
    OpportunitySpecification,
    WorkArrangement,
)
from domains.opportunities.repository import OpportunitySpecRepository
from domains.shared.ids import JobId, OpportunitySpecId
from domains.shared.versioning import EntityVersion


def spec(**kwargs):
    now = datetime.now(timezone.utc)
    data = dict(
        opportunity_spec_id=OpportunitySpecId("opp:backend-1"),
        version=EntityVersion(1),
        status=OpportunitySpecStatus.DRAFT,
        created_at=now,
        updated_at=now,
    )
    data.update(kwargs)
    return OpportunitySpecification(**data)


def test_opportunity_spec_contains_constraints_but_no_role_or_candidate_authority():
    fields = OpportunitySpecification.__dataclass_fields__
    for expected in ("compensation", "location", "work_arrangement", "contract_types"):
        assert expected in fields
    for forbidden in (
        "role_dna_id", "candidate_id", "preferences", "discovery", "intent",
        "permission", "trust", "cv", "document_id",
    ):
        assert forbidden not in fields


def test_work_arrangement_can_remain_unspecified():
    assert spec().work_arrangement is None
    assert spec(work_arrangement=WorkArrangement.REMOTE).work_arrangement is WorkArrangement.REMOTE


def test_compensation_and_location_constraints_validate_ranges():
    with pytest.raises(ValueError):
        CompensationConstraint(minimum=70000, maximum=60000)
    with pytest.raises(ValueError):
        LocationConstraint(radius_km=50)
    assert LocationConstraint(locations=("Paris",), radius_km=50).radius_km == 50


def test_non_manual_origin_requires_explicit_provenance():
    with pytest.raises(ValueError):
        spec(provenance=OpportunityFactSource.INTERNAL_JOB)
    created = spec(
        provenance=OpportunityFactSource.INTERNAL_JOB,
        source_job_id=JobId("job-1"),
    )
    assert created.source_job_id == JobId("job-1")


def test_non_manual_revision_requires_provenance_ref():
    with pytest.raises(ValueError):
        OpportunitySpecRevision(
            version_provenance=OpportunityFactSource.IMPORTED,
            contract_types=("CDI",),
        )


def test_revision_serialization_distinguishes_clear_from_absent():
    revision = OpportunitySpecRevision(
        version_provenance=OpportunityFactSource.MANUAL,
        clear_fields=frozenset({"work_arrangement", "compensation"}),
    )
    serialized = OpportunitySpecRepository.serialize_revision(revision)
    assert serialized["work_arrangement"] is None
    assert serialized["compensation"] is None
    assert "location" not in serialized


def test_list_constraints_are_cleared_explicitly_with_empty_tuple():
    revision = OpportunitySpecRevision(
        version_provenance=OpportunityFactSource.MANUAL,
        contract_types=(),
        must_have_requirements=(),
    )
    serialized = OpportunitySpecRepository.serialize_revision(revision)
    assert serialized["contract_types"] == []
    assert serialized["must_have_requirements"] == []


def test_provenance_only_revision_has_no_business_change():
    revision = OpportunitySpecRevision(version_provenance=OpportunityFactSource.MANUAL)
    serialized = OpportunitySpecRepository.serialize_revision(revision)
    business = {
        key: value
        for key, value in serialized.items()
        if key not in {"version_provenance", "version_provenance_ref"}
    }
    assert business == {}


def test_entity_version_remains_strictly_positive():
    with pytest.raises(ValueError):
        EntityVersion(0)
