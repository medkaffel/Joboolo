"""Strict BSON-compatible A14 adapters; no database access or payload logging.

The immutable envelope is flat at storage level for identity indexes; mutable
operational fields remain a separate value object. Optional fields are omitted,
never stored as null. BSON-naive datetimes are accepted only on decoding.
"""
from dataclasses import fields
from datetime import datetime

from .models import (
    FailureCode, JobEnvelope, JobReference, JobState, OperationalState,
    OutboxRecord, RetryPolicy, utc_millisecond,
)

ENVELOPE_REQUIRED = {
    "_id", "job_type", "idempotency_key", "schema_version", "payload_schema_version",
    "reference", "retry_policy", "created_at", "initial_available_at",
}
ENVELOPE_OPTIONAL = {"correlation_id", "causation_id"}
STATE_REQUIRED = {"state", "attempt_count", "available_at", "updated_at"}
STATE_OPTIONAL = {
    "lease_owner", "lease_token", "lease_until", "completion_token",
    "completed_at", "failed_at", "failure_code",
}
DATES = {"created_at", "initial_available_at", "available_at", "updated_at",
         "lease_until", "completed_at", "failed_at"}


def _shape(value, required, optional=frozenset()):
    if type(value) is not dict or not required <= value.keys() or value.keys() - (required | optional):
        raise ValueError("missing or unknown contract fields")
    if any(item is None for item in value.values()):
        raise ValueError("null fields must be omitted")


def _values(obj):
    return {field.name: getattr(obj, field.name) for field in fields(obj)
            if getattr(obj, field.name) is not None}


def envelope_to_document(envelope: JobEnvelope) -> dict:
    if type(envelope) is not JobEnvelope:
        raise ValueError("expected JobEnvelope")
    result = _values(envelope)
    result["_id"] = result.pop("job_id")
    result["reference"] = _values(envelope.reference)
    result["retry_policy"] = _values(envelope.retry_policy)
    # Validate even an object deliberately corrupted via object.__setattr__.
    envelope_from_document(result, storage=False)
    return result


def envelope_from_document(document: dict, *, storage: bool = True) -> JobEnvelope:
    _shape(document, ENVELOPE_REQUIRED, ENVELOPE_OPTIONAL)
    _shape(document["reference"], {"reference_type", "reference_id", "reference_version"})
    _shape(document["retry_policy"], {"version", "max_attempts", "initial_delay_seconds", "max_delay_seconds"})
    values = dict(document)
    values["job_id"] = values.pop("_id")
    values["reference"] = JobReference(**document["reference"])
    values["retry_policy"] = RetryPolicy(**document["retry_policy"])
    for name in ("created_at", "initial_available_at"):
        values[name] = utc_millisecond(values[name], storage=storage)
    return JobEnvelope(**values)


def record_to_document(record: OutboxRecord) -> dict:
    if type(record) is not OutboxRecord or type(record.operational) is not OperationalState:
        raise ValueError("expected OutboxRecord")
    document = envelope_to_document(record.envelope)
    values = _values(record.operational)
    if type(values["state"]) is not JobState:
        raise ValueError("invalid job state")
    values["state"] = values["state"].value
    if "failure_code" in values:
        if type(values["failure_code"]) is not FailureCode:
            raise ValueError("invalid failure code")
        values["failure_code"] = values["failure_code"].value
    document.update(values)
    record_from_document(document, storage=False)
    return document


def record_from_document(document: dict, *, storage: bool = True) -> OutboxRecord:
    _shape(document, ENVELOPE_REQUIRED | STATE_REQUIRED, ENVELOPE_OPTIONAL | STATE_OPTIONAL)
    envelope = envelope_from_document(
        {key: value for key, value in document.items() if key in ENVELOPE_REQUIRED | ENVELOPE_OPTIONAL},
        storage=storage,
    )
    values = {key: value for key, value in document.items() if key in STATE_REQUIRED | STATE_OPTIONAL}
    try:
        if type(values["state"]) is not str:
            raise ValueError
        values["state"] = JobState(values["state"])
        if "failure_code" in values:
            if type(values["failure_code"]) is not str:
                raise ValueError
            values["failure_code"] = FailureCode(values["failure_code"])
    except ValueError:
        raise ValueError("unsupported operational state or failure code") from None
    for name in DATES & values.keys():
        values[name] = utc_millisecond(values[name], storage=storage)
    return OutboxRecord(envelope, OperationalState(**values))
