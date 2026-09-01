"""P0-005 — Recruiter entitlements: isolated tests.

No real MongoDB, backend server, network call, seeded account, or secret is used.
A small in-memory model of MongoDB's atomic find-filter + update semantics AND of
client sessions / multi-document transactions verifies, for the route's exact
control flow, that:

- standard (non-premium) job creation consumes nothing;
- premium creation consumes exactly one entitlement only when the whole
  transaction succeeds (commit => both user debit and job insert);
- premium with insufficient credits fails with 402 and no write;
- two concurrent premium creations with a single credit => exactly one success;
- premium_credits never goes negative;
- an insertion failure inside the transaction rolls the debit back (no lost credit);
- an unsupported transaction topology fails closed (503) with zero writes;
- the Stripe recruiter_pack grant is idempotent under double call;
- a crash/retry after grant but before ``credited=True`` does not double-grant;
- a missing/absent user leaves the transaction uncredited for retry.
"""

import asyncio
import importlib.util
import sys
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
JOBS_PATH = BACKEND_DIR / "routes" / "jobs.py"
PAYMENTS_PATH = BACKEND_DIR / "routes" / "payments.py"

USER_ID = "user_premium"
COMPANY_ID = "company_premium"
EMAIL = "premium@example.test"


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
    """Model of Mongo raising when a replica set is required for transactions."""

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

    # ---- document-level helpers (tests) ----
    def seed_user(self, **fields):
        base = {"_id": USER_ID, "email": EMAIL, "user_type": "employer", "premium_credits": 0,
                "granted_sessions": [], "hashed_password": "x", "is_active": True}
        base.update(fields)
        self._docs[USER_ID] = base
        return self

    def seed_job(self, job_id, **fields):
        self._docs[job_id] = dict(fields) if fields else {"_id": job_id}
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
                        # Mongo: $ne on an array field => the doc matches only if
                        # the array does NOT contain the value.
                        if ne_value in actual:
                            return False
                    elif actual == ne_value:
                        return False
                if "$gte" in expected:
                    if actual is None or actual < expected["$gte"]:
                        return False
            else:
                if isinstance(actual, list):
                    # Mongo: scalar equality on an array field => array contains value
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
                    if session is not None and session._txn_active:
                        session._journal.append((self.name, "update", doc_id, before))
                    return _UpdateResult(1 if changed else 0)
            return _UpdateResult(0)

    async def insert_one(self, document, session=None):
        async with self._lock:
            doc = dict(document)
            doc_id = doc["_id"]
            self._docs[doc_id] = doc
            if session is not None and session._txn_active:
                session._journal.append((self.name, "insert", doc_id))
            return types.SimpleNamespace(inserted_id=doc_id)

    def _undo(self, ops):
        """Build a coroutine that reverts this collection's journal entries.

        ops entries: ("update", doc_id, before) or ("insert", doc_id).
        """
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


class _NoopCollection:
    async def find_one(self, query):
        return None

    async def update_one(self, query, update, session=None):
        return _UpdateResult(0)


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
        # Motor: returns a TransactionOptions usable directly in `async with`.
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
            # abort => rollback every write performed in the transaction
            await _rollback_journal(self._session._client, self._session._journal)
            return False
        # commit => keep writes
        return False


async def _rollback_journal(client, journal):
    # journal entries are namespaced: (coll, "update", doc_id, before) or
    # (coll, "insert", doc_id). Group by collection so each collection undoes
    # only its own ops (replica-set semantics: abort reverts all writes of the tx).
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
            click_events=_NoopCollection(),
            campaigns=_NoopCollection(),
        )
        self._started_sessions = 0

    async def start_session(self):
        self._started_sessions += 1
        return _FakeSession(self)


# --------------------------------------------------------------------------- #
# Import stubs                                 r                                #
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
    # stripe: only used inside functions (all stubbed in the fixture)
    monkeypatch.setitem(sys.modules, "stripe", types.ModuleType("stripe"))

    storage = types.ModuleType("storage")
    storage.put_object = lambda *a, **k: {"path": "x"}
    storage.APP_NAME = "joboolo"
    monkeypatch.setitem(sys.modules, "storage", storage)

    config = types.ModuleType("config")
    config.get_settings = lambda: types.SimpleNamespace(
        STRIPE_SECRET_KEY="sk_test_x", STRIPE_WEBHOOK_SECRET="whsec_x"
    )
    monkeypatch.setitem(sys.modules, "config", config)


