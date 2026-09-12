"""TS-B1 G0 contracts using in-memory fakes only."""
import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson.int64 import Int64
import pytest
from pymongo.errors import DuplicateKeyError

from domains.shared.ids import (
    HiringCompanyId, MandateId, OpportunitySpecId, OrganizationId,
    RecruiterUserId, RoleDNAId, TalentStreamId,
)
from domains.shared.versioning import EntityVersion
from domains.talent_stream.contracts import (
    OpportunitySpecificationRef, RecruitingActorContext, RoleDNARef,
    StreamRequirementSnapshot,
)
from domains.talent_stream.index_requirements import TALENT_STREAM_REQUIREMENT
from domains.talent_stream.stream_models import (
    TALENT_STREAM_SCHEMA_VERSION, StreamCommandHistoryEntry, StreamCommandKind,
    TalentStream, TalentStreamState, positive_entity_version,
)
from domains.talent_stream.stream_repository import (
    TalentStreamConflictError, TalentStreamReadinessError, TalentStreamRepository,
    TalentStreamStoredDataError, stream_from_document, stream_to_document,
)
from domains.talent_stream.stream_service import (
    TalentStreamNotFoundError, TalentStreamService, create_command_fingerprint,
    transition_command_fingerprint,
)
from scripts.migrate_ts_b1_talent_streams import (
    TalentStreamMigrationError, main as migration_main, migrate, preflight,
)


BACKEND = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)


def actor(*, recruiter="recruiter-1", mandate="mandate-1"):
    return RecruitingActorContext(
        recruiter_user_id=RecruiterUserId(recruiter),
        requesting_organization_id=OrganizationId("requesting-org-1"),
        hiring_company_id=HiringCompanyId("hiring-company-1"),
        mandate_id=None if mandate is None else MandateId(mandate),
    )


def requirement(*, role_version=1, captured_at=NOW):
    return StreamRequirementSnapshot(
        role_dna=RoleDNARef(RoleDNAId("role-1"), EntityVersion(role_version)),
        opportunity_spec=OpportunitySpecificationRef(
            OpportunitySpecId("opportunity-1"), EntityVersion(2),
        ),
        requirement_version=EntityVersion(3),
        captured_at=captured_at,
    )


def entry(kind, version, occurred_at, *, command_id=None, fingerprint=None, prior=None):
    targets = {
        StreamCommandKind.CREATE: TalentStreamState.DRAFT,
        StreamCommandKind.ACTIVATE: TalentStreamState.ACTIVE,
        StreamCommandKind.CLOSE: TalentStreamState.CLOSED,
    }
    return StreamCommandHistoryEntry(
        command_id=command_id or f"command-{version}",
        command_fingerprint=fingerprint or f"fingerprint-{version}",
        command_kind=kind,
        from_state=prior,
        to_state=targets[kind],
        resulting_version=EntityVersion(version),
        occurred_at=occurred_at,
    )


def aggregate(*history, state=None):
    history = history or (entry(StreamCommandKind.CREATE, 1, NOW),)
    return TalentStream(
        stream_id=TalentStreamId("stream-1"),
        version=EntityVersion(len(history)),
        recruiting_actor_context=actor(),
        requirement_snapshot=requirement(),
        state=state or history[-1].to_state,
        created_at=NOW,
        updated_at=history[-1].occurred_at,
        history=tuple(history),
    )


class AsyncCursor:
    def __init__(self, values):
        self.values = iter(values)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.values)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self, db):
        self.db = db
        self.document = None
        self.indexes = {"_id_": {"v": 2, "key": [("_id", 1)]}}
        self.last_filter = None
        self.last_update = None
        self.write_count = 0
        self.cas_replacement = None

    def with_options(self, **_options):
        return self

    async def index_information(self):
        return deepcopy(self.indexes)

    async def find_one(self, query, **_options):
        self.db.actions.append("read")
        if self.document is None or self.document["_id"] != query.get("_id"):
            return None
        return deepcopy(self.document)

    async def insert_one(self, document):
        self.db.actions.append("insert")
        self.write_count += 1
        if self.document is not None:
            raise DuplicateKeyError("private raw duplicate detail")
        self.document = deepcopy(document)

    async def find_one_and_update(self, query, update, **_options):
        self.db.actions.append("update")
        self.write_count += 1
        self.last_filter = deepcopy(query)
        self.last_update = deepcopy(update)
        if self.cas_replacement is not None:
            self.document = stream_to_document(self.cas_replacement)
            self.cas_replacement = None
            return None
        document = self.document
        compared = {key: value for key, value in query.items() if key != "history.2"}
        if document is None or any(document.get(key) != value for key, value in compared.items()):
            return None
        if len(document["history"]) >= 3:
            return None
        document = deepcopy(document)
        document.update(update["$set"])
        document["version"] += update["$inc"]["version"]
        document["history"].append(deepcopy(update["$push"]["history"]))
        self.document = document
        return deepcopy(document)

    def find(self, _query):
        values = [] if self.document is None else [deepcopy(self.document)]
        return AsyncCursor(values)


