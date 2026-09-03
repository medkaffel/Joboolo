"""P0-014 — candidature atomique et idempotente.

Tests unitaires ciblés, sans Mongo réel ni réseau. Ils vérifient le contrôle de
flux critique de `apply_to_job`: transaction, visibilité P0-006, idempotence,
rollback et fail-closed quand les transactions sont indisponibles.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models import ApplicationCreate, UserType  # noqa: E402
from routes import applications as mod  # noqa: E402


JOB_ID = "job_p014"
CANDIDATE_ID = "candidate_p014"
CAMPAIGN_ID = "campaign_p014"


class Result:
    def __init__(self, matched_count=1, modified_count=1):
        self.matched_count = matched_count
        self.modified_count = modified_count


class Collection:
    def __init__(self, db, name):
        self.db = db
        self.name = name

    async def find_one(self, query, *args, session=None, **kwargs):
        if session is not None:
            session.reads.append((self.name, dict(query)))
        docs = self.db.data[self.name]
        for doc in docs.values():
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    async def insert_one(self, doc, session=None):
        if self.name != "applications":
            raise AssertionError("unexpected insert")
        if session is None:
            self.db.data[self.name][doc["_id"]] = dict(doc)
            return Result()
        if session.duplicate_on_insert:
            winner = dict(doc)
            winner["_id"] = "app_winner"
            self.db.data["applications"][winner["_id"]] = winner
            raise DuplicateKeyError("duplicate")
        session.pending_app = dict(doc)
        return Result()

    async def update_one(self, query, update, session=None):
        if self.name != "jobs":
            return Result()
        job = self.db.data["jobs"].get(JOB_ID)
        if not job or query.get("is_active") is True and job.get("is_active") is not True:
            return Result(matched_count=0, modified_count=0)
        if session is not None and session.force_update_miss:
            return Result(matched_count=0, modified_count=0)
        inc = update.get("$inc", {}).get("applications_count", 0)
        if session is not None:
            session.pending_inc += inc
        else:
            job["applications_count"] = job.get("applications_count", 0) + inc
        return Result(matched_count=1, modified_count=1)


class FakeDB:
    def __init__(self):
        self.data = {
            "jobs": {},
            "campaigns": {},
            "applications": {},
            "companies": {},
            "users": {},
        }
        self.jobs = Collection(self, "jobs")
        self.campaigns = Collection(self, "campaigns")
        self.applications = Collection(self, "applications")
        self.companies = Collection(self, "companies")
        self.users = Collection(self, "users")


class Session:
    def __init__(self, db, *, unsupported=False, duplicate_on_insert=False, force_update_miss=False):
        self.db = db
        self.unsupported = unsupported
        self.duplicate_on_insert = duplicate_on_insert
        self.force_update_miss = force_update_miss
        self.pending_app = None
        self.pending_inc = 0
        self.reads = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def with_transaction(self, callback):
        if self.unsupported:
            raise RuntimeError("Transaction numbers are only allowed on a replica set member or mongos, not on a standalone server")
        try:
            result = await callback(self)
        except Exception:
            self.pending_app = None
            self.pending_inc = 0
            raise
        if self.pending_app is not None:
            self.db.data["applications"][self.pending_app["_id"]] = dict(self.pending_app)
        if self.pending_inc:
            job = self.db.data["jobs"][JOB_ID]
            job["applications_count"] = job.get("applications_count", 0) + self.pending_inc
        return result


class Client:
    def __init__(self, session):
        self.session = session

    async def start_session(self):
        return self.session


def candidate(user_type=UserType.CANDIDATE):
    return SimpleNamespace(
        id=CANDIDATE_ID,
        user_type=user_type,
        first_name="Ada",
        last_name="Lovelace",
        email=None,
    )


def seed_public_job(db, **overrides):
    doc = {
        "_id": JOB_ID,
        "title": "Engineer",
        "company_id": "company_1",
        "employer_id": "employer_1",
        "location": "Paris",
        "job_type": "CDI",
        "is_active": True,
        "applications_count": 0,
        "campaign_id": CAMPAIGN_ID,
        "expires_at": None,
    }
    doc.update(overrides)
    db.data["jobs"][JOB_ID] = doc
    db.data["campaigns"][CAMPAIGN_ID] = {
        "_id": CAMPAIGN_ID,
        "status": "active",
        "billing_mode": "per_posting",
    }
    db.data["companies"]["company_1"] = {"_id": "company_1", "name": "ACME", "location": "Paris"}
    return doc


@pytest.fixture
def app_data():
    return ApplicationCreate(job_id=JOB_ID, cover_letter="hello")


def wire(monkeypatch, db, session):
    monkeypatch.setattr(mod, "get_database", lambda: _async_value(db))
    monkeypatch.setattr(mod, "get_client", lambda: Client(session))


async def _async_value(value):
    return value


@pytest.mark.asyncio
async def test_happy_path_is_atomic_and_campaign_read_uses_same_session(monkeypatch, app_data):
    db = FakeDB()
    seed_public_job(db)
    session = Session(db)
    wire(monkeypatch, db, session)

    response = await mod.apply_to_job(app_data, candidate())

    assert response.id.startswith("app_")
    assert len(db.data["applications"]) == 1
    assert db.data["jobs"][JOB_ID]["applications_count"] == 1
    assert ("jobs", {"_id": JOB_ID, "is_active": True}) in session.reads
    assert ("campaigns", {"_id": CAMPAIGN_ID}) in session.reads


@pytest.mark.asyncio
async def test_retry_existing_returns_without_second_increment(monkeypatch, app_data):
    db = FakeDB()
    seed_public_job(db)
    db.data["applications"]["app_existing"] = {
        "_id": "app_existing", "job_id": JOB_ID, "candidate_id": CANDIDATE_ID,
        "status": "pending", "created_at": mod.datetime.utcnow(), "cover_letter": None, "cv_url": None,
    }
    session = Session(db)
    wire(monkeypatch, db, session)

    response = await mod.apply_to_job(app_data, candidate())

    assert response.id == "app_existing"
    assert db.data["jobs"][JOB_ID]["applications_count"] == 0
    assert session.reads == []


@pytest.mark.asyncio
async def test_concurrent_duplicate_relooks_up_winner_without_increment(monkeypatch, app_data):
    db = FakeDB()
    seed_public_job(db)
    session = Session(db, duplicate_on_insert=True)
    wire(monkeypatch, db, session)

    response = await mod.apply_to_job(app_data, candidate())

    assert response.id == "app_winner"
    assert len(db.data["applications"]) == 1
    assert db.data["jobs"][JOB_ID]["applications_count"] == 0


@pytest.mark.asyncio
async def test_job_deactivated_during_transaction_rolls_back_application(monkeypatch, app_data):
    db = FakeDB()
    seed_public_job(db)
    session = Session(db, force_update_miss=True)
    wire(monkeypatch, db, session)

    with pytest.raises(mod.HTTPException) as exc:
        await mod.apply_to_job(app_data, candidate())

    assert exc.value.status_code == 404
    assert db.data["applications"] == {}
    assert db.data["jobs"][JOB_ID]["applications_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("expires_at", ["", "   ", "not-a-date"])
async def test_invalid_or_empty_expires_at_fails_closed_zero_writes(monkeypatch, app_data, expires_at):
    db = FakeDB()
    seed_public_job(db, expires_at=expires_at)
    session = Session(db)
    wire(monkeypatch, db, session)

    with pytest.raises(mod.HTTPException) as exc:
        await mod.apply_to_job(app_data, candidate())

    assert exc.value.status_code == 404
    assert db.data["applications"] == {}
    assert db.data["jobs"][JOB_ID]["applications_count"] == 0


@pytest.mark.asyncio
async def test_non_diffusible_campaign_fails_closed(monkeypatch, app_data):
    db = FakeDB()
    seed_public_job(db)
    db.data["campaigns"][CAMPAIGN_ID]["status"] = "paused"
    session = Session(db)
    wire(monkeypatch, db, session)

    with pytest.raises(mod.HTTPException) as exc:
        await mod.apply_to_job(app_data, candidate())

    assert exc.value.status_code == 404
    assert db.data["applications"] == {}


@pytest.mark.asyncio
async def test_standalone_mongo_returns_503_zero_writes(monkeypatch, app_data):
    db = FakeDB()
    seed_public_job(db)
    session = Session(db, unsupported=True)
    wire(monkeypatch, db, session)

    with pytest.raises(mod.HTTPException) as exc:
        await mod.apply_to_job(app_data, candidate())

    assert exc.value.status_code == 503
    assert db.data["applications"] == {}
    assert db.data["jobs"][JOB_ID]["applications_count"] == 0


@pytest.mark.asyncio
async def test_acl_rejects_non_candidate_before_any_write(monkeypatch, app_data):
    db = FakeDB()
    seed_public_job(db)
    session = Session(db)
    wire(monkeypatch, db, session)

    with pytest.raises(mod.HTTPException) as exc:
        await mod.apply_to_job(app_data, candidate(UserType.EMPLOYER))

    assert exc.value.status_code == 403
    assert db.data["applications"] == {}
    assert db.data["jobs"][JOB_ID]["applications_count"] == 0
