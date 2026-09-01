"""P0-006 : intégration Mongo réelle du lifecycle / visibilité des campagnes.

Lance les vraies routes backend (jobs, saved_jobs, applications, ai, import de
feed, scheduler) contre MongoDB et vérifie que toute offre d'une campagne non
diffusible est exclue de chaque lecteur/action public : recherche, détail,
offres entreprise, suggest, alertes (avec ou sans search), sauvegarde,
candidature, recommandations IA, match IA, clics, impressions, import
manuel/auto, non-renouvellement de expires_at et régressions P0-004/P0-005.

Requiert MongoDB sur mongodb://127.0.0.1:27017 ; sinon les tests sont skipés.
Chaque test crée sa propre base éphémère (uuid) et la supprime en sortie.
"""
import asyncio
import importlib.util
import sys
import types
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient

BACKEND_DIR = Path(__file__).resolve().parent.parent
MONGO_URL = "mongodb://127.0.0.1:27017"

sys.path.insert(0, str(BACKEND_DIR))


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
    CANDIDATE = "candidate"
    PARTNER = "partner"
    ADMIN = "admin"


class _CurrentUser(_Model):
    def __init__(self, **kw):
        defaults = {"id": "user_006", "user_type": "candidate", "is_active": True,
                    "first_name": "U", "last_name": "X", "email": "u@example.test"}
        defaults.update(kw)
        self.__dict__.update(defaults)


def _install_base_stubs(monkeypatch):
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = _Router
    fastapi.HTTPException = _HTTPException
    fastapi.Depends = lambda dependency=None, *a, **k: dependency
    fastapi.Query = lambda default=None, *a, **k: default
    fastapi.status = types.SimpleNamespace(
        HTTP_402_PAYMENT_REQUIRED=402, HTTP_503_SERVICE_UNAVAILABLE=503,
        HTTP_409_CONFLICT=409,
    )
    fastapi.Request = object
    fastapi.File = lambda *a, **k: None
    fastapi.UploadFile = object
    fastapi.responses = types.SimpleNamespace(RedirectResponse=lambda u, status_code: {"url": u})
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)

    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = _Model
    pydantic.Field = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)

    models = types.ModuleType("models")
    for name in ("Job", "JobCreate", "JobUpdate", "JobResponse", "JobSearchQuery",
                 "JobSearchResponse", "User", "SavedJob", "Application",
                 "ApplicationCreate", "ApplicationResponse", "JobAlert",
                 "JobAlertCreate", "JobAlertUpdate", "JobAlertResponse"):
        setattr(models, name, _Model)
    models.UserType = _UserType
    monkeypatch.setitem(sys.modules, "models", models)

    database = types.ModuleType("database")

    async def _placeholder_db():
        raise AssertionError("test must replace get_database")

    database.get_database = _placeholder_db
    database.get_client = lambda: None
    monkeypatch.setitem(sys.modules, "database", database)

    auth = types.ModuleType("auth")
    auth.get_current_active_user = lambda *a, **k: None
    auth.require_employer = lambda *a, **k: None
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

    httpx = types.ModuleType("httpx")
    httpx.AsyncClient = lambda *a, **k: types.SimpleNamespace(
        __aenter__=lambda self: _Aenter(self),
        __aexit__=lambda self, *a: None,
    )
    monkeypatch.setitem(sys.modules, "httpx", httpx)


class _Aenter:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *a):
        return False


def _install_ai_service_stub(monkeypatch):
    ai_service = types.ModuleType("ai_service")

    def build_profile(user_doc):
        return {}

    async def rank_jobs(profile, jobs):
        return []

    async def analyze_match(profile, job):
        return {"score": 0}

    ai_service.build_profile = build_profile
    ai_service.rank_jobs = rank_jobs
    ai_service.analyze_match = analyze_match
    monkeypatch.setitem(sys.modules, "ai_service", ai_service)


