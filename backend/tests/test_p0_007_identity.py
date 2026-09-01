"""P0-007 : identité des offres de feed par `campaign_id`.

Couvre, pour `partner_feed.import_feed` et la migration explicite
`scripts/migrate_p0007_identity_indexes.py`, la source de vérité P0-007 :

- identité STRICTE `(partner_id, campaign_id, external_ref)` pour une offre de
  campagne (campaign_id string non vide) vs `(partner_id, external_ref,
  campaign_id: None)` pour un legacy — les deux branches ne se croisent JAMAIS ;
- deux campagnes avec le même external_ref produisent DEUX offres distinctes ;
- un réimport de la même campagne/référence met à jour le MÊME job : jamais de
  doublon, `campaign_id` jamais « déplacé », `expires_at` jamais renouvelé ;
- fail-closed 503 tant que la garantie d'index n'est pas déployée : les
  créations de jobs de campagne exigent le marqueur `p0007_identity_indexes`
  ET l'index unique physique `p0007_identity_unique` (un marqueur incohérent,
  posé sans index, reste fail-closed) — aucune fenêtre de doublons concurrents ;
- migration : l'index est créé AVANT le marqueur, jamais de `--skip-index` (le
  marqueur signifie réellement « index présent ») ; en cas d'échec de création
  de l'index, AUCUN marqueur n'est posé ; winner = plus ancien `created_at`
  VALIDE (tie-break `_id` croissant, jamais `_id`-âge) ;
- `database.create_indexes()` : un marqueur présent sans index n'est matérialisé
  que si ZÉRO doublon éligible ; avec doublons, log explicite et startup intact
  (aucune dédup destructrice au startup) ;
- `per_posting` campagne : insertion + débit atomiques en transaction Mongo
  (`with_transaction`) ; fail-closed 503 AVANT toute écriture sur une topologie
  sans transactions (standalone) — zéro société/job/débit ; seul l'insert
  réellement gagnant consomme exactement 1 posting ; le loser ne débite ni ne
  rembourse, ne touche jamais `expires_at` ; `charged` = insertions réellement
  facturées par CETTE invocation ;
- le `per_posting` legacy conserve le comportement P0-006 (débit local +
  écriture différée).

Partie 1 : tests DÉTERMINISTES (aucun service externe, fake DB asyncio).
Partie 2 : tests d'INTÉGRATION Mongo réelle (replica set + standalone, skipés
sinon). Les tests per_posting (transactions) sont skipés sans replica set.
"""
import asyncio
import importlib.util
import os
import sys
import types
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError

BACKEND_DIR = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BACKEND_DIR))

PARENT_DIR = BACKEND_DIR.parent
# Scripts directory (migration) lives under backend/.
SCRIPTS_DIR = BACKEND_DIR / "scripts"

PARTNER = "partner_p007"
P0007_MARKER = "p0007_identity_indexes"
INDEX_NAME = "p0007_identity_unique"

REPLICA_SET_URL = os.environ.get("P005_REPLICA_SET_URL", "mongodb://127.0.0.1:27017")
STANDALONE_URL = os.environ.get("P005_STANDALONE_URL", "mongodb://127.0.0.1:27018")


# --------------------------------------------------------------------------- #
# Stubs (fastapi / pydantic / models / database / auth / geo / httpx)         #
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
    CANDIDATE = "candidate"
    PARTNER = "partner"
    ADMIN = "admin"


_CLIENT_HOLDER = {"client": None}


def _install_stubs(monkeypatch):
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = _Router
    fastapi.HTTPException = _HTTPException
    fastapi.Depends = lambda dependency=None, *a, **k: dependency
    fastapi.Query = lambda default=None, *a, **k: default
    fastapi.status = types.SimpleNamespace(
        HTTP_400_BAD_REQUEST=400, HTTP_404_NOT_FOUND=404,
        HTTP_402_PAYMENT_REQUIRED=402, HTTP_409_CONFLICT=409,
        HTTP_500_INTERNAL_SERVER_ERROR=500, HTTP_503_SERVICE_UNAVAILABLE=503,
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
                 "JobSearchResponse", "User", "SavedJob", "Application"):
        setattr(models, name, _Model)
    models.UserType = _UserType
    monkeypatch.setitem(sys.modules, "models", models)

    database = types.ModuleType("database")

    async def _placeholder_db():
        raise AssertionError("test must replace get_database")

    database.get_database = _placeholder_db
    database.get_client = lambda: _CLIENT_HOLDER["client"]
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

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise AssertionError("feed URL fetch is not exercised in these tests")

    httpx.AsyncClient = lambda *a, **k: _MockClient()
    monkeypatch.setitem(sys.modules, "httpx", httpx)


def _load(monkeypatch, rel_path, modname):
    path = BACKEND_DIR / rel_path
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._HTTPException = _HTTPException
    return module


@pytest.fixture
def feed_module(monkeypatch):
    _install_stubs(monkeypatch)
    return _load(monkeypatch, "partner_feed.py", "p0007_feed")


@pytest.fixture
def migrate_module(monkeypatch):
    _install_stubs(monkeypatch)
    return _load(monkeypatch, "scripts/migrate_p0007_identity_indexes.py", "p0007_migrate")


@pytest.fixture(autouse=True)
def _reset_client_holder():
    _CLIENT_HOLDER["client"] = None
    yield


# --------------------------------------------------------------------------- #
# Fake DB asyncio (modèle les sémantiques Mongo utilisées en déterministe)    #
# --------------------------------------------------------------------------- #
class _UpdateResult:
    def __init__(self, modified_count):
        self.modified_count = modified_count


def _matches(doc, query):
    for key, value in query.items():
        actual = doc.get(key)
        if isinstance(value, dict) and "$gte" in value:
            if actual is None or actual < value["$gte"]:
                return False
        elif isinstance(value, dict) and "$ne" in value:
            if actual == value["$ne"]:
                return False
        elif actual != value:
            return False
    return True


class _FakeJobs:
    def __init__(self, docs=None, index_present=True, hide_identity=None,
                 hide_times=1, raise_on_insert=False):
        self._docs = docs or []
        self.index_present = index_present
        self.hide_identity = hide_identity
        self.hide_times = hide_times
        self.raise_on_insert = raise_on_insert

    async def find_one(self, query, session=None):
        for doc in self._docs:
            if _matches(doc, query):
                if self.hide_identity is not None and query == self.hide_identity \
                        and self.hide_times > 0:
                    self.hide_times -= 1
                    return None
                return dict(doc)
        return None

    async def insert_one(self, doc, session=None):
        if self.raise_on_insert:
            self.raise_on_insert = False
            raise DuplicateKeyError(f"duplicate key {INDEX_NAME}")
        self._docs.append(dict(doc))
        return types.SimpleNamespace(inserted_id=doc["_id"])

    async def update_one(self, query, update, session=None):
        for doc in self._docs:
            if _matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                return _UpdateResult(1)
        return _UpdateResult(0)

    async def index_information(self):
        if self.index_present:
            return {INDEX_NAME: {"unique": True}}
        return {}

    def find(self, query=None):
        return [dict(d) for d in self._docs if not query or _matches(d, query)]

    def count(self):
        return len(self._docs)

    def snapshot(self):
        return [dict(d) for d in self._docs]

    def restore(self, snap):
        self._docs = [dict(d) for d in snap]


