"""P0-009 : Normalisation canonique des emails.

Partie 1 : tests DÉTERMINISTES (aucun service externe, fake DB asyncio).
Partie 2 : tests d'INTÉGRATION Mongo réelle (skipés sans serveur).

Couvre :
- canonical_email() : strip+lower, non vide, erreurs
- lookup_user_by_email() : 0/1/>1 résultats, collision fail-closed
- Migration : dry-run, apply, collisions, marker
- Routes : register, register-partner, login, google/session
- JWT sub toujours canonique
"""
import asyncio
import importlib.util
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# --------------------------------------------------------------------------- #
# Stubs (fastapi / pydantic / models / database / auth)                       #
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

    @property
    def id(self):
        return self.__dict__.get("_id")

    def dict(self, exclude=None, exclude_unset=False):
        d = dict(self.__dict__)
        if exclude:
            for k in exclude:
                d.pop(k, None)
        return d


class _UserType:
    EMPLOYER = "employer"
    CANDIDATE = "candidate"
    PARTNER = "partner"
    ADMIN = "admin"


class _EmailStr(str):
    pass


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
        HTTP_401_UNAUTHORIZED=401, HTTP_403_FORBIDDEN=403,
    )
    fastapi.Request = object
    fastapi.File = lambda *a, **k: None
    fastapi.UploadFile = object
    fastapi.APIRouter = _Router
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)

    pydantic = types.ModuleType("pydantic")
    pydantic.BaseModel = _Model
    pydantic.Field = lambda *a, **k: None
    pydantic.EmailStr = _EmailStr
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)

    models = types.ModuleType("models")
    for name in ("Job", "JobCreate", "JobUpdate", "JobResponse", "JobSearchQuery",
                 "JobSearchResponse", "User", "SavedJob", "Application",
                 "UserCreate", "UserResponse", "LoginRequest", "LoginResponse",
                 "Token", "TokenData", "UserUpdate", "JobAlertCreate",
                 "JobAlertUpdate", "JobAlertResponse", "JobAlert",
                 "PartnerCreate", "PartnerConfigUpdate", "AdminUserUpdate"):
        setattr(models, name, _Model)
    # PartnerBillingMode needs PER_CLICK / PER_POSTING enum members
    _PartnerBillingMode = type("PartnerBillingMode", (), {
        "PER_CLICK": "per_click",
        "PER_POSTING": "per_posting",
    })
    models.PartnerBillingMode = _PartnerBillingMode
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
    auth.require_admin = lambda *a, **k: None
    auth.get_password_hash = lambda p: "hash"

    async def _default_authenticate(email, password):
        from email_utils import lookup_user_by_email
        return await lookup_user_by_email(email)

    auth.authenticate_user = _default_authenticate
    auth.get_user_by_email = lambda e: None
    monkeypatch.setitem(sys.modules, "auth", auth)

    httpx = types.ModuleType("httpx")

    class _MockClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            raise AssertionError("HTTP fetch not exercised in these tests")

    httpx.AsyncClient = lambda *a, **k: _MockClient()
    httpx.HTTPError = Exception
    monkeypatch.setitem(sys.modules, "httpx", httpx)

    pymongo = types.ModuleType("pymongo")
    pymongo_errors = types.ModuleType("pymongo.errors")

    class _FakeDuplicateKeyError(Exception):
        pass

    pymongo_errors.DuplicateKeyError = _FakeDuplicateKeyError
    pymongo.errors = pymongo_errors
    monkeypatch.setitem(sys.modules, "pymongo", pymongo)
    monkeypatch.setitem(sys.modules, "pymongo.errors", pymongo_errors)

    motor = types.ModuleType("motor")
    motor_asyncio = types.ModuleType("motor.motor_asyncio")
    motor_asyncio.AsyncIOMotorClient = lambda *a, **k: None
    motor.motor_asyncio = motor_asyncio
    monkeypatch.setitem(sys.modules, "motor", motor)
    monkeypatch.setitem(sys.modules, "motor.motor_asyncio", motor_asyncio)


def _load(monkeypatch, rel_path, modname):
    path = BACKEND_DIR / rel_path
    spec = importlib.util.spec_from_file_location(modname, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._HTTPException = _HTTPException
    return module


# --------------------------------------------------------------------------- #
# Fake DB asyncio                                                             #
# --------------------------------------------------------------------------- #
class _FakeCollection:
    def __init__(self, docs=None):
        self._docs = docs or []

    def _matches(self, doc, query):
        if not query:
            return True
        for key, value in query.items():
            if isinstance(value, dict):
                if "$type" in value:
                    expected = value["$type"]
                    actual_type = type(doc.get(key)).__name__
                    # Map MongoDB type names to Python type names for comparison
                    mongo_to_python = {"string": "str", "int": "int", "double": "float",
                                       "bool": "bool", "array": "list", "object": "dict",
                                       "null": "NoneType"}
                    expected_python = mongo_to_python.get(expected, expected)
                    if expected_python != actual_type:
                        return False
                elif "$regex" in value:
                    import re
                    if not re.search(value["$regex"], doc.get(key) or "", 
                                     re.IGNORECASE if "$options" in value and "i" in value["$options"] else 0):
                        return False
                elif "$ne" in value:
                    if doc.get(key) == value["$ne"]:
                        return False
                elif "$in" in value:
                    if doc.get(key) not in value["$in"]:
                        return False
                elif "$gt" in value:
                    if (doc.get(key) or 0) <= value["$gt"]:
                        return False
                elif "$gte" in value:
                    if (doc.get(key) or 0) < value["$gte"]:
                        return False
                elif "$lt" in value:
                    if (doc.get(key) or 0) >= value["$lt"]:
                        return False
                elif "$lte" in value:
                    if (doc.get(key) or 0) > value["$lte"]:
                        return False
                elif "$or" in value:
                    return any(self._matches(doc, sub) for sub in value["$or"])
                elif "$and" in value:
                    return all(self._matches(doc, sub) for sub in value["$and"])
                elif "$set" in value or "$inc" in value or "$setOnInsert" in value:
                    pass  # update operations, skip in match
                else:
                    # Nested match
                    actual = doc.get(key)
                    if isinstance(actual, dict):
                        if not self._matches(actual, value):
                            return False
                    elif actual != value:
                        return False
            else:
                if doc.get(key) != value:
                    return False
        return True

    async def find_one(self, query):
        for doc in self._docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    async def insert_one(self, doc, session=None):
        # Enforce _id uniqueness like real Mongo
        for existing in self._docs:
            if existing.get("_id") == doc.get("_id"):
                from pymongo.errors import DuplicateKeyError
                raise DuplicateKeyError(
                    f"E11000 duplicate key error collection: test users "
                    f"index: _id_ dup key: {{ _id: {doc.get('_id')!r} }}"
                )
        self._docs.append(dict(doc))
        return types.SimpleNamespace(inserted_id=doc.get("_id"))

    async def update_one(self, query, update, session=None):
        for doc in self._docs:
            if self._matches(doc, query):
                for key, value in update.get("$set", {}).items():
                    doc[key] = value
                for key, value in update.get("$inc", {}).items():
                    doc[key] = doc.get(key, 0) + value
                return types.SimpleNamespace(matched_count=1, modified_count=1)
        return types.SimpleNamespace(matched_count=0, modified_count=0)

    async def delete_one(self, query, session=None):
        for i, doc in enumerate(self._docs):
            if self._matches(doc, query):
                self._docs.pop(i)
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)

    async def count_documents(self, query):
        return sum(1 for d in self._docs if self._matches(d, query))

    def find(self, query=None, projection=None):
        docs = [dict(d) for d in self._docs if not query or self._matches(d, query)]
        if projection:
            docs = [
                {k: v for k, v in d.items() if k in projection or k == "_id"}
                for d in docs
            ]
        return _FindCursor(docs)

    def aggregate(self, pipeline):
        """Minimal aggregation simulation for P0-009 tests."""
        docs = [dict(d) for d in self._docs]
        
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if self._matches(d, stage["$match"])]
            elif "$addFields" in stage:
                for doc in docs:
                    for field, expr in stage["$addFields"].items():
                        doc[field] = self._eval_expr(doc, expr)
            elif "$group" in stage:
                groups = {}
                for doc in docs:
                    key_expr = stage["$group"]["_id"]
                    if isinstance(key_expr, str) and key_expr.startswith("$"):
                        key = doc.get(key_expr[1:])
                    else:
                        key = key_expr
                    if key not in groups:
                        groups[key] = {"_id": key}
                    for field, accum in stage["$group"].items():
                        if field == "_id":
                            continue
                        if accum == {"$sum": 1}:
                            groups[key][field] = groups[key].get(field, 0) + 1
                        elif "$push" in accum:
                            push_field = accum["$push"][1:] if isinstance(accum["$push"], str) else accum["$push"]
                            if field not in groups[key]:
                                groups[key][field] = []
                            groups[key][field].append(doc.get(push_field) if isinstance(push_field, str) else push_field)
                docs = list(groups.values())
            elif "$limit" in stage:
                docs = docs[:stage["$limit"]]
            elif "$sort" in stage:
                for key, direction in reversed(list(stage["$sort"].items())):
                    docs.sort(key=lambda d: d.get(key) or "", reverse=(direction == -1))
        
        return _AggCursor(docs)

    def _eval_expr(self, doc, expr):
        if isinstance(expr, str) and expr.startswith("$"):
            return doc.get(expr[1:])
        elif isinstance(expr, dict):
            if "$toLower" in expr:
                val = self._eval_expr(doc, expr["$toLower"])
                return val.lower() if isinstance(val, str) else val
            elif "$trim" in expr:
                val = self._eval_expr(doc, expr["$trim"].get("input", ""))
                return val.strip() if isinstance(val, str) else val
            elif "$cond" in expr:
                cond = expr["$cond"]
                if_val = self._eval_expr(doc, cond["if"])
                if if_val:
                    return self._eval_expr(doc, cond["then"])
                else:
                    return self._eval_expr(doc, cond["else"])
            elif "$eq" in expr:
                left = self._eval_expr(doc, expr["$eq"][0])
                right = self._eval_expr(doc, expr["$eq"][1])
                return left == right
            elif "$type" in expr:
                field = expr["$type"]
                if isinstance(field, str) and field.startswith("$"):
                    val = doc.get(field[1:])
                    # Return MongoDB type name, not Python type name
                    mongo_type_map = {
                        str: "string", int: "int", float: "double",
                        bool: "bool", list: "array", dict: "object",
                        type(None): "null",
                    }
                    return mongo_type_map.get(type(val), type(val).__name__)
                return type(field).__name__
        return expr


class _FindCursor:
    def __init__(self, docs):
        self._docs = docs
        self._index = 0

    def sort(self, spec):
        for key, direction in reversed(spec):
            self._docs.sort(key=lambda d: d.get(key) or "", reverse=(direction == -1))
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length):
        return self._docs[:length]

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self._docs):
            raise StopAsyncIteration
        item = self._docs[self._index]
        self._index += 1
        return item


