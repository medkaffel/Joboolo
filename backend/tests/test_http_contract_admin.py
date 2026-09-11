"""STAB-005C: representative admin mutation contracts; no audit/runtime changes."""
import sys
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from http_contract_helpers import AUTH, Collection as BaseCollection, assert_error, setup_contract, user_doc
from routes import admin


class Collection(BaseCollection):
    def __init__(self):
        super().__init__()
        self.calls = []

    async def update_one(self, query, update, upsert=False):
        self.calls.append(('update',deepcopy(query),deepcopy(update),upsert))
        doc = await self.find_one(query)
        matched = doc is not None
        if doc is None and upsert:
            doc = deepcopy(query)
            self.docs[doc['_id']] = doc
        if doc is not None:
            self.writes.append(('update',deepcopy(query),deepcopy(update)))
            self.docs[doc['_id']].update(deepcopy(update.get('$set',{})))
            for key, value in update.get('$inc',{}).items():
                self.docs[doc['_id']][key] = doc.get(key,0) + value
        return SimpleNamespace(matched_count=int(matched))

    async def delete_many(self, query):
        self.calls.append(('delete_many',deepcopy(query)))
        ids = [key for key,doc in self.docs.items() if all(doc.get(k)==v for k,v in query.items())]
        for key in ids:
            self.writes.append(('delete',{'_id':key}))
            del self.docs[key]
        return SimpleNamespace(deleted_count=len(ids))


@pytest.fixture
def setup(monkeypatch):
    _, db = setup_contract(monkeypatch, 'auth')
    for name in ('users','partner_profiles','settings','xml_feeds','alerts','jobs'):
        setattr(db,name,Collection())
    db.users.docs['u1'] = {**user_doc(),'user_type':'admin'}
    db.users.docs['target'] = {**user_doc(),'_id':'target','email':'target@example.com','user_type':'partner','is_active':False}
    db.partner_profiles.docs['p1'] = {'_id':'p1','user_id':'target','company_name':'Example','balance':10.0,'postings_remaining':2,'is_active':False}
    db.xml_feeds.docs['f1'] = {'_id':'f1','partner_id':'target','source_name':'Example','url':'https://example.invalid/feed.xml','billing_mode':'per_click'}
    db.alerts.docs['a1'] = {'_id':'a1','is_active':True}
    db.jobs.docs['j1'] = {'_id':'j1','is_active':True}
    monkeypatch.setattr(admin,'get_database',AsyncMock(return_value=db))
    monkeypatch.setenv('FRONTEND_URL','https://example.invalid')
    mail = SimpleNamespace(build_partner_welcome_email=Mock(return_value=('subject','html')),send_alert_email=AsyncMock())
    monkeypatch.setitem(sys.modules,'email_service',mail)
    app = FastAPI(redirect_slashes=False)
    app.include_router(admin.router,prefix='/api')
    return TestClient(app),db,mail


def assert_no_writes(db,mail):
    assert all(not c.writes for c in vars(db).values())
    mail.send_alert_email.assert_not_awaited()


USER_KEYS = set('id email first_name last_name user_type phone location is_active signup_source signup_referrer utm_source utm_campaign created_at'.split())
PROFILE_KEYS = set('company_name billing_mode default_cpc posting_price xml_feed_url postings_remaining balance total_clicks total_spent'.split())


def test_user_update_non_null_shape(setup):
    client,db,mail = setup
    r = client.put('/api/admin/users/target',headers=AUTH,json={'first_name':'Changed','phone':None,'is_active':False,'user_type':'admin'})
    assert r.status_code == 200 and r.headers['content-type']=='application/json'
    data = r.json()
    assert set(data)==USER_KEYS and data['id']=='target' and data['first_name']=='Changed'
    assert data['user_type']=='partner' and data['is_active'] is False
    assert data['phone'] is None and data['signup_source'] is None and data['created_at']=='2026-01-01T00:00:00'
    assert len(db.users.writes)==1
    fields = db.users.writes[0][2]['$set']
    assert set(fields)=={'first_name','is_active','updated_at'} and isinstance(fields['updated_at'],datetime)
    assert db.partner_profiles.writes==[]


@pytest.mark.parametrize('payload',[{}, {'phone':None}])
def test_user_update_empty_no_write(setup,payload):
    client,db,mail = setup
    assert_error(client.put('/api/admin/users/target',headers=AUTH,json=payload),400,'Aucune donnée à mettre à jour')
    assert_no_writes(db,mail)


