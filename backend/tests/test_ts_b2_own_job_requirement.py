"""Hermetic TS-B2 own-job requirement adapter contracts."""
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pymongo.errors import DuplicateKeyError

from domains.opportunities.models import OpportunityFactSource, OpportunitySpecStatus
from domains.roles.models import RoleDNAStatus, RoleFactSource
from domains.talent_stream.own_job_mapping import (
    OWN_JOB_MAPPING_VERSION,
    OwnJobMappingError,
    OwnJobSourceConflictError,
    deterministic_own_job_ids,
    own_job_source_fingerprint,
    prepare_own_job_requirement,
)
from domains.talent_stream.own_job_repository import (
    OwnJobAccessError,
    OwnJobReadinessError,
)
from domains.talent_stream.own_job_service import OwnJobRequirementService


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 12, 21, 30, tzinfo=timezone.utc)


def job(**changes):
    value = {
        "_id": "job-1",
        "employer_id": "recruiter-1",
        "company_id": "company-1",
        "title": " Backend Engineer ",
        "description": "Build APIs",
        "location": " Paris ",
        "salary_min": 50000,
        "salary_max": 70000,
        "salary_currency": "EUR",
        "job_type": "CDI",
        "is_remote": True,
        "requirements": ["Python"],
        "benefits": ["Transport"],
        "tags": ["backend"],
        "is_active": False,
        "expires_at": NOW - timedelta(days=1),
    }
    value.update(changes)
    return value


def test_exact_mapping_preserves_only_certain_role_and_opportunity_facts():
    result = prepare_own_job_requirement(job(), "recruiter-1", "command-1", NOW)
    role = result.role_dna
    opportunity = result.opportunity_specification
    assert role.status is RoleDNAStatus.DRAFT and role.version == 1
    assert role.canonical_title == "Backend Engineer"
    assert role.skills == role.capabilities == role.certifications == role.languages == ()
    assert role.family_code is role.seniority_band is role.experience_band is None
    assert role.provenance is RoleFactSource.IMPORTED and role.source_job_id == "job-1"
    assert opportunity.status is OpportunitySpecStatus.DRAFT and opportunity.version == 1
    assert opportunity.location.locations == ("Paris",)
    assert opportunity.compensation.minimum == 50000
    assert opportunity.compensation.maximum == 70000
    assert opportunity.compensation.currency == "EUR"
    assert opportunity.compensation.basis is None
    assert opportunity.contract_types == ("CDI",)
    assert opportunity.work_arrangement is None
    assert opportunity.must_have_requirements is opportunity.nice_to_have_requirements is None
    assert opportunity.provenance is OpportunityFactSource.INTERNAL_JOB
    assert result.requirement_snapshot.captured_at == NOW
    assert result.source_fingerprint.startswith("sha256:")
    assert OWN_JOB_MAPPING_VERSION in role.version_provenance_ref


def test_absent_optional_facts_stay_unknown_without_legacy_defaults():
    raw = {
        "_id": "job-1", "employer_id": "recruiter-1",
        "company_id": "company-1", "title": "Engineer",
    }
    result = prepare_own_job_requirement(raw, "recruiter-1", "command-1", NOW)
    opportunity = result.opportunity_specification
    assert opportunity.compensation is None
    assert opportunity.location is None
    assert opportunity.contract_types is None
    assert opportunity.work_arrangement is None


@pytest.mark.parametrize("changes", [
    {"title": " "},
    {"is_remote": "true"},
    {"is_active": 1},
    {"salary_min": True},
    {"salary_min": -1},
    {"salary_min": 10, "salary_max": 5},
    {"salary_currency": None},
    {"job_type": "Permanent"},
    {"requirements": "Python"},
    {"benefits": [""]},
    {"tags": [1]},
    {"expires_at": "tomorrow"},
])
def test_malformed_source_fails_closed(changes):
    with pytest.raises(OwnJobMappingError):
        prepare_own_job_requirement(job(**changes), "recruiter-1", "command-1", NOW)


@pytest.mark.parametrize("marker,value", [
    ("is_partner", True),
    ("partner_id", "partner-1"),
    ("campaign_id", "campaign-1"),
    ("external_url", "https://example.test/job"),
    ("external_ref", "external-1"),
])
def test_every_partner_or_external_marker_is_rejected(marker, value):
    with pytest.raises(OwnJobMappingError, match="partner, imported and external"):
        prepare_own_job_requirement(job(**{marker: value}), "recruiter-1", "command-1", NOW)


def test_identity_fingerprint_and_ids_are_deterministic_and_scoped():
    raw = job()
    baseline = prepare_own_job_requirement(raw, "recruiter-1", "command-1", NOW)
    assert baseline == prepare_own_job_requirement(deepcopy(raw), "recruiter-1", "command-1", NOW)
    assert deterministic_own_job_ids("recruiter-1", "job-1", "command-1") != (
        deterministic_own_job_ids("recruiter-1", "job-1", "command-2")
    )
    assert own_job_source_fingerprint(raw, "recruiter-1", "job-1") != (
        own_job_source_fingerprint(job(description="Changed"), "recruiter-1", "job-1")
    )
    with pytest.raises(OwnJobMappingError):
        deterministic_own_job_ids("recruiter-1", "job-1", " ")


class Cursor:
    def __init__(self, values):
        self.values = iter(values)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.values)
        except StopIteration:
            raise StopAsyncIteration