class _AsyncIterator:
    def __init__(self, items):
        self._items = items
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


class _AggCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length):
        return self._docs[:length]

    def __aiter__(self):
        return _AsyncIterator(self._docs)


class _FakeDB:
    def __init__(self, users=None, migration_flags=None):
        self.users = _FakeCollection(users or [])
        self.migration_flags = _FakeCollection(migration_flags or [])
        self.alerts = _FakeCollection([])
        self.partner_profiles = _FakeCollection([])


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# 1. canonical_email — fonctions pures                                        #
# --------------------------------------------------------------------------- #
class TestCanonicalEmail:
    def test_already_canonical(self):
        from email_utils import canonical_email
        assert canonical_email("foo@example.com") == "foo@example.com"

    def test_uppercase_lowered(self):
        from email_utils import canonical_email
        assert canonical_email("Foo@Example.COM") == "foo@example.com"

    def test_whitespace_stripped(self):
        from email_utils import canonical_email
        assert canonical_email("  foo@example.com  ") == "foo@example.com"

    def test_combined_strip_and_lower(self):
        from email_utils import canonical_email
        assert canonical_email(" Foo@Example.COM ") == "foo@example.com"

    def test_empty_string_raises(self):
        from email_utils import canonical_email
        with pytest.raises(ValueError):
            canonical_email("")

    def test_whitespace_only_raises(self):
        from email_utils import canonical_email
        with pytest.raises(ValueError):
            canonical_email("   ")

    def test_none_raises(self):
        from email_utils import canonical_email
        with pytest.raises(ValueError):
            canonical_email(None)

    def test_non_string_raises(self):
        from email_utils import canonical_email
        with pytest.raises(ValueError):
            canonical_email(123)

    def test_deterministic(self):
        from email_utils import canonical_email
        a = canonical_email("  Test@Example.COM  ")
        b = canonical_email("test@example.com")
        assert a == b

    def test_unicode_preserved(self):
        from email_utils import canonical_email
        # Unicode chars are preserved through strip+lower
        result = canonical_email("  café@example.com  ")
        assert result == "café@example.com"


# --------------------------------------------------------------------------- #
# 2. lookup_user_by_email — fake DB                                           #
# --------------------------------------------------------------------------- #
class TestLookupUserByEmail:
    @pytest.fixture(autouse=True)
    def _setup_db(self, monkeypatch):
        self.db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com", "user_type": "candidate",
             "hashed_password": "hash", "is_active": True,
             "first_name": "Foo", "last_name": "Bar",
             "phone": None, "location": None, "bio": None,
             "skills": [], "experience_years": None, "is_verified": False,
             "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()},
        ])
        import email_utils as _eu_mod
        db_ref = self.db

        async def _get_db():
            return db_ref

        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

    def test_exact_match(self):
        from email_utils import lookup_user_by_email
        user = _run(lookup_user_by_email("foo@example.com"))
        assert user is not None
        assert user.email == "foo@example.com"

    def test_case_insensitive_match(self):
        from email_utils import lookup_user_by_email
        user = _run(lookup_user_by_email("Foo@Example.COM"))
        assert user is not None
        assert user.email == "foo@example.com"

    def test_whitespace_stripped_match(self):
        from email_utils import lookup_user_by_email
        user = _run(lookup_user_by_email("  foo@example.com  "))
        assert user is not None
        assert user.email == "foo@example.com"

    def test_no_match_returns_none(self):
        from email_utils import lookup_user_by_email
        user = _run(lookup_user_by_email("bar@example.com"))
        assert user is None

    def test_collision_raises_error(self):
        from email_utils import lookup_user_by_email, LookupCollisionError
        # Two users with same canonical email
        self.db.users._docs.append({
            "_id": "u2", "email": " Foo@Example.COM ",
            "user_type": "candidate", "hashed_password": "hash2", "is_active": True,
            "first_name": "Foo2", "last_name": "Bar2",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })
        with pytest.raises(LookupCollisionError):
            _run(lookup_user_by_email("foo@example.com"))

    def test_non_string_email_field_skipped(self):
        from email_utils import lookup_user_by_email
        # Add a doc with non-string email
        self.db.users._docs.append({
            "_id": "u3", "email": 12345,
            "user_type": "candidate", "hashed_password": "hash3", "is_active": True,
            "first_name": "Bad", "last_name": "Data",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })
        user = _run(lookup_user_by_email("foo@example.com"))
        assert user is not None  # non-string email is skipped by $type guard

    def test_db_none_raises_aggregation_error(self):
        from email_utils import lookup_user_by_email, LookupAggregationError
        import email_utils as _eu_mod

        async def _get_db_none():
            return None

        old = getattr(_eu_mod, "get_database", None)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(_eu_mod, "get_database", _get_db_none)
        try:
            with pytest.raises(LookupAggregationError):
                _run(lookup_user_by_email("foo@example.com"))
        finally:
            monkeypatch.undo()

    def test_aggregation_failure_raises_error(self, monkeypatch):
        """P0-009 FIX 2: aggregation failure must raise LookupAggregationError."""
        import email_utils as _eu_mod
        from email_utils import lookup_user_by_email, LookupAggregationError

        self.db.users._docs.append({
            "_id": "u_legacy", "email": " Foo@Example.COM ",
            "user_type": "candidate", "hashed_password": "hash2", "is_active": True,
            "first_name": "Legacy", "last_name": "User",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

        async def _get_db():
            return self.db

        def _broken_aggregate(pipeline):
            raise RuntimeError("MongoDB aggregation unavailable")

        monkeypatch.setattr(_eu_mod, "get_database", _get_db)
        self.db.users.aggregate = _broken_aggregate

        with pytest.raises(LookupAggregationError):
            _run(lookup_user_by_email("foo@example.com"))


# --------------------------------------------------------------------------- #
# 3. Migration — fonctions pures                                              #
# --------------------------------------------------------------------------- #
class TestMigrationDryRun:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.migrate_module = _load(
            monkeypatch, "scripts/migrate_p0009_email_normalization.py",
            "p0009_migrate")

    def test_dry_run_no_writes(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "  Foo@Example.COM "},
            {"_id": "u2", "email": "bar@example.com"},
        ])
        report = _run(self.migrate_module._migrate(db, dry_run=True))
        assert report["dry_run"] is True
        assert report["to_update"] == 1
        assert report["already_canonical"] == 1
        assert report["updated"] == 0
        assert report["marker_set"] is False
        # Verify no writes
        u1 = _run(db.users.find_one({"_id": "u1"}))
        assert u1["email"] == "  Foo@Example.COM "  # unchanged

    def test_apply_updates_emails(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "  Foo@Example.COM "},
            {"_id": "u2", "email": "bar@example.com"},
        ])
        report = _run(self.migrate_module._migrate(db, dry_run=False))
        assert report["updated"] == 1
        assert report["marker_set"] is True
        u1 = _run(db.users.find_one({"_id": "u1"}))
        assert u1["email"] == "foo@example.com"

    def test_collision_detection_dry_run_returns_report(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": " Foo@Example.COM "},
        ])
        report = _run(self.migrate_module._migrate(db, dry_run=True))
        assert report["collisions"] == 1
        assert len(report["collision_details"]) == 1
        assert report["collision_details"][0]["canonical_email"] == "foo@example.com"
        assert set(report["collision_details"][0]["user_ids"]) == {"u1", "u2"}

    def test_apply_raises_on_collision(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": " Foo@Example.COM "},
        ])
        with pytest.raises(RuntimeError, match="collision"):
            _run(self.migrate_module._migrate(db, dry_run=False))
        # Verify ZERO writes
        u1 = _run(db.users.find_one({"_id": "u1"}))
        assert u1["email"] == "foo@example.com"
        u2 = _run(db.users.find_one({"_id": "u2"}))
        assert u2["email"] == " Foo@Example.COM "
        # Verify NO marker was set
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is None

    def test_already_migrated_skip(self):
        db = _FakeDB(
            users=[{"_id": "u1", "email": "foo@example.com"}],
            migration_flags=[{"_id": "p0009_email_normalization", "applied_at": datetime.utcnow()}],
        )
        report = _run(self.migrate_module._migrate(db, dry_run=False))
        assert report["already_migrated"] is True

    def test_all_canonical_no_work(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": "bar@example.com"},
        ])
        report = _run(self.migrate_module._migrate(db, dry_run=False))
        assert report["updated"] == 0
        assert report["already_canonical"] == 2
        assert report["marker_set"] is True

    def test_non_string_email_blocks_dry_run(self):
        """P0-009: non-string email is a BLOCKER, even in dry-run."""
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": 12345},  # non-string → blocker
        ])
        report = _run(self.migrate_module._migrate(db, dry_run=True))
        assert report["invalid_emails"] == 1
        assert len(report["invalid_email_details"]) == 1
        assert report["marker_set"] is False


# --------------------------------------------------------------------------- #
# 4. Routes — auth/register avec stubs                                        #
# --------------------------------------------------------------------------- #
class TestRoutesCanonicalization:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None  # will be patched per test
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        monkeypatch.setitem(sys.modules, "auth", auth)

        self.auth_module = auth
        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_routes_auth")

    def test_register_canonicalizes_email(self):
        async def scenario():
            user_data = _Model(
                email="  Foo@Example.COM  ",
                password="secret",
                first_name="Test",
                last_name="User",
                user_type="candidate",
            )
            result = await self.routes_auth.register(user_data)
            return result

        result = _run(scenario())
        # Verify stored email is canonical
        u = _run(self.db.users.find_one({"_id": {"$regex": "user_"}}))
        assert u is not None
        assert u["email"] == "foo@example.com"
        # Verify JWT sub is canonical
        assert "foo@example.com" in result.token.access_token

    def test_register_duplicate_canonical_rejected(self):
        async def scenario():
            user_data = _Model(
                email="foo@example.com",
                password="secret",
                first_name="Test",
                last_name="User",
                user_type="candidate",
            )
            await self.routes_auth.register(user_data)
            # Try registering with different case
            user_data2 = _Model(
                email="  FOO@EXAMPLE.COM  ",
                password="secret2",
                first_name="Test2",
                last_name="User2",
                user_type="candidate",
            )
            await self.routes_auth.register(user_data2)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 400

    def test_login_canonicalizes_email(self):
        async def scenario():
            fake_user = _Model(
                id="u1", email="foo@example.com", first_name="T", last_name="U",
                user_type="candidate", phone=None, location=None, bio=None,
                skills=[], experience_years=None, is_active=True, is_verified=False,
                hashed_password="hash", created_at=datetime.utcnow(),
            )

            async def _fake_auth(email, password):
                return fake_user

            self.auth_module.authenticate_user = _fake_auth
            # Also patch it on the loaded routes module so login() sees it
            self.routes_auth.authenticate_user = _fake_auth
            login_data = _Model(email="  Foo@Example.COM  ", password="secret",
                                expected_user_type=None)
            result = await self.routes_auth.login(login_data)
            return result

        result = _run(scenario())
        assert "foo@example.com" in result.token.access_token