class FakeDatabase:
    def __init__(self, *, present=True):
        self.present = present
        self.actions = []
        self.collection = FakeCollection(self)
        self.create_calls = 0

    def __getitem__(self, name):
        assert name == "talent_streams"
        return self.collection

    async def list_collections(self, **_options):
        self.actions.append("readiness")
        records = [] if not self.present else [{
            "name": "talent_streams", "type": "collection", "options": {},
        }]
        return AsyncCursor(records)

    async def create_collection(self, name):
        assert name == "talent_streams"
        self.create_calls += 1
        self.present = True
        return self.collection


@pytest.mark.parametrize("state", list(TalentStreamState))
def test_schema_and_enums_are_closed(state):
    assert TALENT_STREAM_SCHEMA_VERSION == "talent-stream-v1"
    assert {value.value for value in TalentStreamState} == {"draft", "active", "closed"}
    assert {value.value for value in StreamCommandKind} == {"create", "activate", "close"}
    if state is not TalentStreamState.DRAFT:
        with pytest.raises(ValueError):
            aggregate(state=state)


def test_model_is_frozen_and_rejects_unsupported_schema_state_and_history():
    stream = aggregate()
    with pytest.raises(FrozenInstanceError):
        stream.state = TalentStreamState.ACTIVE
    with pytest.raises(ValueError):
        replace(stream, schema_version="future-v9")
    with pytest.raises(ValueError):
        replace(stream, state="draft")
    with pytest.raises(ValueError):
        replace(stream, history=[])


def test_only_four_b1_histories_are_valid_and_bounded():
    created = entry(StreamCommandKind.CREATE, 1, NOW)
    activated = entry(
        StreamCommandKind.ACTIVATE, 2, NOW + timedelta(seconds=1),
        prior=TalentStreamState.DRAFT,
    )
    closed_draft = entry(
        StreamCommandKind.CLOSE, 2, NOW + timedelta(seconds=1),
        prior=TalentStreamState.DRAFT,
    )
    closed_active = entry(
        StreamCommandKind.CLOSE, 3, NOW + timedelta(seconds=2),
        prior=TalentStreamState.ACTIVE,
    )
    assert aggregate(created).state is TalentStreamState.DRAFT
    assert aggregate(created, activated).state is TalentStreamState.ACTIVE
    assert aggregate(created, closed_draft).state is TalentStreamState.CLOSED
    assert aggregate(created, activated, closed_active).state is TalentStreamState.CLOSED
    with pytest.raises(ValueError):
        aggregate(created, activated, closed_active, closed_active)
    with pytest.raises(ValueError):
        aggregate(created, closed_draft, activated)


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.0, "1"])
def test_versions_reject_bool_and_nonpositive_or_noninteger_values(value):
    with pytest.raises(ValueError):
        positive_entity_version(value, "version")


def test_bson_int64_versions_and_utc_round_trip_are_strict():
    document = stream_to_document(aggregate())
    document["version"] = Int64(1)
    document["requirement_snapshot"]["role_dna"]["version"] = Int64(1)
    document["requirement_snapshot"]["opportunity_spec"]["version"] = Int64(2)
    document["requirement_snapshot"]["requirement_version"] = Int64(3)
    document["history"][0]["resulting_version"] = Int64(1)
    for field in ("created_at", "updated_at"):
        document[field] = document[field].replace(tzinfo=None)
    document["requirement_snapshot"]["captured_at"] = NOW.replace(tzinfo=None)
    document["history"][0]["occurred_at"] = NOW.replace(tzinfo=None)
    restored = stream_from_document(document)
    assert restored == aggregate()
    assert restored.created_at.tzinfo is timezone.utc


