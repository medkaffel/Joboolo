"""P0-006 : test déterministe de la composition de requête d'alerte.

Régression : `_build_job_query` doit composer ses critères (dont le `$or` de
`search`) via `$and` SANS JAMAIS écraser le filtre de visibilité public
(`$or` de campagne). Sinon une alerte avec `search` ré-exposerait les offres
de campagnes non diffusibles.

Nécessite aucun service externe ni Mongo : on stube les dépendances
d'import de scheduler.py puis on exerce `_build_job_query` (fonction pure).
"""
import importlib.util
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    # scheduler.py importe `config` (module local du backend) : nécessite le
    # backend sur le path même quand pytest est lancé depuis un autre cwd.
    sys.path.insert(0, str(BACKEND_DIR))


def _install_scheduler_stubs(monkeypatch):
    database = types.ModuleType("database")
    database.get_database = lambda: None
    monkeypatch.setitem(sys.modules, "database", database)

    email_service = types.ModuleType("email_service")

    async def _send(*a, **k):
        return True

    email_service.send_alert_email = _send
    email_service.build_alert_html = lambda *a, **k: "<html>"
    monkeypatch.setitem(sys.modules, "email_service", email_service)

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


@pytest.fixture
def scheduler(monkeypatch):
    _install_scheduler_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location(
        "p006_sched_query", BACKEND_DIR / "scheduler.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _public_filter():
    return {
        "is_active": True,
        "expires_at": {"$not": {"$lte": "ts"}},
        "$or": [
            {"campaign_id": {"$in": ["ok1"]}},
            {"campaign_id": {"$exists": False}},
            {"campaign_id": None},
        ],
    }


def _alert(**kw):
    d = {"search": None, "location": None, "job_type": None,
         "is_remote": None, "salary_min": None}
    d.update(kw)
    return d


def test_search_or_preserves_public_or(scheduler):
    since = datetime.utcnow() - timedelta(days=1)
    pf = _public_filter()
    query = scheduler._build_job_query(_alert(search="Node"), since, pf)

    # le $or public de visibilité est conservé tel quel
    assert query["$or"] == pf["$or"]
    # le $or de search est composé via $and, pas écrasé
    assert "$and" in query
    search_or = [c for c in query["$and"] if "$or" in c and "title" in c["$or"][0]]
    assert len(search_or) == 1
    assert search_or[0]["$or"][0]["title"] == {"$regex": "Node", "$options": "i"}
    # la visibilité et le search doivent tous deux s'appliquer
    assert query["is_active"] is True
    assert "created_at" in query


def test_without_search_no_and_but_public_or_preserved(scheduler):
    since = datetime.utcnow() - timedelta(days=1)
    pf = _public_filter()
    query = scheduler._build_job_query(_alert(), since, pf)
    assert query["$or"] == pf["$or"]
    assert "$and" not in query


def test_other_filters_kept(scheduler):
    since = datetime.utcnow() - timedelta(days=1)
    query = scheduler._build_job_query(
        _alert(search="Dev", location="Paris", job_type="CDI",
               is_remote=True, salary_min=30000),
        since, _public_filter())
    assert query["location"] == {"$regex": "Paris", "$options": "i"}
    assert query["job_type"] == "CDI"
    assert query["is_remote"] is True
    assert query["salary_min"] == {"$gte": 30000}