class _FakeProfiles:
    def __init__(self, profile):
        self.profile = dict(profile)

    async def find_one(self, query, session=None):
        if _matches(self.profile, query):
            return dict(self.profile)
        return None

    async def update_one(self, query, update, session=None):
        if not _matches(self.profile, query):
            return _UpdateResult(0)
        for key, value in update.get("$inc", {}).items():
            self.profile[key] = self.profile.get(key, 0) + value
        for key, value in update.get("$set", {}).items():
            self.profile[key] = value
        return _UpdateResult(1)

    def snapshot(self):
        return dict(self.profile)

    def restore(self, snap):
        self.profile = dict(snap)


class _FakeMeta:
    def __init__(self, docs=None):
        self._docs = docs or []

    async def find_one(self, query, session=None):
        for doc in self._docs:
            if _matches(doc, query):
                return dict(doc)
        return None

    async def insert_one(self, doc, session=None):
        self._docs.append(dict(doc))


class _FakeCompanies:
    def __init__(self):
        self._docs = []

    async def find_one(self, query, session=None):
        for doc in self._docs:
            if _matches(doc, query):
                return dict(doc)
        return None

    async def insert_one(self, doc, session=None):
        d = dict(doc)
        self._docs.append(d)
        return types.SimpleNamespace(inserted_id=d["_id"])


class _TxUnsupportedError(Exception):
    pass


_TX_UNSUPPORTED_MSG = ("Transaction numbers are only allowed on a replica set "
                       "member or mongos, not on a standalone server.")


class _FakeTxnCM:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        if not self._client.transactions_supported:
            raise _TxUnsupportedError(_TX_UNSUPPORTED_MSG)
        return None

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def start_transaction(self):
        return _FakeTxnCM(self._client)

    async def with_transaction(self, callback):
        if not self._client.transactions_supported:
            raise _TxUnsupportedError(_TX_UNSUPPORTED_MSG)
        # Modèle l'atomicité : tout échec du callback restaure l'état.
        snap = self._client.snapshot()
        try:
            return await callback(self)
        except Exception:
            self._client.restore(snap)
            raise


class _FakeClient:
    def __init__(self, db, transactions_supported=True):
        self.db = db
        self.transactions_supported = transactions_supported
        self._session = _FakeSession(self)

    async def start_session(self):
        return self._session

    def snapshot(self):
        return {"jobs": self.db.jobs.snapshot(), "profiles": self.db.partner_profiles.snapshot()}

    def restore(self, snap):
        self.db.jobs.restore(snap["jobs"])
        self.db.partner_profiles.restore(snap["profiles"])


class _FakeDB:
    def __init__(self, profile=None, marker=True, index_present=True, jobs=None):
        self.partner_profiles = _FakeProfiles(profile if profile is not None else {
            "user_id": PARTNER, "billing_mode": "per_click", "company_name": "Acme",
            "default_cpc": 0.5, "posting_price": 1.0, "postings_remaining": 10,
            "total_spent": 0.0,
        })
        self.migration_flags = _FakeMeta([{"_id": P0007_MARKER, "applied_at": datetime.utcnow()}]) \
            if marker else _FakeMeta([])
        self.companies = _FakeCompanies()
        self.jobs = _FakeJobs(jobs, index_present=index_present)


def _xml(ref, title="Dev", url=None):
    return ("<joboolo><ad>"
            f"<id>{ref}</id><title>{title}</title><content>desc</content>"
            f"<city>Paris</city><contract>CDI</contract><url>{url or 'https://x/' + ref}</url>"
            "</ad></joboolo>")


def _run_import(feed_module, db, partner_id=PARTNER, xml=None, ref="r1",
                billing_mode="per_click", campaign_id=None, validity_days=None,
                cpc=0.5):
    async def scenario():
        return await feed_module.import_feed(
            db, partner_id, xml_content=xml if xml is not None else _xml(ref),
            cpc=cpc, billing_mode=billing_mode, campaign_id=campaign_id,
            validity_days=validity_days)
    return asyncio.run(scenario())


def _assert_http(exc, status):
    assert isinstance(exc, _HTTPException)
    assert exc.status_code == status


def _seed_job(identity, **kw):
    doc = {
        "_id": "pjob_seeded", "partner_id": PARTNER, "campaign_id": "c1",
        "external_ref": "r1", "title": "Seeded", "is_partner": True,
        "created_at": datetime.utcnow(), "expires_at": datetime.utcnow() + timedelta(days=30),
    }
    doc.update(identity)
    doc.update(kw)
    return doc


# --------------------------------------------------------------------------- #
# 1. Identité métier (fonctions pures)                                        #
# --------------------------------------------------------------------------- #
class TestIdentity:
    def test_campaign_identity_is_strict_triplet(self, feed_module):
        assert feed_module._job_identity("p1", "c1", "ref-x") == {
            "partner_id": "p1", "campaign_id": "c1", "external_ref": "ref-x",
        }

    def test_legacy_identity_is_null_campaign(self, feed_module):
        # campaign_id absent/None/"" => identité legacy `campaign_id: None`.
        assert feed_module._job_identity("p1", None, "ref-x") == {
            "partner_id": "p1", "campaign_id": None, "external_ref": "ref-x",
        }
        assert feed_module._job_identity("p1", "", "ref-x")["campaign_id"] is None

    def test_identity_never_uses_or(self, feed_module):
        camp = feed_module._job_identity("p1", "c1", "r")
        assert "campaign_id" in camp and camp["campaign_id"] == "c1"
        assert not any("$or" in v for v in camp.values() if isinstance(v, dict))

    def test_is_unsupported_transaction_detection(self, feed_module):
        assert feed_module._is_unsupported_transaction(
            Exception("Transaction numbers are only allowed on a replica set member or mongos"))
        assert feed_module._is_unsupported_transaction(
            Exception("Transactions are not supported by this standalone deployment"))
        assert not feed_module._is_unsupported_transaction(
            Exception("Unhandled exception in client callback"))
        assert not feed_module._is_unsupported_transaction(RuntimeError("boom"))


