"""P0-004 — isolated tests for atomic CPC debit.

No real MongoDB, backend server, network call, seeded account, or secret is used.
The fake partner collection models MongoDB's single-document atomic update with
an asyncio.Lock so concurrent calls exercise the route's exact control flow.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
JOBS_PATH = BACKEND_DIR / "routes" / "jobs.py"

PARTNER_ID = "partner_1"
JOB_ID = "job_1"


class _HTTPException(Exception):
    def __init__(self, status_code, detail=None):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


class _Router:
    def __init__(self, *args, **kwargs):
        pass

    def _decorator(self, *args, **kwargs):
        def deco(fn):
            return fn
        return deco

    get = post = put = delete = _decorator


class _Model:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def dict(self):
        return dict(self.__dict__)


class _UserType:
    EMPLOYER = "employer"


class _UpdateResult:
    def __init__(self, modified_count):
        self.modified_count = modified_count


class _AtomicPartnerCollection:
    """Small in-memory model of MongoDB atomic find-filter + update semantics."""

    def __init__(self, profile):
        self.profile = dict(profile)
        self._lock = asyncio.Lock()
        self.atomic_filters = []

    @staticmethod
    def _matches(document, query):
        for key, expected in query.items():
            actual = document.get(key)
            if isinstance(expected, dict) and "$gte" in expected:
                if actual is None or actual < expected["$gte"]:
                    return False
            elif actual != expected:
                return False
        return True

    async def find_one(self, query):
        async with self._lock:
            if self._matches(self.profile, query):
                return dict(self.profile)
            return None

    async def update_one(self, query, update):
        async with self._lock:
            if "balance" in query and isinstance(query["balance"], dict):
                self.atomic_filters.append(dict(query))
            if not self._matches(self.profile, query):
                return _UpdateResult(0)
            for key, value in update.get("$inc", {}).items():
                self.profile[key] = self.profile.get(key, 0) + value
            for key, value in update.get("$set", {}).items():
                self.profile[key] = value
            return _UpdateResult(1)


class _JobsCollection:
    def __init__(self, job):
        self.job = dict(job)
        self._lock = asyncio.Lock()

    async def find_one(self, query):
        async with self._lock:
            for key, expected in query.items():
                if self.job.get(key) != expected:
                    return None
            return dict(self.job)

    async def update_one(self, query, update):
        async with self._lock:
            if self.job.get("_id") != query.get("_id"):
                return _UpdateResult(0)
            for key, value in update.get("$inc", {}).items():
                self.job[key] = self.job.get(key, 0) + value
            for key, value in update.get("$set", {}).items():
                self.job[key] = value
            return _UpdateResult(1)

    async def update_many(self, query, update):
        return await self.update_one({"_id": self.job.get("_id")}, update)


class _EventsCollection:
    def __init__(self):
        self.records = []
        self._lock = asyncio.Lock()

    async def insert_one(self, document):
        async with self._lock:
            self.records.append(dict(document))
        return types.SimpleNamespace(inserted_id=len(self.records))


class _NoopCollection:
    async def find_one(self, query):
        return None

    async def update_one(self, query, update):
        return _UpdateResult(0)

    async def update_many(self, query, update):
        return _UpdateResult(0)


class _FakeDB:
    def __init__(self, *, balance, cpc=0.5, billing_mode="per_click", is_partner=True, default_cpc=0.5):
        self.partner_profiles = _AtomicPartnerCollection({
            "user_id": PARTNER_ID,
            "billing_mode": billing_mode,
            "balance": balance,
            "default_cpc": default_cpc,
            "total_clicks": 0,
            "total_spent": 0.0,
        })
        self.jobs = _JobsCollection({
            "_id": JOB_ID,
            "partner_id": PARTNER_ID,
            "is_partner": is_partner,
            "external_url": "https://example.test/job",
            "title": "Partner job",
            "cpc": cpc,
            "is_active": True,
            "views_count": 0,
        })
        self.click_events = _EventsCollection()
        self.campaigns = _NoopCollection()
        self.users = _NoopCollection()
        self.companies = _NoopCollection()


def _install_import_stubs(monkeypatch):
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = _Router
    fastapi.HTTPException = _HTTPException
    fastapi.Depends = lambda dependency=None, *a, **k: dependency
    fastapi.Query = lambda default=None, *a, **k: default
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)

    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = _Model
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)

    models = types.ModuleType("models")
    for name in ("Job", "JobCreate", "JobUpdate", "JobResponse", "JobSearchQuery", "JobSearchResponse", "User"):
        setattr(models, name, _Model)
    models.UserType = _UserType
    monkeypatch.setitem(sys.modules, "models", models)

    database = types.ModuleType("database")

    async def _placeholder_db():
        raise AssertionError("test must replace get_database")

    database.get_database = _placeholder_db
    monkeypatch.setitem(sys.modules, "database", database)

    auth = types.ModuleType("auth")

    async def _auth_stub(*args, **kwargs):
        return None

    auth.get_current_active_user = _auth_stub
    auth.require_employer = _auth_stub
    monkeypatch.setitem(sys.modules, "auth", auth)

    geo = types.ModuleType("geo_service")

    async def _resolve(*args, **kwargs):
        return []

    async def _geocode(*args, **kwargs):
        return None

    geo.resolve_location_codes = _resolve
    geo.geocode_place = _geocode
    geo.postcode_regex = lambda code: code
    monkeypatch.setitem(sys.modules, "geo_service", geo)


@pytest.fixture
def jobs_module(monkeypatch):
    _install_import_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location("routes_jobs_p0004", JOBS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def _no_low_balance(*args, **kwargs):
        return None

    module._check_low_balance = _no_low_balance
    module._HTTPException = _HTTPException
    return module


def _run(jobs_module, db, count=1):
    async def scenario():
        async def _get_database():
            return db

        jobs_module.get_database = _get_database
        if count == 1:
            return [await jobs_module.record_partner_click(JOB_ID)]
        return await asyncio.gather(
            *(jobs_module.record_partner_click(JOB_ID) for _ in range(count))
        )

    return asyncio.run(scenario())


def _costs(db):
    return sorted(float(event["cost"]) for event in db.click_events.records)


def test_exact_balance_debit_is_atomic(jobs_module):
    db = _FakeDB(balance=1.0, cpc=0.5)
    responses = _run(jobs_module, db)

    assert responses == [{"redirect_url": "https://example.test/job"}]
    assert db.partner_profiles.profile["balance"] == pytest.approx(0.5)
    assert db.partner_profiles.profile["total_spent"] == pytest.approx(0.5)
    assert db.partner_profiles.profile["total_clicks"] == 1
    assert _costs(db) == [0.5]
    assert db.partner_profiles.atomic_filters == [
        {"user_id": PARTNER_ID, "balance": {"$gte": 0.5}}
    ]


def test_insufficient_balance_is_not_debited_and_job_stops(jobs_module):
    db = _FakeDB(balance=0.3, cpc=0.5)
    _run(jobs_module, db)

    assert db.partner_profiles.profile["balance"] == pytest.approx(0.3)
    assert db.partner_profiles.profile["total_spent"] == pytest.approx(0.0)
    assert db.partner_profiles.profile["total_clicks"] == 1
    assert db.jobs.job["is_active"] is False
    assert db.jobs.job["views_count"] == 1
    assert len(db.click_events.records) == 1
    assert db.click_events.records[0]["cost"] == 0.0
    assert db.click_events.records[0]["stopped"] is True


def test_cpc_zero_counts_click_without_debit(jobs_module):
    db = _FakeDB(balance=1.0, cpc=0.0)
    _run(jobs_module, db)

    assert db.partner_profiles.profile["balance"] == pytest.approx(1.0)
    assert db.partner_profiles.profile["total_spent"] == pytest.approx(0.0)
    assert db.partner_profiles.profile["total_clicks"] == 1
    assert db.jobs.job["is_active"] is True
    assert _costs(db) == [0.0]
    assert db.partner_profiles.atomic_filters == []


def test_default_cpc_from_profile_is_preserved(jobs_module):
    db = _FakeDB(balance=0.5, cpc=None, default_cpc=0.25)
    _run(jobs_module, db)

    assert db.partner_profiles.profile["balance"] == pytest.approx(0.25)
    assert db.partner_profiles.profile["total_spent"] == pytest.approx(0.25)
    assert db.partner_profiles.profile["total_clicks"] == 1
    assert _costs(db) == [0.25]


def test_non_partner_is_rejected_without_billing(jobs_module):
    db = _FakeDB(balance=1.0, cpc=0.5, is_partner=False)

    with pytest.raises(_HTTPException) as exc:
        _run(jobs_module, db)

    assert exc.value.status_code == 400
    assert db.partner_profiles.profile["balance"] == pytest.approx(1.0)
    assert db.partner_profiles.profile["total_clicks"] == 0
    assert db.click_events.records == []


def test_two_concurrent_clicks_with_balance_for_one_charge_exactly_once(jobs_module):
    db = _FakeDB(balance=0.5, cpc=0.5)
    _run(jobs_module, db, count=2)

    assert db.partner_profiles.profile["balance"] == pytest.approx(0.0)
    assert db.partner_profiles.profile["balance"] >= 0
    assert db.partner_profiles.profile["total_spent"] == pytest.approx(0.5)
    assert db.partner_profiles.profile["total_clicks"] == 2
    assert _costs(db) == [0.0, 0.5]
    assert sum(event["cost"] > 0 for event in db.click_events.records) == 1
    assert len(db.partner_profiles.atomic_filters) == 2
    assert all(f == {"user_id": PARTNER_ID, "balance": {"$gte": 0.5}}
               for f in db.partner_profiles.atomic_filters)


def test_five_concurrent_clicks_with_balance_for_two_charge_exactly_twice(jobs_module):
    db = _FakeDB(balance=1.0, cpc=0.5)
    _run(jobs_module, db, count=5)

    assert db.partner_profiles.profile["balance"] == pytest.approx(0.0)
    assert db.partner_profiles.profile["balance"] >= 0
    assert db.partner_profiles.profile["total_spent"] == pytest.approx(1.0)
    assert db.partner_profiles.profile["total_clicks"] == 5
    assert _costs(db) == [0.0, 0.0, 0.0, 0.5, 0.5]
    assert sum(event["cost"] > 0 for event in db.click_events.records) == 2
    assert len(db.click_events.records) == 5
    assert len(db.partner_profiles.atomic_filters) == 5
