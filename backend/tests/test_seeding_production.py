"""Tests P0-002 — aucun seed de démonstration ni admin par défaut en production.

Tests isolés (aucune base réelle ni dépendances externes requises) :
- config.ensure_seeding_allowed() + seed_data.seed_database() : le seed refuse de
  tourner quand APP_ENV=production, avant toute écriture DB ;
- scripts/seed_dev.py : refuse la production et ne seede qu'en dev/test ;
- scripts/create_admin.py : exige ADMIN_INITIAL_PASSWORD (aucun défaut), hash
  avant stockage, ne réécrit jamais un admin existant, ne loggue aucun secret.
"""

import importlib.util
import os
import sys
import types
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import config  # noqa: E402

SCRIPT_DIR = BACKEND_DIR / "scripts"


def _load_script(name):
    path = SCRIPT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _reset_config(monkeypatch):
    """Vide le cache de config pour que chaque test relise APP_ENV."""
    config.reset_settings()
    yield
    config.reset_settings()


class TestEnsureSeedingAllowed:
    def test_allowed_in_development(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "development")
        config.ensure_seeding_allowed()  # ne doit pas lever

    def test_allowed_in_test(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "test")
        config.ensure_seeding_allowed()  # ne doit pas lever

    def test_is_production_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "Production")
        assert config.get_settings().is_production is True

    def test_refused_in_production(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "production")
        with pytest.raises(config.ConfigurationError):
            config.ensure_seeding_allowed()


class TestSeedDataUsesGuard:
    def test_seed_database_refuses_before_any_db_write(self, monkeypatch):
        """En production, seed_database() lève SANS jamais toucher à la DB."""
        monkeypatch.setenv("APP_ENV", "production")
        seed = _load_seed_data(monkeypatch)
        import asyncio
        with pytest.raises(config.ConfigurationError):
            asyncio.run(seed.seed_database())

    def test_seed_database_calls_guard_first(self, monkeypatch):
        """seed_database() invoque la garde en tête, avant toute écriture."""
        called = {"v": 0}

        def _fake_guard():
            called["v"] += 1

        monkeypatch.setattr(config, "ensure_seeding_allowed", _fake_guard)
        seed = _load_seed_data(monkeypatch, neutralize_db=True)
        import asyncio
        asyncio.run(seed.seed_database())
        assert called["v"] >= 1