# --------------------------------------------------------------------------- #
# 2. Migration — sélection winner (fonctions pures)                           #
# --------------------------------------------------------------------------- #
class TestMigrationWinner:
    def test_winner_is_oldest_valid_created_at(self, migrate_module):
        now = datetime.utcnow()
        docs = [
            {"_id": "b", "created_at": now - timedelta(hours=1)},
            {"_id": "a", "created_at": now - timedelta(hours=3)},
            {"_id": "c", "created_at": now - timedelta(hours=2)},
        ]
        assert migrate_module._pick_winner(docs)["_id"] == "a"

    def test_winner_invalid_created_at_loses_to_valid(self, migrate_module):
        now = datetime.utcnow()
        docs = [
            {"_id": "bad_num", "created_at": "2026-09-01"},  # string => invalide
            {"_id": "valid", "created_at": now - timedelta(days=1)},
            {"_id": "missing"},
        ]
        winner = migrate_module._pick_winner(docs)
        assert winner["_id"] == "valid"
        # Sans AUCUNE date valide, le tri reste stable et déterministe (_id).
        assert migrate_module._pick_winner([{"_id": "m2"}, {"_id": "m1"}])["_id"] == "m1"

    def test_winner_tie_break_ascending_id(self, migrate_module):
        now = datetime.utcnow()
        docs = [
            {"_id": "b", "created_at": now},
            {"_id": "a", "created_at": now},
        ]
        assert migrate_module._pick_winner(docs)["_id"] == "a"

    def test_created_at_invalid_values_are_not_valid(self, migrate_module):
        assert migrate_module._is_valid_created_at(datetime.utcnow()) is True
        for bad in (None, "2026-09-01", "2026-09-01T00:00:00", 1234567890):
            assert migrate_module._is_valid_created_at(bad) is False


class TestMigrationMarkers:
    def test_migration_has_no_skip_index_flag(self, migrate_module):
        # Le marqueur signifie réellement « index présent » : il n'existe AUCUN
        # moyen de poser le marqueur sans créer l'index.
        parser = migrate_module._build_parser()
        assert "--skip-index" not in parser._option_string_actions

    def test_migration_index_failure_never_sets_marker(self, migrate_module):
        flags = _MigrateFlags()
        jobs = _MigrateJobs(duplicate_groups=0, index_present=False, create_raises=True)
        db = _MigrateDB(flags=flags, jobs=jobs)
        with pytest.raises(RuntimeError):
            asyncio.run(migrate_module._migrate(db, force=True))
        assert asyncio.run(flags.find_one({"_id": P0007_MARKER})) is None  # AUCUN marqueur

    def test_migration_dry_run_no_writes(self, migrate_module):
        flags = _MigrateFlags()
        jobs = _MigrateJobs(duplicate_groups=0, index_present=False)
        db = _MigrateDB(flags=flags, jobs=jobs)
        report = asyncio.run(migrate_module._migrate(db, dry_run=True))
        assert report["dry_run"] is True
        assert asyncio.run(flags.find_one({"_id": P0007_MARKER})) is None
        assert jobs.index_present is False

    def test_migration_success_creates_index_then_marker(self, migrate_module):
        flags = _MigrateFlags()
        jobs = _MigrateJobs(duplicate_groups=0, index_present=False)
        db = _MigrateDB(flags=flags, jobs=jobs)
        report = asyncio.run(migrate_module._migrate(db))
        assert report["index_created"] is True
        assert report["marker_set"] is True
        assert jobs.index_present is True
        assert asyncio.run(flags.find_one({"_id": P0007_MARKER})) is not None

    def test_migration_idempotent_when_index_ready(self, migrate_module):
        flags = _MigrateFlags([{"_id": P0007_MARKER, "applied_at": datetime.utcnow()}])
        jobs = _MigrateJobs(duplicate_groups=0, index_present=True)
        db = _MigrateDB(flags=flags, jobs=jobs)
        report = asyncio.run(migrate_module._migrate(db))
        assert report["already_migrated"] is True
        assert report["marker_set"] is False


class _MigrateFlags:
    def __init__(self, docs=None):
        self.docs = docs or []

    async def find_one(self, query):
        for d in self.docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    async def insert_one(self, doc):
        self.docs.append(dict(doc))


class _MigrateJobs:
    def __init__(self, duplicate_groups=0, index_present=False, create_raises=False):
        self.duplicate_groups = duplicate_groups
        self._index_present = index_present
        self.create_raises = create_raises

    @property
    def index_present(self):
        return self._index_present

    def aggregate(self, pipeline):
        class _C:
            def __init__(self, rows):
                self.rows = rows

            async def to_list(self, length=None):
                return self.rows
        if self.duplicate_groups:
            return _C([{"_id": {"partner_id": "p", "campaign_id": "c", "external_ref": "r"},
                        "count": self.duplicate_groups}])
        return _C([])

    def find(self, query):
        class _C:
            def __init__(self, docs):
                self.docs = docs

            async def to_list(self, length=None):
                return self.docs
        return _C([])

    async def index_information(self):
        if self._index_present:
            return {INDEX_NAME: {"unique": True}}
        return {}

    async def create_index(self, spec, **kw):
        if self.create_raises:
            raise RuntimeError("creation index refusée (doublons ou serveur)")
        self._index_present = True
        return INDEX_NAME


class _MigrateDB:
    def __init__(self, flags=None, jobs=None):
        self.migration_flags = flags or _MigrateFlags()
        self.jobs = jobs or _MigrateJobs()


# --------------------------------------------------------------------------- #
# 3. Import — cas déterministes (fake DB)                                     #
# --------------------------------------------------------------------------- #
class TestImportFailClosed:
    def test_campaign_import_503_without_marker_no_write(self, feed_module):
        db = _FakeDB(marker=False)
        try:
            _run_import(feed_module, db, campaign_id="c1")
            assert False
        except _HTTPException as exc:
            _assert_http(exc, 503)
        assert db.jobs.count() == 0
        assert db.companies._docs == []

    def test_campaign_import_503_marker_without_physical_index(self, feed_module):
        # État incohérent (marqueur posé sans index, ex. état partiel) : le
        # fail-closed reste actif — un marqueur ne vaut jamais pour un index.
        db = _FakeDB(marker=True, index_present=False)
        try:
            _run_import(feed_module, db, campaign_id="c1")
            assert False
        except _HTTPException as exc:
            _assert_http(exc, 503)
        assert db.jobs.count() == 0
        assert db.companies._docs == []

    def test_legacy_import_works_without_marker(self, feed_module):
        # Le fail-closed ne concerne que les créations de jobs de campagne ;
        # l'import legacy conserve son fonctionnement (aucun marqueur requis).
        db = _FakeDB(marker=False)
        res = _run_import(feed_module, db)
        assert res["imported"] == 1
        assert db.jobs.count() == 1

    def test_campaign_import_requires_valid_partner_id(self, feed_module):
        db = _FakeDB(profile={"user_id": "", "billing_mode": "per_click"})
        with pytest.raises(_HTTPException) as exc:
            _run_import(feed_module, db, partner_id="", campaign_id="c1")
        _assert_http(exc.value, 400)

    def test_unknown_partner_404(self, feed_module):
        db = _FakeDB(marker=True)
        with pytest.raises(_HTTPException) as exc:
            _run_import(feed_module, db, partner_id="nobody", campaign_id="c1")
        _assert_http(exc.value, 404)


