"""TS-B3 G0: hermetic application-source security and data contracts."""
import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from domains.shared.ids import (
    HiringCompanyId,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import EntityVersion
from domains.talent_stream.application_source_models import (
    ApplicationSource,
    ApplicationSourceCursor,
)
from domains.talent_stream.application_source_repository import (
    APPLICATION_FIELDS,
    APPLICATION_SOURCE_REQUIREMENT,
    JOB_FIELDS,
)
from domains.talent_stream.application_source_service import (
    ApplicationSourceAccessError,
    ApplicationSourceConflictError,
    ApplicationSourceService,
    ApplicationSourceStoredDataError,
)
from domains.talent_stream.contracts import (
    OpportunitySpecificationRef,
    RecruitingActorContext,
    RoleDNARef,
    StreamRequirementSnapshot,
)
from domains.talent_stream.own_job_mapping import OwnJobMappingError, prepare_own_job_requirement
from domains.talent_stream.own_job_source import own_job_source_violation
from domains.talent_stream.stream_models import (
    StreamCommandHistoryEntry,
    StreamCommandKind,
    TalentStream,
    TalentStreamState,
)
from models import ApplicationStatus
from mongo_index_safety import verify_metadata


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc)


def requirement(*, opportunity_id="opportunity-1", opportunity_version=1, role_version=1):
    return StreamRequirementSnapshot(
        role_dna=RoleDNARef(RoleDNAId("role-1"), EntityVersion(role_version)),
        opportunity_spec=OpportunitySpecificationRef(
            OpportunitySpecId(opportunity_id), EntityVersion(opportunity_version),
        ),
        requirement_version=EntityVersion(1),
        captured_at=NOW,
    )


def stream(*, recruiter="recruiter-1", stream_id="stream-1", req=None, state=TalentStreamState.DRAFT):
    created = StreamCommandHistoryEntry(
        command_id="create-1",
        command_fingerprint="fingerprint-1",
        command_kind=StreamCommandKind.CREATE,
        from_state=None,
        to_state=TalentStreamState.DRAFT,
        resulting_version=EntityVersion(1),
        occurred_at=NOW,
    )
    history = (created,)
    updated = NOW
    if state is not TalentStreamState.DRAFT:
        kind = StreamCommandKind.ACTIVATE if state is TalentStreamState.ACTIVE else StreamCommandKind.CLOSE
        transition = StreamCommandHistoryEntry(
            command_id="transition-2",
            command_fingerprint="fingerprint-2",
            command_kind=kind,
            from_state=TalentStreamState.DRAFT,
            to_state=state,
            resulting_version=EntityVersion(2),
            occurred_at=NOW + timedelta(seconds=1),
        )
        history = (created, transition)
        updated = transition.occurred_at
    return TalentStream(
        stream_id=TalentStreamId(stream_id),
        version=EntityVersion(len(history)),
        recruiting_actor_context=RecruitingActorContext(
            recruiter_user_id=RecruiterUserId(recruiter),
            requesting_organization_id=OrganizationId("requesting-org-1"),
            hiring_company_id=HiringCompanyId("hiring-org-1"),
            mandate_id=None,
        ),
        requirement_snapshot=req or requirement(),
        state=state,
        created_at=NOW,
        updated_at=updated,
        history=history,
    )


def application(application_id="application-1", **changes):
    value = {
        "_id": application_id,
        "candidate_id": "candidate-1",
        "job_id": "job-1",
        "status": "pending",
        "created_at": NOW + timedelta(minutes=1),
    }
    value.update(changes)
    return value