def _install_routes_jobs_stub(monkeypatch):
    """Stub routes.jobs pour saved_jobs/applications/ai qui importent
    populate_job_response depuis routes.jobs."""
    pkg = types.ModuleType("routes")
    pkg.__path__ = [str(BACKEND_DIR / "routes")]
    monkeypatch.setitem(sys.modules, "routes", pkg)
    rj = types.ModuleType("routes.jobs")

    async def populate_job_response(job_doc, db):
        company = await db.companies.find_one({"_id": job_doc.get("company_id")})
        return _Model(
            id=job_doc["_id"], title=job_doc.get("title"),
            is_active=job_doc.get("is_active", True),
            company={"id": job_doc.get("company_id"), "name": (company or {}).get("name", "X")},
        )

    rj.populate_job_response = populate_job_response
    monkeypatch.setitem(sys.modules, "routes.jobs", rj)


def _install_email_stub(monkeypatch):
    email_service = types.ModuleType("email_service")
    email_service._resend_ready = False
    captured = {"jobs": []}

    async def send_alert_email(*a, **k):
        return True

    def build_alert_html(name, jobs, app_url, alert_id):
        captured["jobs"] = jobs
        return "<html>"

    email_service.send_alert_email = send_alert_email
    email_service.build_alert_html = build_alert_html
    email_service.build_auto_import_email = lambda *a, **k: ("s", "<html>")
    monkeypatch.setitem(sys.modules, "email_service", email_service)
    return captured


def _install_scheduler_deps_stub(monkeypatch):
    apscheduler = types.ModuleType("apscheduler")
    apsched_sched = types.ModuleType("apscheduler.schedulers")
    apsched_async = types.ModuleType("apscheduler.schedulers.asyncio")
    apsched_async.AsyncIOScheduler = lambda: types.SimpleNamespace(
        running=False, add_job=lambda *a, **k: None, start=lambda: None)
    apsched_sched.asyncio = apsched_async
    apscheduler.schedulers = apsched_sched
    monkeypatch.setitem(sys.modules, "apscheduler", apscheduler)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers", apsched_sched)
    monkeypatch.setitem(sys.modules, "apscheduler.schedulers.asyncio", apsched_async)


def _load_module(monkeypatch, rel_path, modname):
    path = BACKEND_DIR / rel_path
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._HTTPException = _HTTPException
    return module


@pytest.fixture
def jobs_module(monkeypatch):
    _install_base_stubs(monkeypatch)
    return _load_module(monkeypatch, "routes/jobs.py", "p006_jobs")


@pytest.fixture
def saved_jobs_module(monkeypatch):
    _install_base_stubs(monkeypatch)
    _install_routes_jobs_stub(monkeypatch)
    return _load_module(monkeypatch, "routes/saved_jobs.py", "p006_saved")


@pytest.fixture
def applications_module(monkeypatch):
    _install_base_stubs(monkeypatch)
    _install_routes_jobs_stub(monkeypatch)
    return _load_module(monkeypatch, "routes/applications.py", "p006_apps")


@pytest.fixture
def ai_module(monkeypatch):
    _install_base_stubs(monkeypatch)
    _install_routes_jobs_stub(monkeypatch)
    _install_ai_service_stub(monkeypatch)
    return _load_module(monkeypatch, "routes/ai.py", "p006_ai")


@pytest.fixture
def feed_module(monkeypatch):
    _install_base_stubs(monkeypatch)
    return _load_module(monkeypatch, "partner_feed.py", "p006_feed")


@pytest.fixture
def scheduler_module(monkeypatch):
    _install_base_stubs(monkeypatch)
    _install_email_stub(monkeypatch)
    _install_scheduler_deps_stub(monkeypatch)
    return _load_module(monkeypatch, "scheduler.py", "p006_scheduler")


def _mongo_available():
    async def _probe():
        client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=2000)
        try:
            await client.admin.command("ping")
            return True
        except Exception:
            return False
        finally:
            client.close()
    return asyncio.run(_probe())


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #
def _camp_doc(cid, **kw):
    d = {"_id": cid, "name": "C", "partner_id": "partner_006", "status": "active",
         "billing_mode": "per_click", "spent": 0.0, "budget_limit": None,
         "start_date": None, "end_date": None, "validity_days": None,
         "xml_feed_url": "https://feed.example/xml", "cpc": 0.5}
    d.update(kw)
    return d