class TestImportCampaignIdentity:
    def test_campaign_import_creates_job_with_triplet(self, feed_module):
        db = _FakeDB(marker=True)
        res = _run_import(feed_module, db, campaign_id="c1", ref="r1")
        assert res["imported"] == 1 and res["updated"] == 0
        jobs = db.jobs.find({"external_ref": "r1"})
        assert len(jobs) == 1
        assert jobs[0]["partner_id"] == PARTNER
        assert jobs[0]["campaign_id"] == "c1"
        assert jobs[0]["external_ref"] == "r1"

    def test_two_campaigns_same_ref_two_jobs(self, feed_module):
        db = _FakeDB(marker=True)
        r1 = _run_import(feed_module, db, campaign_id="c1", ref="r1")
        r2 = _run_import(feed_module, db, campaign_id="c2", ref="r1")
        assert r1["imported"] == 1 and r2["imported"] == 1
        jobs = db.jobs.find({"external_ref": "r1"})
        assert len(jobs) == 2
        assert {j["campaign_id"] for j in jobs} == {"c1", "c2"}

    def test_reimport_same_campaign_updates_same_job(self, feed_module):
        db = _FakeDB(marker=True)
        _run_import(feed_module, db, campaign_id="c1", ref="r1", xml=_xml("r1", title="V1"))
        _run_import(feed_module, db, campaign_id="c2", ref="r2")  # autre campagne
        res = _run_import(feed_module, db, campaign_id="c1", ref="r1", xml=_xml("r1", title="V2"))
        assert res["imported"] == 0 and res["updated"] == 1
        jobs = db.jobs.find()
        assert len(jobs) == 2  # un job par campagne, jamais de doublon
        c1 = [j for j in jobs if j["campaign_id"] == "c1"][0]
        c2 = [j for j in jobs if j["campaign_id"] == "c2"][0]
        assert c1["title"] == "V2"
        assert c2["title"] == "Dev"  # jamais touché par le réimport d'une autre campagne

    def test_campaign_never_claims_legacy_job(self, feed_module):
        db = _FakeDB(marker=True)
        r_legacy = _run_import(feed_module, db, ref="r1")
        assert r_legacy["imported"] == 1
        legacy_job = db.jobs.find({"external_ref": "r1"})[0]
        assert legacy_job["campaign_id"] is None

        r_camp = _run_import(feed_module, db, campaign_id="c1", ref="r1")
        assert r_camp["imported"] == 1
        jobs = db.jobs.find({"external_ref": "r1"})
        assert len(jobs) == 2  # NI réutilisation NI déplacement de campaign_id
        by_camp = {j["campaign_id"] for j in jobs}
        assert by_camp == {"c1", None}

    def test_legacy_never_claims_campaign_job(self, feed_module):
        db = _FakeDB(marker=True)
        _run_import(feed_module, db, campaign_id="c1", ref="r1")
        res = _run_import(feed_module, db, ref="r1")
        assert res["imported"] == 1
        jobs = db.jobs.find({"external_ref": "r1"})
        assert len(jobs) == 2
        legacy = [j for j in jobs if j["campaign_id"] is None]
        assert len(legacy) == 1 and legacy[0]["external_ref"] == "r1"

    def test_per_click_duplicate_key_retry_updates(self, feed_module):
        # Un concurrent gagne la fenêtre find->insert : l'index unique refuse le
        # doublon (DuplicateKeyError) => re-cherche stricte et update.
        db = _FakeDB(marker=True)
        _run_import(feed_module, db, campaign_id="c1", ref="r1", xml=_xml("r1", title="Winner"))
        identity = {"partner_id": PARTNER, "campaign_id": "c1", "external_ref": "r1"}
        db.jobs.hide_identity = identity
        db.jobs.hide_times = 1
        db.jobs.raise_on_insert = True
        res = _run_import(feed_module, db, campaign_id="c1", ref="r1", xml=_xml("r1", title="Loser"))
        assert res["imported"] == 0 and res["updated"] == 1
        jobs = db.jobs.find({"external_ref": "r1"})
        assert len(jobs) == 1
        assert jobs[0]["title"] == "Loser"
        assert jobs[0]["campaign_id"] == "c1"