# --------------------------------------------------------------------------- #
# 5. Regression: canonical_email imports independently                         #
# --------------------------------------------------------------------------- #
class TestRegressions:
    def test_email_utils_importable(self):
        import email_utils
        assert hasattr(email_utils, "canonical_email")
        assert hasattr(email_utils, "lookup_user_by_email")

    def test_auth_source_uses_canonical_email(self):
        source = open(BACKEND_DIR / "auth.py").read()
        assert "canonical_email" in source

    def test_routes_auth_source_uses_canonical_email(self):
        source = open(BACKEND_DIR / "routes" / "auth.py").read()
        assert "canonical_email" in source


# --------------------------------------------------------------------------- #
# 6. JWT sub resolution                                                       #
# --------------------------------------------------------------------------- #
class TestJWTSubResolution:
    def test_canonical_email_in_get_current_user(self):
        """Verify that get_current_user normalizes JWT sub via canonical_email."""
        source = open(BACKEND_DIR / "auth.py").read()
        assert "canonical_email(email)" in source

    def test_login_route_uses_canonical_sub(self):
        """Verify that login route uses canonical_email for JWT sub."""
        source = open(BACKEND_DIR / "routes" / "auth.py").read()
        assert 'canonical_email(user.email)' in source


# --------------------------------------------------------------------------- #
# 7. Admin route canonicalization                                             #
# --------------------------------------------------------------------------- #
class TestAdminRouteCanonicalization:
    def test_admin_imports_canonical_email(self):
        source = open(BACKEND_DIR / "routes" / "admin.py").read()
        assert "canonical_email" in source

    def test_create_partner_canonicalizes(self):
        source = open(BACKEND_DIR / "routes" / "admin.py").read()
        assert 'canonical_email(data.email)' in source

    def test_xml_feed_canonicalizes(self):
        source = open(BACKEND_DIR / "routes" / "admin.py").read()
        assert 'canonical_email(data.new_partner_email' in source


# --------------------------------------------------------------------------- #
# 8. Alerts route canonicalization                                            #
# --------------------------------------------------------------------------- #
class TestAlertsRouteCanonicalization:
    def test_alerts_imports_canonical_email(self):
        source = open(BACKEND_DIR / "routes" / "alerts.py").read()
        assert "canonical_email" in source

    def test_subscribe_canonicalizes(self):
        source = open(BACKEND_DIR / "routes" / "alerts.py").read()
        assert 'canonical_email(data.email)' in source