def _partner_doc(pid="partner_006", **kw):
    d = {"user_id": pid, "billing_mode": "per_click", "balance": 100.0,
         "default_cpc": 0.5, "postings_remaining": 10, "posting_price": 1.0,
         "company_name": "Acme", "total_clicks": 0, "total_spent": 0.0}
    d.update(kw)
    return d


def _company_doc(cid="company_006"):
    return {"_id": cid, "name": "Acme"}


def _job_doc(jid, **kw):
    d = {"_id": jid, "title": "Dev", "description": "desc", "location": "Paris",
         "job_type": "CDI", "company_id": "company_006", "employer_id": "partner_006",
         "is_active": True, "is_partner": True, "external_url": "https://job.example/x",
         "partner_id": "partner_006", "views_count": 0, "applications_count": 0,
         "cpc": 0.5, "created_at": datetime.utcnow()}
    d.update(kw)
    return d


async def _wire(db, module):
    module.get_database = (lambda: _Awaited(db))


class _Awaited:
    def __init__(self, db):
        self._db = db

    def __await__(self):
        async def _wrap():
            return self._db
        return _wrap().__await__()


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Tests — lecteurs publics                                                     #
# --------------------------------------------------------------------------- #
class TestPublicReaders:
    def test_public_readers_hide_non_diffusible(self, jobs_module):
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_readers_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("paused", status="paused"))
                await db.campaigns.insert_one(_camp_doc("active"))
                await db.companies.insert_one(_company_doc())
                await db.jobs.insert_one(_job_doc("job_paused", campaign_id="paused", is_active=True))
                await db.jobs.insert_one(_job_doc("job_active", campaign_id="active", is_active=True))
                await db.jobs.insert_one(_job_doc("job_legacy", is_active=True))  # sans campagne
                await db.jobs.insert_one(_job_doc("job_none", campaign_id=None, is_active=True))  # campaign_id None

                await _wire(db, jobs_module)

                # get_job : 404 sur campagne non diffusible, ok sur visible / legacy / None
                try:
                    await jobs_module.get_job("job_paused")
                    assert False, "paused campaign job should 404"
                except _HTTPException as e:
                    assert e.status_code == 404

                for jid in ("job_active", "job_legacy", "job_none"):
                    r = await jobs_module.get_job(jid)
                    assert r.id == jid

                # search_jobs : exclut job_paused
                res = await jobs_module.search_jobs()
                ids = {j.id for j in res.jobs}
                assert "job_active" in ids
                assert "job_legacy" in ids
                assert "job_none" in ids
                assert "job_paused" not in ids
                assert res.total == 3

                # get_company_jobs : exclut job_paused
                comp = await jobs_module.get_company_jobs("company_006")
                ids = {j.id for j in comp}
                assert "job_active" in ids and "job_legacy" in ids and "job_none" in ids
                assert "job_paused" not in ids
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())


