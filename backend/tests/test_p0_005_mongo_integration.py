"""Real-Mongo integration tests for P0-005 recruiter entitlements.

These tests run the actual create_job and _credit_if_paid flows against a real
MongoDB server and verify transaction success, rollback, concurrency, and
fail-closed (standalone 503 / zero-write) behavior.

Environment variables (optional):
  P005_REPLICA_SET_URL  — MongoDB replica-set server (default: mongodb://127.0.0.1:27017)
  P005_STANDALONE_URL   — MongoDB standalone server (default: mongodb://127.0.0.1:27018)

Each test creates its own ephemeral database (uuid-named) and drops it on exit,
so tests are fully isolated and safe to run in parallel.
"""

import asyncio
import importlib.util
import os
import sys
import types
import uuid
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
JOBS_PATH = BACKEND_DIR / "routes" / "jobs.py"
PAYMENTS_PATH = BACKEND_DIR / "routes" / "payments.py"

REPLICA_SET_URL = os.environ.get("P005_REPLICA_SET_URL", "mongodb://127.0.0.1:27017")
STANDALONE_URL = os.environ.get("P005_STANDALONE_URL", "mongodb://127.0.0.1:27018")

USER_ID = "user_p005_real"
COMPANY_ID = "company_p005_real"
EMAIL = "real_p005@test.example"


# --------------------------------------------------------------------------- #
# Minimal stubs for non-Mongo dependencies                                    #
# --------------------------------------------------------------------------- #
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
    ADMIN = "admin"


def _install_import_stubs(monkeypatch):
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = _Router
    fastapi.HTTPException = _HTTPException
    fastapi.Depends = lambda dependency=None, *a, **k: dependency
    fastapi.Query = lambda default=None, *a, **k: default
    fastapi.status = types.SimpleNamespace(
        HTTP_402_PAYMENT_REQUIRED=402,
        HTTP_503_SERVICE_UNAVAILABLE=503,
    )
    fastapi.Request = object
    fastapi.File = lambda *a, **k: None
    fastapi.UploadFile = object
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)

    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = _Model
    pydantic.Field = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)

    models = types.ModuleType("models")
    for name in ("Job", "JobCreate", "JobUpdate", "JobResponse", "JobSearchQuery",
                 "JobSearchResponse", "User"):
        setattr(models, name, _Model)
    models.UserType = _UserType
    monkeypatch.setitem(sys.modules, "models", models)

    database = types.ModuleType("database")

    async def _placeholder_db():
        raise AssertionError("test must replace get_database")

    def _placeholder_client():
        raise AssertionError("test must replace get_client")

    database.get_database = _placeholder_db
    database.get_client = _placeholder_client
    monkeypatch.setitem(sys.modules, "database", database)

    auth = types.ModuleType("auth")

    async def _auth_stub(*args, **kwargs):
        return None

    auth.get_current_active_user = _auth_stub
    auth.require_employer = _auth_stub
    auth.get_password_hash = lambda p: "hash"
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


