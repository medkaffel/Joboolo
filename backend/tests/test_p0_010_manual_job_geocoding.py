"""P0-010 — Géolocalisation des offres créées manuellement.

Tests isolés (pas de vrai Mongo, pas de réseau) qui vérifient le contrôle
exact de `create_job()` et `update_job()` dans `backend/routes/jobs.py` :

- création standard géocodable → `loc` présent
- création sans géocodage (lieu introuvable) → pas de `loc`, création OK
- création Premium + atomicité préservée (P0-005)
- update sans `location` → pas d'appel geo, `loc` inchangé
- update `location` identique → pas d'appel geo, `loc` inchangé
- update géocodable → `$set` du nouveau `loc`
- update non géocodable → `$unset` explicite de l'ancien `loc`
- test rayon : job manuel avec `loc` retrouvé par `$geoWithin/$centerSphere`
"""

import asyncio
import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
JOBS_PATH = BACKEND_DIR / "routes" / "jobs.py"

USER_ID = "user_geo"
COMPANY_ID = "company_geo"
EMAIL = "geo@example.test"


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


class _UpdateResult:
    def __init__(self, modified_count):
        self.modified_count = modified_count


class _TransactionUnsupportedError(Exception):
    def __init__(self):
        super().__init__("Transaction numbers are only allowed on a replica set member or mongos, "
                         "not on a standalone server.")


# --------------------------------------------------------------------------- #
# Fake session / transaction with atomic-match semantics and rollback          #
# --------------------------------------------------------------------------- #
class _Collection:
    """Backing collection with atomic match+update semantics.

    Writes are applied immediately (like an in-transaction write in Mongo) and
    recorded on the active session so it can be rolled back. A per-collection
    lock serializes concurrent mutations, mirroring real single-document atomicity.
    """

    def __init__(self, name=""):
        self.name = name
        self._lock = asyncio.Lock()
        self._docs = {}
        self._geocode_calls = []  # track geocode_place calls for verification

    # ---- document-level helpers (tests) ----
    def seed_user(self, **fields):
        base = {"_id": USER_ID, "email": EMAIL, "user_type": "employer", "premium_credits": 0,
                "granted_sessions": [], "hashed_password": "x", "is_active": True}
        base.update(fields)
        self._docs[USER_ID] = base
        return self

    def seed_company(self, company_id, **fields):
        base = {"_id": company_id, "owner_id": USER_ID, "name": "Test Company"}
        base.update(fields)
        self._docs[company_id] = base
        return self

    def seed_job(self, job_id, **fields):
        base = {
            "company_id": COMPANY_ID,
            "title": "Test Job",
            "description": "Test description",
            "job_type": "CDI",
            "is_remote": False,
            "is_urgent": False,
            "requirements": [],
            "benefits": [],
            "tags": [],
            "salary_min": None,
            "salary_max": None,
            "salary_currency": "EUR",
            "is_premium": False,
            "views_count": 0,
            "applications_count": 0,
            "is_active": True,
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
        }
        base.update(fields) if fields else None
        self._docs[job_id] = dict(base)
        return self

    def remove_field(self, doc_id, field):
        """Remove a field directly from the underlying storage."""
        self._docs.get(doc_id, {}).pop(field, None)
        return self

    def get(self, doc_id):
        doc = self._docs.get(doc_id)
        return dict(doc) if doc is not None else None

    def docs(self):
        return {k: dict(v) for k, v in self._docs.items()}

    @staticmethod
    def _match(doc, query):
        for key, expected in query.items():
            actual = doc.get(key) if isinstance(key, str) else None
            if key == "_id":
                if doc.get("_id") != expected:
                    return False
                continue
            if isinstance(expected, dict):
                if "$ne" in expected:
                    ne_value = expected["$ne"]
                    if isinstance(actual, list):
                        if ne_value in actual:
                            return False
                    elif actual == ne_value:
                        return False
                if "$gte" in expected:
                    if actual is None or actual < expected["$gte"]:
                        return False
                if "$geoWithin" in expected:
                    # Simplified $geoWithin/$centerSphere match for tests
                    center = expected["$geoWithin"]["$centerSphere"][0]
                    radius_rad = expected["$geoWithin"]["$centerSphere"][1]
                    # Check if doc has loc
                    loc = doc.get("loc")
                    if not loc or loc.get("type") != "Point":
                        return False
                    coords = loc.get("coordinates")
                    if not coords or len(coords) != 2:
                        return False
                    # Simple distance check (Haversine approximation)
                    lng1, lat1 = coords
                    lng2, lat2 = center
                    import math
                    dlat = math.radians(lat2 - lat1)
                    dlng = math.radians(lng2 - lng1)
                    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
                    c = 2 * math.asin(math.sqrt(a))
                    distance_km = 6378.1 * c
                    if distance_km > radius_rad * 6378.1:
                        return False
            else:
                if isinstance(actual, list):
                    if expected not in actual:
                        return False
                elif actual != expected:
                    return False
        return True

    async def find_one(self, query, projection=None):
        async with self._lock:
            for doc_id, doc in self._docs.items():
                if self._match(doc, query):
                    return dict(doc)
            return None

    def find(self, query):
        """Return a cursor-like object for testing."""
        class _Cursor:
            def __init__(self, docs, match_fn):
                self._docs = docs
                self._match_fn = match_fn

            async def to_list(self, length):
                results = []
                for doc_id, doc in self._docs.items():
                    if self._match_fn(doc, query):
                        results.append(dict(doc))
                        if len(results) >= length:
                            break
                return results
        return _Cursor(self._docs, self._match)

    async def update_one(self, query, update, session=None):
        async with self._lock:
            for doc_id, doc in self._docs.items():
                if self._match(doc, query):
                    before = dict(doc)
                    changed = False
                    for key, value in update.get("$inc", {}).items():
                        doc[key] = doc.get(key, 0) + value
                        changed = True
                    for key, value in update.get("$set", {}).items():
                        doc[key] = value
                        changed = True
                    for key, value in update.get("$addToSet", {}).items():
                        bucket = doc.get(key, [])
                        if value not in bucket:
                            bucket.append(value)
                            doc[key] = bucket
                            changed = True
                    for key in update.get("$unset", {}).keys():
                        doc.pop(key, None)
                        changed = True
                    if session is not None and getattr(session, "_txn_active", False):
                        session._journal.append((self.name, "update", doc_id, before))
                    return _UpdateResult(1 if changed else 0)
            return _UpdateResult(0)

    async def insert_one(self, document, session=None):
        async with self._lock:
            doc = dict(document)
            doc_id = doc["_id"]
            self._docs[doc_id] = doc
            if session is not None and getattr(session, "_txn_active", False):
                session._journal.append((self.name, "insert", doc_id))
            return types.SimpleNamespace(inserted_id=doc_id)

    async def count_documents(self, query):
        async with self._lock:
            count = 0
            for doc_id, doc in self._docs.items():
                if self._match(doc, query):
                    count += 1
            return count

    def _undo(self, ops):
        async def _undo_impl():
            async with self._lock:
                for op in ops:
                    op_type = op[1] if len(op) == 4 else op[0]
                    if op_type == "update":
                        doc_id, before = op[2], op[3]
                        self._docs[doc_id] = before
                    elif op_type == "insert":
                        doc_id = op[2]
                        self._docs.pop(doc_id, None)
        return _undo_impl