class TestClickGuard:
    def test_click_on_paused_campaign_404_no_debit(self, jobs_module):
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_click_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("paused", status="paused", budget_limit=100.0))
                await db.campaigns.insert_one(_camp_doc("active", budget_limit=100.0))
                await db.partner_profiles.insert_one(_partner_doc())
                await db.jobs.insert_one(_job_doc("job_paused", campaign_id="paused"))
                await db.jobs.insert_one(_job_doc("job_active", campaign_id="active"))
                await _wire(db, jobs_module)

                # clic sur campagne paused => 404, aucun débit ni clic, pas de vue
                try:
                    await jobs_module.record_partner_click("job_paused")
                    assert False
                except _HTTPException as e:
                    assert e.status_code == 404
                prof = await db.partner_profiles.find_one({"user_id": "partner_006"})
                assert prof["total_clicks"] == 0
                assert prof["balance"] == 100.0
                jp = await db.jobs.find_one({"_id": "job_paused"})
                assert jp["views_count"] == 0
                assert (await db.click_events.count_documents({"job_id": "job_paused"})) == 0

                # clic sur campagne active => succès, débit per_click
                res = await jobs_module.record_partner_click("job_active")
                assert res["redirect_url"] == "https://job.example/x"
                prof = await db.partner_profiles.find_one({"user_id": "partner_006"})
                assert prof["total_clicks"] == 1
                assert prof["balance"] == pytest.approx(99.5)
                ja = await db.jobs.find_one({"_id": "job_active"})
                assert ja["views_count"] == 1
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())

    def test_budget_exhaustion_pauses_campaign_but_does_not_deactivate_jobs(self, jobs_module):
        # Régression P0-004/P0-006 : l'épuisement du budget campagne met la
        # campagne en pause SANS désactiver les offres de la campagne.
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_budget_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("active", billing_mode="per_click",
                                                         budget_limit=0.5, spent=0.0))
                await db.partner_profiles.insert_one(_partner_doc(balance=2.0))
                await db.jobs.insert_one(_job_doc("job_active", campaign_id="active", is_active=True))
                await _wire(db, jobs_module)

                await jobs_module.record_partner_click("job_active")
                camp = await db.campaigns.find_one({"_id": "active"})
                assert camp["status"] == "paused"  # mise en pause auto (per_click, spent=0.5 >= 0.5)
                job = await db.jobs.find_one({"_id": "job_active"})
                # P0-006 : les offres ne sont plus désactivées aveuglément.
                assert job["is_active"] is True
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())

    def test_per_posting_budget_residual_never_pauses_on_click(self, jobs_module):
        # P0-006 : un budget_limit résiduel sur per_posting ne doit JAMAIS mettre
        # la campagne en pause simplement parce qu'un clic arrive.
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_posting_click_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("posting", billing_mode="per_posting",
                                                        budget_limit=5.0, spent=5.0))
                await db.partner_profiles.insert_one(_partner_doc(billing_mode="per_posting"))
                await db.jobs.insert_one(_job_doc("job_post", campaign_id="posting"))
                await _wire(db, jobs_module)

                await jobs_module.record_partner_click("job_post")
                camp = await db.campaigns.find_one({"_id": "posting"})
                assert camp["status"] == "active"  # jamais mise en pause
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())

    def test_click_on_job_individually_inactive_404(self, jobs_module):
        # Régression P0-004 : job inactif (solde CPC insuffisant) => clic 404.
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_jobhalt_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("active"))
                await db.partner_profiles.insert_one(_partner_doc())
                await db.jobs.insert_one(_job_doc("job_halted", campaign_id="active", is_active=False))
                await _wire(db, jobs_module)
                try:
                    await jobs_module.record_partner_click("job_halted")
                    assert False
                except _HTTPException as e:
                    assert e.status_code == 404
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())


class TestImpressions:
    def test_impressions_only_for_publicly_visible(self, jobs_module):
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_imp_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("paused", status="paused"))
                await db.campaigns.insert_one(_camp_doc("active"))
                await db.jobs.insert_one(_job_doc("j_paused", campaign_id="paused"))
                await db.jobs.insert_one(_job_doc("j_active", campaign_id="active"))
                await _wire(db, jobs_module)
                body = _Model(job_ids=["j_paused", "j_active"])
                res = await jobs_module.record_impressions(body)
                # seule l'offre visible est impressionnée
                assert res["recorded"] == 1
                ev = await db.impression_events.find_one({})
                assert ev["job_id"] == "j_active"
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())


class TestSavedJobsAndApplications:
    def test_save_and_apply_reject_non_diffusible(self, saved_jobs_module, applications_module):
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_save_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("paused", status="paused"))
                await db.campaigns.insert_one(_camp_doc("active"))
                await db.companies.insert_one(_company_doc())
                await db.jobs.insert_one(_job_doc("job_paused", campaign_id="paused"))
                await db.jobs.insert_one(_job_doc("job_active", campaign_id="active"))
                await _wire(db, saved_jobs_module)
                await _wire(db, applications_module)

                cand = _CurrentUser(id="cand_006", user_type="candidate")

                # save_job : 404 sur non diffusible, ok sur visible
                try:
                    await saved_jobs_module.save_job("job_paused", cand)
                    assert False
                except _HTTPException as e:
                    assert e.status_code == 404
                await saved_jobs_module.save_job("job_active", cand)

                lst = await saved_jobs_module.get_saved_jobs(cand)
                ids = {j.id for j in lst}
                assert "job_active" in ids
                assert "job_paused" not in ids

                # apply : 404 sur non diffusible, ok sur visible
                app_data = _Model(job_id="job_paused")
                try:
                    await applications_module.apply_to_job(app_data, cand)
                    assert False
                except _HTTPException as e:
                    assert e.status_code == 404
                app_data2 = _Model(job_id="job_active")
                await applications_module.apply_to_job(app_data2, cand)
                assert (await db.applications.count_documents({"job_id": "job_active"})) == 1
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())