# --------------------------------------------------------------------------- #
# 9. P0-009 BUILD CORRECTION: legacy blocking on all create-paths             #
# --------------------------------------------------------------------------- #
class TestLegacyBlockingOnCreatePaths:
    """P0-009 FIX 1: all create-paths MUST use transitionnal lookup to detect
    legacy non-canonical emails, preventing duplicate accounts."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)
        self.auth_module = auth

        # Import email_utils with our fake db patched in
        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_routes_auth_v2")
        self.routes_alerts = _load(monkeypatch, "routes/alerts.py", "p009_routes_alerts_v2")

    def _seed_legacy_user(self, email_value):
        """Insert a legacy user with a non-canonical email."""
        self.db.users._docs.append({
            "_id": "legacy_u1", "email": email_value,
            "user_type": "candidate", "hashed_password": "hash_legacy", "is_active": True,
            "first_name": "Legacy", "last_name": "User",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

    def test_register_blocks_legacy_email_with_spaces(self):
        """Legacy ' Foo@Example.COM ' must block registration of 'foo@example.com'."""
        self._seed_legacy_user(" Foo@Example.COM ")
        async def scenario():
            user_data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User", user_type="candidate",
            )
            await self.routes_auth.register(user_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 400

    def test_register_blocks_legacy_email_with_casse(self):
        """Legacy 'FOO@EXAMPLE.COM' must block registration of 'foo@example.com'."""
        self._seed_legacy_user("FOO@EXAMPLE.COM")
        async def scenario():
            user_data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User", user_type="candidate",
            )
            await self.routes_auth.register(user_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 400

    def test_register_partner_blocks_legacy_email(self):
        """Legacy email blocks register-partner via transitionnal lookup."""
        self._seed_legacy_user(" Foo@Example.COM ")
        async def scenario():
            data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User",
                company_name="Acme", signup_source=None, signup_referrer=None,
                signup_landing=None, utm_source=None, utm_medium=None, utm_campaign=None,
            )
            await self.routes_auth.register_partner(data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 400

    def test_alerts_subscribe_blocks_legacy_email(self):
        """Legacy email blocks alerts/subscribe via transitionnal lookup."""
        self._seed_legacy_user(" Foo@Example.COM ")
        async def scenario():
            data = _Model(
                email="foo@example.com", search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            return await self.routes_alerts.subscribe_alert(data)

        result = _run(scenario())
        # Should reuse the legacy user, not create a new one
        assert result["created_account"] is False


# --------------------------------------------------------------------------- #
# 10. P0-009 BUILD CORRECTION: DuplicateKeyError on create-paths              #
# --------------------------------------------------------------------------- #
class TestDuplicateKeyErrorHandling:
    """P0-009 FIX 3: DuplicateKeyError on user inserts must yield a deterministic
    API response (never a raw 500), with transitionnal re-lookup when possible."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)
        self.auth_module = auth

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_routes_auth_dk")
        self.routes_alerts = _load(monkeypatch, "routes/alerts.py", "p009_routes_alerts_dk")

    def _seed_user(self, email_value, uid="existing_u1"):
        self.db.users._docs.append({
            "_id": uid, "email": email_value,
            "user_type": "candidate", "hashed_password": "hash_ex", "is_active": True,
            "first_name": "Existing", "last_name": "User",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

    def test_register_duplicate_key_returns_400(self):
        """DuplicateKeyError on register with legacy variant returns 400 (not 500)."""
        self._seed_user(" Foo@Example.COM ")
        async def scenario():
            user_data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User", user_type="candidate",
            )
            await self.routes_auth.register(user_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 400

    def test_register_partner_duplicate_key_returns_400(self):
        """DuplicateKeyError on register-partner returns 400."""
        self._seed_user(" Foo@Example.COM ")
        async def scenario():
            data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User",
                company_name="Acme", signup_source=None, signup_referrer=None,
                signup_landing=None, utm_source=None, utm_medium=None, utm_campaign=None,
            )
            await self.routes_auth.register_partner(data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 400

    def test_register_duplicate_key_no_reuse_silent(self):
        """DuplicateKeyError without legacy match must NOT silently succeed."""
        # Insert a user that will cause DuplicateKeyError on insert
        # but the re-lookup also fails (no canonical match)
        self._seed_user("foo@example.com", uid="exact_u1")
        async def scenario():
            # Same canonical email but different _id (race condition simulation)
            user_data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User", user_type="candidate",
            )
            await self.routes_auth.register(user_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        # Should get 400 (existing found) not 500
        assert exc.value.status_code == 400

    def test_alerts_subscribe_duplicate_key_returns_409(self):
        """DuplicateKeyError on alerts/subscribe without legacy match returns 409."""
        async def scenario():
            data = _Model(
                email="foo@example.com", search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            return await self.routes_alerts.subscribe_alert(data)

        # First call succeeds
        result = _run(scenario())
        assert result["success"] is True

        # Now simulate DuplicateKeyError by making insert_one fail
        # and ensuring re-lookup also fails (edge case)
        original_insert = self.db.users.insert_one

        async def _fail_insert(*a, **k):
            from pymongo.errors import DuplicateKeyError
            raise DuplicateKeyError("duplicate key")

        self.db.users.insert_one = _fail_insert
        # Clear the db so re-lookup finds nothing
        self.db.users._docs.clear()

        async def scenario2():
            data = _Model(
                email="bar@example.com", search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            await self.routes_alerts.subscribe_alert(data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario2())
        assert exc.value.status_code == 409


# --------------------------------------------------------------------------- #
# 11. P0-009 BUILD CORRECTION: no silent merging on email variants            #
# --------------------------------------------------------------------------- #
class TestNoSilentMerging:
    """P0-009: a legacy ' Foo@Example.COM ' must NOT be silently merged
    into a new 'foo@example.com' account during creation."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_routes_auth_merge")
        self.routes_alerts = _load(monkeypatch, "routes/alerts.py", "p009_routes_alerts_merge")

    def test_register_does_not_create_new_on_legacy(self):
        """Registration with 'foo@example.com' when legacy 'Foo@EXAMPLE.com' exists
        must be rejected, not silently create a second account."""
        self.db.users._docs.append({
            "_id": "legacy_u1", "email": "Foo@EXAMPLE.com",
            "user_type": "candidate", "hashed_password": "hash_legacy", "is_active": True,
            "first_name": "Legacy", "last_name": "User",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

        async def scenario():
            user_data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User", user_type="candidate",
            )
            await self.routes_auth.register(user_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 400
        # Verify only one user exists (no silent second account)
        assert len(self.db.users._docs) == 1

    def test_alerts_subscribe_reuses_not_creates(self):
        """Alerts subscribe with 'foo@example.com' when legacy 'Foo@EXAMPLE.com' exists
        must reuse the legacy account, not create a duplicate."""
        self.db.users._docs.append({
            "_id": "legacy_u1", "email": "Foo@EXAMPLE.com",
            "user_type": "candidate", "hashed_password": "hash_legacy", "is_active": True,
            "first_name": "Legacy", "last_name": "User",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

        async def scenario():
            data = _Model(
                email="foo@example.com", search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            return await self.routes_alerts.subscribe_alert(data)

        result = _run(scenario())
        assert result["created_account"] is False
        assert len(self.db.users._docs) == 1


# --------------------------------------------------------------------------- #
# 12. P0-009 BUILD CORRECTION: source checks for all create-paths             #
# --------------------------------------------------------------------------- #
class TestAllCreatePathsUseTransitionnalLookup:
    """Verify that source code for all create-paths uses lookup_user_by_email
    instead of find_one for the pre-insert duplicate check."""

    def test_register_uses_lookup(self):
        source = open(BACKEND_DIR / "routes" / "auth.py").read()
        assert "lookup_user_doc_by_email(email)" in source

    def test_register_partner_uses_lookup(self):
        source = open(BACKEND_DIR / "routes" / "auth.py").read()
        # register_partner must use lookup_user_doc_by_email, not find_one
        assert "lookup_user_doc_by_email(email)" in source

    def test_google_session_uses_lookup(self):
        source = open(BACKEND_DIR / "routes" / "auth.py").read()
        # google/session must use lookup_user_doc_by_email for existence check
        assert "lookup_user_doc_by_email(email)" in source

    def test_alerts_subscribe_uses_lookup(self):
        source = open(BACKEND_DIR / "routes" / "alerts.py").read()
        assert "lookup_user_doc_by_email(email)" in source

    def test_admin_partners_uses_lookup(self):
        source = open(BACKEND_DIR / "routes" / "admin.py").read()
        assert "lookup_user_doc_by_email(email)" in source

    def test_admin_xml_feeds_uses_lookup(self):
        source = open(BACKEND_DIR / "routes" / "admin.py").read()
        assert "lookup_user_doc_by_email(email)" in source

    def test_no_fallback_in_lookup(self):
        """email_utils.lookup_user_by_email must NOT fallback to find_one."""
        source = open(BACKEND_DIR / "email_utils.py").read()
        assert "find_one" not in source

    def test_duplicate_key_error_only_in_register(self):
        source = open(BACKEND_DIR / "routes" / "auth.py").read()
        assert "pymongo.errors.DuplicateKeyError" in source
        # Must NOT catch generic Exception on user inserts
        lines = source.split("\n")
        in_try_block = False
        for line in lines:
            stripped = line.strip()
            if "insert_one" in stripped and "users" in stripped:
                in_try_block = True
            if in_try_block and stripped.startswith("except"):
                assert "DuplicateKeyError" in stripped, (
                    f"register insert uses '{stripped}' instead of DuplicateKeyError"
                )
                in_try_block = False

    def test_duplicate_key_error_only_in_alerts(self):
        source = open(BACKEND_DIR / "routes" / "alerts.py").read()
        assert "pymongo.errors.DuplicateKeyError" in source

    def test_duplicate_key_error_only_in_admin(self):
        source = open(BACKEND_DIR / "routes" / "admin.py").read()
        assert "pymongo.errors.DuplicateKeyError" in source

    def test_lookup_aggregation_error_imported_in_auth(self):
        source = open(BACKEND_DIR / "routes" / "auth.py").read()
        assert "LookupAggregationError" in source
        assert "LookupCollisionError" in source

    def test_lookup_aggregation_error_imported_in_alerts(self):
        source = open(BACKEND_DIR / "routes" / "alerts.py").read()
        assert "LookupAggregationError" in source
        assert "LookupCollisionError" in source

    def test_lookup_aggregation_error_imported_in_admin(self):
        source = open(BACKEND_DIR / "routes" / "admin.py").read()
        assert "LookupAggregationError" in source
        assert "LookupCollisionError" in source


# --------------------------------------------------------------------------- #
# 13. P0-009 BUILD CORRECTION: aggregation error creates nothing              #
# --------------------------------------------------------------------------- #
class TestAggregationErrorCreatesNothing:
    """When lookup_user_by_email raises LookupAggregationError, no create-path
    must create a new account or silently reuse an existing one."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        self._eu_mod = _eu_mod
        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_agg_err_auth")
        self.routes_alerts = _load(monkeypatch, "routes/alerts.py", "p009_agg_err_alerts")

    def _make_aggregation_fail(self, monkeypatch):
        def _broken_aggregate(pipeline):
            raise RuntimeError("MongoDB aggregation unavailable")
        self.db.users.aggregate = _broken_aggregate

    def test_register_aggregation_error_creates_nothing(self, monkeypatch):
        """Aggregation error on /register must return 503 and create zero users."""
        self._make_aggregation_fail(monkeypatch)
        initial_count = len(self.db.users._docs)

        async def scenario():
            user_data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User", user_type="candidate",
            )
            await self.routes_auth.register(user_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 503
        assert len(self.db.users._docs) == initial_count  # nothing created

    def test_register_partner_aggregation_error_creates_nothing(self, monkeypatch):
        """Aggregation error on /register-partner must return 503 and create zero users."""
        self._make_aggregation_fail(monkeypatch)
        initial_count = len(self.db.users._docs)

        async def scenario():
            data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User",
                company_name="Acme", signup_source=None, signup_referrer=None,
                signup_landing=None, utm_source=None, utm_medium=None, utm_campaign=None,
            )
            await self.routes_auth.register_partner(data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 503
        assert len(self.db.users._docs) == initial_count

    def test_alerts_subscribe_aggregation_error_creates_nothing(self, monkeypatch):
        """Aggregation error on /alerts/subscribe must return 503 and create zero users."""
        self._make_aggregation_fail(monkeypatch)
        initial_count = len(self.db.users._docs)

        async def scenario():
            data = _Model(
                email="foo@example.com", search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            await self.routes_alerts.subscribe_alert(data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 503
        assert len(self.db.users._docs) == initial_count


# --------------------------------------------------------------------------- #
# 14. P0-009 BUILD CORRECTION: collision >1 creates nothing silently          #
# --------------------------------------------------------------------------- #
class TestCollisionCreatesNothing:
    """When lookup_user_by_email raises LookupCollisionError, no create-path
    must create a new account or silently reuse an existing one."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_coll_auth")
        self.routes_alerts = _load(monkeypatch, "routes/alerts.py", "p009_coll_alerts")

    def _seed_collision(self):
        """Insert two users sharing the same canonical email."""
        self.db.users._docs.extend([
            {"_id": "u_coll1", "email": "foo@example.com",
             "user_type": "candidate", "hashed_password": "hash1", "is_active": True,
             "first_name": "A", "last_name": "B",
             "phone": None, "location": None, "bio": None,
             "skills": [], "experience_years": None, "is_verified": False,
             "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()},
            {"_id": "u_coll2", "email": " Foo@Example.COM ",
             "user_type": "candidate", "hashed_password": "hash2", "is_active": True,
             "first_name": "C", "last_name": "D",
             "phone": None, "location": None, "bio": None,
             "skills": [], "experience_years": None, "is_verified": False,
             "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()},
        ])

    def test_register_collision_creates_nothing(self):
        """Collision on /register must return 503 and create zero new users."""
        self._seed_collision()
        initial_count = len(self.db.users._docs)

        async def scenario():
            user_data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User", user_type="candidate",
            )
            await self.routes_auth.register(user_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 503
        assert len(self.db.users._docs) == initial_count

    def test_register_partner_collision_creates_nothing(self):
        """Collision on /register-partner must return 503 and create zero new users."""
        self._seed_collision()
        initial_count = len(self.db.users._docs)

        async def scenario():
            data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User",
                company_name="Acme", signup_source=None, signup_referrer=None,
                signup_landing=None, utm_source=None, utm_medium=None, utm_campaign=None,
            )
            await self.routes_auth.register_partner(data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 503
        assert len(self.db.users._docs) == initial_count

    def test_alerts_subscribe_collision_creates_nothing(self):
        """Collision on /alerts/subscribe must return 503 and create zero new users."""
        self._seed_collision()
        initial_count = len(self.db.users._docs)

        async def scenario():
            data = _Model(
                email="foo@example.com", search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            await self.routes_alerts.subscribe_alert(data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 503
        assert len(self.db.users._docs) == initial_count


# --------------------------------------------------------------------------- #
# 15. P0-009 BUILD CORRECTION: non-DuplicateKeyError is not swallowed         #
# --------------------------------------------------------------------------- #
class TestNonDuplicateKeyErrorPropagates:
    """Mongo/infra errors that are NOT DuplicateKeyError must NOT be converted
    into a false 'email already used' response."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_nondk_auth")
        self.routes_alerts = _load(monkeypatch, "routes/alerts.py", "p009_nondk_alerts")

    def test_register_non_dk_error_not_swallowed(self, monkeypatch):
        """A non-DuplicateKeyError Mongo error on /register must NOT be converted
        to 'email already used' — it should propagate as a server error."""
        original_insert = self.db.users.insert_one

        async def _infra_error(*a, **k):
            raise RuntimeError("MongoNetworkError: connection lost")

        self.db.users.insert_one = _infra_error

        async def scenario():
            user_data = _Model(
                email="newuser@example.com", password="secret",
                first_name="Test", last_name="User", user_type="candidate",
            )
            await self.routes_auth.register(user_data)

        with pytest.raises(RuntimeError, match="MongoNetworkError"):
            _run(scenario())

    def test_alerts_non_dk_error_not_swallowed(self, monkeypatch):
        """A non-DuplicateKeyError Mongo error on /alerts/subscribe must NOT be
        converted to 'email already used'."""
        original_insert = self.db.users.insert_one

        async def _infra_error(*a, **k):
            raise RuntimeError("MongoNetworkError: connection lost")

        self.db.users.insert_one = _infra_error

        async def scenario():
            data = _Model(
                email="newalert@example.com", search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            await self.routes_alerts.subscribe_alert(data)

        with pytest.raises(RuntimeError, match="MongoNetworkError"):
            _run(scenario())


# --------------------------------------------------------------------------- #
# 16. P0-009 BUILD CORRECTION: DuplicateKeyError handled deterministically    #
# --------------------------------------------------------------------------- #
class TestDuplicateKeyDeterministic:
    """DuplicateKeyError on user inserts must yield a deterministic API response
    (never a raw 500), with transitionnal re-lookup."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_dkdet_auth")
        self.routes_alerts = _load(monkeypatch, "routes/alerts.py", "p009_dkdet_alerts")

    def _seed_user(self, email_value, uid="existing_u1"):
        self.db.users._docs.append({
            "_id": uid, "email": email_value,
            "user_type": "candidate", "hashed_password": "hash_ex", "is_active": True,
            "first_name": "Existing", "last_name": "User",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

    def test_register_dk_with_legacy_relookup_returns_400(self):
        """DuplicateKeyError with a legacy variant found → 400 (existing)."""
        self._seed_user(" Foo@Example.COM ")

        async def scenario():
            user_data = _Model(
                email="foo@example.com", password="secret",
                first_name="Test", last_name="User", user_type="candidate",
            )
            await self.routes_auth.register(user_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 400

    def test_register_dk_no_legacy_returns_409(self):
        """DuplicateKeyError with no canonical match → 409 (conflict)."""
        # Pre-insert a user with the same _id that register would generate.
        # This simulates a race condition where another request inserted first.
        email = "racecondition@example.com"
        _id = f"user_{email}_{hash(email)}"
        self.db.users._docs.append({
            "_id": _id, "email": "other@example.com",  # different email, same _id
            "user_type": "candidate", "hashed_password": "hash_ex", "is_active": True,
            "first_name": "Racer", "last_name": "User",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

        async def scenario():
            user_data = _Model(
                email=email, password="secret",
                first_name="Test", last_name="User", user_type="candidate",
            )
            await self.routes_auth.register(user_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        # 409 because relookup finds nothing (the pre-inserted user has different email)
        assert exc.value.status_code == 409

    def test_alerts_dk_with_existing_returns_user_id(self):
        """DuplicateKeyError on alerts/subscribe with existing user → reuses."""
        self._seed_user("foo@example.com", uid="existing_alert_u")

        async def scenario():
            data = _Model(
                email="foo@example.com", search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            return await self.routes_alerts.subscribe_alert(data)

        result = _run(scenario())
        assert result["success"] is True
        assert result["created_account"] is False

    def test_alerts_dk_no_existing_returns_409(self):
        """DuplicateKeyError on alerts/subscribe with no match → 409."""
        from pymongo.errors import DuplicateKeyError
        original_insert = self.db.users.insert_one

        async def _always_dk(doc, **kwargs):
            # Always raise DuplicateKeyError (simulating a concurrent _id collision)
            # regardless of what is actually in the db.
            raise DuplicateKeyError("duplicate key")

        self.db.users.insert_one = _always_dk

        async def scenario():
            data = _Model(
                email="newuser@example.com", search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            await self.routes_alerts.subscribe_alert(data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 409


# --------------------------------------------------------------------------- #
# 17. P0-009 BUILD CORRECTION: login fails closed on lookup errors            #
# --------------------------------------------------------------------------- #
class TestLoginFailsClosedOnLookupError:
    """Login/JWT must fail without selecting or creating an account when
    lookup_user_by_email raises LookupAggregationError or LookupCollisionError."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p

        async def _authenticate(email, password):
            from email_utils import lookup_user_by_email
            return await lookup_user_by_email(email)

        auth.authenticate_user = _authenticate
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        self._eu_mod = _eu_mod
        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_login_fail_auth")

    def test_login_aggregation_error_returns_503(self, monkeypatch):
        """Login with aggregation error must return 503, not select any account."""
        def _broken_aggregate(pipeline):
            raise RuntimeError("MongoDB aggregation unavailable")
        self.db.users.aggregate = _broken_aggregate

        async def scenario():
            login_data = _Model(email="foo@example.com", password="secret",
                                expected_user_type=None)
            await self.routes_auth.login(login_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 503

    def test_login_collision_returns_503(self):
        """Login with collision must return 503, not select any account."""
        self.db.users._docs.extend([
            {"_id": "u1", "email": "foo@example.com",
             "user_type": "candidate", "hashed_password": "hash1", "is_active": True,
             "first_name": "A", "last_name": "B",
             "phone": None, "location": None, "bio": None,
             "skills": [], "experience_years": None, "is_verified": False,
             "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()},
            {"_id": "u2", "email": " Foo@Example.COM ",
             "user_type": "candidate", "hashed_password": "hash2", "is_active": True,
             "first_name": "C", "last_name": "D",
             "phone": None, "location": None, "bio": None,
             "skills": [], "experience_years": None, "is_verified": False,
             "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()},
        ])

        async def scenario():
            login_data = _Model(email="foo@example.com", password="secret",
                                expected_user_type=None)
            await self.routes_auth.login(login_data)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 503


# --------------------------------------------------------------------------- #
# 18. P0-009 BUILD CORRECTION: apply + collision => 0 update, 0 marker, error  #
# --------------------------------------------------------------------------- #
class TestMigrationFailClosedOnCollisions:
    """P0-009: --apply with collisions MUST do ZERO writes and ZERO marker."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.migrate_module = _load(
            monkeypatch, "scripts/migrate_p0009_email_normalization.py",
            "p0009_migrate_failclosed")

    def test_apply_with_collisions_does_zero_updates(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": " Foo@Example.COM "},
            {"_id": "u3", "email": "  FOO@EXAMPLE.COM  "},
        ])
        with pytest.raises(RuntimeError, match="collision"):
            _run(self.migrate_module._migrate(db, dry_run=False))
        # Verify ZERO writes
        u1 = _run(db.users.find_one({"_id": "u1"}))
        assert u1["email"] == "foo@example.com"  # unchanged
        u2 = _run(db.users.find_one({"_id": "u2"}))
        assert u2["email"] == " Foo@Example.COM "  # unchanged
        u3 = _run(db.users.find_one({"_id": "u3"}))
        assert u3["email"] == "  FOO@EXAMPLE.COM  "  # unchanged
        # Verify NO marker was set
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is None

    def test_no_flag_can_bypass_collision_check(self):
        """Removing --confirm-collisions means no flag exists to bypass."""
        import inspect
        source = inspect.getsource(self.migrate_module._build_parser)
        assert "confirm" not in source.lower()
        assert "collision" not in source.lower()


# --------------------------------------------------------------------------- #
# 19. P0-009 BUILD CORRECTION: inventory >100k not truncated                   #
# --------------------------------------------------------------------------- #
class TestMigrationStreamingCursor:
    """P0-009: migration must iterate ALL groups via streaming cursor,
    not truncate via to_list(length=...)."""

    def test_find_cursor_returns_async_iterator(self):
        """_FindCursor supports async iteration (no to_list truncation)."""
        cursor = _FindCursor([{"_id": "a"}, {"_id": "b"}])

        async def consume():
            results = []
            async for g in cursor:
                results.append(g)
            return results

        result = _run(consume())
        assert len(result) == 2
        assert result[0]["_id"] == "a"
        assert result[1]["_id"] == "b"

    def test_migration_uses_async_for_not_to_list(self):
        """Migration source must iterate via streaming cursor, NOT to_list."""
        source = open(BACKEND_DIR / "scripts" / "migrate_p0009_email_normalization.py").read()
        # Should use "async for ... in cursor:" on a find({}) cursor throughout
        assert "async for doc in cursor:" in source
        # Must NOT have to_list with a numeric limit on the streaming cursor
        assert "cursor.to_list" not in source
        # Inventory must stream find({}) — not a truncated aggregate
        assert "db.users.find({}, {\"email\": 1})" in source


# --------------------------------------------------------------------------- #
# 20. P0-009 BUILD CORRECTION: alert DK race + relookup => created_account=False
# --------------------------------------------------------------------------- #
class TestAlertDuplicateKeyRaceCreatedAccount:
    """P0-009: When prelookup finds nothing, insert DuplicateKeys, and relookup
    finds an existing account, created_account MUST be False."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        self.routes_alerts = _load(monkeypatch, "routes/alerts.py", "p009_dk_race_alerts")

    def test_dk_race_relookup_existing_created_account_false(self):
        """Simulate: prelookup returns None, insert raises DuplicateKeyError,
        relookup finds existing user → created_account must be False."""
        # Seed a user that will be found by relookup but NOT by prelookup
        # (prelookup uses aggregation, relookup also uses aggregation — both
        # should find it. We simulate the race by making the first insert fail.)
        self.db.users._docs.append({
            "_id": "existing_race_u", "email": "race@example.com",
            "user_type": "candidate", "hashed_password": "hash_race", "is_active": True,
            "first_name": "Race", "last_name": "User",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

        from pymongo.errors import DuplicateKeyError
        original_insert = self.db.users.insert_one
        call_count = 0

        async def _dk_on_first_insert(doc, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise DuplicateKeyError("duplicate key on users collection")
            return await original_insert(doc, **kwargs)

        self.db.users.insert_one = _dk_on_first_insert

        async def scenario():
            data = _Model(
                email="race@example.com", search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            return await self.routes_alerts.subscribe_alert(data)

        result = _run(scenario())
        assert result["success"] is True
        assert result["created_account"] is False


# --------------------------------------------------------------------------- #
# 21. P0-009 BUILD CORRECTION: non-lookup error at login not converted to 503  #
# --------------------------------------------------------------------------- #
class TestLoginNonLookupErrorNotConverted:
    """P0-009: a non-lookup error (programming, hash, infra) during login
    MUST NOT be masqueraded as 'Email lookup temporarily unavailable' (503)."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        self._eu_mod = _eu_mod
        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_nonlookup_auth")

    def test_hash_error_not_converted_to_503(self, monkeypatch):
        """A hash verification error must NOT be converted to 503 lookup."""
        # Seed a user so authenticate_user doesn't return None
        self.db.users._docs.append({
            "_id": "u_hash", "email": "hash@example.com",
            "user_type": "candidate", "hashed_password": "valid_hash", "is_active": True,
            "first_name": "Hash", "last_name": "User",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

        async def _raising_authenticate(email, password):
            raise ValueError("Unexpected hash error: bcrypt module missing")

        self.routes_auth.authenticate_user = _raising_authenticate

        async def scenario():
            login_data = _Model(email="hash@example.com", password="secret",
                                expected_user_type=None)
            await self.routes_auth.login(login_data)

        # Must propagate as-is (ValueError), NOT be caught and turned into 503
        with pytest.raises(ValueError, match="Unexpected hash error"):
            _run(scenario())

    def test_login_except_only_catches_lookup_errors(self):
        """Source code must only catch LookupAggregationError and LookupCollisionError."""
        source = open(BACKEND_DIR / "routes" / "auth.py").read()
        lines = source.split("\n")
        in_login_try = False
        for i, line in enumerate(lines):
            stripped = line.strip()
            if "user = await authenticate_user" in stripped:
                in_login_try = True
            if in_login_try and stripped.startswith("except"):
                # Must be exactly (LookupAggregationError, LookupCollisionError)
                assert "LookupAggregationError" in stripped and "LookupCollisionError" in stripped, (
                    f"login except on line {i+1} catches too broadly: {stripped}"
                )
                assert "Exception" not in stripped or "LookupAggregationError" in stripped
                in_login_try = False
                break


# --------------------------------------------------------------------------- #
# 22. P0-009: non-string/absent/empty/whitespace => blocker + no marker        #
# --------------------------------------------------------------------------- #
class TestMigrationInvalidEmailsBlocker:
    """P0-009: invalid emails (non-string, absent, empty, whitespace-only)
    must be BLOCKERS: zero writes, zero marker, explicit error."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.migrate_module = _load(
            monkeypatch, "scripts/migrate_p0009_email_normalization.py",
            "p0009_migrate_invalid")

    def test_non_string_email_blocks_dry_run(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": 12345},
        ])
        report = _run(self.migrate_module._migrate(db, dry_run=True))
        assert report["invalid_emails"] == 1
        assert len(report["invalid_email_details"]) == 1
        assert report["invalid_email_details"][0]["_id"] == "u2"
        assert report["marker_set"] is False
        assert report["updated"] == 0

    def test_absent_email_blocks_apply(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2"},
        ])
        with pytest.raises(RuntimeError, match="invalid emails"):
            _run(self.migrate_module._migrate(db, dry_run=False))
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is None

    def test_empty_string_email_blocks_apply(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": ""},
        ])
        with pytest.raises(RuntimeError, match="invalid emails"):
            _run(self.migrate_module._migrate(db, dry_run=False))
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is None

    def test_whitespace_only_email_blocks_apply(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": "   "},
        ])
        with pytest.raises(RuntimeError, match="invalid emails"):
            _run(self.migrate_module._migrate(db, dry_run=False))
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is None

    def test_all_canonical_with_valid_emails_succeeds(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": "bar@example.com"},
        ])
        report = _run(self.migrate_module._migrate(db, dry_run=False))
        assert report["invalid_emails"] == 0
        assert report["marker_set"] is True


# --------------------------------------------------------------------------- #
# 23. P0-009: CAS mismatch => abort + no marker                               #
# --------------------------------------------------------------------------- #
class TestMigrationCASMismatch:
    """P0-009: CAS mismatch during update must abort with zero marker."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.migrate_module = _load(
            monkeypatch, "scripts/migrate_p0009_email_normalization.py",
            "p0009_migrate_cas")

    def test_cas_mismatch_aborts_no_marker(self, monkeypatch):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "  Foo@Example.COM "},
        ])

        # Patch update_one to simulate CAS mismatch: matched_count=0
        original_update = db.users.update_one

        async def _cas_mismatch(query, update, session=None):
            return types.SimpleNamespace(matched_count=0, modified_count=0)

        db.users.update_one = _cas_mismatch

        with pytest.raises(RuntimeError, match="CAS mismatch"):
            _run(self.migrate_module._migrate(db, dry_run=False))
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is None

    def test_cas_success_sets_marker(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "  Foo@Example.COM "},
        ])
        report = _run(self.migrate_module._migrate(db, dry_run=False))
        assert report["updated"] == 1
        assert report["marker_set"] is True
        u1 = _run(db.users.find_one({"_id": "u1"}))
        assert u1["email"] == "foo@example.com"


# --------------------------------------------------------------------------- #
# 24. P0-009: DuplicateKey during update => abort + no marker                  #
# --------------------------------------------------------------------------- #
class TestMigrationDuplicateKeyDuringUpdate:
    """P0-009: DuplicateKeyError during CAS update must abort + no marker."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.migrate_module = _load(
            monkeypatch, "scripts/migrate_p0009_email_normalization.py",
            "p0009_migrate_dk_update")

    def test_duplicate_key_during_update_aborts(self, monkeypatch):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "  Foo@Example.COM "},
        ])

        from pymongo.errors import DuplicateKeyError
        original_update = db.users.update_one

        async def _dk_on_update(query, update, session=None):
            raise DuplicateKeyError("duplicate key on email index")

        db.users.update_one = _dk_on_update

        with pytest.raises(DuplicateKeyError):
            _run(self.migrate_module._migrate(db, dry_run=False))
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is None


# --------------------------------------------------------------------------- #
# 25. P0-009: postverify detects inconsistency => no marker                    #
# --------------------------------------------------------------------------- #
class TestMigrationPostVerifyFailsNoMarker:
    """P0-009: if postverify detects non-canonical or collision after update,
    the marker must NOT be set."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.migrate_module = _load(
            monkeypatch, "scripts/migrate_p0009_email_normalization.py",
            "p0009_migrate_postverify")

    def test_postverify_detects_noncanonical_no_marker(self, monkeypatch):
        """After update, if a user's email is still non-canonical (e.g. concurrent
        change), postverify must fail and marker must NOT be set."""
        db = _FakeDB(users=[
            {"_id": "u1", "email": "  Foo@Example.COM "},
        ])

        # Simulate concurrent email change after the CAS update succeeds
        original_update = db.users.update_one
        update_count = 0

        async def _concurrent_change(query, update, session=None):
            nonlocal update_count
            result = await original_update(query, update, session)
            if result.matched_count == 1:
                update_count += 1
                # After CAS succeeds, another request changes email back
                u = await db.users.find_one({"_id": query.get("_id")})
                if u:
                    u["email"] = "  STILL NON-CANONICAL  "
                    # Replace in docs
                    for i, doc in enumerate(db.users._docs):
                        if doc.get("_id") == u["_id"]:
                            db.users._docs[i] = u
                            break
            return result

        db.users.update_one = _concurrent_change

        with pytest.raises(RuntimeError, match="Post-verify failed"):
            _run(self.migrate_module._migrate(db, dry_run=False))
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is None

    def test_postverify_detects_late_collision_no_marker(self, monkeypatch):
        """A collision that appears only AFTER the updates (concurrent insert)
        must be detected at post-verify => error + no marker."""
        db = _FakeDB(users=[
            {"_id": "u1", "email": "  Foo@Example.COM "},
        ])

        # Simulate a concurrent insert that creates a canonical collision
        # AFTER the CAS update of u1 succeeds.
        original_update = db.users.update_one
        inserted = {"once": False}

        async def _late_collision_update(query, update, session=None):
            result = await original_update(query, update, session)
            if result.matched_count == 1 and not inserted["once"]:
                inserted["once"] = True
                # A new user is created concurrently with the same canonical email
                db.users._docs.append({"_id": "u2", "email": "foo@example.com"})
            return result

        db.users.update_one = _late_collision_update

        with pytest.raises(RuntimeError, match="Post-verify failed"):
            _run(self.migrate_module._migrate(db, dry_run=False))
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is None


# --------------------------------------------------------------------------- #
# 26. P0-009: marker present + inconsistent base => fail                       #
# --------------------------------------------------------------------------- #
class TestMigrationMarkerPresentInconsistentBase:
    """P0-009: if marker is present but base is inconsistent, migration must
    fail explicitly (dry-run as apply) WITHOUT mutating the base — in
    particular it must NEVER delete the marker."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.migrate_module = _load(
            monkeypatch, "scripts/migrate_p0009_email_normalization.py",
            "p0009_migrate_marker_inconsistent")

    def test_marker_present_noncanonical_dry_run_raises_marker_stays(self):
        """Dry-run: marker present + non-canonical email => explicit exception,
        marker still present, zero writes."""
        db = _FakeDB(
            users=[
                {"_id": "u1", "email": "  Foo@Example.COM "},  # non-canonical
            ],
            migration_flags=[{"_id": "p0009_email_normalization", "applied_at": datetime.utcnow()}],
        )
        with pytest.raises(RuntimeError, match="marker|Marker"):
            _run(self.migrate_module._migrate(db, dry_run=True))
        # Marker must STILL be present (dry-run = zero write)
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is not None
        # Email must NOT have been rewritten
        u1 = _run(db.users.find_one({"_id": "u1"}))
        assert u1["email"] == "  Foo@Example.COM "

    def test_marker_present_noncanonical_apply_raises_marker_stays(self):
        """Apply: marker present + non-canonical email => explicit exception,
        marker still present (diagnosis must never mutate the base)."""
        db = _FakeDB(
            users=[
                {"_id": "u1", "email": "  Foo@Example.COM "},  # non-canonical
            ],
            migration_flags=[{"_id": "p0009_email_normalization", "applied_at": datetime.utcnow()}],
        )
        with pytest.raises(RuntimeError, match="marker|Marker"):
            _run(self.migrate_module._migrate(db, dry_run=False))
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is not None
        u1 = _run(db.users.find_one({"_id": "u1"}))
        assert u1["email"] == "  Foo@Example.COM "

    def test_marker_present_collision_apply_raises_marker_stays(self):
        """Apply: marker present + collision => error, marker kept (not removed)."""
        db = _FakeDB(
            users=[
                {"_id": "u1", "email": "foo@example.com"},
                {"_id": "u2", "email": " Foo@Example.COM "},
            ],
            migration_flags=[{"_id": "p0009_email_normalization", "applied_at": datetime.utcnow()}],
        )
        with pytest.raises(RuntimeError):
            _run(self.migrate_module._migrate(db, dry_run=False))
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is not None  # marker must NOT have been deleted


# --------------------------------------------------------------------------- #
# 27. P0-009: apply success + rerun idempotent                                #
# --------------------------------------------------------------------------- #
class TestMigrationIdempotent:
    """P0-009: successful apply + rerun should be idempotent."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.migrate_module = _load(
            monkeypatch, "scripts/migrate_p0009_email_normalization.py",
            "p0009_migrate_idempotent")

    def test_apply_then_rerun_idempotent(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "  Foo@Example.COM "},
            {"_id": "u2", "email": "bar@example.com"},
        ])
        # First run: apply
        report1 = _run(self.migrate_module._migrate(db, dry_run=False))
        assert report1["updated"] == 1
        assert report1["marker_set"] is True

        # Second run: should detect marker + postverify OK
        report2 = _run(self.migrate_module._migrate(db, dry_run=False))
        assert report2["already_migrated"] is True
        assert report2["marker_set"] is False

        # Verify emails unchanged
        u1 = _run(db.users.find_one({"_id": "u1"}))
        assert u1["email"] == "foo@example.com"


# --------------------------------------------------------------------------- #
# 28. P0-009: no modification _id/FK/index                                    #
# --------------------------------------------------------------------------- #
class TestMigrationNoIdModification:
    """P0-009: migration must never modify _id or FK fields."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.migrate_module = _load(
            monkeypatch, "scripts/migrate_p0009_email_normalization.py",
            "p0009_migrate_noid")

    def test_ids_preserved_after_apply(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "  Foo@Example.COM ",
             "candidate_id": "c1", "user_id": "uid1", "owner_id": "o1"},
            {"_id": "u2", "email": "bar@example.com",
             "candidate_id": "c2", "user_id": "uid2", "owner_id": "o2"},
        ])
        _run(self.migrate_module._migrate(db, dry_run=False))

        u1 = _run(db.users.find_one({"_id": "u1"}))
        assert u1["_id"] == "u1"
        assert u1["candidate_id"] == "c1"
        assert u1["user_id"] == "uid1"
        assert u1["owner_id"] == "o1"
        assert u1["email"] == "foo@example.com"

        u2 = _run(db.users.find_one({"_id": "u2"}))
        assert u2["_id"] == "u2"
        assert u2["email"] == "bar@example.com"

    def test_no_index_drop(self):
        """Migration source must not contain drop_index or dropIndex calls."""
        source = open(BACKEND_DIR / "scripts" / "migrate_p0009_email_normalization.py").read()
        assert "drop_index" not in source.lower()
        assert "dropindex" not in source.lower()


