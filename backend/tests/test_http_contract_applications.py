"""G0 applications HTTP contracts, fake transaction and notification boundary."""
import sys
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from http_contract_helpers import AUTH, Collection, assert_error, setup_contract, user_doc
from routes import applications


class ApplicationCollection(Collection):
    async def find_one(self, query, session=None):
        return await super().find_one(query)

    async def insert_one(self, doc, session=None):
        await super().insert_one(doc)

    async def update_one(self, query, update, session=None):
        doc = await self.find_one(query)
        if doc:
            self.writes.append(('update', deepcopy(query), deepcopy(update)))
            self.docs[doc['_id']].update(update.get('$set', {}))
            for key, amount in update.get('$inc', {}).items():
                self.docs[doc['_id']][key] = doc.get(key, 0) + amount
        return SimpleNamespace(matched_count=int(doc is not None))


class Transaction:
    """Single callback, snapshot rollback; no claim to emulate Mongo concurrency."""
    def __init__(self, collections):
        self.collections = collections
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def with_transaction(self, callback):
        self.calls += 1
        snapshots = [(c, deepcopy(c.docs), deepcopy(c.writes)) for c in self.collections]
        try:
            return await callback(self)
        except Exception:
            for c, docs, writes in snapshots:
                c.docs, c.writes = docs, writes
            raise


@pytest.fixture
def setup(monkeypatch):
    _, db = setup_contract(monkeypatch, 'auth')
    for name in ('jobs','companies','campaigns','applications','files','candidate_documents'):
        setattr(db, name, ApplicationCollection())
    db.users.docs['u1'] = user_doc()
    db.jobs.docs['j1'] = dict(_id='j1', title='Engineer', company_id='c1', employer_id='u1',
                            location='Paris', job_type='CDI', is_active=True, applications_count=0)
    db.companies.docs['c1'] = {'_id':'c1','name':'Example','location':'Paris'}
    tx = Transaction([db.jobs, db.applications])
    monkeypatch.setattr(applications, 'get_database', AsyncMock(return_value=db))
    monkeypatch.setattr(applications, 'get_client', lambda: SimpleNamespace(start_session=AsyncMock(return_value=tx)))
    mail = SimpleNamespace(send_alert_email=AsyncMock(),
                           build_application_confirmation_email=Mock(return_value=('subject','html')),
                           build_new_application_email=Mock(return_value=('subject','html')),
                           build_status_email=Mock(return_value=('subject','html')))
    monkeypatch.setitem(sys.modules, 'email_service', mail)
    monkeypatch.setitem(sys.modules, 'scheduler', SimpleNamespace(APP_URL='https://example.invalid'))
    app = FastAPI(redirect_slashes=False)
    app.include_router(applications.router, prefix='/api')
    return TestClient(app), db, tx, mail


KEYS = set('id job candidate cover_letter cv_url status employer_notes created_at reviewed_at'.split())


def seed_application(db, aid='a1', **changes):
    doc = dict(_id=aid, job_id='j1', candidate_id='u1', status='pending', created_at=datetime(2020,1,1))
    doc.update(changes)
    db.applications.docs[aid] = doc
    return doc


def assert_shape(data, candidate=False):
    assert set(data) == KEYS
    assert data['job'] == {'id':'j1','title':'Engineer','employer_id':'u1',
                           'company':{'name':'Example','location':'Paris'},'location':'Paris','job_type':'CDI'}
    if candidate:
        assert data['candidate'] == {'id':'u1','first_name':'Test','last_name':'User',
                                     'email':'person@example.com','location':'','bio':'','skills':[], 'experience_years':0}
    else:
        assert data['candidate'] == {}
    assert data['cv_url'] is None and data['reviewed_at'] is None


def assert_no_writes(db, mail):
    assert all(not c.writes for c in vars(db).values())
    mail.send_alert_email.assert_not_awaited()