@pytest.mark.parametrize("path", ["version", "role", "opportunity", "requirement", "history"])
def test_strict_rehydration_rejects_bool_versions(path):
    document = stream_to_document(aggregate())
    targets = {
        "version": (document, "version"),
        "role": (document["requirement_snapshot"]["role_dna"], "version"),
        "opportunity": (document["requirement_snapshot"]["opportunity_spec"], "version"),
        "requirement": (document["requirement_snapshot"], "requirement_version"),
        "history": (document["history"][0], "resulting_version"),
    }
    target, key = targets[path]
    target[key] = True
    with pytest.raises(TalentStreamStoredDataError, match="^invalid stored Talent Stream$"):
        stream_from_document(document)


def test_nested_a0_context_and_requirement_are_strict_and_have_no_escape_fields():
    document = stream_to_document(aggregate())
    document["recruiting_actor_context"]["recruiter_user_id"] = " "
    with pytest.raises(TalentStreamStoredDataError):
        stream_from_document(document)
    document = stream_to_document(aggregate())
    document["requirement_snapshot"]["role_dna"]["unexpected"] = "private"
    with pytest.raises(TalentStreamStoredDataError) as error:
        stream_from_document(document)
    assert "private" not in str(error.value)
    assert set(stream_to_document(aggregate())) == {
        "_id", "schema_version", "version", "recruiting_actor_context",
        "requirement_snapshot", "state", "created_at", "updated_at", "history",
    }


def test_requirement_timestamp_must_be_utc_and_not_after_creation():
    stream = aggregate()
    offset = timezone(timedelta(hours=2))
    with pytest.raises(ValueError, match="must be UTC"):
        replace(stream, requirement_snapshot=requirement(captured_at=NOW.astimezone(offset)))
    with pytest.raises(ValueError, match="cannot postdate"):
        replace(stream, requirement_snapshot=requirement(captured_at=NOW + timedelta(seconds=1)))


def test_create_fingerprint_is_canonical_and_covers_business_input():
    baseline = create_command_fingerprint("stream-1", actor(), requirement())
    assert baseline == create_command_fingerprint("stream-1", actor(), requirement())
    assert baseline != create_command_fingerprint("stream-2", actor(), requirement())
    assert baseline != create_command_fingerprint(
        "stream-1", actor(recruiter="recruiter-2"), requirement(),
    )
    assert baseline != create_command_fingerprint("stream-1", actor(), requirement(role_version=2))
    assert baseline.startswith("sha256:") and len(baseline) == 71


def test_transition_fingerprint_covers_stream_kind_and_expected_version():
    baseline = transition_command_fingerprint("stream-1", StreamCommandKind.ACTIVATE, 1)
    assert baseline != transition_command_fingerprint("stream-2", StreamCommandKind.ACTIVATE, 1)
    assert baseline != transition_command_fingerprint("stream-1", StreamCommandKind.CLOSE, 1)
    assert baseline != transition_command_fingerprint("stream-1", StreamCommandKind.ACTIVATE, 2)
    with pytest.raises(ValueError):
        transition_command_fingerprint("stream-1", StreamCommandKind.CREATE, 1)


@pytest.mark.asyncio
async def test_create_is_draft_idempotent_and_readiness_precedes_each_write():
    db = FakeDatabase()
    app = TalentStreamService(db)
    first = await app.create(
        "stream-1", actor(), requirement(), command_id="create-1", occurred_at=NOW,
    )
    replay = await app.create(
        "stream-1", actor(), requirement(), command_id="create-1",
        occurred_at=NOW + timedelta(minutes=5),
    )
    assert first.state is TalentStreamState.DRAFT and first.version == 1
    assert replay == first
    assert db.actions.index("readiness") < db.actions.index("insert")
    assert db.actions.count("readiness") == db.actions.count("insert") == 2


@pytest.mark.asyncio
async def test_duplicate_create_requires_exact_command_and_business_content():
    db = FakeDatabase()
    app = TalentStreamService(db)
    await app.create("stream-1", actor(), requirement(), command_id="create-1", occurred_at=NOW)
    with pytest.raises(TalentStreamConflictError, match="^Talent Stream create conflict$"):
        await app.create(
            "stream-1", actor(recruiter="recruiter-2"), requirement(),
            command_id="create-1", occurred_at=NOW,
        )
    with pytest.raises(TalentStreamConflictError):
        await app.create(
            "stream-1", actor(), requirement(), command_id="create-2", occurred_at=NOW,
        )