class TestImportPerPosting:
    def test_legacy_per_posting_debits_once(self, feed_module):
        db = _FakeDB(profile={
            "user_id": PARTNER, "billing_mode": "per_posting", "company_name": "Acme",
            "posting_price": 2.0, "postings_remaining": 3, "total_spent": 0.0,
        }, marker=True)
        res = _run_import(feed_module, db, billing_mode="per_posting", ref="r1")
        assert res["imported"] == 1
        assert res["postings_remaining"] == 2
        assert res["charged"] == pytest.approx(2.0)
        assert db.partner_profiles.profile["postings_remaining"] == 2
        assert db.partner_profiles.profile["total_spent"] == pytest.approx(2.0)
        assert db.jobs.count() == 1

    def test_legacy_per_posting_no_credit_skips(self, feed_module):
        db = _FakeDB(profile={
            "user_id": PARTNER, "billing_mode": "per_posting", "company_name": "Acme",
            "posting_price": 1.0, "postings_remaining": 0, "total_spent": 0.0,
        }, marker=True)
        res = _run_import(feed_module, db, billing_mode="per_posting", ref="r1")
        assert res["imported"] == 0 and res["skipped_no_credit"] == 1
        assert res["charged"] == 0 and res["postings_remaining"] == 0
        assert db.jobs.count() == 0
        assert db.partner_profiles.profile.get("total_spent", 0) == 0

    def test_campaign_per_posting_insert_debits_atomically(self, feed_module):
        profile = {
            "user_id": PARTNER, "billing_mode": "per_posting", "company_name": "Acme",
            "posting_price": 1.5, "postings_remaining": 3, "total_spent": 0.0,
        }
        db = _FakeDB(profile=profile, marker=True)
        _CLIENT_HOLDER["client"] = _FakeClient(db)
        res = _run_import(feed_module, db, billing_mode="per_posting",
                          campaign_id="c1", ref="r1", validity_days=30)
        assert res["imported"] == 1 and res["updated"] == 0
        assert res["charged"] == pytest.approx(1.5)
        assert res["postings_remaining"] == 2
        assert db.partner_profiles.profile["postings_remaining"] == 2
        assert db.partner_profiles.profile["total_spent"] == pytest.approx(1.5)
        job = db.jobs.find({"external_ref": "r1"})[0]
        assert job["expires_at"] is not None  # P0-006 : expiration posée à l'insertion

    def test_campaign_per_posting_reimport_no_double_debit(self, feed_module):
        profile = {
            "user_id": PARTNER, "billing_mode": "per_posting", "company_name": "Acme",
            "posting_price": 1.0, "postings_remaining": 3, "total_spent": 0.0,
        }
        db = _FakeDB(profile=profile, marker=True)
        _CLIENT_HOLDER["client"] = _FakeClient(db)
        r1 = _run_import(feed_module, db, billing_mode="per_posting",
                         campaign_id="c1", ref="r1", validity_days=30)
        assert r1["charged"] == pytest.approx(1.0)
        first_expires = db.jobs.find({"external_ref": "r1"})[0]["expires_at"]

        r2 = _run_import(feed_module, db, billing_mode="per_posting",
                         campaign_id="c1", ref="r1", xml=_xml("r1", title="V2"), validity_days=30)
        assert r2["imported"] == 0 and r2["updated"] == 1
        assert r2["charged"] == 0  # pas de second débit
        assert db.partner_profiles.profile["postings_remaining"] == 2
        assert db.partner_profiles.profile["total_spent"] == pytest.approx(1.0)
        job = db.jobs.find({"external_ref": "r1"})[0]
        assert job["expires_at"] == first_expires  # jamais renouvelé
        assert job["title"] == "V2"

    def test_campaign_per_posting_no_credit_full_rollback(self, feed_module):
        profile = {
            "user_id": PARTNER, "billing_mode": "per_posting", "company_name": "Acme",
            "posting_price": 1.0, "postings_remaining": 0, "total_spent": 0.0,
        }
        db = _FakeDB(profile=profile, marker=True)
        _CLIENT_HOLDER["client"] = _FakeClient(db)
        res = _run_import(feed_module, db, billing_mode="per_posting",
                          campaign_id="c1", ref="r1", validity_days=30)
        assert res["skipped_no_credit"] == 1
        assert res["imported"] == 0 and res["charged"] == 0
        assert db.jobs.count() == 0
        assert db.partner_profiles.profile["postings_remaining"] == 0
        assert db.partner_profiles.profile.get("total_spent", 0) == 0

    def test_campaign_per_posting_loser_concurrent_never_debits(self, feed_module):
        # Le loser d'une course find->insert (index unique) : sa transaction est
        # abortée, son débit annulé ; il devient un simple update sans re-débit.
        profile = {
            "user_id": PARTNER, "billing_mode": "per_posting", "company_name": "Acme",
            "posting_price": 1.0, "postings_remaining": 3, "total_spent": 0.0,
        }
        seeded = _seed_job({
            "partner_id": PARTNER, "campaign_id": "c1", "external_ref": "r1",
        })
        db = _FakeDB(profile=profile, marker=True, jobs=[seeded])
        db.jobs.hide_identity = {"partner_id": PARTNER, "campaign_id": "c1", "external_ref": "r1"}
        db.jobs.hide_times = 2  # masque la 1re recherche (boucle) puis celle de la transaction
        db.jobs.raise_on_insert = True
        _CLIENT_HOLDER["client"] = _FakeClient(db)
        res = _run_import(feed_module, db, billing_mode="per_posting",
                          campaign_id="c1", ref="r1", xml=_xml("r1", title="Loser"),
                          validity_days=30)
        assert res["imported"] == 0 and res["updated"] == 1
        assert res["charged"] == 0  # jamais débité par le loser
        assert db.partner_profiles.profile["postings_remaining"] == 3
        assert db.partner_profiles.profile["total_spent"] == 0.0
        job = db.jobs.find({"external_ref": "r1"})[0]
        # expires_at jamais touché hors insertion (reste celui du job seed).
        assert job["expires_at"] == seeded["expires_at"]

    def test_campaign_per_posting_client_unavailable_503(self, feed_module):
        profile = {
            "user_id": PARTNER, "billing_mode": "per_posting", "company_name": "Acme",
            "posting_price": 1.0, "postings_remaining": 5, "total_spent": 0.0,
        }
        db = _FakeDB(profile=profile, marker=True)
        _CLIENT_HOLDER["client"] = None
        with pytest.raises(_HTTPException) as exc:
            _run_import(feed_module, db, billing_mode="per_posting",
                        campaign_id="c1", ref="r1", validity_days=30)
        _assert_http(exc.value, 503)
        assert db.jobs.count() == 0
        assert db.companies._docs == []
        assert db.partner_profiles.profile["postings_remaining"] == 5

    def test_campaign_per_posting_standalone_503_zero_writes(self, feed_module):
        # Fail-closed AVANT toute écriture : une topologie sans transactions
        # (standalone) refuse l'import per_posting campagne sans créer société
        # ni job ni débit.
        db = _FakeDB(profile={
            "user_id": PARTNER, "billing_mode": "per_posting", "company_name": "Acme",
            "posting_price": 1.0, "postings_remaining": 5, "total_spent": 0.0,
        }, marker=True)
        _CLIENT_HOLDER["client"] = _FakeClient(db, transactions_supported=False)
        with pytest.raises(_HTTPException) as exc:
            _run_import(feed_module, db, billing_mode="per_posting",
                        campaign_id="c1", ref="r1", validity_days=30)
        _assert_http(exc.value, 503)
        assert db.jobs.count() == 0
        assert db.companies._docs == []
        assert db.partner_profiles.profile["postings_remaining"] == 5
        assert db.partner_profiles.profile["total_spent"] == 0.0

    def test_campaign_per_posting_two_ads_charged_accumulates(self, feed_module):
        profile = {
            "user_id": PARTNER, "billing_mode": "per_posting", "company_name": "Acme",
            "posting_price": 1.0, "postings_remaining": 3, "total_spent": 0.0,
        }
        db = _FakeDB(profile=profile, marker=True)
        _CLIENT_HOLDER["client"] = _FakeClient(db)
        xml = ("<joboolo>"
               "<ad><id>ra</id><title>A</title><content>d</content><city>Paris</city>"
               "<contract>CDI</contract><url>https://x/ra</url></ad>"
               "<ad><id>rb</id><title>B</title><content>d</content><city>Lyon</city>"
               "<contract>CDI</contract><url>https://x/rb</url></ad>"
               "</joboolo>")
        res = _run_import(feed_module, db, xml=xml, billing_mode="per_posting",
                          campaign_id="c1", validity_days=30)
        assert res["imported"] == 2
        assert res["charged"] == pytest.approx(2.0)
        assert res["postings_remaining"] == 1
        assert db.partner_profiles.profile["postings_remaining"] == 1


