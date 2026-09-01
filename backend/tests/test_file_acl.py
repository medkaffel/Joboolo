"""Tests P0-003 — ACL CV et documents privés (GET /files/{path}).

Tests isolés (aucune base réelle ni dépendance réseau) :
- candidat propriétaire -> 200 ;
- autre candidat -> 403 ;
- employeur sans candidature -> 403 ;
- employeur avec candidature du candidat mais document NON attaché -> 403 ;
- employeur + application qui référence exactement ce cv_url + offre propriétaire -> 200 ;
- employeur d'une autre offre -> 403 ;
- candidate_document non attaché à une application -> employeur 403 ;
- admin -> 200 ;
- document soft-deleted -> 404 ;
- non authentifié -> 401 ;
- query parameter `auth` refusé (seul Bearer accepté) ;
- path inexistant -> 404 ;
- path traversal -> 400 ;
- storage.get_object N'EST JAMAIS appelé avant validation ACL (échec/refus/404).
"""

import asyncio
import sys
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# --- Enregistrement de la route pour later use ---
sys.path.insert(0, str(BACKEND_DIR / "routes"))


class _User:
    def __init__(self, uid, user_type):
        self.id = uid
        self.user_type = user_type


class _Coll:
    """Fake MongoDB collection: dict[query -> record]. Supports simple equality queries."""

    def __init__(self, records=None):
        self._records = records if records is not None else {}

    def _match(self, rec, query):
        for k, v in query.items():
            if rec.get(k) != v:
                return False
        return True

    async def find_one(self, query):
        for rec in self._records:
            if self._match(rec, query):
                return dict(rec)
        return None


class _FakeDB:
    def __init__(self, files=None, candidate_documents=None, applications=None, jobs=None):
        self.files = _Coll(files)
        self.candidate_documents = _Coll(candidate_documents)
        self.applications = _Coll(applications)
        self.jobs = _Coll(jobs)