def _load_seed_data(monkeypatch, neutralize_db=False):
    """Charge seed_data avec des modules stubs pour éviter les dépendances lourdes."""
    class _FakeUsers:
        async def find_one(self, *a, **k):
            return None

    class _FakeDB:
        users = _FakeUsers()

    async def _get_database():
        return _FakeDB()

    def _get_password_hash(p):
        return f"HASH({p})"

    models_mod = types.ModuleType("models")
    models_mod.Job = type("Job", (), {})
    models_mod.Company = type("Company", (), {})
    models_mod.User = type("User", (), {})
    models_mod.UserType = type("UserType", (), {"EMPLOYER": "employer", "CANDIDATE": "candidate", "ADMIN": "admin"})
    models_mod.JobType = type("JobType", (), {"CDI": "CDI", "TITULAIRE": "TITULAIRE"})

    db_mod = types.ModuleType("database")
    db_mod.get_database = _get_database
    auth_mod = types.ModuleType("auth")
    auth_mod.get_password_hash = _get_password_hash

    monkeypatch.setitem(sys.modules, "models", models_mod)
    monkeypatch.setitem(sys.modules, "database", db_mod)
    monkeypatch.setitem(sys.modules, "auth", auth_mod)
    monkeypatch.setitem(sys.modules, "config", config)

    spec = importlib.util.spec_from_file_location("seed_data_test", BACKEND_DIR / "seed_data.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)

    if neutralize_db:
        async def _noop(*a, **k):
            return None

        seed.seed_companies = _noop
        seed.seed_users = _noop
        seed.seed_jobs = _noop

    return seed


class TestSeedDevScript:
    def test_refuses_production(self, monkeypatch):
        dev = _load_script("seed_dev")
        monkeypatch.setenv("APP_ENV", "production")
        assert dev.main() == 2

    def test_runs_in_development(self, monkeypatch):
        dev = _load_script("seed_dev")
        monkeypatch.setenv("APP_ENV", "development")

        async def _fake_seed():
            return "done"

        seed_stub = types.ModuleType("seed_data_stub")
        seed_stub.seed_database = _fake_seed
        monkeypatch.setitem(sys.modules, "seed_data", seed_stub)
        assert dev.main() == 0


class TestCreateAdminScript:
    def test_password_required_no_default(self, monkeypatch):
        admin = _load_script("create_admin")
        monkeypatch.delenv("ADMIN_INITIAL_PASSWORD", raising=False)
        monkeypatch.setenv("APP_ENV", "development")
        code = admin.main(["--email", "admin@exemple.fr"])
        assert code == 2

    def test_email_required(self, monkeypatch):
        admin = _load_script("create_admin")
        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "s3cret")
        code = admin.main([])
        assert code == 2

    def test_password_never_default_and_env_wins(self, monkeypatch):
        admin = _load_script("create_admin")
        assert admin._ADMIN_PASSWORD_ENV == "ADMIN_INITIAL_PASSWORD"
        monkeypatch.setenv("ADMIN_INITIAL_PASSWORD", "a-forte-password")
        password = os.environ.get(admin._ADMIN_PASSWORD_ENV)
        assert password == "a-forte-password"
        assert password not in ("AdminJoboolo2026!", "password123")

    def test_hashes_password_before_storage(self, monkeypatch):
        admin = _load_script("create_admin")
        stored_hashes = []

        class _FakeUsers:
            async def find_one(self, query):
                return None

            async def insert_one(self, doc):
                stored_hashes.append(doc["hashed_password"])
                self.inserted = doc

        users_obj = _FakeUsers()

        class _FakeDB:
            users = users_obj

        async def _get_database():
            return _FakeDB()

        def _get_password_hash(p):
            return f"HASH({p})"

        db_mod = types.ModuleType("database")
        db_mod.get_database = _get_database
        auth_mod = types.ModuleType("auth")
        auth_mod.get_password_hash = _get_password_hash
        monkeypatch.setitem(sys.modules, "database", db_mod)
        monkeypatch.setitem(sys.modules, "auth", auth_mod)

        # P0-009: transitionnal lookup finds nothing → email is free.
        import email_utils as _eu
        async def _lookup_none(email):
            return None

        monkeypatch.setattr(_eu, "lookup_user_by_email", _lookup_none)

        import asyncio
        result = asyncio.run(admin._ensure_admin("admin@exemple.fr", "a-forte-password"))
        assert result == "created"
        assert stored_hashes == ["HASH(a-forte-password)"]
        assert "a-forte-password" not in stored_hashes
        assert users_obj.inserted["user_type"] == "admin"
        assert users_obj.inserted["email"] == "admin@exemple.fr"

    def test_idempotent_when_admin_exists(self, monkeypatch):
        admin = _load_script("create_admin")
        insert_called = {"v": False}

        class Existing:
            pass

        class _FakeUsers:
            async def find_one(self, query):
                return Existing()

            async def insert_one(self, doc):
                insert_called["v"] = True

        class _FakeDB:
            users = _FakeUsers()

        async def _get_database():
            return _FakeDB()

        def _get_password_hash(p):
            return f"HASH({p})"

        db_mod = types.ModuleType("database")
        db_mod.get_database = _get_database
        auth_mod = types.ModuleType("auth")
        auth_mod.get_password_hash = _get_password_hash
        monkeypatch.setitem(sys.modules, "database", db_mod)
        monkeypatch.setitem(sys.modules, "auth", auth_mod)

        # P0-009: transitionnal lookup finds an existing account → idempotent.
        import email_utils as _eu
        async def _lookup_exists(email):
            return Existing()

        monkeypatch.setattr(_eu, "lookup_user_by_email", _lookup_exists)

        import asyncio
        result = asyncio.run(admin._ensure_admin("admin@exemple.fr", "whatever"))
        assert result == "exists"
        assert insert_called["v"] is False