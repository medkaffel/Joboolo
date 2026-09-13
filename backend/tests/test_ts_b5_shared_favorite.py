"""TS-B5 G0: explicit SavedJob sharing stays separate from private favorites."""
import asyncio
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from domains.intent.serialization import event_from_document, event_to_document
from domains.intent.service import IntentEventConflictError
from domains.talent_stream.events import (
    IntentKind,
    IntentOrigin,
    IntentSubject,
    TalentIntentEvent,
)
from domains.talent_stream.shared_favorite_models import (
    ShareSavedJobCommand,
    WithdrawSharedFavoriteCommand,
)
from domains.talent_stream.shared_favorite_repository import (
    SharedFavoriteReadinessError,
    SharedFavoriteRepository,
)
from domains.talent_stream.shared_favorite_service import (
    SHARE_EVENT_TYPE,
    SOURCE_TYPE,
    WITHDRAW_EVENT_TYPE,
    SharedFavoriteAccessError,
    SharedFavoriteConflictError,
    SharedFavoriteNotEligibleError,
    SharedFavoriteService,
)


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 13, 16, 0, 0, 1000, tzinfo=timezone.utc)


class TickingClock:
    def __init__(self):
        self.current = NOW

    def __call__(self):
        value = self.current
        self.current += timedelta(milliseconds=1)
        return value


def saved(saved_id="saved-1", candidate="candidate-1", job="job-1", **changes):
    document = {
        "_id": saved_id,
        "user_id": candidate,
        "job_id": job,
        "created_at": NOW.replace(tzinfo=None),
        "updated_at": NOW.replace(tzinfo=None),
    }
    document.update(changes)
    return document


class Repository:
    def __init__(self):
        self.users = {
            "candidate-1": {"_id": "candidate-1", "user_type": "candidate", "is_active": True},
            "candidate-2": {"_id": "candidate-2", "user_type": "candidate", "is_active": True},
        }
        self.saved = {"saved-1": saved()}
        self.jobs = {
            "job-1": {"_id": "job-1", "is_active": True},
            "job-2": {"_id": "job-2", "is_active": True},
        }
        self.campaigns = {}
        self.events_by_key = {}
        self.events_by_id = {}
        self.insert_attempts = 0
        self.saved_reads = 0
        self.on_second_saved_read = None
        self.a11_ready = True
        self.saved_index_ready = True

    async def get_user(self, candidate_id):
        value = self.users.get(candidate_id)
        return deepcopy(value) if value else None

    async def a11_readiness(self):
        if not self.a11_ready:
            raise SharedFavoriteReadinessError("A11 not ready")

    async def saved_jobs_readiness(self):
        if not self.saved_index_ready:
            raise SharedFavoriteReadinessError("SavedJob index not ready")

    async def get_saved_job(self, candidate_id, job_id, saved_job_id):
        self.saved_reads += 1
        if self.saved_reads == 2:
            if self.on_second_saved_read == "delete":
                self.saved.pop(saved_job_id, None)
            elif self.on_second_saved_read == "modify":
                self.saved[saved_job_id]["updated_at"] += timedelta(milliseconds=1)
        value = self.saved.get(saved_job_id)
        if not value or value.get("user_id") != candidate_id or value.get("job_id") != job_id:
            return None
        return deepcopy(value)

    async def get_job(self, job_id):
        value = self.jobs.get(job_id)
        return deepcopy(value) if value else None

    async def get_campaign(self, campaign_id):
        value = self.campaigns.get(campaign_id)
        return deepcopy(value) if value else None

    async def get_event(self, event_id):
        value = self.events_by_id.get(event_id)
        return deepcopy(value) if value else None

    async def get_event_by_idempotency_key(self, key):
        value = self.events_by_key.get(key)
        return deepcopy(value) if value else None

    async def record(self, event):
        self.insert_attempts += 1
        document = event_to_document(event)
        await asyncio.sleep(0)
        existing = self.events_by_key.get(document["idempotency_key"])
        if existing is not None:
            raise IntentEventConflictError("synthetic duplicate")
        self.events_by_key[document["idempotency_key"]] = deepcopy(document)
        self.events_by_id[document["_id"]] = deepcopy(document)
        return event_from_document(document)


def service(repository=None, clock=None):
    instance = object.__new__(SharedFavoriteService)
    instance.repository = repository or Repository()
    instance.clock = clock or TickingClock()
    return instance