@pytest.fixture
def jobs_module(monkeypatch):
    _install_import_stubs(monkeypatch)
    spec = importlib.util.spec_from_file_location("routes_jobs_p0005", JOBS_PATH)
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
    spec = importlib.util.spec_from_file_location("routes_payments_p0005", PAYMENTS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._ensure_stripe = lambda: None
    module._HTTPException = _HTTPException
    return module


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #
def _make_job_data(**over):
    data = {
        "title": "Dev Python", "description": "desc", "company_id": COMPANY_ID,
        "location": "Paris", "job_type": "CDI", "is_remote": False, "is_urgent": False,
        "requirements": [], "benefits": [], "tags": [], "salary_min": None,
        "salary_max": None, "salary_currency": "EUR",
        "is_premium": False,
    }
    data.update(over)
    return _Model(**data)


def _current_user(user_type="employer", id=USER_ID):
    return _Model(id=id, user_type=user_type, is_active=True, email=EMAIL)


def _wire(jobs_module, client, user=_current_user()):
    async def _get_database():
        return client.db

    jobs_module.get_database = _get_database
    # create_job resolves get_client lazily from the (stubbed) database module,
    # so wire the client there rather than on the jobs module.
    sys.modules["database"].get_client = lambda: client
    return user


class _PaymentsContext:
    def __init__(self, payments_module, client):
        self.payments_module = payments_module
        self.client = client
        self.calls = 0

    async def _recruiter_receipt(self, db, record):
        self.calls += 1

    def patch_receipt(self):
        self.payments_module._send_recruiter_receipt = self._recruiter_receipt


async def _credit(payments_module, client, session_id):
    async def _get_database():
        return client.db

    payments_module.get_database = _get_database
    return await payments_module._credit_if_paid(client.db, session_id)


# --------------------------------------------------------------------------- #
# Standard / non-premium                                                       #
# --------------------------------------------------------------------------- #
def test_standard_job_zero_credits_succeeds_no_consumption(jobs_module):
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_job(COMPANY_ID, **{"_id": COMPANY_ID, "owner_id": USER_ID})
    user = _wire(jobs_module, client)

    async def scenario():
        job = await jobs_module.create_job(_make_job_data(is_premium=False), user)
        return job

    job = asyncio.run(scenario())
    assert job is not None
    assert client.db.users.get(USER_ID)["premium_credits"] == 0
    assert len(client.db.users.docs()) == 1
    assert client._started_sessions == 0  # no transaction for standard job


def test_standard_job_preserves_existing_credits(jobs_module):
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=5)
    client.db.companies.seed_job(COMPANY_ID, **{"_id": COMPANY_ID, "owner_id": USER_ID})
    user = _wire(jobs_module, client)

    async def scenario():
        for _ in range(3):
            await jobs_module.create_job(_make_job_data(is_premium=False), user)

    asyncio.run(scenario())
    assert client.db.users.get(USER_ID)["premium_credits"] == 5


# --------------------------------------------------------------------------- #
# Premium                                                                      #
# --------------------------------------------------------------------------- #
def test_premium_zero_credits_402_no_write(jobs_module):
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_job(COMPANY_ID, **{"_id": COMPANY_ID, "owner_id": USER_ID})
    user = _wire(jobs_module, client)

    with pytest.raises(_HTTPException) as exc:
        asyncio.run(jobs_module.create_job(_make_job_data(is_premium=True), user))

    assert exc.value.status_code == 402
    assert client.db.users.get(USER_ID)["premium_credits"] == 0
    assert len(client.db.jobs.docs()) == 0
    assert client._started_sessions == 1