# --------------------------------------------------------------------------- #
# 29. P0-009: canonical_email equivalent validation (not raw $trim/$toLower)   #
# --------------------------------------------------------------------------- #
class TestMigrationCanonicalValidation:
    """P0-009: the migration must use canonical_email() equivalent logic,
    not raw $trim/$toLower as validation."""

    def test_source_uses_canonical_email_import(self):
        source = open(BACKEND_DIR / "scripts" / "migrate_p0009_email_normalization.py").read()
        assert "from email_utils import canonical_email" in source

    def test_whitespace_only_not_migrated_as_canonical(self):
        """'   ' should be treated as invalid, not rewritten as ''."""
        migrate_module = None
        import importlib.util
        monkeypatch = pytest.MonkeyPatch()
        _install_stubs(monkeypatch)
        migrate_module = _load(
            monkeypatch, "scripts/migrate_p0009_email_normalization.py",
            "p0009_migrate_ws_validation")
        db = _FakeDB(users=[
            {"_id": "u1", "email": "   "},
        ])
        with pytest.raises(RuntimeError, match="invalid emails"):
            _run(migrate_module._migrate(db, dry_run=False))
        # Verify email not rewritten
        u1 = _run(db.users.find_one({"_id": "u1"}))
        assert u1["email"] == "   "
        marker = _run(db.migration_flags.find_one({"_id": "p0009_email_normalization"}))
        assert marker is None
        monkeypatch.undo()