class Repository:
    def __init__(self):
        self.user = {"_id": "recruiter-1", "user_type": "employer", "is_active": True}
        self.stream = stream()
        self.opportunity = {
            "_id": "opportunity-1:v1",
            "opportunity_spec_id": "opportunity-1",
            "version": 1,
            "provenance": "internal_job",
            "source_job_id": "job-1",
            # A future mapping version is valid: B3 has no v1 prefix invariant.
            "source_ref": "ts-b2-own-job-v2:opaque-proof",
            "version_provenance": "internal_job",
            "version_provenance_ref": "ts-b2-own-job-v2:opaque-proof",
        }
        self.job = {
            "_id": "job-1", "employer_id": "recruiter-1", "company_id": "company-1",
            "is_active": False, "expires_at": NOW - timedelta(days=1),
        }
        self.company = {"_id": "company-1", "owner_id": "recruiter-1"}
        self.organization = {
            "_id": "hiring-org-1", "organization_id": "hiring-org-1",
            "legacy_company_id": "company-1", "verification_state": "unverified",
            "display_name": "Before",
        }
        self.applications = [application()]
        self.after_read = None
        self.readiness_calls = 0
        self.application_reads = []

    async def readiness(self):
        self.readiness_calls += 1

    async def get_user(self, recruiter_id):
        return deepcopy(self.user) if self.user and self.user.get("_id") == recruiter_id else None

    async def get_stream(self, stream_id):
        return deepcopy(self.stream) if str(self.stream.stream_id) == stream_id else None

    async def get_opportunity(self, opportunity_id, version):
        if self.opportunity and (
            self.opportunity.get("opportunity_spec_id"), self.opportunity.get("version")
        ) == (opportunity_id, version):
            return deepcopy(self.opportunity)
        return None

    async def get_job(self, job_id):
        return deepcopy(self.job) if self.job and self.job.get("_id") == job_id else None

    async def get_company(self, company_id):
        return deepcopy(self.company) if self.company and self.company.get("_id") == company_id else None

    async def get_organization(self, organization_id):
        if self.organization and self.organization.get("_id") == organization_id:
            return deepcopy(self.organization)
        return None

    async def list_applications(self, job_id, *, after, limit):
        self.application_reads.append((job_id, after, limit))
        values = [deepcopy(value) for value in self.applications if value.get("job_id") == job_id]
        values.sort(key=lambda value: (value.get("created_at"), value.get("_id")))
        if after is not None:
            values = [
                value for value in values
                if (value["created_at"], value["_id"])
                > (after.applied_at, after.application_id)
            ]
        values = values[:limit]
        if self.after_read is not None:
            self.after_read(self)
        return values


def service(repository=None):
    app = ApplicationSourceService.__new__(ApplicationSourceService)
    app.repository = repository or Repository()
    return app


@pytest.mark.asyncio
async def test_nominal_contract_is_minimal_ordered_and_mapping_version_agnostic():
    repo = Repository()
    repo.applications = [
        application("application-2", candidate_id="candidate-2", status="accepted", created_at=NOW + timedelta(minutes=2)),
        application("application-1", status="reviewed"),
    ]
    result = await service(repo).list_page("recruiter-1", "stream-1")
    assert tuple(item.application_id for item in result) == ("application-1", "application-2")
    assert result[0].candidate_id == "candidate-1" and result[0].job_id == "job-1"
    assert result[0].status is ApplicationStatus.REVIEWED and result[0].applied_at.tzinfo is timezone.utc
    assert set(result[0].__dataclass_fields__) == {
        "application_id", "candidate_id", "job_id", "status", "applied_at",
    }
    assert repo.readiness_calls == 1


@pytest.mark.asyncio
async def test_no_application_returns_empty_tuple():
    repo = Repository()
    repo.applications = []
    assert await service(repo).list_page("recruiter-1", "stream-1") == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", list(ApplicationStatus))
async def test_every_existing_status_is_a_source_fact(status):
    repo = Repository()
    repo.applications = [application(status=status.value)]
    result = await service(repo).list_page("recruiter-1", "stream-1")
    assert result[0].status is status


@pytest.mark.asyncio
async def test_page_is_bounded_and_cursor_is_stable():
    repo = Repository()
    repo.applications = [
        application(
            f"application-{index:03}",
            candidate_id=f"candidate-{index:03}",
            created_at=NOW + timedelta(milliseconds=index),
        )
        for index in range(101)
    ]
    first = await service(repo).list_page("recruiter-1", "stream-1")
    cursor = ApplicationSourceCursor(
        "stream-1", "job-1", first[-1].applied_at, first[-1].application_id,
    )
    second = await service(repo).list_page("recruiter-1", "stream-1", after=cursor)
    assert len(first) == 100 and len(second) == 1
    assert first[-1].application_id == "application-099"
    assert second[0].application_id == "application-100"


