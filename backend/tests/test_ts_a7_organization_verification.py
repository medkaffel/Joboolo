from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from domains.shared.ids import OrganizationId
from domains.shared.versioning import EntityVersion, PolicyVersion
from domains.trust.organization_models import (
    Organization, OrganizationCreate, OrganizationIdentityRevision,
    OrganizationVerificationReasonCode as Reason,
    OrganizationVerificationState as State,
    OrganizationVerificationTransition,
)
from domains.trust.organization_service import (
    OrganizationConflictError, OrganizationInputNotFoundError, OrganizationService,
)
import domains.trust.organization_service as service_module

NOW = datetime(2026, 9, 4, 20, 0, tzinfo=timezone.utc)


class Collection:
    def __init__(self, docs=()):
        self.docs = {d['_id']: dict(d) for d in docs}
        self.update_sessions = []
        self.insert_sessions = []

    async def find_one(self, query, session=None, **kwargs):
        for doc in self.docs.values():
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    async def insert_one(self, doc, session=None):
        self.insert_sessions.append(session)
        if doc['_id'] in self.docs:
            from pymongo.errors import DuplicateKeyError
            raise DuplicateKeyError('duplicate')
        self.docs[doc['_id']] = dict(doc)
        return SimpleNamespace(inserted_id=doc['_id'])

    async def update_one(self, query, update, session=None):
        self.update_sessions.append(session)
        for doc in self.docs.values():
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get('$set', {}))
                for key, value in update.get('$inc', {}).items():
                    doc[key] = doc.get(key, 0) + value
                return SimpleNamespace(modified_count=1)
        return SimpleNamespace(modified_count=0)


class Tx:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False


class Session:
    def start_transaction(self): return Tx()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False


class Client:
    def __init__(self): self.sessions = []
    async def start_session(self):
        session = Session()
        self.sessions.append(session)
        return session


class DB:
    def __init__(self, organizations=(), companies=()):
        self.organizations = Collection(organizations)
        self.organization_verification_events = Collection()
        self.companies = Collection(companies)


def doc(state='unverified', version=1, **extra):
    value = {
        '_id': 'org:acme', 'organization_id': 'org:acme', 'version': version,
        'legal_name': 'Acme SAS', 'display_name': 'Acme',
        'website_url': 'https://acme.example', 'primary_domain': 'acme.example',
        'registration_country': 'FR', 'registration_id': '123456789',
        'legacy_company_id': None, 'verification_state': state,
        'verification_policy_version': None, 'verification_reason_codes': [],
        'verification_evidence_refs': [], 'verification_actor_id': None,
        'verification_decided_at': None, 'created_at': NOW, 'updated_at': NOW,
    }
    if state != 'unverified':
        value.update(
            verification_policy_version='trust-v1',
            verification_reason_codes=['verification_requested'],
            verification_evidence_refs=['evidence:1'] if state == 'verified' else [],
            verification_actor_id='admin:1', verification_decided_at=NOW,
        )
    value.update(extra)
    return value


def pending():
    return OrganizationVerificationTransition(
        State.PENDING, (Reason.VERIFICATION_REQUESTED,), (),
        PolicyVersion('trust-v1'), 'admin:1',
    )


def verified():
    return OrganizationVerificationTransition(
        State.VERIFIED, (Reason.LEGAL_IDENTITY_CONFIRMED,), ('registry:1',),
        PolicyVersion('trust-v1'), 'admin:2',
    )


@pytest.fixture
def client(monkeypatch):
    value = Client()
    monkeypatch.setattr(service_module, 'get_client', lambda: value)
    return value


def test_identity_validation_and_normalization():
    identity = OrganizationCreate(
        OrganizationId('org:1'), '  Acme   SAS ', primary_domain=' Jobs.ACME.Example. ',
        registration_country='fr', registration_id='123',
    ).to_identity()
    assert identity['legal_name'] == 'Acme SAS'
    assert identity['primary_domain'] == 'jobs.acme.example'
    assert identity['registration_country'] == 'FR'
    with pytest.raises(ValueError):
        OrganizationCreate(OrganizationId('org:2'), 'Acme', registration_country='FR').to_identity()
    with pytest.raises(ValueError):
        OrganizationCreate(OrganizationId('org:3'), 'Acme', primary_domain='https://acme.example').to_identity()


