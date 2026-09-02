"""P0-013 — Crédit partenaire exactement une fois après paiement.

Tests isolés (sans MongoDB réel, sans serveur backend, sans appel réseau, sans
compte seed, sans secret) qui vérifient le contrôle de flux exact de
`_credit_if_paid` pour `partner_topup` et `posting_pack`.

Règles métier obligatoires testées :
- Un `partner_topup` payé doit incrémenter `partner_profiles.balance` exactement
  une fois par `session_id`.
- Un `posting_pack` payé doit incrémenter `partner_profiles.postings_remaining`
  exactement une fois par `session_id`.
- L'effet financier autoritatif doit être atomiquement idempotent dans LE MÊME
  document `partner_profiles`, via un marqueur durable de `session_id`
  (`credited_sessions`) ajouté dans la même opération que le `$inc`.
- `payment_transactions.credited=True` est un marqueur secondaire : il ne peut
  être posé qu'APRÈS confirmation de l'effet autoritatif.
- Crash après effet mais avant `credited=True` : le retry doit détecter le
  `session_id` déjà appliqué, ne pas ré-incrémenter, puis finaliser le marqueur.
- Concurrence webhook + `/payments/status/{session_id}` : un seul effet financier,
  au plus une transition `credited=False -> True`, reçu best-effort une seule
  fois si possible.
- Si `partner_profiles` est absent : aucun crédit fantôme, `credited` reste
  false, erreur/retry explicite (503) ; ne jamais perdre définitivement un
  paiement confirmé.
- Ne PAS modifier `total_spent` lors d'un topup ou achat de pack.
- Ne pas modifier `recruiter_pack`, Stripe Checkout/idempotency key, index
  session, CPC, feed, lifecycle, géolocalisation, email normalization.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
PAYMENTS_PATH = BACKEND_DIR / "routes" / "payments.py"

PARTNER_ID = "partner_p013"
SESSION_ID = "cs_p013_test"
EMAIL = "p013@test.example"


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


class _UpdateResult:
    def __init__(self, modified_count):
        self.modified_count = modified_count


# --------------------------------------------------------------------------- #
# Fake MongoDB with atomic match+update semantics                             #
# --------------------------------------------------------------------------- #
class _Collection:
    """Backing collection with atomic match+update semantics.

    Writes are applied immediately and recorded for verification. A per-collection
    lock serializes concurrent mutations, mirroring real single-document atomicity.
    """

    def __init__(self, name=""):
        self.name = name
        self._lock = asyncio.Lock()
        self._docs = {}

    def seed_partner(self, **fields):
        base = {
            "user_id": PARTNER_ID,
            "company_name": "Test Company",
            "billing_mode": "per_click",
            "default_cpc": 0.5,
            "posting_price": 10.0,
            "balance": 0.0,
            "postings_remaining": 0,
            "total_clicks": 0,
            "total_spent": 0.0,
            "credited_sessions": [],
            "low_balance_notified": False,
        }
        base.update(fields)
        self._docs[PARTNER_ID] = base
        return self

    def seed_transaction(self, *, kind="partner_topup", amount=50.0, postings=5, credited=False, payment_status="paid"):
        self._docs[SESSION_ID] = {
            "_id": SESSION_ID,
            "session_id": SESSION_ID,
            "partner_id": PARTNER_ID,
            "company_name": "Test Company",
            "amount": amount,
            "currency": "eur",
            "kind": kind,
            "postings": postings,
            "status": "completed",
            "payment_status": payment_status,
            "credited": credited,
            "credited_at": None,
            "initiated_by": PARTNER_ID,
        }
        return self

    def get(self, doc_id):
        doc = self._docs.get(doc_id)
        return dict(doc) if doc is not None else None

    def docs(self):
        return {k: dict(v) for k, v in self._docs.items()}

    @staticmethod
    def _match(doc, query):
        for key, expected in query.items():
            actual = doc.get(key)
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
                if "$in" in expected:
                    if actual not in expected["$in"]:
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
                    result = dict(doc)
                    if projection:
                        result = {k: v for k, v in result.items() if projection.get(k, 0) == 1}
                    return result
            return None

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
                    return _UpdateResult(1 if changed else 0)
            return _UpdateResult(0)


class _NoopCollection:
    async def find_one(self, query):
        return None

    async def update_one(self, query, update, session=None):
        return _UpdateResult(0)


class _FakeClient:
    def __init__(self):
        self.db = types.SimpleNamespace(
            users=_Collection("users"),
            jobs=_NoopCollection(),
            companies=_NoopCollection(),
            payment_transactions=_Collection("payment_transactions"),
            partner_profiles=_Collection("partner_profiles"),
            click_events=_NoopCollection(),
            campaigns=_NoopCollection(),
            files=_NoopCollection(),
            import_logs=_NoopCollection(),
            impression_events=_NoopCollection(),
            migration_flags=_NoopCollection(),
        )


# --------------------------------------------------------------------------- #
# Import stubs                                                                #
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
    geo.resolve_location_codes = lambda *a, **k: []
    geo.geocode_place = lambda *a, **k: None
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

    email_service = types.ModuleType("email_service")
    email_service.send_alert_email = lambda *a, **k: None
    email_service.build_topup_receipt_email = lambda *a, **k: ("subject", "html")
    monkeypatch.setitem(sys.modules, "email_service", email_service)


def _mock_stripe_retrieve_paid(monkeypatch):
    """Mock stripe.checkout.Session.retrieve to return a paid session."""
    stripe = sys.modules["stripe"]
    class MockSession:
        payment_status = "paid"
        status = "complete"
        payment_intent = "pi_test"
    def mock_retrieve(session_id):
        return MockSession()
    stripe.checkout.Session.retrieve = mock_retrieve


def _mock_stripe_retrieve_not_paid(monkeypatch):
    """Mock stripe.checkout.Session.retrieve to return a non-paid session."""
    stripe = sys.modules["stripe"]
    class MockSession:
        payment_status = "pending"
        status = "open"
        payment_intent = None
    def mock_retrieve(session_id):
        return MockSession()
    stripe.checkout.Session.retrieve = mock_retrieve


@pytest.fixture
def payments_module(monkeypatch):
    _install_import_stubs(monkeypatch)
    _install_payments_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location("routes_payments_p013", PAYMENTS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._ensure_stripe = lambda: None
    module._HTTPException = _HTTPException
    return module


class _PaymentsContext:
    def __init__(self, payments_module, client):
        self.payments_module = payments_module
        self.client = client
        self.receipt_calls = 0

    async def _counting_receipt(self, db, record):
        self.receipt_calls += 1

    def patch_receipt(self):
        self.payments_module._send_receipt = self._counting_receipt


async def _credit(payments_module, client, session_id):
    async def _get_database():
        return client.db

    payments_module.get_database = _get_database
    return await payments_module._credit_if_paid(client.db, session_id)


# --------------------------------------------------------------------------- #
# Tests: Happy path topup                                                     #
# --------------------------------------------------------------------------- #
def test_partner_topup_happy_path_credits_balance_once(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(balance=100.0)
    client.db.payment_transactions.seed_transaction(kind="partner_topup", amount=50.0)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    rec = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec["credited"] is True
    assert rec["credited_at"] is not None
    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["balance"] == 150.0
    assert SESSION_ID in profile["credited_sessions"]
    assert profile["credited_sessions"].count(SESSION_ID) == 1
    assert profile["low_balance_notified"] is False
    assert profile["total_spent"] == 0.0  # unchanged
    assert ctx.receipt_calls == 1


def test_posting_pack_happy_path_credits_postings_once(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(postings_remaining=10)
    client.db.payment_transactions.seed_transaction(kind="posting_pack", postings=20, amount=200.0)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    rec = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec["credited"] is True
    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["postings_remaining"] == 30
    assert SESSION_ID in profile["credited_sessions"]
    assert profile["credited_sessions"].count(SESSION_ID) == 1
    assert profile["total_spent"] == 0.0  # unchanged
    assert ctx.receipt_calls == 1


# --------------------------------------------------------------------------- #
# Tests: Concurrency - two calls same session => single $inc                  #
# --------------------------------------------------------------------------- #
def test_concurrent_topup_same_session_single_increment(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(balance=0.0)
    client.db.payment_transactions.seed_transaction(kind="partner_topup", amount=100.0)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    async def scenario():
        return await asyncio.gather(
            _credit(payments_module, client, SESSION_ID),
            _credit(payments_module, client, SESSION_ID),
        )

    r1, r2 = asyncio.run(scenario())

    assert r1["credited"] is True
    assert r2["credited"] is True
    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["balance"] == 100.0
    assert profile["credited_sessions"].count(SESSION_ID) == 1
    assert ctx.receipt_calls == 1  # exactly one receipt


def test_concurrent_posting_pack_same_session_single_increment(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(postings_remaining=0)
    client.db.payment_transactions.seed_transaction(kind="posting_pack", postings=10)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    async def scenario():
        return await asyncio.gather(
            _credit(payments_module, client, SESSION_ID),
            _credit(payments_module, client, SESSION_ID),
        )

    r1, r2 = asyncio.run(scenario())

    assert r1["credited"] is True
    assert r2["credited"] is True
    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["postings_remaining"] == 10
    assert profile["credited_sessions"].count(SESSION_ID) == 1
    assert ctx.receipt_calls == 1


# --------------------------------------------------------------------------- #
# Tests: Crash after effect but before credited=True => retry finalizes marker #
# --------------------------------------------------------------------------- #
def test_topup_crash_after_effect_before_credited_retry_finalizes(payments_module):
    """Simulate crash after authoritative effect but before credited=True marker.
    Retry must not double-credit, must finalize credited=True."""
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(balance=0.0)
    client.db.payment_transactions.seed_transaction(kind="partner_topup", amount=75.0)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    # First call: let the authoritative effect apply, but intercept the
    # payment_transactions update to simulate crash (don't apply credited=True).
    original_pt_update = client.db.payment_transactions.update_one

    async def crash_on_credited_update(query, update, session=None):
        # Allow the partner_profiles update to proceed (it happens first)
        # But block the credited=True update on payment_transactions
        if query.get("session_id") == SESSION_ID and "credited" in str(query):
            return _UpdateResult(0)  # simulate crash: update not applied
        return await original_pt_update(query, update, session)

    client.db.payment_transactions.update_one = crash_on_credited_update

    # First call - authoritative effect applies, but credited stays False
    rec1 = asyncio.run(_credit(payments_module, client, SESSION_ID))

    # Restore normal behavior
    client.db.payment_transactions.update_one = original_pt_update

    # After crash: effect applied, credited_sessions has session, but credited=False
    profile_after_crash = client.db.partner_profiles.get(PARTNER_ID)
    assert profile_after_crash["balance"] == 75.0
    assert SESSION_ID in profile_after_crash["credited_sessions"]
    tx_after_crash = client.db.payment_transactions.get(SESSION_ID)
    assert tx_after_crash["credited"] is False

    # Retry: should detect session already credited, not increment again, finalize marker
    rec2 = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec2["credited"] is True
    profile_after_retry = client.db.partner_profiles.get(PARTNER_ID)
    assert profile_after_retry["balance"] == 75.0  # no double increment
    assert profile_after_retry["credited_sessions"].count(SESSION_ID) == 1
    tx_after_retry = client.db.payment_transactions.get(SESSION_ID)
    assert tx_after_retry["credited"] is True
    assert ctx.receipt_calls == 1  # receipt only on final transition


def test_posting_pack_crash_after_effect_before_credited_retry_finalizes(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(postings_remaining=5)
    client.db.payment_transactions.seed_transaction(kind="posting_pack", postings=15)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    original_pt_update = client.db.payment_transactions.update_one

    async def crash_on_credited_update(query, update, session=None):
        if query.get("session_id") == SESSION_ID and "credited" in str(query):
            return _UpdateResult(0)
        return await original_pt_update(query, update, session)

    client.db.payment_transactions.update_one = crash_on_credited_update
    rec1 = asyncio.run(_credit(payments_module, client, SESSION_ID))
    client.db.payment_transactions.update_one = original_pt_update

    profile_after_crash = client.db.partner_profiles.get(PARTNER_ID)
    assert profile_after_crash["postings_remaining"] == 20
    assert SESSION_ID in profile_after_crash["credited_sessions"]
    assert client.db.payment_transactions.get(SESSION_ID)["credited"] is False

    rec2 = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec2["credited"] is True
    profile_after_retry = client.db.partner_profiles.get(PARTNER_ID)
    assert profile_after_retry["postings_remaining"] == 20  # no double increment
    assert profile_after_retry["credited_sessions"].count(SESSION_ID) == 1
    assert client.db.payment_transactions.get(SESSION_ID)["credited"] is True
    assert ctx.receipt_calls == 1


# --------------------------------------------------------------------------- #
# Tests: Partner profile absent => 503 + credited false                       #
# --------------------------------------------------------------------------- #
def test_topup_partner_profile_absent_503_credited_false(payments_module):
    client = _FakeClient()
    # No partner profile seeded
    client.db.payment_transactions.seed_transaction(kind="partner_topup", amount=50.0)

    with pytest.raises(_HTTPException) as exc:
        asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert exc.value.status_code == 503
    assert "non confirmé" in (exc.value.detail or "")
    tx = client.db.payment_transactions.get(SESSION_ID)
    assert tx["credited"] is False
    # No phantom credit created
    assert PARTNER_ID not in client.db.partner_profiles._docs


def test_posting_pack_partner_profile_absent_503_credited_false(payments_module):
    client = _FakeClient()
    client.db.payment_transactions.seed_transaction(kind="posting_pack", postings=10)

    with pytest.raises(_HTTPException) as exc:
        asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert exc.value.status_code == 503
    tx = client.db.payment_transactions.get(SESSION_ID)
    assert tx["credited"] is False
    assert PARTNER_ID not in client.db.partner_profiles._docs


# --------------------------------------------------------------------------- #
# Tests: Session already in credited_sessions + credited=false => no new $inc #
# --------------------------------------------------------------------------- #
def test_topup_session_already_credited_no_new_inc_finalizes_marker(payments_module):
    """Profile already has session in credited_sessions (effect applied earlier),
    but payment_transactions.credited is still False. Retry must not increment
    again, must finalize credited=True."""
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(balance=200.0, credited_sessions=[SESSION_ID])
    client.db.payment_transactions.seed_transaction(kind="partner_topup", amount=50.0, credited=False)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    rec = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec["credited"] is True
    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["balance"] == 200.0  # no new increment
    assert profile["credited_sessions"].count(SESSION_ID) == 1
    assert ctx.receipt_calls == 1


def test_posting_pack_session_already_credited_no_new_inc_finalizes_marker(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(postings_remaining=30, credited_sessions=[SESSION_ID])
    client.db.payment_transactions.seed_transaction(kind="posting_pack", postings=10, credited=False)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    rec = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec["credited"] is True
    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["postings_remaining"] == 30  # no new increment
    assert profile["credited_sessions"].count(SESSION_ID) == 1
    assert ctx.receipt_calls == 1


# --------------------------------------------------------------------------- #
# Tests: total_spent unchanged                                                #
# --------------------------------------------------------------------------- #
def test_topup_total_spent_unchanged(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(balance=0.0, total_spent=500.0)
    client.db.payment_transactions.seed_transaction(kind="partner_topup", amount=100.0)

    asyncio.run(_credit(payments_module, client, SESSION_ID))

    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["total_spent"] == 500.0
    assert profile["balance"] == 100.0


def test_posting_pack_total_spent_unchanged(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(postings_remaining=0, total_spent=300.0)
    client.db.payment_transactions.seed_transaction(kind="posting_pack", postings=20)

    asyncio.run(_credit(payments_module, client, SESSION_ID))

    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["total_spent"] == 300.0
    assert profile["postings_remaining"] == 20


# --------------------------------------------------------------------------- #
# Tests: recruiter_pack unchanged                                             #
# --------------------------------------------------------------------------- #
def test_recruiter_pack_logic_unchanged(payments_module):
    """Verify recruiter_pack still uses users collection with granted_sessions,
    not partner_profiles."""
    client = _FakeClient()
    client.db.users._docs["user_recruiter"] = {
        "_id": "user_recruiter",
        "email": "recruiter@test.example",
        "user_type": "employer",
        "premium_credits": 0,
        "granted_sessions": [],
        "hashed_password": "x",
        "is_active": True,
    }
    client.db.payment_transactions._docs[SESSION_ID] = {
        "_id": SESSION_ID,
        "session_id": SESSION_ID,
        "user_id": "user_recruiter",
        "kind": "recruiter_pack",
        "postings": 5,
        "payment_status": "paid",
        "credited": False,
    }
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    # Patch _send_recruiter_receipt instead
    async def _counting_recruiter_receipt(db, record):
        ctx.receipt_calls += 1
    payments_module._send_recruiter_receipt = _counting_recruiter_receipt

    rec = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec["credited"] is True
    user = client.db.users.get("user_recruiter")
    assert user["premium_credits"] == 5
    assert SESSION_ID in user["granted_sessions"]
    # partner_profiles should not be touched
    assert PARTNER_ID not in client.db.partner_profiles._docs
    assert ctx.receipt_calls == 1


# --------------------------------------------------------------------------- #
# Tests: Regression - P0-004/005/006/007 not affected                         #
# --------------------------------------------------------------------------- #
def test_regression_p005_recruiter_pack_still_works(payments_module):
    """P0-005 recruiter_pack grant logic must remain intact."""
    client = _FakeClient()
    client.db.users._docs["user_p005"] = {
        "_id": "user_p005",
        "email": "p005@test.example",
        "user_type": "employer",
        "premium_credits": 0,
        "granted_sessions": [],
        "hashed_password": "x",
        "is_active": True,
    }
    client.db.payment_transactions._docs["cs_p005"] = {
        "_id": "cs_p005",
        "session_id": "cs_p005",
        "user_id": "user_p005",
        "kind": "recruiter_pack",
        "postings": 3,
        "payment_status": "paid",
        "credited": False,
    }

    rec = asyncio.run(_credit(payments_module, client, "cs_p005"))

    assert rec["credited"] is True
    user = client.db.users.get("user_p005")
    assert user["premium_credits"] == 3
    assert "cs_p005" in user["granted_sessions"]


def test_regression_p005_recruiter_pack_concurrent_single_grant(payments_module):
    """P0-005: concurrent recruiter_pack calls grant exactly once."""
    client = _FakeClient()
    client.db.users._docs["user_p005"] = {
        "_id": "user_p005",
        "email": "p005@test.example",
        "user_type": "employer",
        "premium_credits": 0,
        "granted_sessions": [],
        "hashed_password": "x",
        "is_active": True,
    }
    client.db.payment_transactions._docs["cs_p005_concurrent"] = {
        "_id": "cs_p005_concurrent",
        "session_id": "cs_p005_concurrent",
        "user_id": "user_p005",
        "kind": "recruiter_pack",
        "postings": 7,
        "payment_status": "paid",
        "credited": False,
    }

    async def scenario():
        return await asyncio.gather(
            _credit(payments_module, client, "cs_p005_concurrent"),
            _credit(payments_module, client, "cs_p005_concurrent"),
        )

    r1, r2 = asyncio.run(scenario())
    assert r1["credited"] is True
    assert r2["credited"] is True
    user = client.db.users.get("user_p005")
    assert user["premium_credits"] == 7
    assert user["granted_sessions"].count("cs_p005_concurrent") == 1


# --------------------------------------------------------------------------- #
# Tests: low_balance_notified reset only for topup                            #
# --------------------------------------------------------------------------- #
def test_topup_resets_low_balance_notified(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(balance=0.0, low_balance_notified=True)
    client.db.payment_transactions.seed_transaction(kind="partner_topup", amount=50.0)

    asyncio.run(_credit(payments_module, client, SESSION_ID))

    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["low_balance_notified"] is False


def test_posting_pack_does_not_touch_low_balance_notified(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(postings_remaining=0, low_balance_notified=True)
    client.db.payment_transactions.seed_transaction(kind="posting_pack", postings=10)

    asyncio.run(_credit(payments_module, client, SESSION_ID))

    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["low_balance_notified"] is True  # unchanged for posting_pack


# --------------------------------------------------------------------------- #
# Tests: Non-paid status should not credit                                    #
# --------------------------------------------------------------------------- #
def test_topup_not_paid_does_not_credit(payments_module, monkeypatch):
    _mock_stripe_retrieve_not_paid(monkeypatch)
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(balance=0.0)
    client.db.payment_transactions.seed_transaction(kind="partner_topup", amount=50.0, payment_status="pending")

    rec = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec["credited"] is False
    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["balance"] == 0.0
    assert SESSION_ID not in profile.get("credited_sessions", [])


def test_posting_pack_not_paid_does_not_credit(payments_module, monkeypatch):
    _mock_stripe_retrieve_not_paid(monkeypatch)
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(postings_remaining=0)
    client.db.payment_transactions.seed_transaction(kind="posting_pack", postings=10, payment_status="pending")

    rec = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec["credited"] is False
    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["postings_remaining"] == 0
    assert SESSION_ID not in profile.get("credited_sessions", [])


# --------------------------------------------------------------------------- #
# Tests: Already credited transaction (idempotent)                            #
# --------------------------------------------------------------------------- #
def test_topup_already_credited_idempotent(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(balance=100.0, credited_sessions=[SESSION_ID])
    client.db.payment_transactions.seed_transaction(kind="partner_topup", amount=50.0, credited=True)

    rec = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec["credited"] is True
    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["balance"] == 100.0  # no change


def test_posting_pack_already_credited_idempotent(payments_module):
    client = _FakeClient()
    client.db.partner_profiles.seed_partner(postings_remaining=20, credited_sessions=[SESSION_ID])
    client.db.payment_transactions.seed_transaction(kind="posting_pack", postings=10, credited=True)

    rec = asyncio.run(_credit(payments_module, client, SESSION_ID))

    assert rec["credited"] is True
    profile = client.db.partner_profiles.get(PARTNER_ID)
    assert profile["postings_remaining"] == 20  # no change