@pytest.mark.asyncio
@pytest.mark.parametrize(("cursor_stream_id", "cursor_job_id"), [
    ("stream-2", "job-1"),
    ("stream-1", "job-2"),
    ("stream-2", "job-2"),
])
async def test_cursor_from_another_stream_or_job_is_rejected_before_application_read(
    cursor_stream_id, cursor_job_id,
):
    repo = Repository()
    cursor = ApplicationSourceCursor(
        cursor_stream_id,
        cursor_job_id,
        repo.applications[0]["created_at"],
        repo.applications[0]["_id"],
    )
    with pytest.raises(ValueError, match="cursor does not match scope"):
        await service(repo).list_page("recruiter-1", "stream-1", after=cursor)
    assert repo.application_reads == []


@pytest.mark.asyncio
async def test_other_and_similar_jobs_are_never_selected():
    repo = Repository()
    repo.applications += [
        application("other", job_id="job-2", candidate_id="candidate-2"),
        application("similar", job_id=" job-1 ", candidate_id="candidate-3"),
    ]
    result = await service(repo).list_page("recruiter-1", "stream-1")
    assert tuple(item.application_id for item in result) == ("application-1",)
    assert repo.application_reads[0][0] == "job-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [
    None,
    {"_id": "recruiter-1", "user_type": "employer", "is_active": False},
    {"_id": "recruiter-1", "user_type": "candidate", "is_active": True},
    {"_id": "recruiter-1", "user_type": "partner", "is_active": True},
])
async def test_inactive_missing_and_wrong_role_users_are_denied(user):
    repo = Repository()
    repo.user = user
    with pytest.raises(ApplicationSourceAccessError):
        await service(repo).list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
async def test_admin_has_no_ownership_bypass():
    repo = Repository()
    repo.user["user_type"] = "admin"
    assert len(await service(repo).list_page("recruiter-1", "stream-1")) == 1
    repo.job["employer_id"] = "other-recruiter"
    with pytest.raises(ApplicationSourceAccessError):
        await service(repo).list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda repo: setattr(repo, "stream", stream(recruiter="other-recruiter")),
    lambda repo: repo.job.update(employer_id="other-recruiter"),
    lambda repo: repo.job.update(company_id="company-2"),
    lambda repo: repo.company.update(owner_id="other-recruiter"),
    lambda repo: setattr(repo, "organization", None),
    lambda repo: repo.organization.update(legacy_company_id="company-2"),
])
async def test_stream_job_company_and_organization_scope_is_exact(mutation):
    repo = Repository()
    mutation(repo)
    with pytest.raises(ApplicationSourceAccessError):
        await service(repo).list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"_id": "wrong:v1"},
    {"opportunity_spec_id": "wrong"},
    {"version": True},
    {"provenance": "manual"},
    {"version_provenance": "imported"},
    {"source_job_id": "job-2"},
    {"version_provenance_ref": None},
    {"source_ref": "one", "version_provenance_ref": "two"},
])
async def test_a4_identity_provenance_and_binding_fail_closed(changes):
    repo = Repository()
    repo.opportunity.update(changes)
    with pytest.raises((ApplicationSourceAccessError, ApplicationSourceStoredDataError)):
        await service(repo).list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("marker,value", [
    ("source", "monster.fr"),
    ("is_partner", True),
    ("partner_id", "partner-1"),
    ("campaign_id", "campaign-1"),
    ("external_url", "https://example.test/job"),
    ("external_ref", "external-1"),
])
async def test_every_import_partner_and_external_marker_is_denied(marker, value):
    repo = Repository()
    repo.job[marker] = value
    with pytest.raises(ApplicationSourceAccessError):
        await service(repo).list_page("recruiter-1", "stream-1")


def test_shared_classifier_preserves_b2_errors_and_native_behavior():
    native = {
        "_id": "job-1", "employer_id": "recruiter-1", "company_id": "company-1",
        "title": "Engineer", "source": "", "is_partner": False,
    }
    assert own_job_source_violation(native) is None
    assert prepare_own_job_requirement(native, "recruiter-1", "command-1", NOW)
    with pytest.raises(OwnJobMappingError, match="job.is_partner must be boolean when present"):
        prepare_own_job_requirement({**native, "is_partner": 1}, "recruiter-1", "command-1", NOW)
    with pytest.raises(OwnJobMappingError, match="partner, imported and external"):
        prepare_own_job_requirement({**native, "source": "monster.fr"}, "recruiter-1", "command-1", NOW)


