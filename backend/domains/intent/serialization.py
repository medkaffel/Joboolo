"""Strict A11 v1 adapter for the A0 envelope; no inference or policy evaluation."""
from dataclasses import fields
from datetime import datetime, timezone
import re

from domains.talent_stream.events import (
    ConsentContextRef, IntentKind, IntentOrigin, IntentSubject, PrivacyContextRef,
    TalentIntentEvent,
)

SCHEMA_VERSION = 'intent-event-v1'
EVENT_KINDS = {
    'job_interest_declared': IntentKind.JOB,
    'job_favorite_shared_declared': IntentKind.JOB,
    'job_application_declared': IntentKind.JOB,
    'role_interest_declared': IntentKind.ROLE,
    'company_interest_declared': IntentKind.COMPANY,
    'market_interest_declared': IntentKind.MARKET,
}
REQUIRED = {'_id', 'schema_version', 'subject', 'intent_kind', 'origin', 'event_type',
            'occurred_at', 'created_at', 'source_type'}
OPTIONAL_IDS = {'idempotency_key', 'job_id', 'role_dna_id', 'target_organization_id',
                'source_organization_id', 'source_campaign_id', 'correlation_id', 'causation_id'}
OPTIONAL = OPTIONAL_IDS | {'consent_context', 'privacy_context', 'retention_until'}


def nonblank(value, field):
    if type(value) is not str or not value or value != value.strip() or any(c.isspace() for c in value):
        raise ValueError(f'{field} must be a nonblank string without whitespace')
    return value


def source_token(value):
    nonblank(value, 'source_type')
    if not re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)*', value):
        raise ValueError('source_type must be a lowercase internal token')
    if set(value.split('_')) & {'cpc', 'billing', 'permission', 'permissions', 'grant', 'grants', 'discovery'}:
        raise ValueError('source_type cannot represent billing, Permission or Discovery')
    return value


def utc_millisecond(value, field, *, storage=False):
    if not isinstance(value, datetime):
        raise ValueError(f'{field} must be a datetime')
    if value.tzinfo is None:
        if not storage:
            raise ValueError(f'{field} must be timezone-aware')
        value = value.replace(tzinfo=timezone.utc)
    elif value.utcoffset() is None:
        raise ValueError(f'{field} must have a valid UTC offset')
    value = value.astimezone(timezone.utc)
    if value.microsecond % 1000:
        raise ValueError(f'{field} must have exact BSON millisecond precision')
    return value


def _shape(value, required, allowed, field):
    if type(value) is not dict or not required <= value.keys() or value.keys() - allowed:
        raise ValueError(f'{field} has missing or unknown fields')


def _context(value, version_field, field):
    _shape(value, {version_field, 'context_ref'}, {version_field, 'context_ref'}, field)
    return {k: nonblank(v, f'{field}.{k}') for k, v in value.items()}


def _canonical_document(doc, *, storage):
    _shape(doc, REQUIRED, REQUIRED | OPTIONAL, 'intent event')
    out = {key: nonblank(doc[key], key) for key in ('_id', 'schema_version', 'event_type')}
    if out['schema_version'] != SCHEMA_VERSION:
        raise ValueError('unsupported Intent schema version')
    if type(doc['intent_kind']) is not str or type(doc['origin']) is not str:
        raise ValueError('stored kind and origin must be strings')
    kind = IntentKind(doc['intent_kind'])
    if doc['origin'] != IntentOrigin.DECLARED.value or EVENT_KINDS.get(out['event_type']) != kind:
        raise ValueError('A11 v1 requires an allowed declared event matching its dimension')
    out.update(intent_kind=kind.value, origin=IntentOrigin.DECLARED.value,
               source_type=source_token(doc['source_type']))
    subject = doc['subject']
    _shape(subject, set(), {'candidate_id', 'pseudonymous_id'}, 'subject')
    if len(subject) != 1:
        raise ValueError('subject requires exactly one identity')
    out['subject'] = {k: nonblank(v, f'subject.{k}') for k, v in subject.items()}
    for key in OPTIONAL_IDS:
        if key in doc:
            out[key] = nonblank(doc[key], key)
    if kind == IntentKind.JOB and 'job_id' not in out:
        raise ValueError('Job Intent requires job_id')
    if kind == IntentKind.ROLE and 'role_dna_id' not in out:
        raise ValueError('Role Intent requires role_dna_id')
    if (kind == IntentKind.COMPANY) != ('target_organization_id' in out):
        raise ValueError('only Company Intent requires target_organization_id')
    for key, version in [('consent_context', 'consent_policy_version'), ('privacy_context', 'policy_version')]:
        if key in doc:
            out[key] = _context(doc[key], version, key)
    for key in ('occurred_at', 'created_at', 'retention_until'):
        if key in doc:
            out[key] = utc_millisecond(doc[key], key, storage=storage)
    if out['created_at'] < out['occurred_at']:
        raise ValueError('creation cannot predate occurrence')
    if 'retention_until' in out and out['retention_until'] <= out['occurred_at']:
        raise ValueError('retention must be after occurrence')
    return out


def event_to_document(event: TalentIntentEvent) -> dict:
    if type(event) is not TalentIntentEvent or set(vars(event)) != {f.name for f in fields(TalentIntentEvent)}:
        raise ValueError('expected the exact A0 TalentIntentEvent contract')
    if type(event.subject) is not IntentSubject or set(vars(event.subject)) != {'candidate_id', 'pseudonymous_id'}:
        raise ValueError('expected IntentSubject')
    if type(event.intent_kind) is not IntentKind or type(event.origin) is not IntentOrigin:
        raise ValueError('expected IntentKind and IntentOrigin enums')
    doc = {key: getattr(event, key) for key in REQUIRED - {'_id', 'subject', 'intent_kind', 'origin'}}
    doc.update(_id=event.event_id, intent_kind=event.intent_kind.value, origin=event.origin.value,
               subject={k: v for k, v in vars(event.subject).items() if v is not None})
    for key in OPTIONAL:
        value = getattr(event, key)
        if value is None:
            continue
        if key in ('consent_context', 'privacy_context'):
            expected = ConsentContextRef if key == 'consent_context' else PrivacyContextRef
            if type(value) is not expected:
                raise ValueError(f'expected {expected.__name__}')
            value = vars(value).copy()
        doc[key] = value
    return _canonical_document(doc, storage=False)


def event_from_document(document: dict) -> TalentIntentEvent:
    doc = _canonical_document(document, storage=True)
    doc['event_id'] = doc.pop('_id')
    doc['subject'] = IntentSubject(**doc['subject'])
    doc['intent_kind'] = IntentKind(doc['intent_kind'])
    doc['origin'] = IntentOrigin(doc['origin'])
    if 'consent_context' in doc:
        doc['consent_context'] = ConsentContextRef(**doc['consent_context'])
    if 'privacy_context' in doc:
        doc['privacy_context'] = PrivacyContextRef(**doc['privacy_context'])
    return TalentIntentEvent(**doc)