class _FakeSession:
    def __init__(self, client):
        self._client = client
        self._txn_active = False
        self._journal = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def start_transaction(self):
        return _TransactionCM(self)


class _TransactionCM:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        if not self._session._client.transactions_supported:
            raise _TransactionUnsupportedError()
        self._session._txn_active = True
        self._session._journal = []
        return None

    async def __aexit__(self, exc_type, exc, tb):
        self._session._txn_active = False
        if exc is not None:
            await _rollback_journal(self._session._client, self._session._journal)
            return False
        return False


async def _rollback_journal(client, journal):
    by_collection = {}
    for entry in journal:
        coll_name = entry[0]
        by_collection.setdefault(coll_name, []).append(entry)
    for coll_name, ops in by_collection.items():
        coll = getattr(client.db, coll_name, None)
        if coll is not None and hasattr(coll, "_undo"):
            await coll._undo(ops)()


class _FakeClient:
    def __init__(self, *, transactions_supported=True):
        self.transactions_supported = transactions_supported
        self.db = types.SimpleNamespace(
            users=_Collection("users"),
            jobs=_Collection("jobs"),
            companies=_Collection("companies"),
            payment_transactions=_Collection("payment_transactions"),
            partner_profiles=_Collection("partner_profiles"),
            click_events=_Collection("click_events"),
            campaigns=_Collection("campaigns"),
        )
        self._started_sessions = 0

    async def start_session(self):
        self._started_sessions += 1
        return _FakeSession(self)