@pytest.mark.asyncio
async def test_inactive_and_expired_job_remains_an_application_source():
    repo = Repository()
    assert repo.job["is_active"] is False and repo.job["expires_at"] < NOW
    assert len(await service(repo).list_page("recruiter-1", "stream-1")) == 1
    repo.job = None
    with pytest.raises(ApplicationSourceAccessError):
        await service(repo).list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"_id": None},
    {"candidate_id": None},
    {"candidate_id": " "},
    {"job_id": "other"},
    {"status": "unknown"},
    {"status": 1},
    {"created_at": None},
    {"created_at": "2026-09-13"},
    {"created_at": NOW + timedelta(microseconds=1)},
])
async def test_malformed_matching_application_fails_closed(changes):
    repo = Repository()
    malformed = application()
    malformed.update(changes)
    # Force the malformed record through the domain boundary even when its
    # malformed job_id would not match a real Mongo equality query.
    async def raw(_job_id, *, after, limit):
        return [deepcopy(malformed)]
    repo.list_applications = raw
    with pytest.raises(ApplicationSourceStoredDataError):
        await service(repo).list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["_id", "candidate_id", "job_id", "status", "created_at"])
async def test_missing_application_field_fails_closed(field):
    repo = Repository()
    del repo.applications[0][field]
    async def raw(_job_id, *, after, limit):
        return deepcopy(repo.applications)
    repo.list_applications = raw
    with pytest.raises(ApplicationSourceStoredDataError):
        await service(repo).list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", ["application_id", "candidate_id"])
async def test_duplicate_application_identity_fails_closed(duplicate):
    repo = Repository()
    second = application("application-2", candidate_id="candidate-2")
    if duplicate == "application_id":
        second["_id"] = "application-1"
    else:
        second["candidate_id"] = "candidate-1"
    repo.applications.append(second)
    with pytest.raises(ApplicationSourceStoredDataError, match="duplicate"):
        await service(repo).list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
async def test_naive_bson_datetime_is_rehydrated_as_utc():
    repo = Repository()
    repo.applications[0]["created_at"] = NOW.replace(tzinfo=None)
    result = await service(repo).list_page("recruiter-1", "stream-1")
    assert result[0].applied_at == NOW


@pytest.mark.asyncio
async def test_opaque_identifiers_are_preserved_without_strip_collision():
    repo = Repository()
    repo.user["_id"] = " recruiter-1 "
    repo.stream = stream(recruiter=" recruiter-1 ", stream_id=" stream-1 ")
    repo.opportunity.update({
        "_id": " opportunity-1 :v1",
        "opportunity_spec_id": " opportunity-1 ",
        "source_job_id": " job-1 ",
    })
    repo.stream = replace(repo.stream, requirement_snapshot=requirement(opportunity_id=" opportunity-1 "))
    repo.job.update({"_id": " job-1 ", "employer_id": " recruiter-1 ", "company_id": " company-1 "})
    repo.company.update({"_id": " company-1 ", "owner_id": " recruiter-1 "})
    repo.organization["legacy_company_id"] = " company-1 "
    repo.applications[0].update({"job_id": " job-1 ", "candidate_id": " candidate-1 "})
    result = await service(repo).list_page(" recruiter-1 ", " stream-1 ")
    assert result[0].job_id == " job-1 " and result[0].candidate_id == " candidate-1 "


SECURITY_MUTATIONS = [
    lambda repo: repo.user.update(is_active=False),
    lambda repo: repo.user.update(user_type="candidate"),
    lambda repo: setattr(repo, "stream", stream(recruiter="other-recruiter")),
    lambda repo: setattr(repo, "stream", replace(repo.stream, requirement_snapshot=requirement(role_version=2))),
    lambda repo: repo.opportunity.update(source_job_id="job-2"),
    lambda repo: setattr(repo, "job", None),
    lambda repo: repo.job.update(employer_id="other-recruiter"),
    lambda repo: repo.job.update(company_id="company-2"),
    lambda repo: repo.company.update(owner_id="other-recruiter"),
    lambda repo: repo.organization.update(legacy_company_id="company-2"),
    lambda repo: repo.job.update(source="monster.fr"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", SECURITY_MUTATIONS)
async def test_concurrent_security_scope_change_is_a_conflict(mutation):
    repo = Repository()
    repo.after_read = mutation
    with pytest.raises(ApplicationSourceConflictError):
        await service(repo).list_page("recruiter-1", "stream-1")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda repo: setattr(repo, "stream", stream(state=TalentStreamState.ACTIVE)),
    lambda repo: setattr(repo, "stream", stream(state=TalentStreamState.CLOSED)),
    lambda repo: repo.organization.update(verification_state="suspended"),
    lambda repo: repo.organization.update(display_name="After"),
    lambda repo: repo.job.update(title="Changed business title"),
    lambda repo: repo.job.update(source=""),
    lambda repo: repo.job.update(is_partner=False),
])
async def test_concurrent_out_of_scope_change_does_not_conflict(mutation):
    repo = Repository()
    repo.after_read = mutation
    assert len(await service(repo).list_page("recruiter-1", "stream-1")) == 1