def test_revision_uses_explicit_clear_semantics():
    with pytest.raises(ValueError):
        OrganizationIdentityRevision(registration_country='FR')
    with pytest.raises(ValueError):
        OrganizationIdentityRevision(clear_fields=frozenset({'registration_id'}))
    with pytest.raises(ValueError):
        OrganizationIdentityRevision(display_name='   ')
    with pytest.raises(ValueError):
        OrganizationIdentityRevision(clear_fields=frozenset({'legacy_company_id'}))


def test_transition_contract_is_explainable_and_consistent():
    with pytest.raises(ValueError):
        OrganizationVerificationTransition(
            State.VERIFIED, (Reason.LEGAL_IDENTITY_CONFIRMED,), (), PolicyVersion('p1'), 'admin:1'
        )
    with pytest.raises(ValueError):
        OrganizationVerificationTransition(
            State.VERIFIED, (Reason.EVIDENCE_INSUFFICIENT,), ('e:1',), PolicyVersion('p1'), 'admin:1'
        )
    with pytest.raises(ValueError):
        OrganizationVerificationTransition(
            State.PENDING, (Reason.VERIFICATION_REQUESTED,), (), PolicyVersion(''), 'admin:1'
        )


@pytest.mark.asyncio
async def test_create_starts_unverified_and_does_not_infer_membership():
    db = DB(companies=[{'_id': 'company:1', 'owner_id': 'user:1'}])
    result = await OrganizationService(db).create(
        OrganizationCreate(OrganizationId('org:acme'), 'Acme SAS', legacy_company_id='company:1'),
        created_at=NOW,
    )
    assert result.version == 1 and result.verification_state is State.UNVERIFIED
    persisted = db.organizations.docs['org:acme']
    assert 'owner_id' not in persisted and 'membership_id' not in persisted


@pytest.mark.asyncio
async def test_create_rejects_missing_or_duplicate_legacy_mapping_target():
    with pytest.raises(OrganizationInputNotFoundError):
        await OrganizationService(DB()).create(
            OrganizationCreate(OrganizationId('org:1'), 'Acme', legacy_company_id='missing'), created_at=NOW
        )
    with pytest.raises(OrganizationConflictError):
        await OrganizationService(DB(organizations=[doc()])).create(
            OrganizationCreate(OrganizationId('org:acme'), 'Acme'), created_at=NOW
        )


@pytest.mark.asyncio
async def test_unverified_to_pending_updates_state_and_event_in_same_session(client):
    db = DB(organizations=[doc()])
    result = await OrganizationService(db).transition_verification(
        OrganizationId('org:acme'), EntityVersion(1), pending(), occurred_at=NOW
    )
    assert result.version == 2 and result.verification_state is State.PENDING
    event = next(iter(db.organization_verification_events.docs.values()))
    assert (event['previous_state'], event['new_state'], event['organization_version']) == ('unverified', 'pending', 2)
    session = client.sessions[0]
    assert db.organizations.update_sessions[-1] is session
    assert db.organization_verification_events.insert_sessions[-1] is session


@pytest.mark.asyncio
async def test_unverified_cannot_skip_pending(client):
    with pytest.raises(ValueError):
        await OrganizationService(DB(organizations=[doc()])).transition_verification(
            OrganizationId('org:acme'), EntityVersion(1), verified(), occurred_at=NOW
        )


@pytest.mark.asyncio
async def test_pending_to_verified_requires_and_persists_evidence(client):
    result = await OrganizationService(DB(organizations=[doc('pending', 2)])).transition_verification(
        OrganizationId('org:acme'), EntityVersion(2), verified(), occurred_at=NOW
    )
    assert result.verification_state is State.VERIFIED
    assert result.verification_evidence_refs == ('registry:1',)


@pytest.mark.asyncio
async def test_rejected_can_resubmit_but_cannot_jump_directly_to_verified(client):
    db = DB(organizations=[doc('rejected', 3)])
    result = await OrganizationService(db).transition_verification(
        OrganizationId('org:acme'), EntityVersion(3), pending(), occurred_at=NOW
    )
    assert result.verification_state is State.PENDING
    with pytest.raises(ValueError):
        await OrganizationService(DB(organizations=[doc('rejected', 3)])).transition_verification(
            OrganizationId('org:acme'), EntityVersion(3), verified(), occurred_at=NOW
        )