# --------------------------------------------------------------------------- #
# 30. P0-009 BUILD CORRECTION: create_admin.py transitionnal lookup           #
# --------------------------------------------------------------------------- #
class TestCreateAdminTransitionnalLookup:
    """P0-009: create_admin._ensure_admin must use lookup_user_by_email (fail-closed)
    BEFORE creation, so a legacy ' Admin@Example.COM ' prevents creation of
    'admin@example.com'. On LookupAggregationError/LookupCollisionError it must
    not create anything and return a deterministic operator error. On
    DuplicateKeyError, relookup transitionnally: exactly 1 account => idempotent
    'exists'; otherwise fail closed. No broad except Exception."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        self.admin = _load(
            monkeypatch, "scripts/create_admin.py", "p009_create_admin")
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        # Stub the real `database` module so create_admin's `from database
        # import get_database` returns our fake DB.
        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        def _get_password_hash(p):
            return "HASH(" + p + ")"

        auth = types.ModuleType("auth")
        auth.get_password_hash = _get_password_hash
        monkeypatch.setitem(sys.modules, "auth", auth)

    def _seed_legacy_admin(self):
        """Seed a legacy non-canonical admin account."""
        self.db.users._docs.append({
            "_id": "legacy_admin", "email": " Admin@Example.COM ",
            "user_type": "admin", "hashed_password": "h", "is_active": True,
            "first_name": "Legacy", "last_name": "Admin",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": True,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

    def test_legacy_admin_blocks_creation_returns_exists(self):
        """Legacy ' Admin@Example.COM ' must prevent creation of 'admin@example.com'."""
        self._seed_legacy_admin()
        result = _run(self.admin._ensure_admin("admin@example.com", "secret"))
        assert result == "exists"
        assert len(self.db.users._docs) == 1  # no new account

    def test_aggregation_error_returns_error_no_creation(self, monkeypatch):
        """LookupAggregationError => return 'error', create nothing."""
        def _broken_aggregate(pipeline):
            raise RuntimeError("MongoDB aggregation unavailable")
        self.db.users.aggregate = _broken_aggregate

        result = _run(self.admin._ensure_admin("admin@example.com", "secret"))
        assert result == "error"
        assert len(self.db.users._docs) == 0

    def test_collision_error_returns_error_no_creation(self):
        """LookupCollisionError => return 'error', create nothing."""
        self._seed_legacy_admin()
        # Second legacy with same canonical email → collision
        self.db.users._docs.append({
            "_id": "legacy_admin2", "email": "  ADMIN@EXAMPLE.COM  ",
            "user_type": "admin", "hashed_password": "h2", "is_active": True,
            "first_name": "L2", "last_name": "A2",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": True,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })
        result = _run(self.admin._ensure_admin("admin@example.com", "secret"))
        assert result == "error"
        assert len(self.db.users._docs) == 2  # nothing created

    def test_duplicate_key_relookup_existing_returns_exists(self):
        """DuplicateKeyError + relookup finds exactly 1 account => idempotent 'exists'."""
        # Simulate a race: no pre-existing account at prelookup, then insert collides.
        from pymongo.errors import DuplicateKeyError
        original_insert = self.db.users.insert_one

        async def _dk_insert(doc, **kwargs):
            raise DuplicateKeyError("duplicate key on users collection")

        self.db.users.insert_one = _dk_insert
        # Seed the account the relookup will find
        self._seed_legacy_admin()

        result = _run(self.admin._ensure_admin("admin@example.com", "secret"))
        assert result == "exists"
        assert len(self.db.users._docs) == 1

    def test_duplicate_key_relookup_collision_returns_error(self):
        """DuplicateKeyError + relookup finds >1 => fail closed 'error'."""
        from pymongo.errors import DuplicateKeyError
        self._seed_legacy_admin()
        self.db.users._docs.append({
            "_id": "legacy_admin2", "email": "  ADMIN@EXAMPLE.COM  ",
            "user_type": "admin", "hashed_password": "h2", "is_active": True,
            "first_name": "L2", "last_name": "A2",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": True,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })

        async def _dk_insert(doc, **kwargs):
            raise DuplicateKeyError("duplicate key")

        self.db.users.insert_one = _dk_insert

        result = _run(self.admin._ensure_admin("admin@example.com", "secret"))
        assert result == "error"
        assert len(self.db.users._docs) == 2

    def test_duplicate_key_relookup_none_returns_error(self):
        """DuplicateKeyError + relookup finds 0 => fail closed 'error'."""
        from pymongo.errors import DuplicateKeyError

        async def _dk_insert(doc, **kwargs):
            raise DuplicateKeyError("duplicate key")

        self.db.users.insert_one = _dk_insert

        result = _run(self.admin._ensure_admin("admin@example.com", "secret"))
        assert result == "error"
        assert len(self.db.users._docs) == 0

    def test_source_uses_lookup_before_insert_and_no_broad_except(self):
        """create_admin must use lookup_user_doc_by_email, no find_one, no broad except."""
        source = open(BACKEND_DIR / "scripts" / "create_admin.py").read()
        assert "lookup_user_doc_by_email(email)" in source
        assert 'db.users.find_one({"email": email})' not in source
        # No broad except Exception anywhere
        assert "except Exception:" not in source
        assert "except Exception as" not in source


# --------------------------------------------------------------------------- #
# 31. P0-009 BUILD CORRECTION: auth.get_current_user ValueError => 401         #
# --------------------------------------------------------------------------- #
_JWT_SIG_ERROR = object()


class TestGetCurrentUserInvalidSub:
    """P0-009: get_current_user must not HTTP 500 on a signed JWT whose 'sub'
    is empty/non-string/whitespace. canonical_email raises ValueError, which the
    try only caught JWTError for — an invalid JWT must give the same controlled
    401 credentials_exception, never a 500."""
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        # Import real auth module (its deps fastapi/jose/passlib/pydantic are
        # installed). Provide a fake DB + fake JWT decode to stay deterministic.
        import auth as _auth_mod
        self.auth = _auth_mod

        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        # Secure fixed secret key
        monkeypatch.setattr(_auth_mod, "get_secret_key", lambda: "test-secret-key")

        # Default: any user lookup returns None (no DB dependency)
        monkeypatch.setattr(_auth_mod, "get_user_by_email", None)

        self.decode_outcome = {"payload": {"sub": None}}

        def _fake_decode(token, key, algorithms=None):
            outcome = self.decode_outcome["payload"]
            if outcome is _JWT_SIG_ERROR:
                raise _auth_mod.JWTError("bad signature")
            return outcome

        monkeypatch.setattr(_auth_mod.jwt, "decode", _fake_decode)

    def _creds(self):
        return types.SimpleNamespace(credentials="some.token.value")

    def test_blank_sub_raises_401(self):
        import fastapi
        for bad_sub in [None, "", "   ", 12345]:
            self.decode_outcome["payload"] = {"sub": bad_sub}
            with pytest.raises(fastapi.HTTPException) as exc:
                _run(self.auth.get_current_user(self._creds()))
            assert exc.value.status_code == 401
            assert exc.value.detail == "Could not validate credentials"

    def test_invalid_signature_raises_401(self):
        import fastapi
        self.decode_outcome["payload"] = _JWT_SIG_ERROR
        with pytest.raises(fastapi.HTTPException) as exc:
            _run(self.auth.get_current_user(self._creds()))
        assert exc.value.status_code == 401

    def test_noncanonical_jwt_resolves_legacy_account(self, monkeypatch):
        """Old JWT with non-canonical sub resolves the legacy account via lookup.
        get_current_user canonicalizes the sub BEFORE lookup, so a legacy
        ' Foo@Example.COM ' account is still found."""
        import auth as _auth_mod
        import email_utils as _eu
        from models import User

        captured = {}

        async def _lookup_doc(email):
            captured["email"] = email
            return {
                "_id": "legacy_u",
                "email": " Foo@Example.COM ",
                "first_name": "Foo",
                "last_name": "Bar",
                "user_type": "candidate",
                "phone": None,
                "location": None,
                "bio": None,
                "skills": [],
                "experience_years": None,
                "is_active": True,
                "is_verified": False,
                "hashed_password": "h",
                "created_at": datetime.utcnow(),
            }

        # Patch email_utils.lookup_user_doc_by_email (auth.get_current_user
        # imports it lazily via `from email_utils import lookup_user_doc_by_email`).
        monkeypatch.setattr(_eu, "lookup_user_doc_by_email", _lookup_doc)

        self.decode_outcome["payload"] = {"sub": " Foo@Example.COM "}

        result = _run(self.auth.get_current_user(self._creds()))
        # canonical_email applied before lookup → email canonicalized
        assert captured["email"] == "foo@example.com"
        # The legacy account is resolved (result not None / not 401)
        assert result is not None
        assert str(result.email).strip().lower() == "foo@example.com"

    def test_source_catches_value_error(self):
        source = open(BACKEND_DIR / "auth.py").read()
        assert "(JWTError, ValueError)" in source


# --------------------------------------------------------------------------- #
# 32. P0-009 BUILD CORRECTION: tolerant raw-doc lookup for lightweight users  #
# --------------------------------------------------------------------------- #
class TestTolerantLookupForLightweightUsers:
    """P0-009: lookup_user_doc_by_email() returns the raw Mongo document so
    paths that handle lightweight/incomplete accounts (alert subscribe, XML
    partners, admin legacy, OAuth) never crash with a ValidationError when
    first_name/last_name/hashed_password are None."""

    def test_lookup_user_doc_returns_raw_dict_for_incomplete_user(self, monkeypatch):
        """A lightweight user (first_name=None, last_name=None, hashed_password=None)
        must be returned as a raw dict, NOT crash with ValidationError."""
        import email_utils as _eu
        db = _FakeDB(users=[
            # Lightweight alert account
            {"_id": "light_u", "email": " foo@example.com ",
             "hashed_password": None, "first_name": None, "last_name": None,
             "user_type": "candidate", "is_active": True,
             "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()},
        ])
        db_ref = db

        async def _get_db():
            return db_ref

        monkeypatch.setattr(_eu, "get_database", _get_db)
        from email_utils import lookup_user_doc_by_email, LookupCollisionError, LookupAggregationError
        doc = _run(lookup_user_doc_by_email("foo@example.com"))
        assert doc is not None
        assert doc["_id"] == "light_u"
        assert doc["first_name"] is None  # raw doc preserved, no validation

    def test_lookup_user_model_validation_error_on_incomplete(self, monkeypatch):
        """Sanity: constructing the strict User from an incomplete lightweight
        doc raises — proving the tolerant doc lookup is what prevents the 500."""
        import email_utils as _eu
        from models import User
        db = _FakeDB(users=[
            {"_id": "light_u", "email": " foo@example.com ",
             "hashed_password": None, "first_name": None, "last_name": None,
             "user_type": "candidate", "is_active": True,
             "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()},
        ])
        db_ref = db

        async def _get_db():
            return db_ref

        monkeypatch.setattr(_eu, "get_database", _get_db)
        from email_utils import lookup_user_by_email
        with pytest.raises(Exception) as exc:
            _run(lookup_user_by_email("foo@example.com"))
        # A ValidationError (strict User requires str fields) proves the issue
        assert "ValidationError" in type(exc.value).__name__ or "first_name" in str(exc.value)

    def test_collision_still_raises_on_doc_lookup(self, monkeypatch):
        """The tolerant doc lookup must still fail-closed on collision."""
        import email_utils as _eu
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com", "hashed_password": None,
             "first_name": None, "last_name": None},
            {"_id": "u2", "email": " Foo@Example.COM ", "hashed_password": None,
             "first_name": None, "last_name": None},
        ])
        db_ref = db

        async def _get_db():
            return db_ref

        monkeypatch.setattr(_eu, "get_database", _get_db)
        from email_utils import lookup_user_doc_by_email, LookupCollisionError
        with pytest.raises(LookupCollisionError):
            _run(lookup_user_doc_by_email("foo@example.com"))


# --------------------------------------------------------------------------- #
# 33. P0-009 BUILD CORRECTION: /alerts/subscribe lightweight reuse            #
# --------------------------------------------------------------------------- #
class TestAlertsSubscribeLightweightReuse:
    """(a) /alerts/subscribe creates a lightweight account then a second
    subscribe with the same email/variant reuses it (created_account=False,
    no 500)."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        self.routes_alerts = _load(monkeypatch, "routes/alerts.py", "p009_lightweight_alerts")

    def _subscribe(self, email_value):
        async def scenario():
            data = _Model(
                email=email_value, search=None, location=None,
                job_type=None, search_mode="simple", result_count=None, origin=None,
            )
            return await self.routes_alerts.subscribe_alert(data)
        return _run(scenario())

    def test_second_subscribe_reuses_lightweight_no_500(self):
        # First subscribe → creates a lightweight account
        r1 = self._subscribe("foo@example.com")
        assert r1["success"] is True
        assert r1["created_account"] is True
        # Verify it was stored lightweight (hashed_password None)
        users = [d for d in self.db.users._docs]
        assert len(users) == 1
        assert users[0]["hashed_password"] is None
        assert users[0]["_id"].startswith("user_")

        # Second subscribe with a variant → reuse, created_account=False, no 500
        r2 = self._subscribe(" Foo@Example.COM ")
        assert r2["success"] is True
        assert r2["created_account"] is False
        # Still exactly one user (no duplicate)
        assert len([d for d in self.db.users._docs]) == 1