@pytest.mark.parametrize('method,path,payload,detail', [
    ('PUT','/api/admin/users/missing',{'first_name':'Changed'},'Utilisateur introuvable'),
    ('POST','/api/admin/users/missing/toggle',{},'Utilisateur introuvable'),
    ('DELETE','/api/admin/users/missing',{},'Utilisateur introuvable'),
    ('POST','/api/admin/partners/missing/validate',{},'Partenaire introuvable'),
    ('PUT','/api/admin/partners/missing/config',{'add_balance':1},'Partenaire introuvable'),
    ('PUT','/api/admin/xml-feeds/missing',{'url':'https://example.invalid/new'},'Flux introuvable'),
    ('PUT','/api/admin/alerts/missing/toggle',{},'Alerte introuvable'),
    ('POST','/api/admin/jobs/missing/toggle',{},'Offre introuvable')])
def test_missing_mutation_target_no_write(setup,method,path,payload,detail):
    client,db,mail = setup
    assert_error(client.request(method,path,headers=AUTH,json=payload),404,detail)
    assert_no_writes(db,mail)
    assert db.partner_profiles.calls==[]


@pytest.mark.parametrize('method,path,collection,key', [
    ('POST','/api/admin/users/target/toggle','users','target'),
    ('PUT','/api/admin/alerts/a1/toggle','alerts','a1'),
    ('POST','/api/admin/jobs/j1/toggle','jobs','j1')])
def test_toggle_exact_write(setup,method,path,collection,key):
    client,db,mail = setup
    coll = getattr(db,collection)
    before = coll.docs[key]['is_active']
    r = client.request(method,path,headers=AUTH)
    assert r.status_code==200 and r.json()=={'id':key,'is_active':not before}
    assert coll.writes==[('update',{'_id':key},{'$set':{'is_active':not before}})]
    # User toggle currently does not synchronize the partner profile.
    assert db.partner_profiles.writes==[]
    assert sum(len(c.writes) for c in vars(db).values())==1


def test_delete_user_also_deletes_partner_profiles_only(setup):
    client,db,mail = setup
    db.partner_profiles.docs['p2'] = {'_id':'p2','user_id':'target'}
    db.partner_profiles.docs['foreign'] = {'_id':'foreign','user_id':'other'}
    r = client.delete('/api/admin/users/target',headers=AUTH)
    assert r.status_code==200 and r.json()=={'message':'Compte supprimé'}
    assert 'target' not in db.users.docs and set(db.partner_profiles.docs)=={'foreign'}
    assert db.partner_profiles.calls==[('delete_many',{'user_id':'target'})]
    assert len(db.users.writes)==1 and len(db.partner_profiles.writes)==2
    assert all(not getattr(db,name).writes for name in ('settings','xml_feeds','alerts','jobs'))
    mail.send_alert_email.assert_not_awaited()


@pytest.mark.parametrize('email_fails',[False,True])
def test_validate_partner_double_write_and_best_effort_email(setup,email_fails):
    client,db,mail = setup
    if email_fails: mail.send_alert_email.side_effect=RuntimeError('synthetic email failure')
    r = client.post('/api/admin/partners/target/validate',headers=AUTH)
    assert r.status_code==200 and r.json()=={'message':'Partenaire validé et activé','is_active':True}
    fields = db.users.writes[0][2]['$set']
    assert set(fields)=={'is_active','pending_validation','updated_at'}
    assert fields['is_active'] is True and fields['pending_validation'] is False and isinstance(fields['updated_at'],datetime)
    assert db.partner_profiles.writes==[('update',{'user_id':'target'},{'$set':fields})]
    assert len(db.users.writes)==1
    mail.build_partner_welcome_email.assert_called_once_with('Example','https://example.invalid')
    mail.send_alert_email.assert_awaited_once_with('target@example.com','subject','html')


def test_partner_config_set_inc_and_user_sync(setup):
    client,db,mail = setup
    payload = {'company_name':'Changed','billing_mode':'per_posting','default_cpc':0.5,'posting_price':20,
               'xml_feed_url':'https://example.invalid/new.xml','add_pack':3,'add_balance':5,'is_active':True}
    r = client.put('/api/admin/partners/target/config',headers=AUTH,json=payload)
    assert r.status_code==200 and set(r.json())==USER_KEYS|{'profile'}
    assert set(r.json()['profile'])==PROFILE_KEYS
    assert r.json()['is_active'] is True and r.json()['profile']['postings_remaining']==5 and r.json()['profile']['balance']==15
    assert db.users.writes==[('update',{'_id':'target'},{'$set':{'is_active':True}})]
    ops = db.partner_profiles.writes[0][2]
    assert ops['$inc']=={'postings_remaining':3,'balance':5}
    assert set(ops['$set'])=={'company_name','billing_mode','default_cpc','posting_price','xml_feed_url','is_active','updated_at'}
    assert isinstance(ops['$set'].pop('updated_at'),datetime)
    assert ops['$set']=={k:v for k,v in payload.items() if k not in ('add_pack','add_balance')}
    assert len(db.partner_profiles.writes)==1


