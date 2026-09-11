"""G0 public jobs HTTP contracts; query capture is not a Mongo execution test."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from http_contract_helpers import Collection, assert_error, setup_contract
from routes import jobs
import campaign_lifecycle


NOW = datetime(2026, 9, 1, tzinfo=timezone.utc)
KEYS = set('id title description company location salary_min salary_max salary_currency job_type is_remote is_urgent requirements benefits tags is_active is_premium views_count applications_count created_at is_new is_partner external_url cpc logo_url'.split())


def job_doc(**changes):
    return dict(dict(_id='j1', title='Python', description='Engineer', company_id='c1',
                     employer_id='e1', location='Paris', job_type='CDI', is_active=True,
                     views_count=0, applications_count=0, created_at=datetime(2020, 1, 1)), **changes)


@pytest.fixture
def setup(monkeypatch):
    setup_contract(monkeypatch, 'auth')  # Shared fail-closed HTTP transport guards.
    db = SimpleNamespace(jobs=Collection(), companies=Collection(), campaigns=MagicMock())
    db.companies.docs['c1'] = {'_id':'c1', 'name':'Example', 'location':'Paris'}
    campaigns = [dict(_id='active', status='active'), dict(_id='paused', status='paused'),
                 dict(_id='future', status='active', start_date='2099-01-01'),
                 dict(_id='spent', status='active', billing_mode='per_click', spent=5, budget_limit=5)]
    db.campaigns.find.return_value.to_list = AsyncMock(return_value=campaigns)
    db.campaigns.find_one = AsyncMock(side_effect=lambda q: next((c for c in campaigns if c['_id']==q['_id']), None))
    monkeypatch.setattr(campaign_lifecycle, '_now', lambda now=None: now or NOW)
    monkeypatch.setattr(jobs, 'get_database', AsyncMock(return_value=db))
    monkeypatch.setattr(jobs, 'resolve_location_codes', AsyncMock(return_value=[]))
    monkeypatch.setattr(jobs, 'geocode_place', AsyncMock(return_value=None))
    app = FastAPI(redirect_slashes=False)
    app.include_router(jobs.router, prefix='/api')
    return TestClient(app), db


def list_result(db, docs, total=None):
    # The route must forward the exact visibility predicates to both operations.
    db.jobs.count_documents = AsyncMock(return_value=len(docs) if total is None else total)
    cursor = MagicMock()
    cursor.sort.return_value = cursor
    cursor.skip.return_value = cursor
    cursor.limit.return_value = cursor
    cursor.to_list = AsyncMock(return_value=docs)
    db.jobs.find = MagicMock(return_value=cursor)
    return cursor


def assert_visibility(db):
    query = db.jobs.count_documents.call_args.args[0]
    assert query == db.jobs.find.call_args.args[0]
    assert query['is_active'] is True
    assert query['$and'][:2] == [
        {'$or':[{'campaign_id':{'$in':['active']}}, {'campaign_id':{'$exists':False}}, {'campaign_id':None}]},
        {'$or':[{'expires_at':{'$exists':False}}, {'expires_at':None}, {'expires_at':{'$gt':NOW}}]},
    ]
    return query


def test_list_shape_and_defaults(setup):
    client, db = setup
    cursor = list_result(db, [job_doc()])
    r = client.get('/api/jobs')
    assert r.status_code == 200 and r.headers['content-type'] == 'application/json'
    data = r.json()
    assert set(data) == {'jobs','total','page','limit','total_pages'}
    assert (data['total'],data['page'],data['limit'],data['total_pages']) == (1,1,20,1)
    item = data['jobs'][0]
    assert set(item) == KEYS and item['id'] == 'j1'
    assert item['company'] == {'id':'c1','name':'Example','location':'Paris','industry':'','size':''}
    assert all(item[k] is None for k in ('salary_min','salary_max','external_url','cpc','logo_url'))
    assert item['requirements'] == item['benefits'] == item['tags'] == []
    assert item['is_new'] is False and item['views_count'] == 0
    assert_visibility(db)
    cursor.sort.assert_called_once_with([('created_at',-1)])
    cursor.skip.assert_called_once_with(0)
    cursor.limit.assert_called_once_with(20)
    assert db.jobs.writes == []


@pytest.mark.parametrize('params', [{}, {'search':'Python'}, {'location':'Paris'}, {'company_id':'c1'},
                                  {'search':'Python','location':'Paris','company':'Example','company_id':'ignored'}])
def test_filters_preserve_public_visibility(setup, params):
    client, db = setup
    list_result(db, [])
    db.companies.distinct = AsyncMock(return_value=['c1'])
    r = client.get('/api/jobs', params=params)
    assert r.status_code == 200 and r.json()['jobs'] == [] and r.json()['total_pages'] == 0
    q = assert_visibility(db)
    assert len(q['$and']) == 2 + bool(params.get('search')) + bool(params.get('location'))
    if 'search' in params:
        assert q['$and'][2]['$or'][0] == {'title':{'$regex':'Python','$options':'i'}}
    if 'location' in params:
        assert q['$and'][-1] == {'$or':[{'location':{'$regex':'Paris','$options':'i'}}]}
    if 'company' in params:
        assert q['company_id'] == {'$in':['c1']}  # Name overrides explicit ID today.
    elif 'company_id' in params:
        assert q['company_id'] == 'c1'
    assert db.jobs.writes == []


@pytest.mark.parametrize('sort,expected', [('created_at',('created_at',-1)),('salary_min',('salary_min',-1)),('title',('title',1)),('unknown',('created_at',-1))])
def test_sort_and_pagination(setup, sort, expected):
    client, db = setup
    cursor = list_result(db, [], total=5)
    r = client.get('/api/jobs', params={'sort':sort,'page':4,'limit':2})
    assert r.json() == {'jobs':[],'total':5,'page':4,'limit':2,'total_pages':3}
    assert r.status_code == 200
    cursor.sort.assert_called_once_with([expected])
    cursor.skip.assert_called_once_with(6)
    cursor.limit.assert_called_once_with(2)
    cursor.to_list.assert_awaited_once_with(length=2)


@pytest.mark.parametrize('field,value', [('page',0),('page','bad'),('limit',0),('limit',101)])
def test_pagination_validation(setup, field, value):
    client, db = setup
    list_result(db, [])
    r = client.get('/api/jobs', params={field:value})
    assert r.status_code == 422 and r.json()['detail'][0]['loc'] == ['query',field]
    db.jobs.count_documents.assert_not_awaited()
    assert db.jobs.writes == []


def test_detail_shape_and_view_increment(setup):
    client, db = setup
    db.jobs.docs['j1'] = job_doc()
    db.jobs.update_one = AsyncMock()
    r = client.get('/api/jobs/j1')
    assert r.status_code == 200 and set(r.json()) == KEYS
    assert r.json()['views_count'] == 1 and r.json()['id'] == 'j1'
    db.jobs.update_one.assert_awaited_once_with({'_id':'j1'},{'$inc':{'views_count':1}})


@pytest.mark.parametrize('changes', [None, {'is_active':False}, {'expires_at':datetime(2000,1,1)},
                                   {'expires_at':''}, {'expires_at':'invalid'}, {'campaign_id':'paused'},
                                   {'campaign_id':'future'}, {'campaign_id':'spent'}, {'campaign_id':'missing'}])
def test_hidden_or_missing_detail_no_write(setup, changes):
    client, db = setup
    if changes is not None:
        db.jobs.docs['j1'] = job_doc(**changes)
    assert_error(client.get('/api/jobs/j1'),404,'Job not found')
    assert db.jobs.writes == []


def test_no_slash_redirect(setup):
    client, db = setup
    r = client.get('/api/jobs/', follow_redirects=False)
    assert_error(r,404,'Not Found')
    assert 'location' not in r.headers and db.jobs.writes == []
