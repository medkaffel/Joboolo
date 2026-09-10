"""G0 helpers: minimal route mounting, in-memory equality queries, no app startup."""
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import auth as security
import email_utils
from routes import auth, alerts, candidate_profiles


class Collection:
    def __init__(self):
        self.docs = {}
        self.writes = []

    async def insert_one(self, doc):
        self.writes.append(('insert', deepcopy(doc)))
        self.docs[doc['_id']] = deepcopy(doc)

    async def find_one(self, query):
        return next((deepcopy(d) for d in self.docs.values()
                     if all(d.get(k) == v for k, v in query.items())), None)

    def find(self, query):
        docs = [deepcopy(d) for d in self.docs.values()
                if all(d.get(k) == v for k, v in query.items())]
        class Cursor:
            def sort(self, fields):
                for key, direction in reversed(fields):
                    docs.sort(key=lambda d: d[key], reverse=direction < 0)
                return self
            async def to_list(self, length):
                return docs[:length]
        return Cursor()

    async def update_one(self, query, update):
        doc = await self.find_one(query)
        if doc:
            self.writes.append(('update', deepcopy(query), deepcopy(update)))
            self.docs[doc['_id']].update(deepcopy(update['$set']))

    async def delete_one(self, query):
        doc = await self.find_one(query)
        if doc:
            self.writes.append(('delete', deepcopy(query)))
            del self.docs[doc['_id']]
        return SimpleNamespace(deleted_count=int(doc is not None))


def user_doc(**overrides):
    return dict(_id='u1', email='person@example.com', first_name='Test', last_name='User',
                user_type='candidate', hashed_password='test-hash', is_active=True,
                is_verified=False, created_at=datetime(2026, 1, 1), **overrides)


def setup_contract(monkeypatch, domain):
    db = SimpleNamespace(users=Collection(), alerts=Collection())
    async def lookup(email):
        return await db.users.find_one({'email': email_utils.canonical_email(email)})
    for module in (auth, alerts, candidate_profiles):
        monkeypatch.setattr(module, 'get_database', AsyncMock(return_value=db))
    for module in (auth, alerts, email_utils):
        monkeypatch.setattr(module, 'lookup_user_doc_by_email', lookup)
    monkeypatch.setattr(auth, 'get_password_hash', lambda _: 'test-hash')
    monkeypatch.setattr(security, 'verify_password', lambda plain, hashed: plain == 'synthetic-password' and hashed == 'test-hash')
    monkeypatch.setattr(auth, 'create_access_token', lambda **_: 'synthetic-token')
    monkeypatch.setattr(security, 'get_secret_key', lambda: 'synthetic-key')
    def decode(token, *args, **kwargs):
        if token != 'valid':
            raise security.JWTError('invalid test token')
        return {'sub': 'person@example.com'}
    monkeypatch.setattr(security.jwt, 'decode', decode)
    # Fail closed if a future handler accidentally reaches an external transport.
    import httpx
    import requests
    def no_network(*args, **kwargs):
        raise AssertionError('G0 must not use an external socket')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', no_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', no_network)
    monkeypatch.setattr(requests.Session, 'request', no_network)
    app = FastAPI()
    if domain == 'auth':
        # Same active PUT ownership as server.py, without importing server/startup.
        for route in auth.router.routes:
            if route.path in ('/auth/register', '/auth/login', '/auth/me'):
                if not (route.path == '/auth/me' and 'PUT' in route.methods):
                    app.router.routes.append(route)
        app.include_router(candidate_profiles.compat_router)
    else:
        app.include_router(alerts.router)
    return TestClient(app), db


AUTH = {'Authorization': 'Bearer valid'}


def assert_error(response, status, detail, bearer=False):
    assert response.status_code == status
    assert response.json() == {'detail': detail}
    assert response.headers['content-type'] == 'application/json'
    assert response.headers.get('www-authenticate') == ('Bearer' if bearer else None)
