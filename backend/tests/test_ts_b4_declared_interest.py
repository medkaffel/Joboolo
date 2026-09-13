"""TS-B4 G0: hermetic declared-interest identity, eligibility and isolation."""
import ast
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from domains.intent.serialization import event_to_document
from domains.intent.service import IntentEventConflictError
from domains.talent_stream.declared_interest_models import (
    MAX_CALLER_IDEMPOTENCY_KEY_LENGTH,
    DeclareJobInterestCommand,
    canonical_identity_json,
    deterministic_interest_identity,
)
from domains.talent_stream.declared_interest_repository import (
    CAMPAIGN_FIELDS,
    JOB_FIELDS,
    USER_FIELDS,
)
from domains.talent_stream.declared_interest_service import (
    DeclaredInterestAccessError,
    DeclaredInterestConflictError,
    DeclaredInterestJobNotEligibleError,
    DeclaredInterestService,
)


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 13, 12, 0, 0, 123456, tzinfo=timezone.utc)


class TickingClock:
    def __init__(self):
        self.value = NOW

    def __call__(self):
        current = self.value
        self.value += timedelta(milliseconds=1)
        return current


class Repository:
    """Only the reads and the one A11 write allowed to B4 are exposed."""

    def __init__(self):
        self.users = {
            "candidate-1": {
                "_id": "candidate-1", "user_type": "candidate", "is_active": True,
            },
            "candidate-2": {
                "_id": "candidate-2", "user_type": "candidate", "is_active": True,
            },
        }
        self.jobs = {
            "job-1": {"_id": "job-1", "is_active": True},
            "job-2": {"_id": "job-2", "is_active": True},
        }
        self.campaigns = {}
        self.events = {}
        self.readiness_calls = 0
        self.user_reads = []
        self.job_reads = []
        self.campaign_reads = []
        self.insert_attempts = 0

    async def get_user(self, candidate_id):
        self.user_reads.append(candidate_id)
        return deepcopy(self.users.get(candidate_id))

    async def get_event_by_idempotency_key(self, key):
        return deepcopy(self.events.get(key))

    async def readiness(self):
        self.readiness_calls += 1

    async def get_job(self, job_id):
        self.job_reads.append(job_id)
        return deepcopy(self.jobs.get(job_id))

    async def get_campaign(self, campaign_id):
        self.campaign_reads.append(campaign_id)
        return deepcopy(self.campaigns.get(campaign_id))

    async def record(self, event):
        self.insert_attempts += 1
        await asyncio.sleep(0)
        key = str(event.idempotency_key)
        if key in self.events:
            raise IntentEventConflictError("synthetic race")
        self.events[key] = event_to_document(event)
        return event


def service(repository=None, clock=None):
    instance = object.__new__(DeclaredInterestService)
    instance.repository = repository or Repository()
    instance.clock = clock or TickingClock()
    return instance


@pytest.mark.asyncio
async def test_nominal_event_has_only_the_exact_b4_a11_fields():
    result = await service().declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    document = event_to_document(result)
    assert set(document) == {
        "_id", "schema_version", "subject", "intent_kind", "origin",
        "event_type", "occurred_at", "created_at", "source_type",
        "idempotency_key", "job_id",
    }
    assert document["schema_version"] == "intent-event-v1"
    assert document["subject"] == {"candidate_id": "candidate-1"}
    assert document["intent_kind"] == "job"
    assert document["origin"] == "declared"
    assert document["event_type"] == "job_interest_declared"
    assert document["source_type"] == "candidate_declared"
    assert document["job_id"] == "job-1"
    assert document["occurred_at"] == document["created_at"]
    assert document["occurred_at"].microsecond == 123000


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [
    None,
    {"_id": "candidate-1", "user_type": "candidate", "is_active": False},
    {"_id": "candidate-1", "user_type": "employer", "is_active": True},
    {"_id": "candidate-1", "user_type": "admin", "is_active": True},
    {"_id": "other", "user_type": "candidate", "is_active": True},
])
async def test_only_the_exact_current_active_candidate_can_declare(user):
    repo = Repository()
    repo.users["candidate-1"] = user
    with pytest.raises(DeclaredInterestAccessError):
        await service(repo).declare(
            "candidate-1", "job-1", caller_idempotency_key="command-1",
        )
    assert repo.events == {} and repo.job_reads == []