async def share(current, *, candidate="candidate-1", job="job-1", saved_id="saved-1", key="share-1"):
    return await current.share(
        candidate, job, saved_id, caller_idempotency_key=key,
    )


async def withdraw(current, share_event, *, candidate="candidate-1", job="job-1", key="withdraw-1"):
    return await current.withdraw(
        candidate, job, str(share_event.event_id), caller_idempotency_key=key,
    )


def test_private_saved_job_routes_have_no_b5_side_effect_or_dependency():
    source = (BACKEND / "routes/saved_jobs.py").read_text(encoding="utf-8")
    assert "shared_favorite" not in source
    assert "talent_intent_events" not in source
    assert "IntentEvent" not in source
    assert "db.saved_jobs.insert_one" in source
    assert "db.saved_jobs.delete_one" in source


def test_b5_command_identity_preserves_the_exact_caller_key_and_scopes_candidate():
    plain = ShareSavedJobCommand("candidate-1", "job-1", "saved-1", "key")
    spaced = ShareSavedJobCommand("candidate-1", "job-1", "saved-1", " key ")
    other = ShareSavedJobCommand("candidate-2", "job-1", "saved-1", "key")
    assert plain.event_id != spaced.event_id != other.event_id
    with pytest.raises(ValueError):
        ShareSavedJobCommand(" candidate-1 ", "job-1", "saved-1", "key")


@pytest.mark.asyncio
async def test_share_writes_the_exact_minimal_a11_event_and_nothing_else():
    repo = Repository()
    before = deepcopy((repo.users, repo.saved, repo.jobs, repo.campaigns))
    result = await share(service(repo))
    document = event_to_document(result)
    assert set(document) == {
        "_id", "schema_version", "subject", "intent_kind", "origin",
        "event_type", "occurred_at", "created_at", "source_type",
        "idempotency_key", "job_id", "correlation_id",
    }
    assert document["schema_version"] == "intent-event-v1"
    assert document["subject"] == {"candidate_id": "candidate-1"}
    assert document["intent_kind"] == "job"
    assert document["origin"] == "declared"
    assert document["event_type"] == SHARE_EVENT_TYPE
    assert document["source_type"] == SOURCE_TYPE
    assert document["job_id"] == "job-1"
    assert document["correlation_id"] == "saved-1"
    assert document["occurred_at"] == document["created_at"] == NOW
    assert deepcopy((repo.users, repo.saved, repo.jobs, repo.campaigns)) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [
    None,
    {"_id": "candidate-1", "user_type": "candidate", "is_active": False},
    {"_id": "candidate-1", "user_type": "employer", "is_active": True},
])
async def test_share_requires_the_current_active_candidate(user):
    repo = Repository()
    if user is None:
        repo.users.pop("candidate-1")
    else:
        repo.users["candidate-1"] = user
    with pytest.raises(SharedFavoriteAccessError):
        await share(service(repo))
    assert repo.events_by_id == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("document", [
    None,
    saved(candidate="candidate-2"),
    saved(job="job-2"),
])
async def test_missing_or_foreign_saved_job_is_refused(document):
    repo = Repository()
    if document is None:
        repo.saved.clear()
    else:
        repo.saved["saved-1"] = document
    with pytest.raises(SharedFavoriteNotEligibleError):
        await share(service(repo))
    assert repo.events_by_id == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"_id": "bad id"},
    {"user_id": True},
    {"job_id": 1},
    {"created_at": "2026-09-13"},
    {"updated_at": True},
    {"created_at": NOW.replace(tzinfo=None, microsecond=1001)},
    {"updated_at": NOW.replace(tzinfo=None) - timedelta(milliseconds=1)},
])
async def test_malformed_saved_job_is_refused_without_repair(changes):
    repo = Repository()
    malformed = saved(**changes)
    repo.saved = {str(malformed.get("_id")): malformed}
    requested_id = str(malformed.get("_id"))
    with pytest.raises((SharedFavoriteNotEligibleError, ValueError)):
        await share(service(repo), saved_id=requested_id)
    assert repo.events_by_id == {}
    assert repo.saved[requested_id] == malformed


@pytest.mark.asyncio
async def test_naive_and_aware_valid_mongo_dates_are_accepted():
    for dates in (
        {},
        {"created_at": NOW, "updated_at": NOW + timedelta(milliseconds=1)},
    ):
        repo = Repository()
        repo.saved["saved-1"] = saved(**dates)
        assert (await share(service(repo))).correlation_id == "saved-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("ready", ["a11", "saved"])
