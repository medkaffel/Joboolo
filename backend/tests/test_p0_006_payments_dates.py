"""P0-006 : tests déterministes de la validation des dates de campagne créée /
mise à jour (backend/routes/payments.py).

Nécessite aucun service externe ni Mongo : on stube fastapi/pydantic/stripe et
les modules internes non testés pour importer `payments.py`, puis on exerce les
fonctions pures `_validate_campaign_dates` et `_validate_campaign_status`.

Couvre :
- format strict YYYY-MM-DD + vraie date calendrier (400 sinon) ;
- état final fusionné start_date <= end_date (400 sinon) ;
- update partielle : une borne envoyée est validée contre l'autre borne déjà
  stockée (incohérence => 400) ;
- status restreint à active|paused.
"""
import asyncio
import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
PAYMENTS_PATH = BACKEND_DIR / "routes" / "payments.py"


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


def _install_stubs(monkeypatch):
    fastapi = types.ModuleType("fastapi")
    fastapi.APIRouter = _Router
    fastapi.HTTPException = _HTTPException
    fastapi.Depends = lambda dependency=None, *a, **k: dependency
    fastapi.Query = lambda default=None, *a, **k: default
    fastapi.status = types.SimpleNamespace(
        HTTP_402_PAYMENT_REQUIRED=402, HTTP_403_FORBIDDEN=403,
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

    stripe = types.ModuleType("stripe")
    stripe.error = types.SimpleNamespace(
        StripeError=Exception, SignatureVerificationError=Exception)
    stripe.checkout = types.SimpleNamespace(
        Session=types.SimpleNamespace(create=lambda **k: types.SimpleNamespace(
            id="s", url="u", payment_intent="pi")))
    stripe.Webhook = types.SimpleNamespace(construct_event=lambda *a, **k: {})
    monkeypatch.setitem(sys.modules, "stripe", stripe)

    models = types.ModuleType("models")
    for name in ("Job", "JobCreate", "JobUpdate", "JobResponse", "JobSearchQuery",
                 "JobSearchResponse", "User"):
        setattr(models, name, _Model)
    models.UserType = types.SimpleNamespace(
        EMPLOYER="employer", CANDIDATE="candidate", PARTNER="partner", ADMIN="admin")
    monkeypatch.setitem(sys.modules, "models", models)

    database = types.ModuleType("database")
    database.get_database = lambda: None
    database.get_client = lambda: None
    monkeypatch.setitem(sys.modules, "database", database)

    auth = types.ModuleType("auth")
    auth.get_current_active_user = lambda *a, **k: None
    auth.require_employer = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "auth", auth)

    storage = types.ModuleType("storage")
    storage.put_object = lambda *a, **k: {"path": "p"}
    storage.APP_NAME = "test"
    monkeypatch.setitem(sys.modules, "storage", storage)

    config = types.ModuleType("config")
    config.get_settings = lambda: types.SimpleNamespace(
        STRIPE_SECRET_KEY=None, STRIPE_WEBHOOK_SECRET=None)
    monkeypatch.setitem(sys.modules, "config", config)