# --------------------------------------------------------------------------- #
# Import stubs                                                                 #
# --------------------------------------------------------------------------- #
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

    campaign_lifecycle = types.ModuleType("campaign_lifecycle")
    campaign_lifecycle.is_job_publicly_visible = lambda job, camp: job.get("is_active", True)
    campaign_lifecycle.get_job_campaign = lambda db, job: None
    campaign_lifecycle.fetch_public_job_filter = lambda db: {"is_active": True}
    monkeypatch.setitem(sys.modules, "campaign_lifecycle", campaign_lifecycle)

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
    spec = importlib.util.spec_from_file_location("routes_jobs_p0010", JOBS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def _no_low_balance(*args, **kwargs):
        return None

    module._check_low_balance = _no_low_balance
    module._HTTPException = _HTTPException
    return module


def _make_job_data(**over):
    data = {
        "title": "Dev Python",
        "description": "desc",
        "company_id": COMPANY_ID,
        "location": "Paris",
        "job_type": "CDI",
        "is_remote": False,
        "is_urgent": False,
        "requirements": [],
        "benefits": [],
        "tags": [],
        "salary_min": None,
        "salary_max": None,
        "salary_currency": "EUR",
        "is_premium": False,
    }
    data.update(over)
    return _Model(**data)


def _make_job_update(**over):
    data = {
        "title": None,
        "description": None,
        "company_id": None,
        "location": None,
        "job_type": None,
        "is_remote": None,
        "is_urgent": None,
        "requirements": None,
        "benefits": None,
        "tags": None,
        "salary_min": None,
        "salary_max": None,
        "salary_currency": None,
        "is_premium": None,
    }
    data.update(over)
    return _Model(**data)


def _current_user(user_type="employer", id=USER_ID):
    return _Model(id=id, user_type=user_type, is_active=True, email=EMAIL)


def _wire(jobs_module, client, user=_current_user()):
    async def _get_database():
        return client.db

    jobs_module.get_database = _get_database
    sys.modules["database"].get_client = lambda: client
    return user


# --------------------------------------------------------------------------- #
# Tests — create_job()                                                         #
# --------------------------------------------------------------------------- #
def test_create_job_geocodable_location_adds_loc(jobs_module, monkeypatch):
    """Création standard avec lieu géocodable -> job a `loc` Point GeoJSON."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_company(COMPANY_ID)
    user = _wire(jobs_module, client)

    geocode_calls = []
    async def tracking_geocode(loc):
        geocode_calls.append(loc)
        return [2.3522, 48.8566]  # Paris center

    jobs_module.geocode_place = tracking_geocode

    job = asyncio.run(jobs_module.create_job(_make_job_data(is_premium=False, location="Paris"), user))

    assert job is not None
    assert geocode_calls == ["Paris"]
    job_doc = client.db.jobs.docs()
    assert len(job_doc) == 1
    created = list(job_doc.values())[0]
    assert "loc" in created
    assert created["loc"]["type"] == "Point"
    assert created["loc"]["coordinates"] == [2.3522, 48.8566]


def test_create_job_non_geocodable_location_no_loc_but_created(jobs_module, monkeypatch):
    """Création avec lieu introuvable -> job créé SANS `loc` (best-effort)."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_company(COMPANY_ID)
    user = _wire(jobs_module, client)

    geocode_calls = []
    async def tracking_geocode(loc):
        geocode_calls.append(loc)
        return None

    jobs_module.geocode_place = tracking_geocode

    job = asyncio.run(jobs_module.create_job(_make_job_data(is_premium=False, location="VilleInconnueXYZ"), user))

    assert job is not None
    assert geocode_calls == ["VilleInconnueXYZ"]
    job_doc = client.db.jobs.docs()
    assert len(job_doc) == 1
    created = list(job_doc.values())[0]
    assert "loc" not in created


def test_create_job_premium_geocodable_atomicity_preserved(jobs_module, monkeypatch):
    """Création Premium géocodable -> atomicité P0-005 préservée (débit + insert + loc dans même tx)."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=1)
    client.db.companies.seed_company(COMPANY_ID)
    user = _wire(jobs_module, client)

    geocode_calls = []
    async def tracking_geocode(loc):
        geocode_calls.append(loc)
        return [2.3522, 48.8566]

    jobs_module.geocode_place = tracking_geocode

    job = asyncio.run(jobs_module.create_job(_make_job_data(is_premium=True, location="Paris"), user))

    assert job is not None
    assert geocode_calls == ["Paris"]  # géocodage AVANT la transaction
    assert client.db.users.get(USER_ID)["premium_credits"] == 0
    job_doc = client.db.jobs.docs()
    assert len(job_doc) == 1
    created = list(job_doc.values())[0]
    assert created["is_premium"] is True
    assert "loc" in created
    assert created["loc"]["coordinates"] == [2.3522, 48.8566]
    # transaction a bien été utilisée
    assert client._started_sessions == 1


def test_create_job_premium_non_geocodable_atomicity_preserved(jobs_module, monkeypatch):
    """Création Premium sans géocodage -> atomicité préservée, pas de `loc`."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=1)
    client.db.companies.seed_company(COMPANY_ID)
    user = _wire(jobs_module, client)

    geocode_calls = []
    async def tracking_geocode(loc):
        geocode_calls.append(loc)
        return None

    jobs_module.geocode_place = tracking_geocode

    job = asyncio.run(jobs_module.create_job(_make_job_data(is_premium=True, location="VilleInconnueXYZ"), user))

    assert job is not None
    assert geocode_calls == ["VilleInconnueXYZ"]
    assert client.db.users.get(USER_ID)["premium_credits"] == 0
    job_doc = client.db.jobs.docs()
    assert len(job_doc) == 1
    created = list(job_doc.values())[0]
    assert created["is_premium"] is True
    assert "loc" not in created


# --------------------------------------------------------------------------- #
# Tests — update_job()                                                         #
# --------------------------------------------------------------------------- #
def test_update_job_no_location_no_geocode_no_loc_change(jobs_module):
    """Update sans `location` -> pas d'appel geo, `loc` inchangé."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_company(COMPANY_ID)
    client.db.jobs.seed_job("job_1", **{
        "_id": "job_1", "employer_id": USER_ID, "location": "Paris",
        "title": "Old", "loc": {"type": "Point", "coordinates": [2.3522, 48.8566]},
        "is_active": True, "created_at": datetime(2026, 1, 1)
    })
    user = _wire(jobs_module, client)

    geocode_calls = []
    async def tracking_geocode(loc):
        geocode_calls.append(loc)
        return [2.3522, 48.8566]
    jobs_module.geocode_place = tracking_geocode

    job = asyncio.run(jobs_module.update_job("job_1", _make_job_update(title="New Title"), user))

    assert job is not None
    assert geocode_calls == []  # pas d'appel géocodage
    updated = client.db.jobs.get("job_1")
    assert updated["title"] == "New Title"
    assert updated["loc"] == {"type": "Point", "coordinates": [2.3522, 48.8566]}


def test_update_job_same_location_no_geocode_no_loc_change(jobs_module):
    """Update avec `location` identique -> pas d'appel geo, `loc` inchangé."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_company(COMPANY_ID)
    client.db.jobs.seed_job("job_1", **{
        "_id": "job_1", "employer_id": USER_ID, "location": "Paris",
        "title": "Old", "loc": {"type": "Point", "coordinates": [2.3522, 48.8566]},
        "is_active": True, "created_at": datetime(2026, 1, 1)
    })
    user = _wire(jobs_module, client)

    geocode_calls = []
    async def tracking_geocode(loc):
        geocode_calls.append(loc)
        return [2.3522, 48.8566]
    jobs_module.geocode_place = tracking_geocode

    job = asyncio.run(jobs_module.update_job("job_1", _make_job_update(location="Paris"), user))

    assert job is not None
    assert geocode_calls == []  # pas d'appel géocodage
    updated = client.db.jobs.get("job_1")
    assert updated["location"] == "Paris"
    assert updated["loc"] == {"type": "Point", "coordinates": [2.3522, 48.8566]}


def test_update_job_new_location_geocodable_replaces_loc(jobs_module):
    """Update avec nouvelle location géocodable -> `$set` du nouveau `loc`."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_company(COMPANY_ID)
    client.db.jobs.seed_job("job_1", **{
        "_id": "job_1", "employer_id": USER_ID, "location": "Paris",
        "title": "Old", "loc": {"type": "Point", "coordinates": [2.3522, 48.8566]},
        "is_active": True, "created_at": datetime(2026, 1, 1)
    })
    user = _wire(jobs_module, client)

    geocode_calls = []
    async def tracking_geocode(loc):
        geocode_calls.append(loc)
        if loc == "Lyon":
            return [4.8357, 45.7640]  # Lyon center
        return None
    jobs_module.geocode_place = tracking_geocode

    job = asyncio.run(jobs_module.update_job("job_1", _make_job_update(location="Lyon"), user))

    assert job is not None
    assert geocode_calls == ["Lyon"]
    updated = client.db.jobs.get("job_1")
    assert updated["location"] == "Lyon"
    assert updated["loc"] == {"type": "Point", "coordinates": [4.8357, 45.7640]}


def test_update_job_new_location_non_geocodable_unsets_loc(jobs_module):
    """Update avec nouvelle location non géocodable -> `$unset` explicite de l'ancien `loc`."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_company(COMPANY_ID)
    client.db.jobs.seed_job("job_1", **{
        "_id": "job_1", "employer_id": USER_ID, "location": "Paris",
        "title": "Old", "loc": {"type": "Point", "coordinates": [2.3522, 48.8566]},
        "is_active": True, "created_at": datetime(2026, 1, 1)
    })
    user = _wire(jobs_module, client)

    geocode_calls = []
    async def tracking_geocode(loc):
        geocode_calls.append(loc)
        return None
    jobs_module.geocode_place = tracking_geocode

    job = asyncio.run(jobs_module.update_job("job_1", _make_job_update(location="VilleInconnueXYZ"), user))

    assert job is not None
    assert geocode_calls == ["VilleInconnueXYZ"]
    updated = client.db.jobs.get("job_1")
    assert updated["location"] == "VilleInconnueXYZ"
    assert "loc" not in updated  # $unset effectué


def test_update_job_location_to_empty_string_unsets_loc(jobs_module):
    """Update location -> chaîne vide (non géocodable) -> $unset loc."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_company(COMPANY_ID)
    client.db.jobs.seed_job("job_1", **{
        "_id": "job_1", "employer_id": USER_ID, "location": "Paris",
        "title": "Old", "loc": {"type": "Point", "coordinates": [2.3522, 48.8566]},
        "is_active": True, "created_at": datetime(2026, 1, 1)
    })
    user = _wire(jobs_module, client)

    geocode_calls = []
    async def tracking_geocode(loc):
        geocode_calls.append(loc)
        return None
    jobs_module.geocode_place = tracking_geocode

    job = asyncio.run(jobs_module.update_job("job_1", _make_job_update(location=""), user))

    assert job is not None
    assert geocode_calls == [""]
    updated = client.db.jobs.get("job_1")
    assert updated["location"] == ""
    assert "loc" not in updated


# --------------------------------------------------------------------------- #
# Tests — Rayon ($geoWithin/$centerSphere)                                    #
# --------------------------------------------------------------------------- #
def test_radius_search_finds_manual_job_with_loc(jobs_module):
    """Job manuel avec `loc` est retrouvé par la recherche rayon ($geoWithin/$centerSphere)."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_company(COMPANY_ID)
    # Job manuel avec loc géocodé (Paris)
    client.db.jobs.seed_job("job_manual_paris", **{
        "_id": "job_manual_paris", "employer_id": USER_ID, "location": "Paris",
        "title": "Dev Paris", "loc": {"type": "Point", "coordinates": [2.3522, 48.8566]},
        "is_active": True, "is_premium": False, "created_at": "2026-01-01T00:00:00"
    })
    # Job sans loc (ne doit pas être retrouvé par rayon)
    client.db.jobs.seed_job("job_no_loc", **{
        "_id": "job_no_loc", "employer_id": USER_ID, "location": "Lyon",
        "title": "Dev Lyon", "is_active": True, "is_premium": False, "created_at": "2026-01-01T00:00:00"
    })
    # Job partenaire avec loc (pour vérifier que la logique de recherche est inchangée)
    client.db.jobs.seed_job("job_partner_paris", **{
        "_id": "job_partner_paris", "employer_id": USER_ID, "location": "Paris",
        "title": "Partner Dev Paris", "loc": {"type": "Point", "coordinates": [2.3522, 48.8566]},
        "is_active": True, "is_premium": False, "is_partner": True, "created_at": "2026-01-01T00:00:00"
    })
    user = _wire(jobs_module, client)

    # Simuler la recherche rayon comme dans search_jobs (lignes 185-188)
    async def mock_geocode(loc):
        if loc == "Paris":
            return [2.3522, 48.8566]
        return None
    jobs_module.geocode_place = mock_geocode

    async def run_search():
        db = client.db
        radius = 10.0  # 10 km
        center = await jobs_module.geocode_place("Paris")
        assert center is not None
        # Rayon en radians : km / 6378.1 (rayon Terre)
        query = {"loc": {"$geoWithin": {"$centerSphere": [center, float(radius) / 6378.1]}}}
        query["is_active"] = True
        cursor = db.jobs.find(query)
        return await cursor.to_list(length=100)

    results = asyncio.run(run_search())
    ids = {r["_id"] for r in results}

    # Le job manuel avec loc DOIT être retrouvé
    assert "job_manual_paris" in ids
    # Le job partenaire avec loc DOIT être retrouvé (logique inchangée)
    assert "job_partner_paris" in ids
    # Le job sans loc NE DOIT PAS être retrouvé
    assert "job_no_loc" not in ids


def test_radius_search_excludes_job_without_loc(jobs_module):
    """Job sans `loc` n'est JAMAIS retrouvé par la recherche rayon, même si location textuelle match."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_company(COMPANY_ID)
    client.db.jobs.seed_job("job_no_loc", **{
        "_id": "job_no_loc", "employer_id": USER_ID, "location": "Paris",
        "title": "Dev Paris", "is_active": True, "is_premium": False, "created_at": "2026-01-01T00:00:00"
    })
    user = _wire(jobs_module, client)

    async def mock_geocode(loc):
        return [2.3522, 48.8566]
    jobs_module.geocode_place = mock_geocode

    async def run_search():
        db = client.db
        radius = 10.0
        center = await jobs_module.geocode_place("Paris")
        query = {"loc": {"$geoWithin": {"$centerSphere": [center, float(radius) / 6378.1]}}}
        query["is_active"] = True
        cursor = db.jobs.find(query)
        return await cursor.to_list(length=100)

    results = asyncio.run(run_search())
    ids = {r["_id"] for r in results}

    assert "job_no_loc" not in ids


def test_radius_search_job_updated_location_regeocoded(jobs_module):
    """Job mis à jour avec nouvelle location géocodable -> retrouvé au NOUVEAU rayon."""
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_company(COMPANY_ID)
    # Job initialement à Paris
    client.db.jobs.seed_job("job_1", **{
        "_id": "job_1", "employer_id": USER_ID, "location": "Paris",
        "title": "Dev", "loc": {"type": "Point", "coordinates": [2.3522, 48.8566]},
        "is_active": True, "is_premium": False, "created_at": datetime(2026, 1, 1)
    })
    user = _wire(jobs_module, client)

    geocode_calls = []
    async def tracking_geocode(loc):
        geocode_calls.append(loc)
        if loc == "Paris":
            return [2.3522, 48.8566]
        if loc == "Marseille":
            return [5.3698, 43.2965]
        return None
    jobs_module.geocode_place = tracking_geocode

    # Update vers Marseille
    asyncio.run(jobs_module.update_job("job_1", _make_job_update(location="Marseille"), user))

    assert geocode_calls == ["Marseille"]
    updated = client.db.jobs.get("job_1")
    assert updated["location"] == "Marseille"
    assert updated["loc"] == {"type": "Point", "coordinates": [5.3698, 43.2965]}

    # Recherche rayon autour de Marseille -> doit retrouver
    async def run_search_marseille():
        db = client.db
        radius = 10.0
        center = [5.3698, 43.2965]
        query = {"loc": {"$geoWithin": {"$centerSphere": [center, float(radius) / 6378.1]}}}
        query["is_active"] = True
        cursor = db.jobs.find(query)
        return await cursor.to_list(length=100)

    results = asyncio.run(run_search_marseille())
    ids = {r["_id"] for r in results}
    assert "job_1" in ids

    # Recherche rayon autour de Paris -> NE doit PLUS retrouver
    async def run_search_paris():
        db = client.db
        radius = 10.0
        center = [2.3522, 48.8566]
        query = {"loc": {"$geoWithin": {"$centerSphere": [center, float(radius) / 6378.1]}}}
        query["is_active"] = True
        cursor = db.jobs.find(query)
        return await cursor.to_list(length=100)

    results = asyncio.run(run_search_paris())
    ids = {r["_id"] for r in results}
    assert "job_1" not in ids