async def test_missing_readiness_refuses_before_insert(ready):
    repo = Repository()
    if ready == "a11":
        repo.a11_ready = False
    else:
        repo.saved_index_ready = False
    with pytest.raises(SharedFavoriteReadinessError):
        await share(service(repo))
    assert repo.events_by_id == {}


class IndexCollection:
    def __init__(self, indexes):
        self.indexes = indexes

    async def index_information(self):
        return deepcopy(self.indexes)


@pytest.mark.asyncio
@pytest.mark.parametrize("indexes,accepted", [
    ({"custom-name": {"key": [("user_id", 1), ("job_id", 1)], "unique": True}}, True),
    ({"_id_": {"key": [("_id", 1)], "unique": True}}, False),
    ({"pair": {"key": [("user_id", 1), ("job_id", 1)]}}, False),
    ({"pair": {"key": [("job_id", 1), ("user_id", 1)], "unique": True}}, False),
])
async def test_saved_job_readiness_uses_spec_not_index_name(indexes, accepted):
    repository = object.__new__(SharedFavoriteRepository)
    repository.db = SimpleNamespace(saved_jobs=IndexCollection(indexes))
    if accepted:
        assert await repository.saved_jobs_readiness() is True
    else:
        with pytest.raises(SharedFavoriteReadinessError):
            await repository.saved_jobs_readiness()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    lambda repo: repo.jobs.pop("job-1"),
    lambda repo: repo.jobs["job-1"].update(is_active=False),
    lambda repo: repo.jobs["job-1"].update(expires_at=NOW),
])
async def test_new_share_requires_a_current_visible_job(mutation):
    repo = Repository()
    mutation(repo)
    with pytest.raises(SharedFavoriteNotEligibleError):
        await share(service(repo))
    assert repo.events_by_id == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("campaign_id", [{"$ne": None}, "", "bad id"])
async def test_malformed_campaign_id_is_fail_closed(campaign_id):
    repo = Repository()
    repo.jobs["job-1"]["campaign_id"] = campaign_id
    with pytest.raises(SharedFavoriteNotEligibleError):
        await share(service(repo))
    assert repo.events_by_id == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["delete", "modify"])
async def test_second_saved_job_read_rejects_disappearance_or_change(change):
    repo = Repository()
    repo.on_second_saved_read = change
    with pytest.raises(SharedFavoriteNotEligibleError):
        await share(service(repo))
    assert repo.events_by_id == {}


@pytest.mark.asyncio
async def test_committed_share_retry_survives_job_and_saved_job_deletion():
    repo = Repository()
    current = service(repo)
    first = await share(current)
    repo.saved.clear()
    repo.jobs.clear()
    second = await share(current)
    assert second == first and len(repo.events_by_id) == 1


@pytest.mark.asyncio
async def test_same_key_other_job_or_saved_job_conflicts():
    for changed in ("job", "saved"):
        repo = Repository()
        current = service(repo)
        await share(current)
        if changed == "job":
            repo.saved["saved-2"] = saved("saved-2", job="job-2")
            args = {"job": "job-2", "saved_id": "saved-2"}
        else:
            repo.saved["saved-2"] = saved("saved-2")
            args = {"saved_id": "saved-2"}
        with pytest.raises(SharedFavoriteConflictError):
            await share(current, **args)
        assert len(repo.events_by_id) == 1


@pytest.mark.asyncio
async def test_same_raw_key_for_opposite_action_conflicts():
    repo = Repository()
    current = service(repo)
    positive = await share(current, key="same-key")
    with pytest.raises(SharedFavoriteConflictError):
        await withdraw(current, positive, key="same-key")
    assert len(repo.events_by_id) == 1


@pytest.mark.asyncio
async def test_concurrent_share_has_one_canonical_winner_and_timestamp():
    repo = Repository()
    current = service(repo, TickingClock())
    results = await asyncio.gather(*(share(current) for _ in range(20)))
    assert len({result.event_id for result in results}) == 1
    assert len({result.occurred_at for result in results}) == 1
    assert len(repo.events_by_id) == 1