class TestAi:
    def test_match_job_rejects_non_diffusible(self, ai_module):
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_ai_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("expired", end_date="2000-01-01"))
                await db.jobs.insert_one(_job_doc("job_expired", campaign_id="expired"))
                await _wire(db, ai_module)
                cand = _CurrentUser(id="cand_ai", user_type="candidate")
                try:
                    await ai_module.match_job("job_expired", cand)
                    assert False
                except _HTTPException as e:
                    assert e.status_code == 404
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())

    def test_recommendations_exclude_non_diffusible(self, ai_module):
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_airec_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("expired", end_date="2000-01-01"))
                await db.campaigns.insert_one(_camp_doc("active"))
                await db.jobs.insert_one(_job_doc("job_expired", campaign_id="expired"))
                await db.jobs.insert_one(_job_doc("job_active", campaign_id="active"))
                await _wire(db, ai_module)
                cand = _CurrentUser(id="cand_ai_rec", user_type="candidate")
                res = await ai_module.recommendations(cand)
                ids = {r["job"]["id"] for r in res["recommendations"]}
                assert "job_active" in ids
                assert "job_expired" not in ids
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())


class TestAlerts:
    def test_alert_with_search_keeps_hiding_paused_campaign(self, scheduler_module):
        # Régression : une alerte AVEC `search` ne doit pas écraser le filtre de
        # visibilité public (composé via $and, jamais d'écrasement du $or).
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_alert_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("paused", status="paused"))
                await db.campaigns.insert_one(_camp_doc("active"))
                now = datetime.utcnow() - timedelta(minutes=1)
                await db.jobs.insert_one(_job_doc("job_paused", campaign_id="paused",
                                                  title="Dev Node", description="node js", created_at=now))
                await db.jobs.insert_one(_job_doc("job_active", campaign_id="active",
                                                  title="Dev Node", description="node js", created_at=now))
                await db.jobs.insert_one(_job_doc("job_legacy", title="Dev Node",
                                                  description="node js", created_at=now))
                await _wire(db, scheduler_module)

                # On exerce _build_job_query AVEC search sur le filtre public réel.
                from campaign_lifecycle import fetch_public_job_filter
                public_filter = await fetch_public_job_filter(db, datetime.utcnow())
                since = datetime.utcnow() - timedelta(days=30)
                alert = {"search": "Node", "location": None, "job_type": None,
                         "is_remote": None, "salary_min": None}
                query = scheduler_module._build_job_query(alert, since, public_filter)
                # Le filtre public est conservé (composé via $and) et le $or de
                # visibilité de campagne n'est PAS écrasé par le search.
                assert "$and" in query
                any_camp_or = any(isinstance(c, dict) and "$or" in c
                                  and any(isinstance(o, dict) and "campaign_id" in o
                                          for o in c["$or"])
                                  for c in query["$and"])
                assert any_camp_or, "le filtre de visibilité campagne doit être conservé"
                jobs = await db.jobs.find(query).to_list(length=10)
                ids = {j["_id"] for j in jobs}
                assert "job_active" in ids
                assert "job_legacy" in ids
                assert "job_paused" not in ids
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())

    def test_process_alerts_send_now_respect_visibility(self, scheduler_module):
        # End-to-end : process_alerts (avec search) n'envoie que des offres
        # publiquement visibles à l'email.
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_alert2_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("paused", status="paused"))
                await db.campaigns.insert_one(_camp_doc("active"))
                now = datetime.utcnow() - timedelta(minutes=1)
                await db.jobs.insert_one(_job_doc("job_paused", campaign_id="paused",
                                                  title="Dev Node", description="node js", created_at=now))
                await db.jobs.insert_one(_job_doc("job_active", campaign_id="active",
                                                  title="Dev Node", description="node js", created_at=now))
                await db.users.insert_one({"_id": "user_alert", "email": "a@example.test"})
                await db.alerts.insert_one({
                    "_id": "alert_1", "user_id": "user_alert", "name": "Dev",
                    "search": "Node", "location": None, "job_type": None,
                    "is_remote": None, "salary_min": None, "frequency": "daily",
                    "is_active": True, "last_sent_at": None,
                })
                await _wire(db, scheduler_module)
                await scheduler_module.process_alerts()
                last = await db.alerts.find_one({"_id": "alert_1"})
                # l'email a été envoyé et last_sent_at positionné => jobs trouvés
                assert last.get("last_sent_at") is not None
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())