def test_apply_success_and_retry_hidden_job(setup):
    client, db, tx, mail = setup
    r = client.post('/api/applications',headers=AUTH,json={'job_id':'j1','cover_letter':'Hello'})
    assert r.status_code == 200 and r.headers['content-type'] == 'application/json'
    data = r.json()
    assert_shape(data)
    assert data['status'] == 'pending' and data['cover_letter'] == 'Hello' and data['employer_notes'] is None
    stored = db.applications.docs[data['id']]
    assert stored['candidate_id'] == 'u1' and stored['job_id'] == 'j1'
    assert stored['created_at'] == stored['updated_at']
    assert db.jobs.docs['j1']['applications_count'] == 1 and tx.calls == 1
    assert len(db.applications.writes) == len(db.jobs.writes) == 1
    assert mail.send_alert_email.await_count == 2
    # Retry fast path precedes visibility and ignores the replacement payload.
    db.jobs.docs['j1']['is_active'] = False
    again = client.post('/api/applications',headers=AUTH,json={'job_id':'j1','cover_letter':'Changed'})
    assert again.status_code == 200 and again.json() == data
    assert tx.calls == 1 and len(db.applications.writes) == len(db.jobs.writes) == 1
    assert mail.send_alert_email.await_count == 2


@pytest.mark.parametrize('state', ['missing','inactive','expired','campaign'])
def test_apply_unavailable_job_no_write(setup, state):
    client, db, tx, mail = setup
    if state == 'missing':
        db.jobs.docs.clear()
    else:
        db.jobs.docs['j1'].update({'inactive':{'is_active':False},'expired':{'expires_at':datetime(2000,1,1)},'campaign':{'campaign_id':'missing'}}[state])
    assert_error(client.post('/api/applications',headers=AUTH,json={'job_id':'j1'}),404,'Job not found or no longer active')
    assert tx.calls == 0
    assert_no_writes(db,mail)


def test_apply_unowned_cv_no_write(setup):
    client, db, tx, mail = setup
    assert_error(client.post('/api/applications',headers=AUTH,json={'job_id':'j1','cv_url':'foreign/cv.pdf'}),403,'CV indisponible ou non autorisé')
    assert tx.calls == 1
    assert_no_writes(db,mail)


def test_apply_transaction_unavailable(setup, monkeypatch):
    client, db, tx, mail = setup
    monkeypatch.setattr(applications, 'get_client', lambda: None)
    assert_error(client.post('/api/applications',headers=AUTH,json={'job_id':'j1'}),503,'Les transactions MongoDB ne sont pas disponibles. Candidature momentanément indisponible.')
    assert_no_writes(db,mail)


def test_candidate_list_order_shape_and_private_notes(setup):
    client, db, tx, mail = setup
    assert client.get('/api/applications',headers=AUTH).json() == []
    seed_application(db, employer_notes='Internal note')
    seed_application(db,'new',created_at=datetime(2021,1,1))
    seed_application(db,'foreign',candidate_id='u2')
    r = client.get('/api/applications',headers=AUTH)
    assert r.status_code == 200 and [a['id'] for a in r.json()] == ['new','a1']
    assert_shape(r.json()[0])
    assert r.json()[1]['employer_notes'] == 'Internal note'  # Current exposure, not corrected here.
    assert_no_writes(db,mail)


@pytest.mark.parametrize('role', ['employer','admin'])
@pytest.mark.parametrize('method,detail', [('POST','Only candidates can apply to jobs'),('GET','Only candidates can view their applications')])
def test_candidate_only_role_errors(setup, role, method, detail):
    client, db, tx, mail = setup
    db.users.docs['u1']['user_type'] = role
    assert_error(client.request(method,'/api/applications',headers=AUTH,json={'job_id':'j1'}),403,detail)
    assert_no_writes(db,mail)


@pytest.mark.parametrize('role', ['employer','admin'])
def test_employer_list_candidate_info(setup, role):
    client, db, tx, mail = setup
    db.users.docs['u1']['user_type'] = role
    seed_application(db)
    seed_application(db,'new',created_at=datetime(2021,1,1))
    seed_application(db,'foreign',job_id='j2')
    r = client.get('/api/applications/job/j1',headers=AUTH)
    assert r.status_code == 200 and [a['id'] for a in r.json()] == ['new','a1']
    assert_shape(r.json()[0],candidate=True)
    assert_no_writes(db,mail)