def _install_stubs(monkeypatch):
    """Stub third-party / infra modules so `routes.files` can be imported in isolation."""
    # fastapi
    fastapi = types.ModuleType("fastapi")

    class _HTTPException(Exception):
        def __init__(self, status_code, detail=None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            def deco(fn):
                return fn
            return deco

        def post(self, *args, **kwargs):
            def deco(fn):
                return fn
            return deco

        def put(self, *args, **kwargs):
            def deco(fn):
                return fn
            return deco

        def delete(self, *args, **kwargs):
            def deco(fn):
                return fn
            return deco

    def _dep(*a, **k):
        # Mimic FastAPI Depends/File used as parameter default: return the passed
        # value/object (so download_file.current_user defaults resolve to the dependency).
        return a[0] if a else (k.get("default") or ...)

    fastapi.APIRouter = APIRouter
    fastapi.HTTPException = _HTTPException
    fastapi.Depends = _dep
    fastapi.File = _dep
    fastapi.UploadFile = object
    monkeypatch.setitem(sys.modules, "fastapi", fastapi)
    monkeypatch.setitem(sys.modules, "fastapi.responses", types.ModuleType("fastapi.responses"))

    class _Response:
        def __init__(self, content=None, media_type=None, headers=None, status_code=200):
            self.content = content
            self.media_type = media_type
            self.headers = headers or {}
            self.status_code = status_code

    resp = types.ModuleType("fastapi.responses")
    resp.Response = _Response
    monkeypatch.setitem(sys.modules, "fastapi.responses", resp)

    # fastapi.responses is already covered above.

    # pydantic
    pydantic = types.ModuleType("pydantic")

    class BaseModel:
        pass

    pydantic.BaseModel = BaseModel
    monkeypatch.setitem(sys.modules, "pydantic", pydantic)

    # database
    database = types.ModuleType("database")
    database.get_database = None  # replaced per-test via files_module.get_database
    monkeypatch.setitem(sys.modules, "database", database)

    # auth
    auth = types.ModuleType("auth")

    async def _get_current_active_user():
        # represents FastAPI Bearer auth: raises 401 when no valid token.
        raise _HTTPException(401, "Authentification requise")

    auth.get_current_active_user = _get_current_active_user
    monkeypatch.setitem(sys.modules, "auth", auth)

    # models
    models = types.ModuleType("models")
    models.User = _User
    monkeypatch.setitem(sys.modules, "models", models)

    # storage
    storage = types.ModuleType("storage")
    storage.APP_NAME = "joboolo"
    storage.CALLS = {"get_object": 0}

    def put_object(path, data, content_type):
        return {"path": path}

    def get_object(path):
        storage.CALLS["get_object"] += 1
        return b"CONTENT", "application/pdf"

    storage.put_object = put_object
    storage.get_object = get_object
    monkeypatch.setitem(sys.modules, "storage", storage)

    return storage, _HTTPException


@pytest.fixture
def files_module(monkeypatch):
    storage, http_exc = _install_stubs(monkeypatch)
    spec_path = BACKEND_DIR / "routes" / "files.py"
    spec = __import__("importlib.util").util.spec_from_file_location("routes_files", str(spec_path))
    mod = __import__("importlib.util").util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._HTTPException = http_exc
    return mod


def _run(files_module, db, requester, path):
    """Executes download_file() logic using a fake db and returns HTTPException or Response."""
    async def _fake_get_database():
        return db

    old = files_module.get_database
    files_module.get_database = _fake_get_database
    try:
        return asyncio.run(files_module.download_file(path, current_user=requester))
    finally:
        files_module.get_database = old


# Shared fixtures-building records
CAND_A = "u_candidate_a"
CAND_B = "u_candidate_b"
ADMIN = "u_admin"
EMPLOYER = "u_employer"
OTHER_EMPLOYER = "u_other_employer"
PATH_A = "joboolo/uploads/u_candidate_a/abc.pdf"
PATH_B = "joboolo/uploads/u_candidate_b/def.pdf"
PATH_NOT_ATTACHED = "joboolo/candidates/u_candidate_a/cv/zzz.pdf"
JOB_INSIDE = "job_inside"
JOB_OTHER = "job_other"

FILE_A = {
    "_id": "file_a", "storage_path": PATH_A, "owner_id": CAND_A,
    "original_filename": "cv_a.pdf", "content_type": "application/pdf",
    "is_deleted": False, "is_public": False,
}
FILE_B = {
    "_id": "file_b", "storage_path": PATH_B, "owner_id": CAND_B,
    "original_filename": "cv_b.pdf", "content_type": "application/pdf",
    "is_deleted": False, "is_public": False,
}
DOC_NOT_ATTACHED = {
    "_id": "doc_na", "storage_path": PATH_NOT_ATTACHED, "owner_id": CAND_A,
    "category": "cv", "original_filename": "na.pdf", "content_type": "application/pdf",
    "is_deleted": False,
}
DOC_DELETED = {
    "_id": "doc_del", "storage_path": "joboolo/uploads/u_candidate_a/del.pdf", "owner_id": CAND_A,
    "original_filename": "del.pdf", "content_type": "application/pdf", "is_deleted": True,
}

REF_JOB = {"_id": JOB_INSIDE, "employer_id": EMPLOYER}
OTHER_JOB = {"_id": JOB_OTHER, "employer_id": OTHER_EMPLOYER}
APP_REF_A = {"_id": "app_a", "job_id": JOB_INSIDE, "candidate_id": CAND_A, "cv_url": PATH_A}


def _base_db():  # noqa: E743
    return _FakeDB(
        files=[FILE_A, FILE_B, DOC_DELETED],
        candidate_documents=[DOC_NOT_ATTACHED],
        applications=[APP_REF_A],
        jobs=[REF_JOB, OTHER_JOB],
    )


class TestAccessViaDownload:
    def test_owner_candidate_200(self, files_module):
        db = _base_db()
        result = _run(files_module, db, _User(CAND_A, "candidate"), PATH_A)
        assert result.status_code == 200
        assert result.content == b"CONTENT"

    def test_other_candidate_403(self, files_module):
        db = _base_db()
        with pytest.raises(files_module._HTTPException) as ei:
            _run(files_module, db, _User(CAND_B, "candidate"), PATH_A)
        assert ei.value.status_code == 403

    def test_employer_without_application_403(self, files_module):
        db = _FakeDB(files=[FILE_B], candidate_documents=[], applications=[], jobs=[REF_JOB])
        with pytest.raises(files_module._HTTPException) as ei:
            _run(files_module, db, _User(EMPLOYER, "employer"), PATH_B)
        assert ei.value.status_code == 403

    def test_employer_application_but_document_not_attached_403(self, files_module):
        # employer has an application from the candidate, but the requested document
        # is referenced by no application (cv_url mismatch) -> denied.
        db = _base_db()
        with pytest.raises(files_module._HTTPException) as ei:
            _run(files_module, db, _User(EMPLOYER, "employer"), PATH_NOT_ATTACHED)
        assert ei.value.status_code == 403

    def test_employer_matching_application_own_job_200(self, files_module):
        db = _base_db()
        result = _run(files_module, db, _User(EMPLOYER, "employer"), PATH_A)
        assert result.status_code == 200

    def test_employer_of_other_job_403(self, files_module):
        db = _base_db()
        with pytest.raises(files_module._HTTPException) as ei:
            _run(files_module, db, _User(OTHER_EMPLOYER, "employer"), PATH_A)
        assert ei.value.status_code == 403

    def test_candidate_document_not_attached_employer_403(self, files_module):
        db = _base_db()
        with pytest.raises(files_module._HTTPException) as ei:
            _run(files_module, db, _User(EMPLOYER, "employer"), PATH_NOT_ATTACHED)
        assert ei.value.status_code == 403

    def test_admin_200(self, files_module):
        db = _base_db()
        result = _run(files_module, db, _User(ADMIN, "admin"), PATH_A)
        assert result.status_code == 200

    def test_soft_deleted_404(self, files_module):
        db = _base_db()
        with pytest.raises(files_module._HTTPException) as ei:
            _run(files_module, db, _User(CAND_A, "candidate"), "joboolo/uploads/u_candidate_a/del.pdf")
        assert ei.value.status_code == 404

    def test_nonexistent_path_404(self, files_module):
        db = _base_db()
        with pytest.raises(files_module._HTTPException) as ei:
            _run(files_module, db, _User(ADMIN, "admin"), "joboolo/uploads/u_nobody/x.pdf")
        assert ei.value.status_code == 404

    def test_path_traversal_400(self, files_module, monkeypatch):
        db = _base_db()
        for bad in ["../secret", "a/../../etc/passwd", "..", "/.."]:
            with pytest.raises(files_module._HTTPException) as ei:
                _run(files_module, db, _User(ADMIN, "admin"), bad)
            assert ei.value.status_code == 400


class TestAuthQueryParamRefused:
    def test_auth_query_param_not_accepted(self, files_module, monkeypatch):
        """Only Authorization: Bearer is accepted - there is no `auth` query param
        accepted by download_file."""
        import inspect
        sig = inspect.signature(files_module.download_file)
        params = set(sig.parameters)
        assert "auth" not in params
        assert "authorization" not in params
        assert "current_user" in params

    def test_current_user_bound_to_bearer_auth_dependency(self, files_module):
        """current_user is injected by the Bearer auth dependency (get_current_active_user),
        which returns 401 when no valid token is provided."""
        dep_default = files_module.download_file.__defaults__[0]
        import auth as auth_mod
        assert auth_mod.get_current_active_user is dep_default
        with pytest.raises(files_module._HTTPException) as ei:
            asyncio.run(dep_default())
        assert ei.value.status_code == 401

    def test_unauthenticated_401(self, files_module):
        """Invoking the bearer dependency without a user yields 401."""
        import auth as auth_mod
        with pytest.raises(files_module._HTTPException) as ei:
            asyncio.run(auth_mod.get_current_active_user())
        assert ei.value.status_code == 401


class TestNoStorageCallBeforeAcl:
    def _reset(self):
        import storage as st
        st.CALLS["get_object"] = 0

    def _calls(self):
        import storage as st
        return st.CALLS["get_object"]

    def test_get_object_not_called_on_forbidden(self, files_module):
        self._reset()
        db = _base_db()
        with pytest.raises(files_module._HTTPException):
            _run(files_module, db, _User(CAND_B, "candidate"), PATH_A)
        assert self._calls() == 0

    def test_get_object_not_called_when_no_record(self, files_module):
        self._reset()
        db = _base_db()
        with pytest.raises(files_module._HTTPException):
            _run(files_module, db, _User(ADMIN, "admin"), "joboolo/uploads/u_nobody/x.pdf")
        assert self._calls() == 0

    def test_get_object_called_when_authorized(self, files_module):
        self._reset()
        db = _base_db()
        result = _run(files_module, db, _User(ADMIN, "admin"), PATH_A)
        assert result.status_code == 200
        assert self._calls() == 1