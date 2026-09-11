"""A11 G0: strict A0 adapter, append-only identity recovery and migration preflight."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pymongo.errors import DuplicateKeyError

from domains.intent.serialization import EVENT_KINDS, event_from_document, event_to_document
from domains.intent.service import IntentEventConflictError, IntentEventService
from domains.talent_stream.events import (
    ConsentContextRef, IntentKind, IntentOrigin, IntentSubject, PrivacyContextRef, TalentIntentEvent,
)
from scripts.migrate_ts_a11_intent_event_indexes import (
    INDEX_NAME, PARTIAL, IntentMigrationError, migrate,
)

NOW = datetime(2026, 9, 11, 12, 0, 0, 123000, tzinfo=timezone.utc)


def event(**changes):
    values = dict(event_id='event-1', schema_version='intent-event-v1',
                  subject=IntentSubject(candidate_id='candidate-1'), intent_kind=IntentKind.JOB,
                  origin=IntentOrigin.DECLARED, event_type='job_interest_declared', job_id='job-1',
                  occurred_at=NOW, created_at=NOW, source_type='candidate_declared')
    values.update(changes)
    return TalentIntentEvent(**values)


class Cursor:
    def __init__(self, docs): self.docs = iter(deepcopy(docs))
    def __aiter__(self): return self
    async def __anext__(self):
        try: return next(self.docs)
        except StopIteration: raise StopAsyncIteration


class Collection:
    """Only operations authorized for A11 exist on this double."""
    def __init__(self, docs=()):
        self.docs = deepcopy(list(docs))
        self.inserts = 0
        self.created_indexes = []
        self.indexes = {'_id_': {'key':[('_id',1)]}}
        self.collection_options = {}
    def with_options(self, **options):
        assert options['write_concern'].document == {'w':'majority'}
        assert options['read_preference'].name == 'Primary'
        return self
    async def insert_one(self, doc):
        if any(d['_id']==doc['_id'] or ('idempotency_key' in doc and d.get('idempotency_key')==doc['idempotency_key']) for d in self.docs):
            raise DuplicateKeyError('synthetic duplicate')
        self.docs.append(deepcopy(doc)); self.inserts += 1
    async def find_one(self, query, **kwargs):
        return next((deepcopy(d) for d in self.docs if all(d.get(k)==v for k,v in query.items())),None)
    def find(self, query): return Cursor(self.docs)
    async def options(self): return deepcopy(self.collection_options)
    async def index_information(self): return deepcopy(self.indexes)
    async def create_index(self, keys, **options):
        self.created_indexes.append((deepcopy(keys),deepcopy(options)))
        self.indexes[options['name']] = {'key':deepcopy(keys), **deepcopy(options)}


def database(docs=()):
    # Any attempted profiles/preferences/grants/billing write fails: no such collection.
    return SimpleNamespace(talent_intent_events=Collection(docs))


@pytest.mark.parametrize('event_type,kind', list(EVENT_KINDS.items()))
@pytest.mark.parametrize('pseudo',[False,True])
def test_allowed_dimensions_subjects_and_exact_roundtrip(event_type,kind,pseudo):
    obj = event(event_type=event_type,intent_kind=kind,
                subject=IntentSubject(pseudonymous_id='pseudo-1') if pseudo else IntentSubject(candidate_id='candidate-1'),
                job_id='job-1' if kind==IntentKind.JOB else None,
                role_dna_id='role-1' if kind==IntentKind.ROLE else None,
                target_organization_id='target-1' if kind==IntentKind.COMPANY else None)
    doc = event_to_document(obj)
    assert event_from_document(doc)==obj
    assert doc['_id']==obj.event_id and 'event_id' not in doc and 'idempotency_key' not in doc
    assert doc['subject']==({'pseudonymous_id':'pseudo-1'} if pseudo else {'candidate_id':'candidate-1'})
    assert set(doc)=={'_id','schema_version','subject','intent_kind','origin','event_type','occurred_at','created_at','source_type'} | ({'job_id'} if kind==IntentKind.JOB else {'role_dna_id'} if kind==IntentKind.ROLE else {'target_organization_id'} if kind==IntentKind.COMPANY else set())


def test_all_optional_fields_and_distinct_company_target_provenance():
    obj = event(intent_kind=IntentKind.COMPANY,event_type='company_interest_declared',
                target_organization_id='target',source_organization_id='source',source_campaign_id='campaign',
                role_dna_id='role',idempotency_key='key',correlation_id='correlation',causation_id='cause',
                consent_context=ConsentContextRef('consent-v1','consent:1'),
                privacy_context=PrivacyContextRef('privacy-v1','privacy:1'),retention_until=NOW+timedelta(days=1))
    doc = event_to_document(obj)
    assert event_from_document(doc)==obj
    assert doc['target_organization_id']=='target' and doc['source_organization_id']=='source'
    assert doc['consent_context']=={'consent_policy_version':'consent-v1','context_ref':'consent:1'}
    assert doc['privacy_context']=={'policy_version':'privacy-v1','context_ref':'privacy:1'}
    assert doc['job_id']=='job-1' and doc['role_dna_id']=='role'  # Context does not change dimension.


@pytest.mark.parametrize('field,value', [
    ('_id',''),('_id','   '),('_id',12),('_id',' id'),('schema_version','future-v2'),
    ('event_type','discovery_enabled'),('event_type','job_view'),('event_type','cpc_click'),
    ('event_type','role_interest_inferred'),('event_type','unknown'),
    ('origin','observed'),('origin','inferred'),('origin',False),('intent_kind','unknown'),
    ('intent_kind','market'),('source_type',''),('source_type','Candidate_Declared'),
    ('source_type','https://example.invalid'),('source_type','cpc'),('source_type','billing_click'),
    ('source_type','permission_granted'),('source_type','discovery_state'),
    ('subject',{}),('subject',{'candidate_id':'c','pseudonymous_id':'p'}),
    ('subject',{'candidate_id':''}),('subject',{'candidate_id':None}),('subject',{'email':'a@example.com'}),
    ('idempotency_key',None),('idempotency_key',''),('job_id',None),('job_id',123),
    ('consent_context',{'consent_policy_version':'','context_ref':'x'}),
    ('privacy_context',{'policy_version':'v1','context_ref':'x','grant':True}),
    ('privacy_context',None),('retention_until',NOW),
    ('created_at',NOW-timedelta(seconds=1)),('target_organization_id','org'),
])
def test_document_rejects_invalid_contract(field,value):
    doc = event_to_document(event()); doc[field]=value
    with pytest.raises(ValueError): event_from_document(doc)


@pytest.mark.parametrize('field',['_id','schema_version','subject','intent_kind','origin','event_type','occurred_at','created_at','source_type','job_id'])
def test_required_fields_are_not_defaulted(field):
    doc = event_to_document(event()); del doc[field]
    with pytest.raises(ValueError): event_from_document(doc)


@pytest.mark.parametrize('field',['event_id','email','phone','cv_url','cost','cpc','billing_amount','permission','grant','discovery','metadata'])
def test_unknown_fields_cannot_smuggle_personal_or_other_domain_data(field):
    doc = event_to_document(event()); doc[field]='forbidden'
    with pytest.raises(ValueError): event_from_document(doc)


def test_role_requires_reference_and_company_never_uses_source_as_target():
    for kind,etype in [(IntentKind.ROLE,'role_interest_declared'),(IntentKind.COMPANY,'company_interest_declared')]:
        doc = event_to_document(event()); doc.update(intent_kind=kind.value,event_type=etype,source_organization_id='source')
        with pytest.raises(ValueError): event_from_document(doc)


@pytest.mark.parametrize('field',['occurred_at','created_at','retention_until'])
def test_business_dates_require_timezone_and_exact_milliseconds(field):
    for value in (NOW.replace(tzinfo=None),NOW+timedelta(microseconds=1),'2026-09-11'):
        obj = event(retention_until=NOW+timedelta(days=1))
        # Bypass A0 temporal construction to exercise the stricter A11 boundary.
        object.__setattr__(obj,field,value)
        with pytest.raises((ValueError,TypeError)): event_to_document(obj)


def test_utc_equivalence_and_naive_bson_only_at_rehydration():
    shifted = NOW.astimezone(timezone(timedelta(hours=2)))
    obj = event(occurred_at=shifted,created_at=shifted)
    doc = event_to_document(obj)
    assert doc['occurred_at']==NOW and doc['occurred_at'].tzinfo==timezone.utc
    doc['occurred_at']=NOW.replace(tzinfo=None); doc['created_at']=NOW.replace(tzinfo=None)
    assert event_from_document(doc)==event()
    doc['occurred_at']=doc['occurred_at'].replace(microsecond=123001)
    with pytest.raises(ValueError): event_from_document(doc)


@pytest.mark.parametrize('field,value',[('subject',{'candidate_id':'c'}),('origin','declared'),('intent_kind','job'),('consent_context',{}),('schema_version',True),('event_id','')])
def test_malformed_a0_objects_fail_before_insert(field,value):
    obj=event(); object.__setattr__(obj,field,value)
    with pytest.raises(ValueError): event_to_document(obj)


@pytest.mark.asyncio
async def test_record_retry_without_or_with_key_is_append_only():
    for key in (None,'key'):
        db=database(); service=IntentEventService(db); obj=event(idempotency_key=key)
        assert await service.record(obj)==obj
        assert await service.record(obj)==obj
        assert db.talent_intent_events.inserts==1 and len(db.talent_intent_events.docs)==1
        assert set(vars(db))=={'talent_intent_events'}


@pytest.mark.asyncio
@pytest.mark.parametrize('changes',[
    {'source_organization_id':'different'},{'subject':IntentSubject(candidate_id='other')},
    {'job_id':'other'},{'created_at':NOW+timedelta(seconds=1)}, {'idempotency_key':'other'},
    {'event_id':'other'},{'retention_until':NOW+timedelta(days=1)},
    {'privacy_context':PrivacyContextRef('v1','other')},
])
async def test_identity_or_key_payload_conflicts_never_overwrite(changes):
    db=database(); service=IntentEventService(db); obj=event(idempotency_key='key')
    await service.record(obj)
    before=deepcopy(db.talent_intent_events.docs)
    with pytest.raises(IntentEventConflictError): await service.record(replace(obj,**changes))
    assert db.talent_intent_events.docs==before and db.talent_intent_events.inserts==1


@pytest.mark.asyncio
async def test_identity_and_key_pointing_to_different_documents_conflicts():
    first=event_to_document(event(idempotency_key='a'))
    second=event_to_document(event(event_id='event-2',idempotency_key='b'))
    db=database([first,second])
    with pytest.raises(IntentEventConflictError):
        await IntentEventService(db).record(event(idempotency_key='b'))
    assert db.talent_intent_events.inserts==0


@pytest.mark.asyncio
@pytest.mark.parametrize('corruption',[{'schema_version':'future'}, {'cost':1}, {'subject':{'candidate_id':''}}])
async def test_corrupt_duplicate_is_not_idempotent_success(corruption):
    doc=event_to_document(event()); doc.update(corruption); db=database([doc])
    with pytest.raises(IntentEventConflictError): await IntentEventService(db).record(event())
    assert db.talent_intent_events.inserts==0


@pytest.mark.asyncio
async def test_duplicate_without_matching_record_and_invalid_input_fail_closed():
    db=database(); coll=db.talent_intent_events
    coll.insert_one=AsyncMock(side_effect=DuplicateKeyError('synthetic'))
    with pytest.raises(IntentEventConflictError): await IntentEventService(db).record(event())
    coll.insert_one.reset_mock()
    with pytest.raises(ValueError): await IntentEventService(db).record(event(job_id=None))
    coll.insert_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_preflight_default_read_only_then_minimal_repeatable_migration():
    db=database([event_to_document(event())]); coll=db.talent_intent_events
    assert await migrate(db)=={'documents_checked':1,'idempotency_index_ready':False}
    assert coll.created_indexes==[]
    assert (await migrate(db,apply=True))['idempotency_index_ready'] is True
    await migrate(db,apply=True)
    assert coll.created_indexes==[([('idempotency_key',1)],dict(name=INDEX_NAME,unique=True,partialFilterExpression=PARTIAL,collation={'locale':'simple'}))]
    assert coll.inserts==0


@pytest.mark.asyncio
@pytest.mark.parametrize('bad_docs',[
    [{'_id':'broken'}],
    [event_to_document(event()),event_to_document(event())],
    [event_to_document(event(idempotency_key='key')),event_to_document(event(event_id='other',idempotency_key='key'))],
])
async def test_preflight_rejects_malformed_or_duplicate_data_without_mutation(bad_docs):
    db=database(bad_docs)
    with pytest.raises(IntentMigrationError): await migrate(db,apply=True)
    assert db.talent_intent_events.created_indexes==[] and db.talent_intent_events.docs==bad_docs


@pytest.mark.asyncio
@pytest.mark.parametrize('index',[
    {'key':[('retention_until',1)],'expireAfterSeconds':0},
    {'key':[('idempotency_key',1)],'unique':False,'partialFilterExpression':PARTIAL},
    {'key':[('idempotency_key',1)],'unique':True},
    {'key':[('idempotency_key',1)],'unique':True,'partialFilterExpression':PARTIAL,'collation':{'locale':'en'}},
])
async def test_preflight_rejects_incompatible_indexes_without_repair(index):
    db=database(); db.talent_intent_events.indexes[INDEX_NAME]=index
    with pytest.raises(IntentMigrationError): await migrate(db,apply=True)
    assert db.talent_intent_events.created_indexes==[]


@pytest.mark.asyncio
async def test_preflight_rejects_nonbinary_collection_collation():
    db=database(); db.talent_intent_events.collection_options={'collation':{'locale':'en'}}
    with pytest.raises(IntentMigrationError): await migrate(db,apply=True)
    assert db.talent_intent_events.created_indexes==[]
