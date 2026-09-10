"""STAB-005A G0: ordinary auth HTTP contracts; no OAuth or professional-profile writes."""
import pytest
from unittest.mock import AsyncMock
from http_contract_helpers import AUTH, assert_error, setup_contract, user_doc
from routes import auth
from email_utils import LookupCollisionError


@pytest.fixture
def setup(monkeypatch):
    return setup_contract(monkeypatch, 'auth')


PAYLOAD = dict(email='person@example.com', first_name='Test', last_name='User', password='synthetic-password')
USER_KEYS = {'id','email','first_name','last_name','user_type','phone','location','bio','skills',
             'experience_years','is_active','is_verified','created_at','profile_photo_url',
             'social_link_1','social_link_2','social_link_3'}


def assert_user(data):
    assert set(data) == USER_KEYS
    assert data['email'] == 'person@example.com'
    assert data['phone'] is None and data['bio'] is None
    assert data['profile_photo_url'] is None and data['skills'] == []
    assert 'hashed_password' not in data


def test_register_success_shape_and_duplicate_no_write(setup):
    client, db = setup
    r = client.post('/auth/register', json=PAYLOAD)
    assert r.status_code == 200 and r.headers['content-type'] == 'application/json'
    assert set(r.json()) == {'user','token'}
    assert r.json()['token'] == {'access_token':'synthetic-token','token_type':'bearer'}
    assert_user(r.json()['user'])
    assert r.json()['user']['user_type'] == 'candidate'
    stored = next(iter(db.users.docs.values()))
    assert stored['hashed_password'] == 'test-hash' and 'password' not in stored
    assert stored['is_active'] is True and stored['is_verified'] is False
    assert_error(client.post('/auth/register', json=PAYLOAD),400,'Email already registered')
    assert len(db.users.writes) == 1


def test_register_validation_no_write(setup):
    client, db = setup
    r = client.post('/auth/register', json={**PAYLOAD,'email':'invalid'})
    assert r.status_code == 422
    assert r.json()['detail'][0]['loc'] == ['body','email']
    assert db.users.writes == []


def test_login_success_and_invalid_credentials(setup):
    client, db = setup
    db.users.docs['u1'] = user_doc()
    r = client.post('/auth/login',json={'email':PAYLOAD['email'],'password':PAYLOAD['password']})
    assert r.status_code == 200
    assert_user(r.json()['user'])
    assert r.json()['token'] == {'access_token':'synthetic-token','token_type':'bearer'}
    for email, password in [('absent@example.com','synthetic-password'),(PAYLOAD['email'],'wrong')]:
        assert_error(client.post('/auth/login',json={'email':email,'password':password}),401,'Incorrect email or password',True)
    assert db.users.writes == []


@pytest.mark.parametrize('method', ['GET','PUT'])
@pytest.mark.parametrize('header,status,detail,bearer', [({},403,'Not authenticated',False),({'Authorization':'Bearer invalid'},401,'Could not validate credentials',True)])
def test_me_auth_errors_no_write(setup,method,header,status,detail,bearer):
    client, db = setup
    assert_error(client.request(method,'/auth/me',headers=header,json={}),status,detail,bearer)
    assert db.users.writes == []


def test_me_get_and_identity_update_null_is_ignored(setup):
    client, db = setup
    db.users.docs['u1'] = user_doc()
    r = client.get('/auth/me',headers=AUTH)
    assert r.status_code == 200
    assert_user(r.json())
    assert 'etag' not in r.headers
    r = client.put('/auth/me',headers=AUTH,json={'first_name':'Changed','phone':None,'user_type':'admin'})
    assert r.status_code == 200 and set(r.json()) == USER_KEYS
    assert r.json()['first_name'] == 'Changed' and r.json()['user_type'] == 'candidate'
    assert set(db.users.writes[-1][2]['$set']) == {'first_name','updated_at'}
    count = len(db.users.writes)
    assert client.put('/auth/me',headers=AUTH,json={'phone':None}).status_code == 200
    assert len(db.users.writes) == count


def test_inactive_login_and_me_have_different_status(setup):
    client, db = setup
    doc = user_doc(); doc['is_active'] = False; db.users.docs['u1'] = doc
    assert_error(client.post('/auth/login',json={'email':PAYLOAD['email'],'password':PAYLOAD['password']}),403,'Votre compte est en attente de validation par notre équipe.')
    assert_error(client.get('/auth/me',headers=AUTH),400,'Inactive user')
    assert db.users.writes == []


def test_register_lookup_collision_no_write(setup,monkeypatch):
    client, db = setup
    monkeypatch.setattr(auth,'lookup_user_doc_by_email',AsyncMock(side_effect=LookupCollisionError()))
    assert_error(client.post('/auth/register',json=PAYLOAD),503,'Email lookup temporarily unavailable, please retry')
    assert db.users.writes == []