def test_premium_one_credit_succeeds_and_decrements(jobs_module):
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=1)
    client.db.companies.seed_job(COMPANY_ID, **{"_id": COMPANY_ID, "owner_id": USER_ID})
    user = _wire(jobs_module, client)

    job = asyncio.run(jobs_module.create_job(_make_job_data(is_premium=True), user))

    assert job is not None
    assert client.db.users.get(USER_ID)["premium_credits"] == 0
    jobs = client.db.jobs.docs()
    assert len(jobs) == 1
    created = list(jobs.values())[0]
    assert created["is_premium"] is True
    assert created["premium_granted_at"] is not None
    assert client._started_sessions == 1


def test_premium_missing_premium_credits_field_treated_as_zero(jobs_module):
    client = _FakeClient()
    client.db.users.seed_user()  # no premium_credits key
    client.db.users.get(USER_ID).pop("premium_credits", None)
    client.db.companies.seed_job(COMPANY_ID, **{"_id": COMPANY_ID, "owner_id": USER_ID})
    user = _wire(jobs_module, client)

    with pytest.raises(_HTTPException) as exc:
        asyncio.run(jobs_module.create_job(_make_job_data(is_premium=True), user))

    assert exc.value.status_code == 402
    assert len(client.db.jobs.docs()) == 0


def test_credit_never_negative_under_exhaustion(jobs_module):
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=0)
    client.db.companies.seed_job(COMPANY_ID, **{"_id": COMPANY_ID, "owner_id": USER_ID})
    user = _wire(jobs_module, client)

    errs = []
    for _ in range(10):
        try:
            asyncio.run(jobs_module.create_job(_make_job_data(is_premium=True), user))
        except _HTTPException as e:
            errs.append(e.status_code)

    assert errs == [402] * 10
    assert client.db.users.get(USER_ID)["premium_credits"] == 0
    assert len(client.db.jobs.docs()) == 0


def test_two_concurrent_premium_with_one_credit_exactly_one_succeeds(jobs_module):
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=1)
    client.db.companies.seed_job(COMPANY_ID, **{"_id": COMPANY_ID, "owner_id": USER_ID})
    user = _wire(jobs_module, client)

    async def scenario():
        async def call():
            try:
                await jobs_module.create_job(_make_job_data(is_premium=True), user)
                return "ok"
            except _HTTPException as e:
                return e.status_code

        results = await asyncio.gather(call(), call())
        return results

    results = asyncio.run(scenario())
    assert results.count("ok") == 1
    assert results.count(402) == 1
    assert client.db.users.get(USER_ID)["premium_credits"] == 0
    jobs = client.db.jobs.docs()
    assert len(jobs) == 1  # exactly one job committed


def test_insertion_failure_inside_transaction_rolls_back_credit(jobs_module):
    client = _FakeClient()
    client.db.users.seed_user(premium_credits=1)
    client.db.companies.seed_job(COMPANY_ID, **{"_id": COMPANY_ID, "owner_id": USER_ID})
    user = _wire(jobs_module, client)

    original = client.db.jobs.insert_one

    async def failing_insert(document, session=None):
        raise OSError("insert failed")

    client.db.jobs.insert_one = failing_insert

    with pytest.raises(OSError):
        asyncio.run(jobs_module.create_job(_make_job_data(is_premium=True), user))

    # Failed transaction => debit rolled back, no job
    assert client.db.users.get(USER_ID)["premium_credits"] == 1
    assert len(client.db.jobs.docs()) == 0


def test_transaction_unsupported_fails_closed_503_zero_writes(jobs_module):
    client = _FakeClient(transactions_supported=False)
    client.db.users.seed_user(premium_credits=1)
    client.db.companies.seed_job(COMPANY_ID, **{"_id": COMPANY_ID, "owner_id": USER_ID})
    user = _wire(jobs_module, client)

    with pytest.raises(_HTTPException) as exc:
        asyncio.run(jobs_module.create_job(_make_job_data(is_premium=True), user))

    assert exc.value.status_code == 503
    assert "transaction" in (exc.value.detail or "").lower()
    assert client.db.users.get(USER_ID)["premium_credits"] == 1  # no debit
    assert len(client.db.jobs.docs()) == 0  # no insert