def test_partner_config_zero_noop_and_negative_increment(setup):
    client,db,mail = setup
    assert client.put('/api/admin/partners/target/config',headers=AUTH,json={'add_pack':0,'add_balance':0,'company_name':None}).status_code==200
    assert_no_writes(db,mail)
    r = client.put('/api/admin/partners/target/config',headers=AUTH,json={'add_pack':-3,'add_balance':-20})
    assert r.status_code==200 and r.json()['profile']['postings_remaining']==-1 and r.json()['profile']['balance']==-10
    assert db.partner_profiles.writes==[('update',{'user_id':'target'},{'$inc':{'postings_remaining':-3,'balance':-20}})]
    assert db.users.writes==[]


def test_settings_empty_then_upsert_defaults_and_overrides(setup):
    client,db,mail = setup
    defaults = {'pack_validity_days':30,'low_balance_threshold':10.0,'feed_refresh_hours':24,'recruiter_premium_price':299.0}
    r = client.put('/api/admin/settings',headers=AUTH,json={})
    assert r.status_code==200 and r.json()==defaults
    assert_no_writes(db,mail)
    r = client.put('/api/admin/settings',headers=AUTH,json={'feed_refresh_hours':6,'low_balance_threshold':None})
    assert r.status_code==200 and r.json()=={**defaults,'feed_refresh_hours':6}
    assert db.settings.calls==[('update',{'_id':'global'},{'$set':{'feed_refresh_hours':6}},True)]
    assert db.settings.docs=={'global':{'_id':'global','feed_refresh_hours':6}}
    assert client.put('/api/admin/settings',headers=AUTH,json={}).json()==r.json()
    assert len(db.settings.writes)==1


def test_xml_update_shape_and_profile_sync_without_import(setup):
    client,db,mail = setup
    payload = {'source_name':'Changed','url':'https://example.invalid/new.xml','billing_mode':'per_posting','cpc':0.4,'pack_price':12}
    r = client.put('/api/admin/xml-feeds/f1',headers=AUTH,json=payload)
    assert r.status_code==200 and r.json()=={**payload,'id':'f1','partner_id':'target','company_name':'Example','last_import_at':None,'last_result':None,'created_at':None}
    assert db.xml_feeds.writes==[('update',{'_id':'f1'},{'$set':payload})]
    sync = db.partner_profiles.writes[0][2]['$set']
    assert set(sync)=={'xml_feed_url','billing_mode','default_cpc','posting_price','updated_at'}
    assert {k:v for k,v in sync.items() if k!='updated_at'}=={'xml_feed_url':payload['url'],'billing_mode':'per_posting','default_cpc':0.4,'posting_price':12}
    assert isinstance(sync['updated_at'],datetime)
    assert client.put('/api/admin/xml-feeds/f1',headers=AUTH,json={'url':None}).json()==r.json()
    assert len(db.xml_feeds.writes)==len(db.partner_profiles.writes)==1
    mail.send_alert_email.assert_not_awaited()


SAMPLE = [('PUT','/api/admin/users/target',{'first_name':'Changed'}),
          ('POST','/api/admin/partners/target/validate',{}),
          ('PUT','/api/admin/settings',{'feed_refresh_hours':6}),
          ('PUT','/api/admin/xml-feeds/f1',{'source_name':'Changed'}),
          ('POST','/api/admin/jobs/j1/toggle',{})]


@pytest.mark.parametrize('method,path,payload',SAMPLE)
@pytest.mark.parametrize('role',['candidate','employer','partner'])
def test_real_require_admin_denies_other_roles(setup,method,path,payload,role):
    client,db,mail = setup
    db.users.docs['u1']['user_type']=role
    assert_error(client.request(method,path,headers=AUTH,json=payload),403,"Réservé à l'administrateur")
    assert_no_writes(db,mail)


@pytest.mark.parametrize('method,path,payload',SAMPLE)
@pytest.mark.parametrize('headers,status,detail,bearer',[({},403,'Not authenticated',False),({'Authorization':'Bearer invalid'},401,'Could not validate credentials',True)])
def test_auth_errors_no_write(setup,method,path,payload,headers,status,detail,bearer):
    client,db,mail = setup
    assert_error(client.request(method,path,headers=headers,json=payload),status,detail,bearer)
    assert_no_writes(db,mail)