# --------------------------------------------------------------------------- #
# 4. Intégration Mongo réelle (skipés sans serveur)                            #
# --------------------------------------------------------------------------- #
def _mongo_reachable(url):
    async def _probe():
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=2000)
        try:
            await client.admin.command("ping")
            return True
        except Exception:
            return False
        finally:
            client.close()
    return asyncio.run(_probe())


def _check_replica_set(url=REPLICA_SET_URL):
    async def _probe():
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=2000)
        try:
            await client.admin.command("ping")
            hello = await client.admin.command("hello")
            return hello.get("setName") is not None
        except Exception:
            return False
        finally:
            client.close()
    return asyncio.run(_probe())


def _check_standalone(url=STANDALONE_URL):
    async def _probe():
        client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=2000)
        try:
            await client.admin.command("ping")
            hello = await client.admin.command("hello")
            return hello.get("setName") is None
        except Exception:
            return False
        finally:
            client.close()
    return asyncio.run(_probe())


async def _seed_partner(db, **kw):
    doc = {"user_id": PARTNER, "billing_mode": "per_click", "company_name": "Acme",
           "default_cpc": 0.5, "posting_price": 1.0, "postings_remaining": 10,
           "balance": 100.0, "total_spent": 0.0}
    doc.update(kw)
    await db.partner_profiles.insert_one(doc)


async def _seed_marker_and_index(db):
    await db.migration_flags.insert_one({"_id": P0007_MARKER, "applied_at": datetime.utcnow()})
    await db.jobs.create_index(
        [("partner_id", 1), ("campaign_id", 1), ("external_ref", 1)],
        name=INDEX_NAME, unique=True,
        partialFilterExpression={"campaign_id": {"$type": "string"}})


def _run(coro):
    return asyncio.run(coro)


class TestRealMongoFailClosed:
    def test_real_no_marker_no_index_campaign_creation_503(self, feed_module):
        if not _mongo_reachable(REPLICA_SET_URL):
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_fail_{uuid.uuid4().hex}"]
            try:
                await _seed_partner(db)
                try:
                    await feed_module.import_feed(
                        db, PARTNER, xml_content=_xml("r1"), cpc=0.5,
                        billing_mode="per_click", campaign_id="c1")
                    assert False
                except _HTTPException as exc:
                    assert exc.status_code == 503
                # index absent => marqueur absent => aucune création
                names = {i["name"] for i in await db.jobs.list_indexes().to_list(length=100)}
                assert INDEX_NAME not in names
                assert await db.migration_flags.count_documents({}) == 0
                assert await db.jobs.count_documents({}) == 0
                assert await db.companies.count_documents({}) == 0
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())

    def test_real_inconsistent_marker_without_index_stays_fail_closed(self, feed_module):
        if not _mongo_reachable(REPLICA_SET_URL):
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_incoherent_{uuid.uuid4().hex}"]
            try:
                await _seed_partner(db)
                # Marqueur posé MAIS aucun index : état partiel incohérent.
                await db.migration_flags.insert_one({"_id": P0007_MARKER, "applied_at": datetime.utcnow()})
                try:
                    await feed_module.import_feed(
                        db, PARTNER, xml_content=_xml("r1"), cpc=0.5,
                        billing_mode="per_click", campaign_id="c1")
                    assert False
                except _HTTPException as exc:
                    assert exc.status_code == 503
                    assert exc.detail and "index" in str(exc.detail).lower()
                assert await db.jobs.count_documents({}) == 0
                assert await db.companies.count_documents({}) == 0
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())


class TestRealMigration:
    def test_real_migration_creates_index_then_marker(self, feed_module, migrate_module):
        if not _mongo_reachable(REPLICA_SET_URL):
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_migr_{uuid.uuid4().hex}"]
            try:
                await _seed_partner(db)
                now = datetime.utcnow()
                await db.jobs.insert_one({
                    "_id": "j_old", "partner_id": PARTNER, "campaign_id": "cm",
                    "external_ref": "r9", "created_at": now - timedelta(hours=10),
                    "views_count": 5, "applications_count": 0, "title": "OLD",
                })
                await db.jobs.insert_one({
                    "_id": "j_new", "partner_id": PARTNER, "campaign_id": "cm",
                    "external_ref": "r9", "created_at": now - timedelta(hours=1),
                    "views_count": 3, "applications_count": 0, "title": "NEW",
                })
                await db.jobs.insert_one({
                    "_id": "j_bad", "partner_id": PARTNER, "campaign_id": "cm",
                    "external_ref": "r9", "created_at": "2026-09-01",  # invalide
                    "views_count": 1, "applications_count": 0, "title": "BAD",
                })
                # applications : collision candidate c_x sur winner/loser => dédup ;
                # candidate c_y (loser j_bad) => repointage vers le winner.
                await db.applications.insert_one({"_id": "app_w1", "job_id": "j_old", "candidate_id": "c_x"})
                await db.applications.insert_one({"_id": "app_l1", "job_id": "j_new", "candidate_id": "c_x"})
                await db.applications.insert_one({"_id": "app_l2", "job_id": "j_bad", "candidate_id": "c_y"})
                # saved_jobs : même schéma de collision.
                await db.saved_jobs.insert_one({"_id": "sv_w", "user_id": "u_x", "job_id": "j_old"})
                await db.saved_jobs.insert_one({"_id": "sv_l", "user_id": "u_x", "job_id": "j_new"})
                await db.saved_jobs.insert_one({"_id": "sv_l2", "user_id": "u_z", "job_id": "j_bad"})
                # events / messages à repointés.
                for i in range(2):
                    await db.click_events.insert_one({"_id": f"cl_{i}", "job_id": "j_new"})
                await db.click_events.insert_one({"_id": "cl_bad", "job_id": "j_bad"})
                await db.impression_events.insert_one({"_id": "imp1", "job_id": "j_new"})
                await db.messages.insert_one({"_id": "msg1", "job_id": "j_bad"})

                # L'index n'existe pas encore : les créations de campagne sont
                # fail-closed et le marqueur est absent.
                names = {i["name"] for i in await db.jobs.list_indexes().to_list(length=100)}
                assert INDEX_NAME not in names
                assert await db.migration_flags.count_documents({}) == 0
                try:
                    await feed_module.import_feed(
                        db, PARTNER, xml_content=_xml("r9"), cpc=0.5,
                        billing_mode="per_click", campaign_id="cm")
                    assert False
                except _HTTPException as exc:
                    assert exc.status_code == 503

                report = await migrate_module._migrate(db)
                assert report["groups"] == 1
                assert report["jobs_deleted"] == 2
                assert report["applications_repointed"] == 1   # app_l2 (c_y)
                assert report["applications_deduped"] == 1     # app_l1 (c_x, collision)
                assert report["saved_jobs_repointed"] == 1     # sv_l2
                assert report["saved_jobs_deduped"] == 1       # sv_l
                assert report["click_events_repointed"] == 3
                assert report["impression_events_repointed"] == 1
                assert report["messages_repointed"] == 1
                assert report["views_merged"] == 4             # 5 + 3 + 1
                assert report["index_created"] is True
                assert report["marker_set"] is True

                # INDEX CRÉÉ PUIS MARQUEUR POSÉ (dans cet ordre).
                names = {i["name"] for i in await db.jobs.list_indexes().to_list(length=100)}
                assert INDEX_NAME in names
                assert await db.migration_flags.find_one({"_id": P0007_MARKER}) is not None

                # Winner = plus ancien created_at VALIDE (j_old), jamais _id-âge.
                jobs = await db.jobs.find({"campaign_id": "cm"}).to_list(length=10)
                assert len(jobs) == 1 and jobs[0]["_id"] == "j_old"
                assert jobs[0]["views_count"] == 9             # compteurs stockés fusionnés
                assert jobs[0]["applications_count"] == 2      # app_w1(c_x) + app_l2(c_y)

                # Consolidation : unité d'unicité préservée.
                assert await db.applications.count_documents({"job_id": "j_old"}) == 2
                assert await db.saved_jobs.count_documents({"job_id": "j_old"}) == 2
                assert await db.click_events.count_documents({"job_id": "j_old"}) == 3
                assert await db.impression_events.count_documents({"job_id": "j_old"}) == 1
                assert await db.messages.count_documents({"job_id": "j_old"}) == 1

                # Après migration : l'import de campagne redevient possible.
                r = await feed_module.import_feed(
                    db, PARTNER, xml_content=_xml("r9"), cpc=0.5,
                    billing_mode="per_click", campaign_id="cm")
                assert r["imported"] >= 0

                # Idempotence : seconde exécution sans écriture.
                report2 = await migrate_module._migrate(db)
                assert report2["already_migrated"] is True
                assert await db.jobs.count_documents({"campaign_id": "cm"}) == 1
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())


