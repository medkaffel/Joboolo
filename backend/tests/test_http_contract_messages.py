"""STAB-005C: real HTTP messaging contracts, local collections and auth doubles."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from http_contract_helpers import AUTH, assert_error, setup_contract, user_doc
from test_security_messages import Collection as SecurityCollection, matches
from routes import messages


class Collection(SecurityCollection):
    def __init__(self, docs=()):
        super().__init__(list(docs))
        self.events = []

    def find(self, query):
        self.events.append(('find', deepcopy(query)))
        docs = deepcopy([d for d in self.docs if matches(d, query)])
        class Cursor:
            def sort(self, fields):
                for key, direction in reversed(fields):
                    docs.sort(key=lambda d: d[key], reverse=direction < 0)
                return self
            async def to_list(self, length):
                return docs[:length]
        return Cursor()

    async def update_many(self, query, update):
        self.events.append(('update_many', deepcopy(query), deepcopy(update)))
        await super().update_many(query, update)


@pytest.fixture
def setup(monkeypatch):
    _, db = setup_contract(monkeypatch, 'auth')
    db.users = Collection([user_doc(), dict(_id='e1', user_type='employer', is_active=True,
                                           first_name='Example', last_name='Recruiter')])
    db.jobs = Collection([{'_id':'j1','employer_id':'e1','is_active':False}])
    db.applications = Collection([{'candidate_id':'u1','job_id':'j1'}])
    db.messages = Collection()
    monkeypatch.setattr(messages, 'get_database', AsyncMock(return_value=db))
    app = FastAPI(redirect_slashes=False)
    app.include_router(messages.router, prefix='/api')
    return TestClient(app), db


def message(mid, sender='e1', recipient='u1', read=False, second=0):
    return dict(_id=mid, sender_id=sender, recipient_id=recipient, text=mid, read=read,
                created_at=datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=second))


def assert_no_writes(db):
    assert all(not c.writes for c in vars(db).values())


@pytest.mark.parametrize('text,expected', [('  Hello \n','Hello'),(' '+ 'x'*4001+' ', 'x'*4000)])
@pytest.mark.parametrize('job_id', [None,'j1'])
def test_send_trim_limit_shape_and_single_write(setup, text, expected, job_id):
    client, db = setup
    r = client.post('/api/messages',headers=AUTH,json={'recipient_id':'e1','text':text,'job_id':job_id})
    assert r.status_code == 200 and r.headers['content-type'] == 'application/json'
    data = r.json()
    assert set(data) == {'id','text','from_me','job_id','created_at'}
    assert data['text'] == expected and data['from_me'] is True and data['job_id'] == job_id
    assert db.messages.writes == 1 and len(db.messages.docs) == 1
    doc = db.messages.docs[0]
    assert set(doc) == {'_id','sender_id','recipient_id','text','job_id','read','created_at'}
    assert doc['_id'] == data['id'] and doc['created_at'].isoformat() == data['created_at']
    assert doc['text'] == expected and doc['read'] is False
    assert (doc['sender_id'],doc['recipient_id'],doc['job_id']) == ('u1','e1',job_id)


def test_empty_message_precedes_relationship_error(setup):
    client, db = setup
    assert_error(client.post('/api/messages',headers=AUTH,json={'recipient_id':'missing','text':' \n '}),400,'Message vide')
    assert_no_writes(db)


@pytest.mark.parametrize('change', ['application_removed','job_removed','transferred','inactive','role_changed','unrelated_job'])
def test_send_relationship_and_job_constraint(setup, change):
    client, db = setup
    db.messages.docs.append(message('old'))
    job_id = 'j1'
    if change == 'application_removed': db.applications.docs.clear()
    elif change == 'job_removed': db.jobs.docs.clear()
    elif change == 'transferred': db.jobs.docs[0]['employer_id'] = 'other'
    elif change == 'inactive': db.users.docs[1]['is_active'] = False
    elif change == 'role_changed': db.users.docs[1]['user_type'] = 'candidate'
    else:
        job_id = 'unrelated'
        db.jobs.docs.append({'_id':job_id,'employer_id':'e1'})
    assert_error(client.post('/api/messages',headers=AUTH,json={'recipient_id':'e1','text':'Hello','job_id':job_id}),403,'Vous ne pouvez pas contacter cet utilisateur')
    assert_no_writes(db)


def test_contact_boolean_and_unread_only_current_senders(setup):
    client, db = setup
    db.users.docs.append({'_id':'stranger','user_type':'employer','is_active':True,'email':'hidden@example.com'})
    db.messages.docs = [message('allowed'),message('read',read=True),message('denied',sender='stranger'),message('out',sender='u1',recipient='e1')]
    for other, allowed in [('e1',True),('stranger',False),('missing',False),('u1',False)]:
        r = client.get('/api/messages/can-contact/'+other,headers=AUTH)
        assert r.status_code == 200 and r.json() == {'allowed':allowed}
    r = client.get('/api/messages/unread-count',headers=AUTH)
    assert r.status_code == 200 and r.json() == {'count':1}
    db.applications.docs.clear()
    assert client.get('/api/messages/unread-count',headers=AUTH).json() == {'count':0}
    assert_no_writes(db)


def test_conversations_shape_order_unread_and_revoked_filter(setup):
    client, db = setup
    db.users.docs.append({'_id':'e2','user_type':'employer','is_active':True})
    db.jobs.docs.append({'_id':'j2','employer_id':'e2'})
    db.applications.docs.append({'candidate_id':'u1','job_id':'j2'})
    db.messages.docs = [message('older'),message('latest',sender='u1',recipient='e1',second=3),
                        message('second',sender='e2',second=2),message('forbidden',sender='stranger',second=4)]
    r = client.get('/api/messages/conversations',headers=AUTH)
    assert r.status_code == 200
    assert r.json() == [dict(other_id='e1', name='Example Recruiter',user_type='employer',last_message='latest',last_from_me=True,unread=1,last_at=message('',second=3)['created_at'].isoformat()),
                        dict(other_id='e2',name='Utilisateur',user_type='employer',last_message='second',last_from_me=False,unread=1,last_at=message('',second=2)['created_at'].isoformat())]
    db.applications.docs = [db.applications.docs[1]]
    assert [c['other_id'] for c in client.get('/api/messages/conversations',headers=AUTH).json()] == ['e2']
    assert_no_writes(db)


def test_conversations_current_window_limits_unread(setup):
    client, db = setup
    db.messages.docs = [message(str(i),second=i) for i in range(2001)]
    r = client.get('/api/messages/conversations',headers=AUTH)
    assert r.status_code == 200 and len(r.json()) == 1
    assert r.json()[0]['unread'] == 2000 and r.json()[0]['last_message'] == '2000'
    assert client.get('/api/messages/unread-count',headers=AUTH).json() == {'count':2001}
    assert_no_writes(db)


def test_thread_marks_all_incoming_before_reading_returned_batch(setup):
    client, db = setup
    db.messages.docs = [message(str(i),second=i) for i in reversed(range(2001))]
    db.messages.docs += [message('outgoing',sender='u1',recipient='e1',second=-1),message('other',sender='e2')]
    r = client.get('/api/messages/thread/e1',headers=AUTH)
    assert r.status_code == 200 and set(r.json()) == {'other','messages'}
    assert r.json()['other'] == {'id':'e1','name':'Example Recruiter','user_type':'employer'}
    batch = r.json()['messages']
    assert len(batch) == 2000 and [m['id'] for m in batch] == ['outgoing']+[str(i) for i in range(1999)]
    assert batch[0] == {'id':'outgoing','text':'outgoing','from_me':True,'created_at':message('',second=-1)['created_at'].isoformat()}
    assert batch[1] == {'id':'0','text':'0','from_me':False,'created_at':message('')['created_at'].isoformat()}
    assert all(d['read'] for d in db.messages.docs if d['sender_id']=='e1')
    assert all(not d['read'] for d in db.messages.docs if d['sender_id']!='e1')
    assert db.messages.writes == 1
    assert db.messages.events[0] == ('update_many',{'sender_id':'e1','recipient_id':'u1','read':False},{'$set':{'read':True}})
    assert db.messages.events[1][0] == 'find'
    assert client.get('/api/messages/unread-count',headers=AUTH).json() == {'count':0}


@pytest.mark.parametrize('other', ['missing','stranger'])
def test_thread_denied_without_identity_or_write(setup, other):
    client, db = setup
    db.users.docs.append({'_id':'stranger','user_type':'employer','is_active':True})
    assert_error(client.get('/api/messages/thread/'+other,headers=AUTH),403,'Conversation non autorisée')
    assert_no_writes(db)


@pytest.mark.parametrize('method,path', [('POST','/api/messages'),('GET','/api/messages/unread-count'),('GET','/api/messages/can-contact/e1'),('GET','/api/messages/conversations'),('GET','/api/messages/thread/e1')])
@pytest.mark.parametrize('headers,status,detail,bearer', [({},403,'Not authenticated',False),({'Authorization':'Bearer invalid'},401,'Could not validate credentials',True)])
def test_auth_errors_no_write(setup, method, path, headers, status, detail, bearer):
    client, db = setup
    assert_error(client.request(method,path,headers=headers,json={'recipient_id':'e1','text':'Hi'}),status,detail,bearer)
    assert_no_writes(db)


def test_no_slash_redirect(setup):
    client, db = setup
    r = client.get('/api/messages/conversations/',headers=AUTH,follow_redirects=False)
    assert_error(r,404,'Not Found')
    assert 'location' not in r.headers
    assert_no_writes(db)