# --------------------------------------------------------------------------- #
# Stripe recruiter_pack grant                                                   #
# --------------------------------------------------------------------------- #
def _seed_recruiter_transaction(client, *, user_id=USER_ID, postings=3, credited=False):
    client.db.users.seed_user(premium_credits=0)
    client.db.payment_transactions.seed_job("cs_123", **{
        "_id": "cs_123", "session_id": "cs_123", "user_id": user_id,
        "kind": "recruiter_pack", "postings": postings,
        "payment_status": "paid", "credited": credited,
    })


def test_recruiter_pack_double_call_credits_once(payments_module):
    client = _FakeClient()
    _seed_recruiter_transaction(client, postings=3)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    r1 = asyncio.run(_credit(payments_module, client, "cs_123"))
    r2 = asyncio.run(_credit(payments_module, client, "cs_123"))

    assert r1.get("credited") is True
    assert r2.get("credited") is True
    user = client.db.users.get(USER_ID)
    assert user["premium_credits"] == 3
    assert user["granted_sessions"].count("cs_123") == 1
    assert ctx.calls == 1  # receipt sent once


def test_recruiter_pack_crash_retry_after_grant_does_not_double_grant(payments_module):
    # Simulate: first call grants (credits + granted_sessions) but process crashes
    # before `credited=True` is set. The retry must not increment again.
    client = _FakeClient()
    _seed_recruiter_transaction(client, postings=3)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    # First call with a monkeypatched transactions update_one that records the
    # grant but leaves `credited` untouched (simulating the crash window).
    original_pt_update = client.db.payment_transactions.update_one

    async def crash_update_one(query, update, session=None):
        # Do NOT apply the credited=True update (simulate crash here)
        return _UpdateResult(0)

    client.db.payment_transactions.update_one = crash_update_one
    r1 = asyncio.run(_credit(payments_module, client, "cs_123"))
    client.db.payment_transactions.update_one = original_pt_update

    user_after_crash = client.db.users.get(USER_ID)
    assert user_after_crash["premium_credits"] == 3
    assert "cs_123" in user_after_crash["granted_sessions"]
    # credited stays False for retry
    assert client.db.payment_transactions.get("cs_123")["credited"] is False

    # Retry after crash: grant filter sees session already granted => no extra inc,
    # only flips credited=True.
    r2 = asyncio.run(_credit(payments_module, client, "cs_123"))
    user_after_retry = client.db.users.get(USER_ID)
    assert user_after_retry["premium_credits"] == 3
    assert user_after_retry["granted_sessions"].count("cs_123") == 1
    assert client.db.payment_transactions.get("cs_123")["credited"] is True


def test_recruiter_pack_user_absent_leaves_uncredited(payments_module):
    client = _FakeClient()
    # transaction references a user that no longer exists
    client.db.users.seed_user(premium_credits=0)
    client.db.users.get(USER_ID)["_id"] = "other_user"
    client.db.payment_transactions.seed_job("cs_xyz", **{
        "_id": "cs_xyz", "session_id": "cs_xyz", "user_id": "missing_user",
        "kind": "recruiter_pack", "postings": 2,
        "payment_status": "paid", "credited": False,
    })

    rec = asyncio.run(_credit(payments_module, client, "cs_xyz"))

    # Grant could not be confirmed (user absent) => credited stays False for retry
    assert rec.get("credited") is False
    assert client.db.payment_transactions.get("cs_xyz")["credited"] is False


def test_recruiter_pack_grant_not_confirmed_leaves_uncredited(payments_module):
    client = _FakeClient()
    _seed_recruiter_transaction(client, postings=3)
    ctx = _PaymentsContext(payments_module, client)
    ctx.patch_receipt()

    # Force the grant to fail (e.g. transient error) => modified_count 0 and the
    # session not present => must remain uncredited for retry.
    original_users_update = client.db.users.update_one

    async def failing_users_update(query, update, session=None):
        return _UpdateResult(0)

    client.db.users.update_one = failing_users_update
    rec = asyncio.run(_credit(payments_module, client, "cs_123"))
    client.db.users.update_one = original_users_update

    assert rec.get("credited") is False
    assert client.db.payment_transactions.get("cs_123")["credited"] is False
    user = client.db.users.get(USER_ID)
    assert user["premium_credits"] == 0