class TestRealMongoCampaigns:
    def test_real_two_campaigns_same_ref_two_jobs(self, feed_module):
        if not _mongo_reachable(REPLICA_SET_URL):
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_ab_{uuid.uuid4().hex}"]
            try:
                await _seed_partner(db)
                await _seed_marker_and_index(db)
                r1 = await feed_module.import_feed(
                    db, PARTNER, xml_content=_xml("r1", title="A"), cpc=0.5,
                    billing_mode="per_click", campaign_id="c1")
                r2 = await feed_module.import_feed(
                    db, PARTNER, xml_content=_xml("r1", title="B"), cpc=0.5,
                    billing_mode="per_click", campaign_id="c2")
                assert r1["imported"] == 1 and r2["imported"] == 1
                jobs = await db.jobs.find({"external_ref": "r1"}).to_list(length=10)
                assert len(jobs) == 2
                assert {j["campaign_id"] for j in jobs} == {"c1", "c2"}
                assert {j["title"] for j in jobs} == {"A", "B"}
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())

    def test_real_reimport_updates_only_its_campaign_job(self, feed_module):
        if not _mongo_reachable(REPLICA_SET_URL):
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_reimp_{uuid.uuid4().hex}"]
            try:
                await _seed_partner(db)
                await _seed_marker_and_index(db)
                await feed_module.import_feed(db, PARTNER, xml_content=_xml("r1", title="A"),
                                              cpc=0.5, billing_mode="per_click", campaign_id="c1")
                await feed_module.import_feed(db, PARTNER, xml_content=_xml("r1", title="B"),
                                              cpc=0.5, billing_mode="per_click", campaign_id="c2")
                res = await feed_module.import_feed(db, PARTNER, xml_content=_xml("r1", title="A2"),
                                                    cpc=0.5, billing_mode="per_click", campaign_id="c1")
                assert res["updated"] == 1 and res["imported"] == 0
                jobs = await db.jobs.find({"external_ref": "r1"}).to_list(length=10)
                assert len(jobs) == 2  # jamais de doublon
                by_camp = {j["campaign_id"]: j["title"] for j in jobs}
                assert by_camp["c1"] == "A2"
                assert by_camp["c2"] == "B"  # le job de B reste inchangé
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())

    def test_real_legacy_isolation_both_ways(self, feed_module):
        if not _mongo_reachable(REPLICA_SET_URL):
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_legacy_{uuid.uuid4().hex}"]
            try:
                await _seed_partner(db)
                await _seed_marker_and_index(db)
                # 1) campaign d'abord, puis legacy même ref.
                await feed_module.import_feed(db, PARTNER, xml_content=_xml("r1"),
                                              cpc=0.5, billing_mode="per_click",
                                              campaign_id="c1")
                res = await feed_module.import_feed(db, PARTNER, xml_content=_xml("r1"),
                                                    cpc=0.5, billing_mode="per_click")
                assert res["imported"] == 1
                jobs = await db.jobs.find({"external_ref": "r1"}).to_list(length=10)
                assert len(jobs) == 2
                # 2) legacy ensuite => nouveau job legacy, NUL ne réclame l'autre.
                res2 = await feed_module.import_feed(db, PARTNER, xml_content=_xml("r2"),
                                                     cpc=0.5, billing_mode="per_click")
                assert res2["imported"] == 1
                jobs = await db.jobs.find({"external_ref": "r2"}).to_list(length=10)
                assert len(jobs) == 1 and jobs[0]["campaign_id"] is None
                legacy = await db.jobs.find({"campaign_id": None, "external_ref": "r1"}).to_list(length=10)
                assert len(legacy) == 1
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())

    def test_real_per_click_unique_index_under_concurrency(self, feed_module):
        if not _mongo_reachable(REPLICA_SET_URL):
            pytest.skip("MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_conc_{uuid.uuid4().hex}"]
            try:
                await _seed_partner(db)
                await _seed_marker_and_index(db)

                async def _one(title):
                    return await feed_module.import_feed(
                        db, PARTNER, xml_content=_xml("r1", title=title), cpc=0.5,
                        billing_mode="per_click", campaign_id="c1")

                res = await asyncio.gather(_one("A"), _one("B"))
                outs = sorted((r["imported"], r["updated"]) for r in res)
                assert outs == [(0, 1), (1, 0)]  # exactement 1 insertion, 1 update
                jobs = await db.jobs.find({"campaign_id": "c1", "external_ref": "r1"}).to_list(length=10)
                assert len(jobs) == 1  # jamais de doublon sous concurrence
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())


