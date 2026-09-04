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
from domains.opportunities.service import OpportunitySpecService
import domains.opportunities.service as opportunity_service_module
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


@pytest.mark.asyncio
async def test_revision_appends_new_version_without_mutating_previous(monkeypatch):
    now = datetime.now(timezone.utc)
    original = {
        "_id": "opp:backend-1:v1",
        "opportunity_spec_id": "opp:backend-1",
        "version": 1,
        "status": "draft",
        "created_at": now,
        "updated_at": now,
        "work_arrangement": "remote",
        "contract_types": ["CDI"],
        "provenance": "manual",
        "version_provenance": None,
        "version_provenance_ref": None,
    }

    class Collection:
        def __init__(self):
            self.docs = [dict(original)]

        async def find_one(self, query, sort=None, session=None):
            matching = [
                doc for doc in self.docs
                if all(doc.get(key) == value for key, value in query.items())
            ]
            if sort:
                matching.sort(key=lambda doc: doc["version"], reverse=True)
            return dict(matching[0]) if matching else None

        async def insert_one(self, doc, session=None):
            self.docs.append(dict(doc))

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def start_transaction(self):
            return self

    class Client:
        async def start_session(self):
            return Session()

    class DB:
        opportunity_specs = Collection()

    db = DB()
    monkeypatch.setattr(opportunity_service_module, "get_client", lambda: Client())
    revised = await OpportunitySpecService(db).revise(
        OpportunitySpecId("opp:backend-1"),
        EntityVersion(1),
        OpportunitySpecRevision(
            version_provenance=OpportunityFactSource.MANUAL,
            clear_fields=frozenset({"work_arrangement"}),
            contract_types=("CDD",),
        ),
    )

    assert original["work_arrangement"] == "remote"
    assert db.opportunity_specs.docs[0]["work_arrangement"] == "remote"
    assert revised["version"] == 2
    assert revised["work_arrangement"] is None
    assert revised["contract_types"] == ["CDD"]
    assert len(db.opportunity_specs.docs) == 2