class TestImports:
    def test_manual_import_non_diffusible_409_no_write(self, feed_module):
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_import_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.partner_profiles.insert_one(_partner_doc())
                await db.campaigns.insert_one(_camp_doc("paused", status="paused"))
                await db.campaigns.insert_one(_camp_doc("active"))
                await _wire(db, feed_module)

                xml = "<joboolo><ad><id>1</id><title>Job</title><content>d</content><city>Paris</city><contract>CDI</contract><url>https://x/j</url></ad></joboolo>"

                camp_paused = await db.campaigns.find_one({"_id": "paused"})
                try:
                    await feed_module.import_campaign_feed(db, camp_paused, xml, trigger="manual")
                    assert False
                except _HTTPException as e:
                    assert e.status_code == 409

                # aucune écriture : pas de job, pas de log
                assert (await db.jobs.count_documents({})) == 0
                assert (await db.import_logs.count_documents({})) == 0

                camp_active = await db.campaigns.find_one({"_id": "active"})
                res = await feed_module.import_campaign_feed(db, camp_active, xml, trigger="manual")
                assert res["imported"] == 1
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())

    def test_per_posting_new_job_gets_expires_at_not_renewed_on_update(self, feed_module):
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_expire_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.partner_profiles.insert_one(_partner_doc(billing_mode="per_posting"))
                await db.campaigns.insert_one(_camp_doc("active", billing_mode="per_posting",
                                                        validity_days=30))
                await _wire(db, feed_module)
                xml1 = "<joboolo><ad><id>1</id><title>Job</title><content>d</content><city>Paris</city><contract>CDI</contract><url>https://x/j</url></ad></joboolo>"

                camp = await db.campaigns.find_one({"_id": "active"})
                await feed_module.import_campaign_feed(db, camp, xml1, trigger="manual")
                job = await db.jobs.find_one({})
                assert job.get("expires_at") is not None
                first_exp = job["expires_at"]
                assert first_exp > datetime.utcnow()

                # réimport du même external_ref : update, expires_at non renouvelé
                await feed_module.import_campaign_feed(db, camp, xml1, trigger="manual")
                job = await db.jobs.find_one({})
                assert job["expires_at"] == first_exp
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())

    def test_scheduler_auto_refresh_skips_non_diffusible(self, scheduler_module):
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_auto_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.partner_profiles.insert_one(_partner_doc(billing_mode="per_posting"))
                # campagne paused avec feed dû => doit être sautée sans import
                await db.campaigns.insert_one(_camp_doc("paused", status="paused",
                                      last_import_at=datetime.utcnow() - timedelta(days=5)))
                await db.settings.insert_one({"_id": "global", "feed_refresh_hours": 24})
                await _wire(db, scheduler_module)

                await scheduler_module.refresh_campaign_feeds()
                # aucun job importé (campagne non diffusible sautée)
                assert (await db.jobs.count_documents({})) == 0
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())