class TestRealPerPosting:
    def test_real_per_posting_insert_and_reimport(self, feed_module):
        if not _check_replica_set():
            pytest.skip("Replica-set MongoDB required for per_posting transactions")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_ppost_{uuid.uuid4().hex}"]
            _CLIENT_HOLDER["client"] = client
            try:
                await _seed_partner(db, billing_mode="per_posting", postings_remaining=2)
                await _seed_marker_and_index(db)

                async def _import(ref):
                    return await feed_module.import_feed(
                        db, PARTNER, xml_content=_xml(ref), cpc=0.5,
                        billing_mode="per_posting", campaign_id="c1", validity_days=30)

                r1 = await _import("r1")
                assert r1["imported"] == 1 and r1["charged"] == pytest.approx(1.0)
                assert r1["postings_remaining"] == 1
                prof = await db.partner_profiles.find_one({"user_id": PARTNER})
                assert prof["postings_remaining"] == 1
                assert prof["total_spent"] == pytest.approx(1.0)
                job = await db.jobs.find_one({"campaign_id": "c1", "external_ref": "r1"})
                assert job["expires_at"] > datetime.utcnow()

                r2 = await _import("r1")  # réimport : update, aucun débit
                assert r2["imported"] == 0 and r2["updated"] == 1
                assert r2["charged"] == 0 and r2["postings_remaining"] == 1
                prof = await db.partner_profiles.find_one({"user_id": PARTNER})
                assert prof["postings_remaining"] == 1
                assert prof["total_spent"] == pytest.approx(1.0)
                job2 = await db.jobs.find_one({"campaign_id": "c1", "external_ref": "r1"})
                assert job2["expires_at"] == job["expires_at"]
                assert (await db.jobs.count_documents({"external_ref": "r1"})) == 1
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())

    def test_real_per_posting_concurrency_one_posting(self, feed_module):
        if not _check_replica_set():
            pytest.skip("Replica-set MongoDB required for per_posting transactions")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_ppconc_{uuid.uuid4().hex}"]
            _CLIENT_HOLDER["client"] = client
            try:
                await _seed_partner(db, billing_mode="per_posting", postings_remaining=1)
                await _seed_marker_and_index(db)

                async def _one():
                    return await feed_module.import_feed(
                        db, PARTNER, xml_content=_xml("r1"), cpc=0.5,
                        billing_mode="per_posting", campaign_id="c1", validity_days=30)

                res = await asyncio.gather(_one(), _one())
                ins = [r for r in res if r["imported"] == 1]
                ups = [r for r in res if r["imported"] == 0 and r["updated"] == 1]
                assert len(ins) == 1 and len(ups) == 1  # 1 insertion, exactement 1 débit
                assert sum(r["charged"] for r in res) == pytest.approx(1.0)
                jobs = await db.jobs.find({"campaign_id": "c1", "external_ref": "r1"}).to_list(length=10)
                assert len(jobs) == 1  # 1 posting => 1 seul job
                prof = await db.partner_profiles.find_one({"user_id": PARTNER})
                assert prof["postings_remaining"] == 0
                assert prof["total_spent"] == pytest.approx(1.0)  # jamais 2 débits
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())

    def test_real_per_posting_zero_posting_no_job(self, feed_module):
        if not _check_replica_set():
            pytest.skip("Replica-set MongoDB required for per_posting transactions")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_ppzero_{uuid.uuid4().hex}"]
            _CLIENT_HOLDER["client"] = client
            try:
                await _seed_partner(db, billing_mode="per_posting", postings_remaining=0)
                await _seed_marker_and_index(db)
                res = await feed_module.import_feed(
                    db, PARTNER, xml_content=_xml("r1"), cpc=0.5,
                    billing_mode="per_posting", campaign_id="c1", validity_days=30)
                assert res["skipped_no_credit"] == 1
                assert res["imported"] == 0 and res["charged"] == 0
                assert await db.jobs.count_documents({}) == 0
                prof = await db.partner_profiles.find_one({"user_id": PARTNER})
                assert prof["postings_remaining"] == 0
                assert prof["total_spent"] == 0
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())

    def test_real_per_posting_charged_exact_per_invocation(self, feed_module):
        if not _check_replica_set():
            pytest.skip("Replica-set MongoDB required for per_posting transactions")

        async def scenario():
            client = AsyncIOMotorClient(REPLICA_SET_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_ppcharged_{uuid.uuid4().hex}"]
            _CLIENT_HOLDER["client"] = client
            try:
                await _seed_partner(db, billing_mode="per_posting", postings_remaining=2)
                await _seed_marker_and_index(db)

                async def _import(ref):
                    return await feed_module.import_feed(
                        db, PARTNER, xml_content=_xml(ref), cpc=0.5,
                        billing_mode="per_posting", campaign_id="c1", validity_days=30)

                r1 = await _import("r1")
                assert r1["charged"] == pytest.approx(1.0)
                r1b = await _import("r1")
                assert r1b["charged"] == 0  # réimport : jamais de nouveau post
                r2 = await _import("r2")
                assert r2["charged"] == pytest.approx(1.0)
                prof = await db.partner_profiles.find_one({"user_id": PARTNER})
                assert prof["postings_remaining"] == 0
                assert prof["total_spent"] == pytest.approx(2.0)
                assert (await db.jobs.count_documents({"campaign_id": "c1"})) == 2
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())


class TestRealStandaloneClosed:
    def test_real_standalone_per_posting_503_zero_writes(self, feed_module):
        if not _check_standalone():
            pytest.skip("Standalone MongoDB not available")

        async def scenario():
            client = AsyncIOMotorClient(STANDALONE_URL, serverSelectionTimeoutMS=3000)
            db = client[f"p007_standalone_{uuid.uuid4().hex}"]
            _CLIENT_HOLDER["client"] = client
            try:
                await _seed_partner(db, billing_mode="per_posting", postings_remaining=3)
                await _seed_marker_and_index(db)

                with pytest.raises(_HTTPException) as exc:
                    await feed_module.import_feed(
                        db, PARTNER, xml_content=_xml("r1"), cpc=0.5,
                        billing_mode="per_posting", campaign_id="c1", validity_days=30)
                assert exc.value.status_code == 503

                # ZÉRO écriture : pas de job, pas de société, profil intact.
                assert await db.jobs.count_documents({}) == 0
                assert await db.companies.count_documents({}) == 0
                prof = await db.partner_profiles.find_one({"user_id": PARTNER})
                assert prof["postings_remaining"] == 3
                assert prof["total_spent"] == 0
            finally:
                await client.drop_database(db.name)
                client.close()

        _run(scenario())