@pytest.mark.parametrize('missing', [True,False])
def test_employer_list_missing_or_foreign(setup, missing):
    client, db, tx, mail = setup
    db.users.docs['u1']['user_type'] = 'employer'
    if missing:
        db.jobs.docs.clear()
    else:
        db.jobs.docs['j1']['employer_id'] = 'u2'
    assert_error(client.get('/api/applications/job/j1',headers=AUTH),404,"Job not found or you don't have permission to view its applications")
    assert_no_writes(db,mail)


@pytest.mark.parametrize('status', ['pending','reviewed','accepted','rejected'])
def test_status_success_and_empty_notes_ignored(setup, status):
    client, db, tx, mail = setup
    db.users.docs['u1']['user_type'] = 'employer'
    seed_application(db, employer_notes='Old')
    r = client.put('/api/applications/a1/status',headers=AUTH,json={'status':status,'employer_notes':'New'})
    assert r.status_code == 200 and r.json() == {'message':'Application status updated successfully'}
    write = db.applications.writes[0]
    assert write[1] == {'_id':'a1'}
    assert set(write[2]['$set']) == {'status','employer_notes','reviewed_at','updated_at'}
    assert write[2]['$set']['status'] == status and write[2]['$set']['employer_notes'] == 'New'
    assert isinstance(write[2]['$set']['reviewed_at'],datetime)
    assert mail.send_alert_email.await_count == int(status != 'pending')
    assert client.put('/api/applications/a1/status',headers=AUTH,json={'status':status,'employer_notes':''}).status_code == 200
    assert 'employer_notes' not in db.applications.writes[-1][2]['$set']
    assert db.applications.docs['a1']['employer_notes'] == 'New'


@pytest.mark.parametrize('case,status,detail', [('invalid',400,'Invalid status'),('missing',404,'Application not found'),('foreign',403,"You don't have permission to update this application")])
def test_status_errors_no_write(setup, case, status, detail):
    client, db, tx, mail = setup
    db.users.docs['u1']['user_type'] = 'employer'
    if case == 'foreign':
        seed_application(db)
        db.jobs.docs['j1']['employer_id'] = 'u2'
    assert_error(client.put('/api/applications/a1/status',headers=AUTH,json={'status':'bad' if case=='invalid' else 'accepted'}),status,detail)
    assert_no_writes(db,mail)


@pytest.mark.parametrize('method,path', [('GET','/api/applications/job/j1'),('PUT','/api/applications/a1/status')])
def test_employer_only_role_errors(setup, method, path):
    client, db, tx, mail = setup
    assert_error(client.request(method,path,headers=AUTH,json={'status':'accepted'}),403,'Not enough permissions')
    assert_no_writes(db,mail)


@pytest.mark.parametrize('method,path', [('GET','/api/applications'),('POST','/api/applications'),('GET','/api/applications/job/j1'),('PUT','/api/applications/a1/status')])
@pytest.mark.parametrize('headers,status,detail,bearer', [({},403,'Not authenticated',False),({'Authorization':'Bearer invalid'},401,'Could not validate credentials',True)])
def test_auth_errors_no_write(setup, method, path, headers, status, detail, bearer):
    client, db, tx, mail = setup
    assert_error(client.request(method,path,headers=headers,json={'job_id':'j1','status':'accepted'}),status,detail,bearer)
    assert_no_writes(db,mail)

@pytest.mark.parametrize('method,path,field', [('POST','/api/applications','job_id'),('PUT','/api/applications/a1/status','status')])
def test_missing_required_body_field_no_write(setup, method, path, field):
    client, db, tx, mail = setup
    if method == 'PUT':
        db.users.docs['u1']['user_type'] = 'employer'
    r = client.request(method,path,headers=AUTH,json={})
    assert r.status_code == 422 and r.json()['detail'][0]['loc'] == ['body',field]
    assert_no_writes(db,mail)


def test_no_slash_redirect(setup):
    client, db, tx, mail = setup
    r = client.get('/api/applications/',headers=AUTH,follow_redirects=False)
    assert_error(r,404,'Not Found')
    assert 'location' not in r.headers
    assert_no_writes(db,mail)