@pytest.mark.asyncio
@pytest.mark.parametrize("job", [
    None,
    {"_id": "job-1", "is_active": False},
    {"_id": "job-1"},
    {"_id": "job-1", "is_active": True, "expires_at": NOW - timedelta(seconds=1)},
    {"_id": "job-1", "is_active": True, "expires_at": ""},
    {"_id": "job-1", "is_active": True, "expires_at": "not-a-date"},
    {"_id": "other", "is_active": True},
])
async def test_missing_inactive_expired_or_malformed_job_is_refused(job):
    repo = Repository()
    repo.jobs["job-1"] = job
    with pytest.raises(DeclaredInterestJobNotEligibleError):
        await service(repo).declare(
            "candidate-1", "job-1", caller_idempotency_key="command-1",
        )
    assert repo.events == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("campaign", [
    None,
    {"_id": "campaign-1", "status": "paused"},
    {"_id": "campaign-1", "status": "active", "end_date": "2026-09-12"},
    {"_id": "campaign-1", "status": "active", "start_date": "invalid"},
    {
        "_id": "campaign-1", "status": "active", "billing_mode": "per_click",
        "budget_limit": 10.0, "spent": 10.0,
    },
])
async def test_required_campaign_must_be_currently_diffusable(campaign):
    repo = Repository()
    repo.jobs["job-1"]["campaign_id"] = "campaign-1"
    repo.campaigns["campaign-1"] = campaign
    with pytest.raises(DeclaredInterestJobNotEligibleError):
        await service(repo).declare(
            "candidate-1", "job-1", caller_idempotency_key="command-1",
        )
    assert repo.campaign_reads == ["campaign-1"] and repo.events == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [
    {},
    {"source": "monster.fr", "employer_id": "missing-source-account"},
    {
        "is_partner": True, "partner_id": "partner-1",
        "external_url": "https://example.invalid/job", "external_ref": "ref-1",
    },
])
async def test_visible_internal_imported_and_partner_jobs_are_equally_eligible(extra):
    repo = Repository()
    repo.jobs["job-1"].update(extra)
    result = await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    assert result.job_id == "job-1" and len(repo.events) == 1


@pytest.mark.parametrize("key", [None, 1, True, "", "   ", {}, []])
def test_caller_key_is_required_and_strictly_typed(key):
    with pytest.raises(ValueError):
        DeclareJobInterestCommand("candidate-1", "job-1", key)


def test_caller_key_length_is_bounded_without_normalization():
    accepted = "x" * MAX_CALLER_IDEMPOTENCY_KEY_LENGTH
    command = DeclareJobInterestCommand("candidate-1", "job-1", accepted)
    assert command.caller_idempotency_key == accepted
    with pytest.raises(ValueError):
        DeclareJobInterestCommand("candidate-1", "job-1", accepted + "x")


def test_opaque_keys_and_canonical_components_cannot_collide_silently():
    plain = deterministic_interest_identity("candidate-1", "command-1")
    spaced = deterministic_interest_identity("candidate-1", " command-1 ")
    other_candidate = deterministic_interest_identity("candidate-2", "command-1")
    assert len({plain, spaced, other_candidate}) == 3
    assert canonical_identity_json("candidate-1", "ab") != canonical_identity_json(
        "candidate-1a", "b",
    )
    assert " command-1 " in canonical_identity_json("candidate-1", " command-1 ")


@pytest.mark.parametrize("field", ["candidate_id", "job_id"])
def test_a11_persisted_identifiers_are_rejected_not_trimmed(field):
    values = {"candidate_id": "candidate-1", "job_id": "job-1"}
    values[field] = f" {values[field]} "
    with pytest.raises(ValueError):
        DeclareJobInterestCommand(
            values["candidate_id"], values["job_id"], "command-1",
        )


@pytest.mark.asyncio
async def test_retry_is_stable_and_never_reloads_the_job():
    repo = Repository()
    first = await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    repo.jobs.pop("job-1")
    repo.job_reads.clear()
    second = await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    assert second == first
    assert repo.job_reads == [] and repo.insert_attempts == 1


@pytest.mark.asyncio
async def test_retry_still_requires_a_current_active_candidate():
    repo = Repository()
    await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    repo.users["candidate-1"]["is_active"] = False
    repo.job_reads.clear()
    with pytest.raises(DeclaredInterestAccessError):
        await service(repo).declare(
            "candidate-1", "job-1", caller_idempotency_key="command-1",
        )
    assert repo.job_reads == [] and repo.insert_attempts == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda repo: repo.jobs["job-1"].update(is_active=False),
    lambda repo: repo.jobs["job-1"].update(expires_at=NOW - timedelta(seconds=1)),
    lambda repo: repo.jobs["job-1"].update(campaign_id="missing-campaign"),
    lambda repo: repo.jobs.pop("job-1"),
])
async def test_retry_survives_later_job_or_campaign_ineligibility(mutation):
    repo = Repository()
    first = await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    mutation(repo)
    second = await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    assert second == first and repo.insert_attempts == 1