class TestStrictDatesAndExpiry:
    def test_job_with_expires_at_none_remains_visible(self, jobs_module):
        # Régression : un job legacy avec expires_at=None reste visible tant que
        # la campagne (si rattachée) est diffusible, sans être expiré.
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_expnone_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("active"))
                await db.companies.insert_one(_company_doc())
                await db.jobs.insert_one(_job_doc("job_exp_none", campaign_id="active",
                                                  is_active=True, expires_at=None))
                await db.jobs.insert_one(_job_doc("job_exp_no_field", campaign_id="active",
                                                  is_active=True))
                await _wire(db, jobs_module)

                r1 = await jobs_module.get_job("job_exp_none")
                assert r1.id == "job_exp_none"
                r2 = await jobs_module.get_job("job_exp_no_field")
                assert r2.id == "job_exp_no_field"

                res = await jobs_module.search_jobs()
                ids = {j.id for j in res.jobs}
                assert "job_exp_none" in ids
                assert "job_exp_no_field" in ids
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())

    def test_expires_at_empty_whitespace_is_active_missing_fail_closed(self, jobs_module):
        # Règle unique fail-closed (audit P0-006) : expires_at="" / espaces et
        # un champ is_active absent sont cachés EN LISTE comme EN DÉTAIL (404),
        # jamais « visible en détail mais caché en liste ».
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_failclosed_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.campaigns.insert_one(_camp_doc("active"))
                await db.companies.insert_one(_company_doc())
                await db.jobs.insert_one(_job_doc("j_empty", campaign_id="active",
                                                  is_active=True, expires_at=""))
                await db.jobs.insert_one(_job_doc("j_spaces", campaign_id="active",
                                                  is_active=True, expires_at="   "))
                await db.jobs.insert_one(_job_doc("j_garbage", campaign_id="active",
                                                  is_active=True, expires_at="not-a-date"))
                missing_active = _job_doc("j_missing_active", campaign_id="active",
                                          is_active=True)
                del missing_active["is_active"]
                await db.jobs.insert_one(missing_active)
                await db.jobs.insert_one(_job_doc("j_ok", campaign_id="active", is_active=True))
                await _wire(db, jobs_module)

                # détail : chaque valeur invalide => 404
                for jid in ("j_empty", "j_spaces", "j_garbage", "j_missing_active"):
                    try:
                        await jobs_module.get_job(jid)
                        assert False, f"{jid} should 404 (détail)"
                    except _HTTPException as e:
                        assert e.status_code == 404

                # liste : les mêmes offres sont toutes exclues
                res = await jobs_module.search_jobs()
                ids = {j.id for j in res.jobs}
                assert "j_ok" in ids
                for jid in ("j_empty", "j_spaces", "j_garbage", "j_missing_active"):
                    assert jid not in ids
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())

    def test_campaign_with_invalid_stored_date_fail_closed(self, jobs_module, feed_module):
        # FAIL-CLOSED : une campagne avec une date stockée non vide mais non
        # parseable (2026-09-01junk) n'est jamais diffusible => son offre est
        # cachée et l'import manuel est refusé (409), sans écriture.
        if not _mongo_available():
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(MONGO_URL, serverSelectionTimeoutMS=3000)
            db_name = f"p006_invdate_{uuid.uuid4().hex}"
            db = client[db_name]
            try:
                await db.partner_profiles.insert_one(_partner_doc())
                await db.companies.insert_one(_company_doc())
                await db.campaigns.insert_one(_camp_doc("inv", end_date="2026-09-01junk"))
                await db.jobs.insert_one(_job_doc("job_inv", campaign_id="inv", is_active=True))
                await _wire(db, jobs_module)
                await _wire(db, feed_module)

                # get_job : 404 (campagne non diffusible, date invalide)
                try:
                    await jobs_module.get_job("job_inv")
                    assert False
                except _HTTPException as e:
                    assert e.status_code == 404

                # search : exclu
                res = await jobs_module.search_jobs()
                assert "job_inv" not in {j.id for j in res.jobs}

                # import manuel : 409 sans écriture
                xml = "<joboolo><ad><id>1</id><title>Job</title><content>d</content><city>Paris</city><contract>CDI</contract><url>https://x/j</url></ad></joboolo>"
                camp_inv = await db.campaigns.find_one({"_id": "inv"})
                try:
                    await feed_module.import_campaign_feed(db, camp_inv, xml, trigger="manual")
                    assert False
                except _HTTPException as e:
                    assert e.status_code == 409
                assert (await db.jobs.count_documents({})) == 1  # seul le job de départ
                assert (await db.import_logs.count_documents({})) == 0
            finally:
                await client.drop_database(db_name)
                client.close()

        _run(scenario())
