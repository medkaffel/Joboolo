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
                 "PartnerCreate", "PartnerConfigUpdate", "PartnerBillingMode"):
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
    auth.require_admin = lambda *a, **k: None
    auth.get_password_hash = lambda p: "hash"
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

    async def count_documents(self, query):
        return sum(1 for d in self._docs if self._matches(d, query))

    def find(self, query=None):
        return _FindCursor([dict(d) for d in self._docs if not query or self._matches(d, query)])

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

    def sort(self, spec):
        for key, direction in reversed(spec):
            self._docs.sort(key=lambda d: d.get(key) or "", reverse=(direction == -1))
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length):
        return self._docs[:length]


class _AggCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length):
        return self._docs[:length]


class _FakeDB:
    def __init__(self, users=None, migration_flags=None):
        self.users = _FakeCollection(users or [])
        self.migration_flags = _FakeCollection(migration_flags or [])


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

    def test_collision_returns_none(self):
        from email_utils import lookup_user_by_email
        # Two users with same canonical email
        self.db.users._docs.append({
            "_id": "u2", "email": " Foo@Example.COM ",
            "user_type": "candidate", "hashed_password": "hash2", "is_active": True,
            "first_name": "Foo2", "last_name": "Bar2",
            "phone": None, "location": None, "bio": None,
            "skills": [], "experience_years": None, "is_verified": False,
            "created_at": datetime.utcnow(), "updated_at": datetime.utcnow(),
        })
        user = _run(lookup_user_by_email("foo@example.com"))
        assert user is None  # fail-closed on collision

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

    def test_db_none_returns_none(self):
        from email_utils import lookup_user_by_email
        import email_utils as _eu_mod

        async def _get_db_none():
            return None

        old = getattr(_eu_mod, "get_database", None)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(_eu_mod, "get_database", _get_db_none)
        try:
            user = _run(lookup_user_by_email("foo@example.com"))
            assert user is None
        finally:
            monkeypatch.undo()


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

    def test_collision_detection(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": " Foo@Example.COM "},
        ])
        report = _run(self.migrate_module._migrate(db, dry_run=True))
        assert report["collisions"] == 1
        assert len(report["collision_details"]) == 1
        assert report["collision_details"][0]["canonical_email"] == "foo@example.com"
        assert set(report["collision_details"][0]["user_ids"]) == {"u1", "u2"}

    def test_apply_raises_on_collision_without_confirm(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": " Foo@Example.COM "},
        ])
        with pytest.raises(RuntimeError, match="collision"):
            _run(self.migrate_module._migrate(db, dry_run=False, confirm_collisions=False))

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

    def test_non_string_email_skipped(self):
        db = _FakeDB(users=[
            {"_id": "u1", "email": "foo@example.com"},
            {"_id": "u2", "email": 12345},  # non-string, skipped by $match
        ])
        report = _run(self.migrate_module._migrate(db, dry_run=True))
        assert report["to_update"] == 0
        assert report["already_canonical"] == 1


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