@pytest.mark.asyncio
async def test_withdrawal_is_append_only_minimal_and_needs_no_live_job_or_saved_job():
    repo = Repository()
    current = service(repo)
    positive = await share(current)
    positive_document = deepcopy(repo.events_by_id[str(positive.event_id)])
    repo.saved.clear()
    repo.jobs.clear()
    negative = await withdraw(current, positive)
    document = event_to_document(negative)
    assert document["event_type"] == WITHDRAW_EVENT_TYPE
    assert document["correlation_id"] == "saved-1"
    assert document["causation_id"] == positive.event_id
    assert document["job_id"] == "job-1"
    assert "consent_context" not in document and "privacy_context" not in document
    assert repo.events_by_id[str(positive.event_id)] == positive_document
    assert len(repo.events_by_id) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("source_kind", [
    "missing", "other-candidate", "other-job", "b4", "bad-identity", "other-b5",
])
async def test_withdrawal_rejects_missing_or_wrong_source(source_kind):
    repo = Repository()
    current = service(repo)
    positive = await share(current)
    source_id = str(positive.event_id)
    if source_kind == "missing":
        repo.events_by_id.pop(source_id)
    elif source_kind == "other-candidate":
        repo.events_by_id[source_id]["subject"] = {"candidate_id": "candidate-2"}
    elif source_kind == "other-job":
        repo.events_by_id[source_id]["job_id"] = "job-2"
    elif source_kind == "b4":
        repo.events_by_id[source_id]["event_type"] = "job_interest_declared"
    elif source_kind == "bad-identity":
        repo.events_by_id[source_id]["idempotency_key"] = (
            "ts-b5-share-v1:sha256:" + "0" * 64
        )
    else:
        repo.saved["saved-2"] = saved("saved-2", candidate="candidate-2")
        other = await share(
            current, candidate="candidate-2", saved_id="saved-2", key="other",
        )
        source_id = str(other.event_id)
    with pytest.raises((SharedFavoriteConflictError, SharedFavoriteNotEligibleError)):
        await current.withdraw(
            "candidate-1", "job-1", source_id,
            caller_idempotency_key="withdraw-1",
        )
    assert not any(
        doc["event_type"] == WITHDRAW_EVENT_TYPE
        for doc in repo.events_by_id.values()
    )


@pytest.mark.asyncio
async def test_withdrawal_retry_and_concurrency_are_idempotent():
    repo = Repository()
    current = service(repo, TickingClock())
    positive = await share(current)
    results = await asyncio.gather(*(withdraw(current, positive) for _ in range(20)))
    assert len({result.event_id for result in results}) == 1
    assert len({result.occurred_at for result in results}) == 1
    assert len(repo.events_by_id) == 2


@pytest.mark.asyncio
async def test_unsave_resave_requires_a_new_saved_job_and_explicit_share():
    repo = Repository()
    current = service(repo)
    old = await share(current)
    repo.saved = {"saved-2": saved("saved-2")}
    with pytest.raises(SharedFavoriteConflictError):
        await share(current, saved_id="saved-2", key="share-1")
    new = await share(current, saved_id="saved-2", key="share-2")
    assert old.correlation_id == "saved-1"
    assert new.correlation_id == "saved-2"
    assert old.event_id != new.event_id


@pytest.mark.asyncio
async def test_withdraw_then_reshare_is_an_explicit_new_append_only_event():
    repo = Repository()
    current = service(repo)
    first = await share(current)
    negative = await withdraw(current, first)
    second = await share(current, key="share-2")
    assert [first.event_type, negative.event_type, second.event_type] == [
        SHARE_EVENT_TYPE, WITHDRAW_EVENT_TYPE, SHARE_EVENT_TYPE,
    ]
    assert len(repo.events_by_id) == 3


def test_domain_boundary_has_no_http_ui_permission_or_secondary_writes():
    names = (
        "shared_favorite_models.py",
        "shared_favorite_repository.py",
        "shared_favorite_service.py",
    )
    source = "\n".join(
        (BACKEND / "domains/talent_stream" / name).read_text(encoding="utf-8")
        for name in names
    )
    forbidden = {
        "candidate_profiles", "candidate_documents", "talent_stream_grants",
        "applications", "contact_requests", "notifications", "messages",
        "professional_match", "opportunity_fit",
    }
    assert all(token not in source for token in forbidden)
    tree = ast.parse(
        (BACKEND / "domains/talent_stream/shared_favorite_repository.py").read_text(
            encoding="utf-8"
        )
    )
    direct_writes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name in {
                "insert_one", "insert_many", "update_one", "update_many",
                "delete_one", "delete_many", "replace_one", "bulk_write",
            }:
                direct_writes.append(name)
    assert direct_writes == []
    server = (BACKEND / "server.py").read_text(encoding="utf-8")
    assert "shared_favorite" not in server
    assert not (BACKEND / "routes/talent_stream_shared_favorite.py").exists()
