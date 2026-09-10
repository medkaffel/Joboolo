"""STAB-005A G0: subscribe and owned alert CRUD HTTP contracts."""
from datetime import datetime
from unittest.mock import AsyncMock
import pytest
from http_contract_helpers import AUTH, assert_error, setup_contract, user_doc
from routes import alerts
from email_utils import LookupAggregationError


@pytest.fixture
def setup(monkeypatch):
    return setup_contract(monkeypatch, 'alerts')


KEYS = {'id','name','search','location','job_type','is_remote','salary_min','frequency','is_active','last_sent_at','created_at'}


def test_subscribe_creates_lightweight_candidate_without_session(setup):
    client, db = setup
    r = client.post('/api/alerts/subscribe',json={'email':' PERSON@EXAMPLE.COM ','search':'Python','location':'Paris'})
    assert r.status_code == 200 and r.headers['content-type'] == 'application/json'
    assert set(r.json()) == {'success','alert_id','created_account'}
    assert r.json()['success'] is True and r.json()['created_account'] is True
    user = next(iter(db.users.docs.values()))
    assert user['email'] == 'person@example.com' and user['user_type'] == 'candidate'
    assert user['hashed_password'] is None and user['first_name'] is None and user['last_name'] is None
    assert user['is_active'] is True and user['profile_complete'] is False
    assert user['signup_origin'] == 'alert_subscribe'
    alert = db.alerts.docs[r.json()['alert_id']]
    assert alert['user_id'] == user['_id'] and alert['name'] == 'Python · Paris'
    assert alert['frequency'] == 'daily' and alert['last_sent_at'] is None
    assert len(db.users.writes) == len(db.alerts.writes) == 1


def test_subscribe_reuses_inactive_employer_and_allows_repeated_alerts(setup):
    client, db = setup
    doc = user_doc(); doc.update(user_type='employer',is_active=False)
    db.users.docs['u1'] = doc
    for _ in range(2):
        r = client.post('/api/alerts/subscribe',json={'email':doc['email']})
        assert r.status_code == 200 and r.json()['created_account'] is False
    assert db.users.writes == [] and len(db.alerts.writes) == 2
    assert all(d['user_id'] == 'u1' and d['name'] == 'Toutes les offres' for d in db.alerts.docs.values())


def test_subscribe_current_email_validation_is_only_string(setup):
    client, db = setup
    r = client.post('/api/alerts/subscribe',json={'email':'not-an-email'})
    assert r.status_code == 200 and r.json()['created_account'] is True
    assert next(iter(db.users.docs.values()))['email'] == 'not-an-email'


def test_subscribe_lookup_failure_and_missing_field_no_writes(setup,monkeypatch):
    client, db = setup
    r = client.post('/api/alerts/subscribe',json={})
    assert r.status_code == 422 and r.json()['detail'][0]['loc'] == ['body','email']
    monkeypatch.setattr(alerts,'lookup_user_doc_by_email',AsyncMock(side_effect=LookupAggregationError()))
    assert_error(client.post('/api/alerts/subscribe',json={'email':'person@example.com'}),503,'Email lookup temporarily unavailable, please retry')
    assert db.users.writes == db.alerts.writes == []


def test_authenticated_create_list_update_delete_shape(setup):
    client, db = setup
    db.users.docs['u1'] = user_doc()
    assert client.get('/api/alerts',headers=AUTH).json() == []
    r = client.post('/api/alerts',headers=AUTH,json={'search':'Python'})
    assert r.status_code == 200 and set(r.json()) == KEYS
    data = r.json(); aid = data['id']
    assert data['name'] == 'Python' and data['frequency'] == 'daily'
    assert all(data[k] is None for k in ('location','job_type','is_remote','salary_min','last_sent_at'))
    # Private storage fields are omitted, not serialized as null.
    assert 'user_id' not in data and 'updated_at' not in data
    db.alerts.docs['foreign'] = {**db.alerts.docs[aid],'_id':'foreign','user_id':'u2'}
    r = client.get('/api/alerts',headers=AUTH)
    assert r.status_code == 200 and r.json() == [data]
    r = client.put('/api/alerts/'+aid,headers=AUTH,json={'name':None,'frequency':'weekly','is_active':False})
    assert r.status_code == 200 and set(r.json()) == KEYS
    assert r.json()['name'] == 'Python' and r.json()['frequency'] == 'weekly' and r.json()['is_active'] is False
    assert 'name' not in db.alerts.writes[-1][2]['$set']
    r = client.delete('/api/alerts/'+aid,headers=AUTH)
    assert r.status_code == 200 and r.json() == {'message':'Alerte supprimée'}
    assert aid not in db.alerts.docs and 'foreign' in db.alerts.docs


@pytest.mark.parametrize('method', ['PUT','DELETE'])
@pytest.mark.parametrize('target', ['missing','foreign'])
def test_ownership_missing_and_foreign_are_identical(setup,method,target):
    client, db = setup
    db.users.docs['u1'] = user_doc()
    db.alerts.docs['foreign'] = {'_id':'foreign','user_id':'u2','created_at':datetime(2026,1,1)}
    assert_error(client.request(method,'/api/alerts/'+target,headers=AUTH,json={'name':'Changed'}),404,'Alerte introuvable')
    assert db.alerts.writes == [] and db.alerts.docs['foreign']['user_id'] == 'u2'


@pytest.mark.parametrize('method,path', [('GET','/api/alerts'),('POST','/api/alerts'),('PUT','/api/alerts/a1'),('DELETE','/api/alerts/a1')])
@pytest.mark.parametrize('headers,status,detail,bearer', [({},403,'Not authenticated',False),({'Authorization':'Bearer invalid'},401,'Could not validate credentials',True)])
def test_authenticated_routes_auth_errors_no_writes(setup,method,path,headers,status,detail,bearer):
    client, db = setup
    assert_error(client.request(method,path,headers=headers,json={}),status,detail,bearer)
    assert db.alerts.writes == db.users.writes == []


def test_update_invalid_frequency_no_write(setup):
    client, db = setup
    db.users.docs['u1'] = user_doc()
    r = client.put('/api/alerts/a1',headers=AUTH,json={'frequency':'hourly'})
    assert r.status_code == 422 and r.json()['detail'][0]['loc'] == ['body','frequency']
    assert db.alerts.writes == []
