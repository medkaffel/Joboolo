"""Public role boundaries. In-process HTTP, fake DB/identity provider, no secrets."""
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from models import UserUpdate, User
from routes import auth, alerts, admin


@pytest.fixture
def setup(monkeypatch):
    db = SimpleNamespace(
        users=SimpleNamespace(insert_one=AsyncMock(), update_one=AsyncMock()),
        partner_profiles=SimpleNamespace(insert_one=AsyncMock()),
        alerts=SimpleNamespace(insert_one=AsyncMock()),
    )
    for module in (auth, alerts, admin):
        monkeypatch.setattr(module, "get_database", AsyncMock(return_value=db))
        monkeypatch.setattr(module, "lookup_user_doc_by_email", AsyncMock(return_value=None))
    monkeypatch.setattr(auth, "get_password_hash", lambda _: "fake-hash-not-a-secret")
    monkeypatch.setattr(auth, "create_access_token", lambda **_: "fake-test-token")
    # No notification is allowed to escape the test.
    monkeypatch.setitem(sys.modules, "email_service", SimpleNamespace(send_alert_email=AsyncMock()))
    app = FastAPI()
    app.include_router(auth.router)
    app.include_router(alerts.router)
    app.include_router(admin.router)
    return TestClient(app), db


def payload(**overrides):
    return {"email": "person@example.com", "first_name": "Test", "last_name": "User",
            "password": "synthetic-test-password", **overrides}


@pytest.mark.parametrize("role", ["admin", "partner", "ADMIN", "root", "", None])
def test_public_registration_rejects_privileged_or_unknown_role(setup, role):
    client, db = setup
    response = client.post("/auth/register", json=payload(user_type=role))
    assert response.status_code == 422
    db.users.insert_one.assert_not_awaited()


@pytest.mark.parametrize("role", ["candidate", "employer"])
def test_public_allowed_roles_cannot_inject_privileged_fields(setup, role):
    client, db = setup
    response = client.post("/auth/register", json=payload(
        user_type=role, is_admin=True, is_verified=True, role="admin"))
    assert response.status_code == 200
    saved = db.users.insert_one.await_args.args[0]
    assert saved["user_type"] == role and saved["is_verified"] is False
    assert "is_admin" not in saved and "role" not in saved


def test_public_registration_defaults_to_candidate(setup):
    client, db = setup
    assert client.post("/auth/register", json=payload()).status_code == 200
    assert db.users.insert_one.await_args.args[0]["user_type"] == "candidate"


def test_register_guard_also_rejects_validation_bypass(setup):
    _, db = setup
    with pytest.raises(auth.HTTPException) as exc:
        asyncio.run(auth.register(SimpleNamespace(user_type="admin")))
    assert exc.value.status_code == 403
    db.users.insert_one.assert_not_awaited()


def test_partner_registration_cannot_create_admin_or_active_account(setup):
    client, db = setup
    response = client.post("/auth/register-partner", json=payload(
        user_type="admin", is_active=True, company_name="Example"))
    assert response.status_code == 200 and response.json()["pending"] is True
    saved = db.users.insert_one.await_args.args[0]
    assert saved["user_type"] == "partner" and saved["is_active"] is False
    assert "token" not in response.json()


def test_public_alert_subscription_cannot_create_admin(setup):
    client, db = setup
    response = client.post("/alerts/subscribe", json={"email": "person@example.com", "user_type": "admin"})
    assert response.status_code == 200
    assert db.users.insert_one.await_args.args[0]["user_type"] == "candidate"
    assert "token" not in response.json()


def test_profile_input_discards_role_and_activation_changes():
    assert UserUpdate(user_type="admin", is_active=True, is_verified=True).model_dump(exclude_unset=True) == {}


@pytest.mark.parametrize("method,path", [
    ("post", "/admin/partners"), ("put", "/admin/users/fake"),
    ("post", "/admin/users/fake/toggle"), ("post", "/admin/partners/fake/validate"),
    ("put", "/auth/me"),
])
def test_public_caller_cannot_reach_account_management(setup, method, path):
    client, db = setup
    response = client.request(method, path, json=payload(user_type="admin"))
    assert response.status_code in (401, 403)
    db.users.insert_one.assert_not_awaited()
    db.users.update_one.assert_not_awaited()


def test_google_role_is_not_taken_from_client_or_provider(setup, monkeypatch):
    client, db = setup
    provider = AsyncMock()
    provider.__aenter__.return_value = provider
    provider.get.return_value = httpx.Response(200, json={
        "email": "person@example.com", "name": "Test User", "user_type": "admin",
    })
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **_: provider)
    response = client.post("/auth/google/session", json={"session_id": "fake", "user_type": "admin"})
    assert response.status_code == 200
    assert db.users.insert_one.await_args.args[0]["user_type"] == "candidate"
    assert response.json()["user"]["user_type"] == "candidate"


def test_invalid_google_session_cannot_issue_token(setup, monkeypatch):
    client, db = setup
    provider = AsyncMock()
    provider.__aenter__.return_value = provider
    provider.get.return_value = httpx.Response(401)
    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **_: provider)
    response = client.post("/auth/google/session", json={"session_id": "fake"})
    assert response.status_code == 401
    db.users.insert_one.assert_not_awaited()


def test_login_expected_role_does_not_promote_candidate(setup, monkeypatch):
    client, db = setup
    candidate = User(
        _id="fake-candidate", email="person@example.com", first_name="Test", last_name="User",
        user_type="candidate", hashed_password="fake-hash", created_at=datetime.utcnow(),
    )
    monkeypatch.setattr(auth, "authenticate_user", AsyncMock(return_value=candidate))
    response = client.post("/auth/login", json={
        "email": "person@example.com", "password": "fake", "expected_user_type": "admin",
    })
    assert response.status_code == 403
    db.users.update_one.assert_not_awaited()


def test_all_admin_endpoints_require_admin_dependency():
    from auth import require_admin
    for route in admin.router.routes:
        assert any(dependency.call is require_admin for dependency in route.dependant.dependencies), route.path