def _install_payments_stubs(monkeypatch):
    stripe = types.ModuleType("stripe")
    stripe.api_key = None
    stripe.checkout = types.SimpleNamespace(Session=types.SimpleNamespace(retrieve=None))
    stripe.error = types.SimpleNamespace(StripeError=type("StripeError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "stripe", stripe)

    storage = types.ModuleType("storage")
    storage.put_object = lambda *a, **k: {"path": "x"}
    storage.APP_NAME = "joboolo"
    monkeypatch.setitem(sys.modules, "storage", storage)

    config = types.ModuleType("config")
    config.get_settings = lambda: types.SimpleNamespace(
        STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET="whsec_x"
    )
    monkeypatch.setitem(sys.modules, "config", config)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
def jobs_module(monkeypatch):
    _install_import_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location("routes_jobs_p0005_real", JOBS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def _no_low_balance(*args, **kwargs):
        return None

    module._check_low_balance = _no_low_balance
    module._HTTPException = _HTTPException
    return module


@pytest.fixture
def payments_module(monkeypatch):
    _install_import_stubs(monkeypatch)
    _install_payments_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location("routes_payments_p0005_real", PAYMENTS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._ensure_stripe = lambda: None
    module._HTTPException = _HTTPException
    return module


# --------------------------------------------------------------------------- #
# Topology helpers (synchronous wrappers for pytest.skip)                     #
# --------------------------------------------------------------------------- #
def _check_replica_set():
    """Return True if the replica-set URL is reachable and supports transactions."""
    async def _probe():
        client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
        try:
            await client.admin.command("ping")
            hello = await client.admin.command("hello")
            return hello.get("setName") is not None
        except Exception:
            return False
        finally:
            client.close()

    return asyncio.run(_probe())


def _check_standalone():
    """Return True if the standalone URL is reachable and does NOT support transactions."""
    async def _probe():
        client = AsyncIOMotorClient(STANDALONE_URL, serverSelectionTimeoutMS=3000)
        try:
            await client.admin.command("ping")
            hello = await client.admin.command("hello")
            return hello.get("setName") is None
        except Exception:
            return False
        finally:
            client.close()

    return asyncio.run(_probe())


# --------------------------------------------------------------------------- #
# User / job helpers                                                          #
# --------------------------------------------------------------------------- #
async def _seed_user(db, **extra):
    doc = {
        "_id": USER_ID, "email": EMAIL, "user_type": "employer",
        "premium_credits": 0, "granted_sessions": [],
        "hashed_password": "hash", "is_active": True,
    }
    doc.update(extra)
    await db.users.insert_one(doc)


async def _seed_company(db):
    await db.companies.insert_one({"_id": COMPANY_ID, "owner_id": USER_ID})


def _make_job_data(**over):
    data = {
        "title": "Dev Python", "description": "desc",
        "company_id": COMPANY_ID, "location": "Paris", "job_type": "CDI",
        "is_remote": False, "is_urgent": False, "requirements": [],
        "benefits": [], "tags": [], "salary_min": None, "salary_max": None,
        "salary_currency": "EUR", "is_premium": False,
    }
    data.update(over)
    return _Model(**data)


def _current_user():
    return _Model(id=USER_ID, user_type="employer", is_active=True, email=EMAIL)


async def _wire_jobs(jobs_module, db, client):
    async def _get_database():
        return db

    jobs_module.get_database = _get_database
    sys.modules["database"].get_client = lambda: client


async def _wire_payments(payments_module, db):
    async def _get_database():
        return db

    payments_module.get_database = _get_database


# --------------------------------------------------------------------------- #
# Replica-set tests: transactions (success / rollback / concurrency)          #
# --------------------------------------------------------------------------- #
class TestReplicaSetTransactions:
    def test_premium_create_success(self, jobs_module):
        if not _check_replica_set():
            pytest.skip("Replica-set MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p005_repl_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await _seed_user(db, premium_credits=1)
                await _seed_company(db)
                await _wire_jobs(jobs_module, db, client)

                job = await jobs_module.create_job(
                    _make_job_data(is_premium=True), _current_user()
                )
                assert job is not None

                user = await db.users.find_one({"_id": USER_ID})
                assert user["premium_credits"] == 0

                jobs = await db.jobs.find({}).to_list(10)
                assert len(jobs) == 1
                assert jobs[0]["is_premium"] is True
                assert jobs[0]["premium_granted_at"] is not None
            finally:
                await client.drop_database(db_name)
                client.close()

        asyncio.run(scenario())

    def test_premium_create_rollback_on_insert_failure(self, jobs_module):
        if not _check_replica_set():
            pytest.skip("Replica-set MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p005_repl_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await _seed_user(db, premium_credits=1)
                await _seed_company(db)
                await _wire_jobs(jobs_module, db, client)

                original_insert = db.jobs.insert_one

                async def failing_insert(document, session=None):
                    raise OSError("simulated insert failure")

                db.jobs.insert_one = failing_insert

                with pytest.raises(OSError):
                    await jobs_module.create_job(
                        _make_job_data(is_premium=True), _current_user()
                    )

                db.jobs.insert_one = original_insert

                user = await db.users.find_one({"_id": USER_ID})
                assert user["premium_credits"] == 1

                jobs = await db.jobs.find({}).to_list(10)
                assert len(jobs) == 0
            finally:
                await client.drop_database(db_name)
                client.close()

        asyncio.run(scenario())

    def test_premium_create_concurrent_one_succeeds(self, jobs_module):
        if not _check_replica_set():
            pytest.skip("Replica-set MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p005_repl_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await _seed_user(db, premium_credits=1)
                await _seed_company(db)
                await _wire_jobs(jobs_module, db, client)

                results = {"ok": 0, "fail": 0}

                async def call():
                    try:
                        await jobs_module.create_job(
                            _make_job_data(is_premium=True), _current_user()
                        )
                        results["ok"] += 1
                    except _HTTPException as e:
                        # Either 402 (insufficient credits after the winner
                        # committed) or 503-class failures are acceptable losers;
                        # the invariant is that only one job is created and the
                        # credit is never overspent.
                        assert e.status_code in (402, 503)
                        results["fail"] += 1
                    except Exception:
                        # A concurrent transaction writing the same user doc may
                        # abort on a MongoDB write conflict (transient error).
                        results["fail"] += 1

                await asyncio.gather(call(), call())

                assert results["ok"] == 1
                assert results["fail"] == 1

                user = await db.users.find_one({"_id": USER_ID})
                assert user["premium_credits"] == 0

                jobs = await db.jobs.find({}).to_list(10)
                assert len(jobs) == 1
                assert jobs[0]["is_premium"] is True
            finally:
                await client.drop_database(db_name)
                client.close()

        asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Standalone test: 503 + zero writes                                         #
# --------------------------------------------------------------------------- #
class TestStandaloneClosed:
    def test_premium_standalone_503_zero_writes(self, jobs_module):
        if not _check_standalone():
            pytest.skip("Standalone MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(STANDALONE_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p005_standalone_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await _seed_user(db, premium_credits=1)
                await _seed_company(db)
                await _wire_jobs(jobs_module, db, client)

                with pytest.raises(_HTTPException) as exc:
                    await jobs_module.create_job(
                        _make_job_data(is_premium=True), _current_user()
                    )

                assert exc.value.status_code == 503
                assert "transaction" in (exc.value.detail or "").lower()

                user = await db.users.find_one({"_id": USER_ID})
                assert user["premium_credits"] == 1

                jobs = await db.jobs.find({}).to_list(10)
                assert len(jobs) == 0
            finally:
                await client.drop_database(db_name)
                client.close()

        asyncio.run(scenario())


# --------------------------------------------------------------------------- #
# Concurrent Stripe grant with real Mongo: single receipt                     #
# --------------------------------------------------------------------------- #
class TestConcurrentStripeGrant:
    def test_concurrent_credit_if_paid_single_receipt(self, payments_module):
        if not _check_replica_set():
            pytest.skip("Replica-set MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p005_stripe_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.users.insert_one({
                    "_id": USER_ID, "email": EMAIL, "user_type": "employer",
                    "premium_credits": 0, "granted_sessions": [],
                    "hashed_password": "hash", "is_active": True,
                })
                await db.payment_transactions.insert_one({
                    "_id": "cs_concurrent", "session_id": "cs_concurrent",
                    "user_id": USER_ID, "kind": "recruiter_pack",
                    "postings": 7, "payment_status": "paid", "credited": False,
                })

                await _wire_payments(payments_module, db)

                receipt_counter = {"calls": 0}

                async def counting_receipt(db_arg, record):
                    receipt_counter["calls"] += 1

                original_receipt = payments_module._send_recruiter_receipt
                payments_module._send_recruiter_receipt = counting_receipt

                try:
                    r1, r2 = await asyncio.gather(
                        payments_module._credit_if_paid(db, "cs_concurrent"),
                        payments_module._credit_if_paid(db, "cs_concurrent"),
                    )
                finally:
                    payments_module._send_recruiter_receipt = original_receipt

                assert r1["credited"] is True
                assert r2["credited"] is True

                user = await db.users.find_one({"_id": USER_ID})
                assert user["premium_credits"] == 7
                assert user["granted_sessions"].count("cs_concurrent") == 1

                tx = await db.payment_transactions.find_one(
                    {"session_id": "cs_concurrent"}
                )
                assert tx["credited"] is True

                assert receipt_counter["calls"] == 1
            finally:
                await client.drop_database(db_name)
                client.close()

        asyncio.run(scenario())