@pytest.mark.asyncio
async def test_activate_close_and_delayed_replay_preserve_current_state():
    db = FakeDatabase()
    app = TalentStreamService(db)
    await app.create("stream-1", actor(), requirement(), command_id="create-1", occurred_at=NOW)
    active = await app.activate(
        "stream-1", command_id="activate-1", expected_version=1,
        occurred_at=NOW + timedelta(seconds=1),
    )
    closed = await app.close(
        "stream-1", command_id="close-1", expected_version=2,
        occurred_at=NOW + timedelta(seconds=2),
    )
    writes = db.collection.write_count
    replay = await app.activate(
        "stream-1", command_id="activate-1", expected_version=1,
        occurred_at=NOW + timedelta(hours=1),
    )
    assert active.state is TalentStreamState.ACTIVE and active.version == 2
    assert closed.state is replay.state is TalentStreamState.CLOSED
    assert replay.version == 3 and len(replay.history) == 3
    assert db.collection.write_count == writes


@pytest.mark.asyncio
async def test_draft_may_close_and_closed_is_terminal():
    db = FakeDatabase()
    app = TalentStreamService(db)
    await app.create("stream-1", actor(), requirement(), command_id="create-1", occurred_at=NOW)
    closed = await app.close(
        "stream-1", command_id="close-1", expected_version=1,
        occurred_at=NOW + timedelta(seconds=1),
    )
    assert closed.state is TalentStreamState.CLOSED and len(closed.history) == 2
    with pytest.raises(TalentStreamConflictError):
        await app.close(
            "stream-1", command_id="close-2", expected_version=2,
            occurred_at=NOW + timedelta(seconds=2),
        )


@pytest.mark.asyncio
async def test_command_identity_collision_and_expected_version_are_fail_closed():
    db = FakeDatabase()
    app = TalentStreamService(db)
    await app.create("stream-1", actor(), requirement(), command_id="shared", occurred_at=NOW)
    with pytest.raises(TalentStreamConflictError, match="command identity conflict"):
        await app.activate(
            "stream-1", command_id="shared", expected_version=1,
            occurred_at=NOW + timedelta(seconds=1),
        )
    with pytest.raises(ValueError):
        await app.activate("stream-1", command_id="activate", expected_version=True)
    with pytest.raises(TalentStreamConflictError, match="state or version conflict"):
        await app.activate("stream-1", command_id="activate", expected_version=2)


@pytest.mark.asyncio
async def test_atomic_cas_shape_and_single_history_append():
    db = FakeDatabase()
    app = TalentStreamService(db)
    await app.create("stream-1", actor(), requirement(), command_id="create-1", occurred_at=NOW)
    await app.activate(
        "stream-1", command_id="activate-1", expected_version=1,
        occurred_at=NOW + timedelta(seconds=1),
    )
    assert db.collection.last_filter == {
        "_id": "stream-1", "schema_version": TALENT_STREAM_SCHEMA_VERSION,
        "version": 1, "state": "draft", "history.2": {"$exists": False},
    }
    update = db.collection.last_update
    assert update["$inc"] == {"version": 1}
    assert set(update) == {"$set", "$inc", "$push"}
    assert update["$push"]["history"]["command_kind"] == "activate"


@pytest.mark.asyncio
async def test_cas_loser_recovers_only_the_exact_applied_command():
    db = FakeDatabase()
    app = TalentStreamService(db)
    initial = await app.create(
        "stream-1", actor(), requirement(), command_id="create-1", occurred_at=NOW,
    )
    fingerprint = transition_command_fingerprint("stream-1", StreamCommandKind.ACTIVATE, 1)
    applied = aggregate(
        initial.history[0],
        entry(
            StreamCommandKind.ACTIVATE, 2, NOW + timedelta(seconds=1),
            prior=TalentStreamState.DRAFT, command_id="activate-1", fingerprint=fingerprint,
        ),
    )
    db.collection.cas_replacement = applied
    recovered = await app.activate(
        "stream-1", command_id="activate-1", expected_version=1,
        occurred_at=NOW + timedelta(seconds=1),
    )
    assert recovered == applied

    db = FakeDatabase()
    app = TalentStreamService(db)
    initial = await app.create(
        "stream-1", actor(), requirement(), command_id="create-1", occurred_at=NOW,
    )
    db.collection.cas_replacement = aggregate(
        initial.history[0],
        entry(
            StreamCommandKind.ACTIVATE, 2, NOW + timedelta(seconds=1),
            prior=TalentStreamState.DRAFT, command_id="other-command",
        ),
    )
    with pytest.raises(TalentStreamConflictError, match="state or version conflict"):
        await app.activate(
            "stream-1", command_id="activate-1", expected_version=1,
            occurred_at=NOW + timedelta(seconds=1),
        )