@pytest.mark.asyncio
async def test_concurrent_application_status_is_a_point_in_time_fact():
    repo = Repository()
    repo.after_read = lambda value: value.applications[0].update(status="accepted")
    result = await service(repo).list_page("recruiter-1", "stream-1")
    assert result[0].status is ApplicationStatus.PENDING
    assert (await service(repo).list_page("recruiter-1", "stream-1"))[0].status is ApplicationStatus.ACCEPTED


def test_models_are_immutable_and_limit_is_strict():
    item = ApplicationSource("application-1", "candidate-1", "job-1", ApplicationStatus.PENDING, NOW)
    with pytest.raises(FrozenInstanceError):
        item.status = ApplicationStatus.ACCEPTED
    with pytest.raises(ValueError):
        ApplicationSourceCursor("stream-1", "job-1", NOW, " ")


@pytest.mark.parametrize(("stream_id", "job_id"), [
    (" ", "job-1"),
    ("stream-1", " "),
])
def test_cursor_scope_identifiers_are_required_and_opaque(stream_id, job_id):
    with pytest.raises(ValueError):
        ApplicationSourceCursor(stream_id, job_id, NOW, "application-1")

    spaced = ApplicationSourceCursor(
        " stream-1 ", " job-1 ", NOW, " application-1 ",
    )
    assert spaced.stream_id == " stream-1 "
    assert spaced.job_id == " job-1 "


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [True, 0, 101, 1.0])
async def test_invalid_page_size_is_rejected_before_reads(limit):
    repo = Repository()
    with pytest.raises(ValueError):
        await service(repo).list_page("recruiter-1", "stream-1", limit=limit)
    assert repo.readiness_calls == 0


def test_application_index_correctness_does_not_require_job_id_single_index():
    collections = {"applications": {"type": "collection", "options": {}}}
    indexes = {"applications": {
        "_id_": {"v": 2, "key": [("_id", 1)]},
        "job_id_1_candidate_id_1": {
            "v": 2, "key": [("job_id", 1), ("candidate_id", 1)], "unique": True,
        },
    }}
    assert verify_metadata((APPLICATION_SOURCE_REQUIREMENT,), collections, indexes).ok
    del indexes["applications"]["job_id_1_candidate_id_1"]
    assert not verify_metadata((APPLICATION_SOURCE_REQUIREMENT,), collections, indexes).ok


def test_repository_projection_and_source_are_pii_free_and_read_only():
    assert set(APPLICATION_FIELDS) == {"_id", "candidate_id", "job_id", "status", "created_at"}
    assert set(JOB_FIELDS) == {
        "_id", "employer_id", "company_id", "source", "is_partner",
        "partner_id", "campaign_id", "external_url", "external_ref",
    }
    forbidden_fields = {
        "email", "phone", "cv", "cv_url", "cover_letter", "employer_notes",
        "photo", "profile", "preferences", "salary",
    }
    assert forbidden_fields.isdisjoint(APPLICATION_FIELDS)

    files = [
        BACKEND / "domains/talent_stream/application_source_repository.py",
        BACKEND / "domains/talent_stream/application_source_service.py",
    ]
    forbidden_calls = {
        "insert_one", "insert_many", "update_one", "update_many", "delete_one",
        "delete_many", "replace_one", "find_one_and_update", "bulk_write",
    }
    text = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "populate_application_response" not in text
    assert all(token not in text for token in ("candidate_profiles", "candidate_documents", "files.find"))
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                assert name not in forbidden_calls