@pytest.mark.asyncio
async def test_new_key_after_job_closes_is_refused():
    repo = Repository()
    await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    repo.jobs["job-1"]["is_active"] = False
    with pytest.raises(DeclaredInterestJobNotEligibleError):
        await service(repo).declare(
            "candidate-1", "job-1", caller_idempotency_key="command-2",
        )
    assert len(repo.events) == 1


@pytest.mark.asyncio
async def test_same_candidate_key_for_another_job_is_a_conflict():
    repo = Repository()
    await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="same-command",
    )
    with pytest.raises(DeclaredInterestConflictError):
        await service(repo).declare(
            "candidate-1", "job-2", caller_idempotency_key="same-command",
        )
    assert len(repo.events) == 1


@pytest.mark.asyncio
async def test_same_raw_key_for_another_candidate_has_an_independent_scope():
    repo = Repository()
    first = await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="same-command",
    )
    second = await service(repo).declare(
        "candidate-2", "job-1", caller_idempotency_key="same-command",
    )
    assert first.event_id != second.event_id and len(repo.events) == 2


@pytest.mark.asyncio
async def test_new_command_creates_a_new_append_only_event():
    repo = Repository()
    first = await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    second = await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="command-2",
    )
    assert first.event_id != second.event_id and len(repo.events) == 2


@pytest.mark.asyncio
async def test_concurrent_different_server_timestamps_return_one_winner():
    repo = Repository()
    current = service(repo, TickingClock())
    results = await asyncio.gather(*(
        current.declare(
            "candidate-1", "job-1", caller_idempotency_key="command-1",
        )
        for _ in range(20)
    ))
    assert len({result.event_id for result in results}) == 1
    assert len({result.occurred_at for result in results}) == 1
    assert len(repo.events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("corruption", [
    {"permission": True},
    {"source_type": "candidate_observed"},
    {"subject": {"candidate_id": "candidate-2"}},
    {"consent_context": {"consent_policy_version": "fake", "context_ref": "fake"}},
])
async def test_corrupt_or_non_b4_existing_event_fails_closed(corruption):
    repo = Repository()
    await service(repo).declare(
        "candidate-1", "job-1", caller_idempotency_key="command-1",
    )
    key = next(iter(repo.events))
    repo.events[key].update(corruption)
    corrupted = deepcopy(repo.events)
    with pytest.raises(DeclaredInterestConflictError):
        await service(repo).declare(
            "candidate-1", "job-1", caller_idempotency_key="command-1",
        )
    assert repo.events == corrupted and repo.insert_attempts == 1


def test_repository_projections_and_domain_boundary_are_minimal():
    assert set(USER_FIELDS) == {"_id", "user_type", "is_active"}
    assert set(JOB_FIELDS) == {"_id", "is_active", "expires_at", "campaign_id"}
    assert set(CAMPAIGN_FIELDS) == {
        "_id", "status", "start_date", "end_date", "billing_mode",
        "budget_limit", "spent",
    }
    source = "\n".join(
        (BACKEND / "domains/talent_stream" / name).read_text(encoding="utf-8")
        for name in (
            "declared_interest_models.py",
            "declared_interest_repository.py",
            "declared_interest_service.py",
        )
    )
    forbidden = {
        "applications", "saved_jobs", "candidate_profiles", "candidate_documents",
        "talent_stream_grants", "contact_requests", "companies", "organizations",
        "professional_match", "opportunity_fit",
    }
    assert all(token not in source for token in forbidden)

    repository_tree = ast.parse(
        (BACKEND / "domains/talent_stream/declared_interest_repository.py").read_text(
            encoding="utf-8"
        )
    )
    direct_writes = []
    for node in ast.walk(repository_tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name in {
                "insert_one", "insert_many", "update_one", "update_many",
                "delete_one", "delete_many", "replace_one", "bulk_write",
            }:
                direct_writes.append(name)
    assert direct_writes == []


def test_b4_registers_no_http_route_or_frontend_surface():
    server = (BACKEND / "server.py").read_text(encoding="utf-8")
    assert "declared_interest" not in server and "job_interest_declared" not in server
    assert not (BACKEND / "routes/talent_stream_interest.py").exists()