@pytest.mark.asyncio
async def test_stale_version_fails_closed_without_event(client):
    db = DB(organizations=[doc(version=4)])
    with pytest.raises(OrganizationConflictError):
        await OrganizationService(db).transition_verification(
            OrganizationId('org:acme'), EntityVersion(3), pending(), occurred_at=NOW
        )
    assert not db.organization_verification_events.docs


@pytest.mark.asyncio
async def test_non_sensitive_identity_change_preserves_verified_state(client):
    db = DB(organizations=[doc('verified', 3)])
    result = await OrganizationService(db).revise_identity(
        OrganizationId('org:acme'), EntityVersion(3), OrganizationIdentityRevision(display_name='Acme France'),
        actor_id='admin:1', policy_version=PolicyVersion('trust-v2'), occurred_at=NOW,
    )
    assert result.verification_state is State.VERIFIED
    assert not db.organization_verification_events.docs


@pytest.mark.asyncio
async def test_sensitive_identity_change_revokes_verified_state_and_audits(client):
    db = DB(organizations=[doc('verified', 3)])
    result = await OrganizationService(db).revise_identity(
        OrganizationId('org:acme'), EntityVersion(3), OrganizationIdentityRevision(legal_name='Acme Holding SAS'),
        actor_id='admin:1', policy_version=PolicyVersion('trust-v2'), occurred_at=NOW,
    )
    assert result.verification_state is State.UNVERIFIED
    assert result.verification_reason_codes == (Reason.IDENTITY_CHANGED_REVERIFICATION_REQUIRED,)
    event = next(iter(db.organization_verification_events.docs.values()))
    assert event['previous_state'] == 'verified' and event['new_state'] == 'unverified'


@pytest.mark.asyncio
async def test_sensitive_change_invalidates_pending_review(client):
    result = await OrganizationService(DB(organizations=[doc('pending', 2)])).revise_identity(
        OrganizationId('org:acme'), EntityVersion(2), OrganizationIdentityRevision(primary_domain='new.acme.example'),
        actor_id='admin:1', policy_version=PolicyVersion('trust-v2'), occurred_at=NOW,
    )
    assert result.verification_state is State.UNVERIFIED


@pytest.mark.asyncio
async def test_legacy_company_id_is_immutable_once_attached(client):
    db = DB(
        organizations=[doc(legacy_company_id='company:1')],
        companies=[{'_id': 'company:1'}, {'_id': 'company:2'}],
    )
    with pytest.raises(ValueError):
        await OrganizationService(db).revise_identity(
            OrganizationId('org:acme'), EntityVersion(1), OrganizationIdentityRevision(legacy_company_id='company:2'),
            actor_id='admin:1', policy_version=PolicyVersion('trust-v1'), occurred_at=NOW,
        )


@pytest.mark.asyncio
async def test_registration_identity_clear_revokes_verified_state(client):
    result = await OrganizationService(DB(organizations=[doc('verified', 3)])).revise_identity(
        OrganizationId('org:acme'), EntityVersion(3),
        OrganizationIdentityRevision(clear_fields=frozenset({'registration_country', 'registration_id'})),
        actor_id='admin:1', policy_version=PolicyVersion('trust-v2'), occurred_at=NOW,
    )
    assert result.registration_country is None and result.registration_id is None
    assert result.verification_state is State.UNVERIFIED


def test_organization_contract_has_no_recruiter_permission_or_cv_authority():
    fields = Organization.__dataclass_fields__
    for forbidden in ('owner_id', 'user_type', 'membership_id', 'recruiter_user_id', 'mandate_id', 'grant', 'permission', 'cv'):
        assert forbidden not in fields


def test_migration_is_explicit_unique_and_never_backfills_legacy_data():
    text = (Path(__file__).parents[1] / 'scripts' / 'migrate_ts_a7_organization_indexes.py').read_text()
    assert 'unique=True' in text
    assert 'legacy_company_id' in text
    assert 'registration_country' in text and 'registration_id' in text
    assert 'organization_verification_events' in text
    assert 'no automatic companies/partner_profiles backfill performed' in text
    assert 'insert_many' not in text and 'update_many' not in text