@pytest.fixture
def payments(monkeypatch):
    _install_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location("p006_payments", PAYMENTS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# _validate_campaign_dates — format et calendrier réels                      #
# --------------------------------------------------------------------------- #
def test_valid_dates_accepted(payments):
    payments._validate_campaign_dates("2026-01-01", "2026-12-31")  # no raise


def test_valid_single_boundary_accepted(payments):
    payments._validate_campaign_dates("2026-01-01", None)
    payments._validate_campaign_dates(None, "2026-12-31")
    payments._validate_campaign_dates(None, None)


def test_clearing_with_empty_string_accepted(payments):
    # '' = suppression de la borne (aucune contrainte)
    payments._validate_campaign_dates("", "")


def test_invalid_format_rejected(payments):
    for bad in ("01/01/2026", "2026-1-1", "2026-13-01", "2026-00-10",
                "2026-01-32", "2026-02-30", "not-a-date", "2026-01", "20260101"):
        with pytest.raises(_HTTPException) as e:
            payments._validate_campaign_dates(bad, None)
        assert e.value.status_code == 400

    with pytest.raises(_HTTPException) as e:
        payments._validate_campaign_dates(None, "bad-end")
    assert e.value.status_code == 400


def test_non_calendar_day_rejected(payments):
    # 30 février n'existe pas => 400
    with pytest.raises(_HTTPException) as e:
        payments._validate_campaign_dates("2026-02-30", None)
    assert e.value.status_code == 400


def test_junk_suffix_date_rejected(payments):
    # Strict : une valeur avec suffixe, ISO ou espace interne est rejetée (400),
    # fail-closed. (Des espaces purement extérieurs sont trimés par la saisie.)
    for bad in ("2026-09-01junk", "2026-09-01T10:00:00", "2026-09-01 09",
                "2026-09-01x", "2026-09 01", "2026/09/01", "2026-1-1"):
        with pytest.raises(_HTTPException) as e:
            payments._validate_campaign_dates(bad, None)
        assert e.value.status_code == 400


# --------------------------------------------------------------------------- #
# _validate_campaign_dates — normalisation AVANT écriture                     #
# --------------------------------------------------------------------------- #
def test_outer_spaces_normalized_before_write(payments):
    # Régression : une borne avec des espaces extérieurs est acceptée MAIS sa
    # valeur NORMALISÉE (trim, strict YYYY-MM-DD) doit être renvoyée pour être
    # stockée. Sinon la valeur brute serait stockée (invalide) puis fail-closed
    # à la lecture alors qu'elle avait été validée à l'écriture.
    start, end = payments._validate_campaign_dates("  2026-01-01  ", "  2026-12-31 ")
    assert start == "2026-01-01"
    assert end == "2026-12-31"
    assert start == start.strip() and "  " not in start


def test_outer_spaces_single_boundary_normalized(payments):
    start, end = payments._validate_campaign_dates(" 2026-05-05", None)
    assert start == "2026-05-05"
    assert end is None
    start, end = payments._validate_campaign_dates(None, "2026-05-05 ")
    assert start is None
    assert end == "2026-05-05"


def test_no_space_values_returned_as_is(payments):
    start, end = payments._validate_campaign_dates("2026-01-01", "2026-12-31")
    assert start == "2026-01-01"
    assert end == "2026-12-31"
    start, end = payments._validate_campaign_dates("", "")
    assert start is None
    assert end is None
    start, end = payments._validate_campaign_dates(None, None)
    assert start is None
    assert end is None


# --------------------------------------------------------------------------- #
# create_campaign — les dates NORMALISÉES sont réellement stockées             #
# --------------------------------------------------------------------------- #
class _CampaignsDB:
    def __init__(self):
        self.inserted = None

    async def insert_one(self, doc):
        self.inserted = doc


class _FakeDB:
    def __init__(self):
        self.campaigns = _CampaignsDB()


def _install_routes_admin_stub(monkeypatch):
    """routes.admin = get_settings requis par create_campaign (import lazy)."""
    routes = types.ModuleType("routes")
    routes.__path__ = []
    admin = types.ModuleType("routes.admin")

    async def get_settings(db):
        return {"pack_validity_days": 30}

    admin.get_settings = get_settings
    routes.admin = admin
    monkeypatch.setitem(sys.modules, "routes", routes)
    monkeypatch.setitem(sys.modules, "routes.admin", admin)


def test_create_campaign_stores_normalized_dates(payments, monkeypatch):
    # Régression : une borne saisie avec des espaces extérieurs est acceptée et
    # stockée NORMALISÉE (strict YYYY-MM-DD, sans espace). Jamais de valeur
    # brute stockée qui serait invalide à la lecture (fail-closed en cachette).
    _install_routes_admin_stub(monkeypatch)
    db = _FakeDB()

    async def _fake_db():
        return db

    payments.get_database = _fake_db
    partner = _Model(id="partner_audit", user_type="partner")
    data = _Model(
        name="C", billing_mode="per_click", cpc=None, cpc_max=None,
        pack_price=None, xml_feed_url="https://feed.example/xml", logo_url=None,
        start_date="  2026-01-01  ", end_date="  2026-12-31 ", budget_limit=None,
    )
    asyncio.run(payments.create_campaign(data, partner))
    assert db.campaigns.inserted["start_date"] == "2026-01-01"
    assert db.campaigns.inserted["end_date"] == "2026-12-31"
    assert "  " not in db.campaigns.inserted["start_date"]
    assert "  " not in db.campaigns.inserted["end_date"]

    # Le retour de la route expose les valeurs propres stockées.
    out = payments._campaign_out(db.campaigns.inserted)
    assert out["start_date"] == "2026-01-01"
    assert out["end_date"] == "2026-12-31"


# --------------------------------------------------------------------------- #
# _validate_campaign_dates — état final fusionné                              #
# --------------------------------------------------------------------------- #
def test_start_after_end_rejected(payments):
    with pytest.raises(_HTTPException) as e:
        payments._validate_campaign_dates("2026-12-31", "2026-01-01")
    assert e.value.status_code == 400


def test_start_equal_end_accepted(payments):
    payments._validate_campaign_dates("2026-05-05", "2026-05-05")


def test_partial_update_against_stored_bound_inconsistent(payments):
    # Simule une update partielle : l'utilisateur envoie un nouveau start_date
    # postérieur à l'end_date déjà stockée => 400.
    stored_end = "2026-06-01"
    new_start = "2026-07-01"
    with pytest.raises(_HTTPException) as e:
        payments._validate_campaign_dates(new_start, stored_end)
    assert e.value.status_code == 400


def test_partial_update_against_stored_bound_consistent(payments):
    stored_end = "2026-06-01"
    new_start = "2026-01-01"
    payments._validate_campaign_dates(new_start, stored_end)  # no raise


def test_partial_update_end_against_stored_start_inconsistent(payments):
    stored_start = "2026-05-01"
    new_end = "2026-01-01"
    with pytest.raises(_HTTPException) as e:
        payments._validate_campaign_dates(stored_start, new_end)
    assert e.value.status_code == 400


# --------------------------------------------------------------------------- #
# _validate_campaign_status                                                   #
# --------------------------------------------------------------------------- #
def test_valid_statuses_accepted(payments):
    payments._validate_campaign_status(None)  # pas de changement
    payments._validate_campaign_status("active")
    payments._validate_campaign_status("paused")


def test_invalid_status_rejected(payments):
    for bad in ("archived", "ACTIVE", "deleted", 123):
        with pytest.raises(_HTTPException) as e:
            payments._validate_campaign_status(bad)
        assert e.value.status_code == 400