class Collection:
    def __init__(self, documents=(), indexes=None):
        self.documents = [deepcopy(value) for value in documents]
        self.indexes = deepcopy(indexes or {"_id_": {"v": 2, "key": [("_id", 1)]}})
        self.fail_once = False

    async def find_one(self, query, *args, sort=None, **kwargs):
        matches = [
            document for document in self.documents
            if all(document.get(key) == value for key, value in query.items())
        ]
        if sort:
            matches.sort(key=lambda document: document[sort[0][0]], reverse=sort[0][1] < 0)
        return deepcopy(matches[0]) if matches else None

    async def insert_one(self, document, **kwargs):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("injected write interruption")
        if any(existing.get("_id") == document.get("_id") for existing in self.documents):
            raise DuplicateKeyError("duplicate")
        self.documents.append(deepcopy(document))

    async def index_information(self):
        return deepcopy(self.indexes)


def indexes(name, fields):
    return {
        "_id_": {"v": 2, "key": [("_id", 1)]},
        name: {"v": 2, "key": [(field, 1) for field in fields], "unique": True},
    }


class DB:
    def __init__(self, *, user_type="employer", active=True, source=None):
        self.users = Collection([{"_id": "recruiter-1", "user_type": user_type, "is_active": active}])
        self.jobs = Collection([source or job()])
        self.companies = Collection([{"_id": "company-1", "owner_id": "recruiter-1"}])
        self.role_dnas = Collection(indexes=indexes(
            "ts_a3_role_dna_version_unique", ("role_dna_id", "version"),
        ))
        self.opportunity_specs = Collection(indexes=indexes(
            "ts_a4_opportunity_spec_version_unique", ("opportunity_spec_id", "version"),
        ))

    def __getitem__(self, name):
        return getattr(self, name)

    async def list_collections(self, **kwargs):
        return Cursor([
            {"name": "role_dnas", "type": "collection", "options": {}},
            {"name": "opportunity_specs", "type": "collection", "options": {}},
        ])


@pytest.mark.asyncio
async def test_service_retries_reuse_exact_pair_and_stable_timestamp():
    db = DB()
    service = OwnJobRequirementService(db)
    first = await service.prepare("recruiter-1", "job-1", command_id="command-1", captured_at=NOW)
    replay = await service.prepare("recruiter-1", "job-1", command_id="command-1")
    assert replay == first
    assert len(db.role_dnas.documents) == len(db.opportunity_specs.documents) == 1


@pytest.mark.asyncio
async def test_partial_pair_is_completed_only_by_exact_retry():
    db = DB()
    db.opportunity_specs.fail_once = True
    service = OwnJobRequirementService(db)
    with pytest.raises(RuntimeError, match="injected write interruption"):
        await service.prepare("recruiter-1", "job-1", command_id="command-1", captured_at=NOW)
    assert len(db.role_dnas.documents) == 1 and not db.opportunity_specs.documents
    result = await service.prepare("recruiter-1", "job-1", command_id="command-1")
    assert result.requirement_snapshot.captured_at == NOW
    assert len(db.role_dnas.documents) == len(db.opportunity_specs.documents) == 1


@pytest.mark.asyncio
async def test_same_command_after_business_edit_conflicts_and_new_command_is_new_pair():
    db = DB()
    service = OwnJobRequirementService(db)
    first = await service.prepare("recruiter-1", "job-1", command_id="command-1", captured_at=NOW)
    db.jobs.documents[0]["title"] = "Changed title"
    with pytest.raises(OwnJobSourceConflictError):
        await service.prepare("recruiter-1", "job-1", command_id="command-1")
    second = await service.prepare(
        "recruiter-1", "job-1", command_id="command-2",
        captured_at=NOW + timedelta(seconds=1),
    )
    assert first.requirement_snapshot.role_dna != second.requirement_snapshot.role_dna
    assert len(db.role_dnas.documents) == len(db.opportunity_specs.documents) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("user_type,active", [("candidate", True), ("partner", True), ("employer", False)])
async def test_non_employer_or_inactive_actor_is_rejected(user_type, active):
    with pytest.raises(OwnJobAccessError):
        await OwnJobRequirementService(DB(user_type=user_type, active=active)).prepare(
            "recruiter-1", "job-1", command_id="command-1",
        )


@pytest.mark.asyncio
async def test_admin_still_requires_exact_job_and_company_ownership():
    db = DB(user_type="admin")
    await OwnJobRequirementService(db).prepare(
        "recruiter-1", "job-1", command_id="command-1", captured_at=NOW,
    )
    db.companies.documents[0]["owner_id"] = "someone-else"
    with pytest.raises(OwnJobAccessError):
        await OwnJobRequirementService(db).prepare(
            "recruiter-1", "job-1", command_id="command-2",
        )


@pytest.mark.asyncio
async def test_index_contract_fails_before_any_a3_a4_write():
    db = DB()
    db.role_dnas.indexes.pop("ts_a3_role_dna_version_unique")
    with pytest.raises(OwnJobReadinessError):
        await OwnJobRequirementService(db).prepare(
            "recruiter-1", "job-1", command_id="command-1",
        )
    assert not db.role_dnas.documents and not db.opportunity_specs.documents


def test_adapter_has_no_route_network_stream_creation_or_adjacent_lot_dependency():
    files = (
        "domains/talent_stream/own_job_mapping.py",
        "domains/talent_stream/own_job_repository.py",
        "domains/talent_stream/own_job_service.py",
    )
    forbidden = {
        "fastapi", "requests", "httpx", "aiohttp", "geo_service",
        "domains.intent", "domains.permissions", "domains.privacy",
        "domains.matching", "domains.preferences",
    }
    for relative in files:
        tree = ast.parse((BACKEND / relative).read_text(encoding="utf-8"))
        imports = {
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imports.update(
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert not imports & forbidden
        attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert "start_transaction" not in attributes
    service = (BACKEND / files[-1]).read_text(encoding="utf-8")
    assert "TalentStreamService" not in service