@pytest.mark.asyncio
async def test_read_missing_returns_none_and_service_is_explicit():
    db = FakeDatabase()
    assert await TalentStreamRepository(db).get("missing") is None
    assert db.collection.write_count == 0
    with pytest.raises(TalentStreamNotFoundError, match="^Talent Stream not found$"):
        await TalentStreamService(db).get("missing")


@pytest.mark.asyncio
async def test_readiness_rejects_missing_or_extra_index_without_write():
    missing = FakeDatabase(present=False)
    with pytest.raises(TalentStreamReadinessError):
        await TalentStreamService(missing).create(
            "stream-1", actor(), requirement(), command_id="create-1", occurred_at=NOW,
        )
    assert missing.collection.write_count == 0
    extra = FakeDatabase()
    extra.collection.indexes["unexpected"] = {"v": 2, "key": [("state", 1)]}
    with pytest.raises(TalentStreamReadinessError):
        await TalentStreamService(extra).create(
            "stream-1", actor(), requirement(), command_id="create-1", occurred_at=NOW,
        )
    assert extra.collection.write_count == 0


def test_b1_manifest_is_exact_and_has_native_identity_only():
    assert TALENT_STREAM_REQUIREMENT.name == "talent_streams"
    assert TALENT_STREAM_REQUIREMENT.indexes == ()
    assert TALENT_STREAM_REQUIREMENT.ordinary and TALENT_STREAM_REQUIREMENT.simple_collation
    assert TALENT_STREAM_REQUIREMENT.forbid_ttl
    assert TALENT_STREAM_REQUIREMENT.forbid_extra_indexes


@pytest.mark.asyncio
async def test_migration_is_read_only_by_default_and_apply_is_repeatable():
    db = FakeDatabase(present=False)
    missing = {"ready": False, "documents_checked": 0, "diagnostics": 1}
    assert await preflight(db) == missing
    assert await migrate(db) == missing
    assert db.create_calls == 0 and not db.present
    assert await migrate(db, apply=True) == {
        "ready": True, "documents_checked": 0, "diagnostics": 0,
    }
    assert db.create_calls == 1
    assert (await migrate(db, apply=True))["ready"]
    assert db.create_calls == 1


@pytest.mark.asyncio
async def test_migration_rejects_incompatible_metadata_and_malformed_documents():
    db = FakeDatabase()
    db.collection.indexes["ttl"] = {
        "v": 2, "key": [("updated_at", 1)], "expireAfterSeconds": 10,
    }
    with pytest.raises(TalentStreamMigrationError, match="^incompatible Talent Stream metadata$"):
        await preflight(db)
    db = FakeDatabase()
    db.collection.document = {"_id": "private-id", "private": "do-not-render"}
    with pytest.raises(TalentStreamMigrationError) as error:
        await preflight(db)
    assert "private-id" not in str(error.value) and "do-not-render" not in str(error.value)


@pytest.mark.asyncio
async def test_migration_requires_explicit_environment(monkeypatch, capsys):
    monkeypatch.delenv("MONGO_URL", raising=False)
    monkeypatch.delenv("DB_NAME", raising=False)
    assert await migration_main() == 2
    assert capsys.readouterr().out.strip() == '{"error":"explicit_configuration_required"}'


def test_no_transaction_or_adjacent_lot_dependency():
    files = (
        "domains/talent_stream/stream_models.py",
        "domains/talent_stream/stream_repository.py",
        "domains/talent_stream/stream_service.py",
    )
    forbidden_imports = {
        "database", "fastapi", "async_outbox", "domains.intent", "domains.permissions",
        "domains.privacy", "domains.matching", "domains.preferences",
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
        assert not (imports & forbidden_imports)
        attributes = {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        assert not ({"start_session", "start_transaction"} & attributes)


def test_migration_only_has_explicit_collection_creation_mutation():
    path = BACKEND / "scripts/migrate_ts_b1_talent_streams.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    forbidden = {
        "create_index", "insert_one", "update_one", "update_many", "replace_one",
        "delete_one", "delete_many", "drop", "drop_index", "rename", "bulk_write",
    }
    assert not (calls & forbidden)
    assert "create_collection" in calls
    assert "database" not in {
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

