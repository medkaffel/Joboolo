"""Real-Mongo integration tests for P0-004 atomic CPC debit.

These tests run the actual record_partner_click route against MongoDB and verify
that concurrent requests cannot overspend the partner balance. They require a
MongoDB server on mongodb://127.0.0.1:27017 and the motor package.
"""

import asyncio
import importlib.util
import sys
import types
import uuid
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
JOBS_PATH = BACKEND_DIR / "routes" / "jobs.py"
MONGO_URL = "mongodb://127.0.0.1:27017"
PARTNER_ID = "partner_real"
JOB_ID = "job_real"


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
    spec = importlib.util.spec_from_file_location("routes_jobs_p0004_real_mongo", JOBS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def _no_low_balance(*args, **kwargs):
        return None

    module._check_low_balance = _no_low_balance
    module._HTTPException = _HTTPException
    return module


def _run_real_mongo_case(jobs_module, *, balance, cpc, requests, expected_charged):
    async def scenario():
        client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
        db_name = f"joboolo_p0004_{uuid.uuid4().hex}"
        db = client[db_name]
        try:
            await client.admin.command("ping")
            await db.partner_profiles.insert_one({
                "user_id": PARTNER_ID,
                "billing_mode": "per_click",
                "balance": balance,
                "default_cpc": cpc,
                "total_clicks": 0,
                "total_spent": 0.0,
            })
            await db.jobs.insert_one({
                "_id": JOB_ID,
                "partner_id": PARTNER_ID,
                "is_partner": True,
                "external_url": "https://example.test/job",
                "title": "Real Mongo partner job",
                "cpc": cpc,
                "is_active": True,
                "views_count": 0,
            })

            async def _get_database():
                return db

            jobs_module.get_database = _get_database

            responses = await asyncio.gather(
                *(jobs_module.record_partner_click(JOB_ID) for _ in range(requests))
            )
            assert all(r == {"redirect_url": "https://example.test/job"} for r in responses)

            profile = await db.partner_profiles.find_one({"user_id": PARTNER_ID})
            events = await db.click_events.find({"partner_id": PARTNER_ID}).to_list(length=requests + 5)
            job = await db.jobs.find_one({"_id": JOB_ID})

            assert profile["balance"] == pytest.approx(balance - expected_charged * cpc)
            assert profile["balance"] >= -1e-12
            assert profile["total_spent"] == pytest.approx(expected_charged * cpc)
            assert profile["total_clicks"] == requests
            assert len(events) == requests
            assert job["views_count"] == requests

            paid = [event for event in events if float(event["cost"]) > 0]
            free = [event for event in events if float(event["cost"]) == 0]
            assert len(paid) == expected_charged
            assert len(free) == requests - expected_charged
            assert all(float(event["cost"]) == pytest.approx(cpc) for event in paid)
        finally:
            await client.drop_database(db_name)
            client.close()

    asyncio.run(scenario())


def test_real_mongo_two_concurrent_clicks_charge_once(jobs_module):
    _run_real_mongo_case(
        jobs_module,
        balance=0.5,
        cpc=0.5,
        requests=2,
        expected_charged=1,
    )


def test_real_mongo_twenty_concurrent_clicks_charge_exact_budget(jobs_module):
    _run_real_mongo_case(
        jobs_module,
        balance=1.0,
        cpc=0.5,
        requests=20,
        expected_charged=2,
    )


def test_real_mongo_hundred_concurrent_clicks_never_go_negative(jobs_module):
    _run_real_mongo_case(
        jobs_module,
        balance=5.0,
        cpc=0.5,
        requests=100,
        expected_charged=10,
    )