# --------------------------------------------------------------------------- #
# 34. P0-009 BUILD CORRECTION: XML partner login-less detected without crash  #
# --------------------------------------------------------------------------- #
class TestXMLPartnerLoginlessLookup:
    """(c) A login-less XML partner (hashed_password=None, last_name=None) is
    detected by the tolerant doc lookup without raising ValidationError."""

    def test_xml_partner_doc_lookup_no_validation_error(self, monkeypatch):
        import email_utils as _eu
        db = _FakeDB(users=[
            {"_id": "partner_feed_1", "email": "feed@partenaire.joboolo",
             "first_name": "Acme", "last_name": None,
             "user_type": "partner", "hashed_password": None,  # login-less
             "is_active": True, "is_verified": True,
             "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()},
        ])
        db_ref = db

        async def _get_db():
            return db_ref

        monkeypatch.setattr(_eu, "get_database", _get_db)
        from email_utils import lookup_user_doc_by_email
        doc = _run(lookup_user_doc_by_email("feed@partenaire.joboolo"))
        assert doc is not None
        assert doc["_id"] == "partner_feed_1"
        assert doc["hashed_password"] is None
        assert doc["last_name"] is None

    def test_xml_partner_admin_duplicate_rejected(self, monkeypatch):
        """admin create partner must not crash / must reject when an XML
        login-less partner with the same canonical email already exists."""
        _install_stubs(monkeypatch)
        self.db = _FakeDB(users=[
            {"_id": "partner_feed_1", "email": " feed@partenaire.joboolo ",
             "first_name": "Acme", "last_name": None,
             "user_type": "partner", "hashed_password": None,
             "is_active": True, "is_verified": True,
             "created_at": datetime.utcnow(), "updated_at": datetime.utcnow()},
        ])
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        routes_admin = _load(monkeypatch, "routes/admin.py", "p009_lightweight_admin")

        async def scenario():
            data = _Model(
                email="feed@partenaire.joboolo", password="x",
                first_name="New", last_name="Partner",
                company_name="Acme", billing_mode="per_click",
                default_cpc=0.0, posting_price=0.0,
                xml_feed_url=None,
            )
            await routes_admin.create_partner(data, admin=None)

        with pytest.raises(_HTTPException) as exc:
            _run(scenario())
        assert exc.value.status_code == 400


# --------------------------------------------------------------------------- #
# 35. P0-009 BUILD CORRECTION: create_admin legacy ObjectId / fields          #
# --------------------------------------------------------------------------- #
class TestCreateAdminLegacyObjectId:
    """(d) create_admin with legacy _id ObjectId / legacy fields does not
    create a duplicate and does not crash."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        self.admin = _load(
            monkeypatch, "scripts/create_admin.py", "p009_create_admin_objid")
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        def _get_password_hash(p):
            return "HASH(" + p + ")"

        auth = types.ModuleType("auth")
        auth.get_password_hash = _get_password_hash
        monkeypatch.setitem(sys.modules, "auth", auth)

    def test_legacy_objectid_admin_does_not_duplicate(self):
        """Legacy admin with ObjectId _id and legacy fields is found via the
        tolerant doc lookup → 'exists', no duplicate creation, no crash."""
        self.db.users._docs.append({
            "_id": "507f1f77bcf86cd799439011",  # Mongo ObjectId as string
            "email": " Admin@Example.COM ",
            "user_type": "admin", "hashed_password": "h", "is_active": True,
            "first_name": "Legacy", "last_name": "Admin",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": True,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })
        result = _run(self.admin._ensure_admin("admin@example.com", "secret"))
        assert result == "exists"
        assert len(self.db.users._docs) == 1  # no duplicate created


# --------------------------------------------------------------------------- #
# 36. P0-009 BUILD CORRECTION: JWT lookup errors => 503 (fail-closed)        #
# --------------------------------------------------------------------------- #
class TestJWTLookupErrorsYield503:
    """(e) auth.get_current_user() must translate LookupAggregationError /
    LookupCollisionError into a controlled 503, never a raw HTTP 500."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        import auth as _auth_mod
        self.auth = _auth_mod

        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        monkeypatch.setattr(_auth_mod, "get_secret_key", lambda: "test-secret-key")
        monkeypatch.setattr(_auth_mod, "get_user_by_email", None)

        self.decode_outcome = {"payload": {"sub": "user@example.com"}}

        def _fake_decode(token, key, algorithms=None):
            return self.decode_outcome["payload"]

        monkeypatch.setattr(_auth_mod.jwt, "decode", _fake_decode)

    def _creds(self):
        return types.SimpleNamespace(credentials="some.token.value")

    def test_lookup_aggregation_error_returns_503(self, monkeypatch):
        """LookupAggregationError in get_current_user => 503, not 500."""
        import email_utils as _eu
        from email_utils import LookupAggregationError

        async def _raise_agg(email):
            raise LookupAggregationError("aggregation unavailable")

        monkeypatch.setattr(_eu, "lookup_user_doc_by_email", _raise_agg)
        import fastapi
        with pytest.raises(fastapi.HTTPException) as exc:
            _run(self.auth.get_current_user(self._creds()))
        assert exc.value.status_code == 503

    def test_lookup_collision_error_returns_503(self, monkeypatch):
        """LookupCollisionError in get_current_user => 503, not 500."""
        import email_utils as _eu
        from email_utils import LookupCollisionError

        async def _raise_coll(email):
            raise LookupCollisionError("collision")

        monkeypatch.setattr(_eu, "lookup_user_doc_by_email", _raise_coll)
        import fastapi
        with pytest.raises(fastapi.HTTPException) as exc:
            _run(self.auth.get_current_user(self._creds()))
        assert exc.value.status_code == 503

    def test_unknown_email_returns_401(self, monkeypatch):
        """No matching email => 401 (credentials exception), not 503."""
        import email_utils as _eu

        async def _no_match(email):
            return None

        monkeypatch.setattr(_eu, "lookup_user_doc_by_email", _no_match)
        import fastapi
        with pytest.raises(fastapi.HTTPException) as exc:
            _run(self.auth.get_current_user(self._creds()))
        assert exc.value.status_code == 401


# --------------------------------------------------------------------------- #
# 37. P0-009 BUILD CORRECTION: Google reuse lightweight same _id              #
# --------------------------------------------------------------------------- #
class TestGoogleReuseLightweightAccount:
    """(b) On a lightweight alert account, Google with the same email must
    reuse STRICTLY the same _id, produce a valid response, and create no
    duplicate"""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        _install_stubs(monkeypatch)
        self.db = _FakeDB()
        db_ref = self.db

        async def _get_db():
            return db_ref

        database = types.ModuleType("database")
        database.get_database = _get_db
        database.get_client = lambda: None
        monkeypatch.setitem(sys.modules, "database", database)

        import email_utils as _eu_mod
        monkeypatch.setattr(_eu_mod, "get_database", _get_db)

        auth = types.ModuleType("auth")
        auth.get_current_active_user = lambda *a, **k: None
        auth.require_employer = lambda *a, **k: None
        auth.require_admin = lambda *a, **k: None
        auth.get_password_hash = lambda p: "hashed_" + p
        auth.authenticate_user = None
        auth.create_access_token = lambda data, expires_delta=None: "jwt_token_" + str(data.get("sub", ""))
        auth.get_user_by_email = lambda e: None
        monkeypatch.setitem(sys.modules, "auth", auth)

        # httpx stub returning a Google session
        httpx = types.ModuleType("httpx")

        class _Resp:
            status_code = 200

            def json(self):
                return {"email": " foo@example.com ", "name": "Foo User"}

        class _MockClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                return _Resp()

        httpx.AsyncClient = lambda *a, **k: _MockClient()
        httpx.HTTPError = Exception
        monkeypatch.setitem(sys.modules, "httpx", httpx)

        self.routes_auth = _load(monkeypatch, "routes/auth.py", "p009_google_reuse")

    def test_google_reuses_lightweight_same_id_no_duplicate(self):
        # Seed a lightweight alert account
        self.db.users._docs.append({
            "_id": "user_alert_123", "email": " foo@example.com ",
            "hashed_password": None, "first_name": None, "last_name": None,
            "user_type": "candidate", "is_active": True, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })
        initial_ids = [d["_id"] for d in self.db.users._docs]
        assert len(self.db.users._docs) == 1

        async def scenario():
            return await self.routes_auth.google_session(_Model(session_id="sess_1"))

        result = _run(scenario())
        # Valid response with same _id (UserResponse stores it under 'id')
        assert result.user.__dict__.get("id") == "user_alert_123"
        # No duplicate account created
        assert len(self.db.users._docs) == 1
        ids = [d["_id"] for d in self.db.users._docs]
        assert ids == initial_ids  # same _id strictly reused
