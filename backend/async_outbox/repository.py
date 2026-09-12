"""Narrow A14 persistence primitives; no worker, connection or index creation.

Caller owns transaction lifetime and downstream effect idempotency. Readiness
is checked on every mutation, not cached: schema changes must still be excluded
operationally while writers run (metadata reads cannot lock indexes).
"""
import secrets

from pymongo import ReadPreference, ReturnDocument
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern

from mongo_index_safety import verify_metadata
from .index_requirements import OUTBOX_REQUIREMENT
from .models import (
    ENVELOPE_SCHEMA_VERSION, FailureCode, JobState, OperationalState,
    OutboxRecord, bounded_int, opaque_token,
)
from .serialization import envelope_to_document, record_from_document, record_to_document


class OutboxReadinessError(RuntimeError):
    pass


class OutboxConflictError(RuntimeError):
    pass


class OutboxTransactionRequiredError(RuntimeError):
    pass


class OutboxLeaseLostError(RuntimeError):
    pass


class OutboxStoredRecordError(RuntimeError):
    pass


def _decode(document):
    try:
        return record_from_document(document)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise OutboxStoredRecordError("invalid stored outbox record") from None


def _initial(envelope):
    return record_to_document(OutboxRecord(envelope, OperationalState(
        state=JobState.PENDING, attempt_count=0,
        available_at=envelope.initial_available_at, updated_at=envelope.created_at,
    )))


def _ownership(job_id, token):
    return {
        "_id": opaque_token(job_id), "schema_version": ENVELOPE_SCHEMA_VERSION,
        "state": "leased", "lease_token": opaque_token(token),
        "$expr": {"$gt": ["$lease_until", "$$NOW"]},
    }


def _clear_lease():
    return {"$unset": ["lease_owner", "lease_token", "lease_until"]}


class OutboxRepository:
    def __init__(self, db):
        self.db = db
        self.collection = db[OUTBOX_REQUIREMENT.name].with_options(
            read_preference=ReadPreference.PRIMARY, write_concern=WriteConcern(w="majority"),
        )

    async def readiness(self):
        """Metadata only; return warnings, raise for any correctness failure."""
        try:
            collections = {}
            cursor = await self.db.list_collections(filter={"name": OUTBOX_REQUIREMENT.name})
            async for record in cursor:
                collections[record["name"]] = record
            indexes = {}
            if collections.get(OUTBOX_REQUIREMENT.name, {}).get("type") == "collection":
                indexes[OUTBOX_REQUIREMENT.name] = await self.collection.index_information()
            report = verify_metadata((OUTBOX_REQUIREMENT,), collections, indexes)
        except Exception:
            raise OutboxReadinessError("outbox metadata unavailable") from None
        if not report.ok:
            raise OutboxReadinessError("outbox invariants not ready")
        return report

    async def publish(self, envelope):
        """Autonomous publication: never starts a transaction."""
        document = _initial(envelope)
        await self.readiness()
        try:
            await self.collection.insert_one(document)
        except DuplicateKeyError:
            return await self.recover_publication(envelope)
        return _decode(document)

    async def publish_in_transaction(self, envelope, *, session):
        """No recovery here: caller must abort on conflict, then recover outside."""
        if session is None or getattr(session, "in_transaction", False) is not True:
            raise OutboxTransactionRequiredError("active caller transaction required")
        document = _initial(envelope)
        await self.readiness()
        try:
            await self.collection.insert_one(document, session=session)
        except DuplicateKeyError:
            raise OutboxConflictError("publication conflict; abort transaction before recovery") from None
        return _decode(document)

    async def recover_publication(self, envelope):
        """Read-only, no session: both unique identities must converge."""
        expected = envelope_to_document(envelope)
        by_id = await self.collection.find_one({"_id": envelope.job_id}, collation={"locale": "simple"})
        by_key = await self.collection.find_one({
            "job_type": envelope.job_type, "idempotency_key": envelope.idempotency_key,
        }, collation={"locale": "simple"})
        if by_id is None or by_key is None or by_id.get("_id") != by_key.get("_id"):
            raise OutboxConflictError("outbox identity collision")
        try:
            records = (_decode(by_id), _decode(by_key))
            if any(envelope_to_document(record.envelope) != expected for record in records):
                raise OutboxConflictError("outbox envelope conflict")
        except OutboxStoredRecordError:
            raise OutboxConflictError("invalid stored publication") from None
        # Operational state may advance between reads; envelope must not.
        return records[-1]

    async def claim(self, lease_owner, *, lease_seconds):
        opaque_token(lease_owner)
        bounded_int(lease_seconds, 1, 3600)
        token = secrets.token_hex(32)
        await self.readiness()
        document = await self.collection.find_one_and_update({
            "schema_version": ENVELOPE_SCHEMA_VERSION,
            "retry_policy.version": "exponential-v1",
            "$expr": {"$and": [
                {"$lt": ["$attempt_count", "$retry_policy.max_attempts"]},
                {"$or": [
                    {"$and": [{"$eq": ["$state", "pending"]}, {"$lte": ["$available_at", "$$NOW"]}]},
                    {"$and": [{"$eq": ["$state", "leased"]}, {"$lte": ["$lease_until", "$$NOW"]}]},
                ]},
            ]},
        }, [
            {"$set": {"state": "leased", "lease_owner": {"$literal": lease_owner},
                      "lease_token": {"$literal": token}, "updated_at": "$$NOW",
                      "lease_until": {"$add": ["$$NOW", lease_seconds * 1000]},
                      "attempt_count": {"$add": ["$attempt_count", 1]}}},
            {"$unset": "failure_code"},
        ], sort=[("available_at", 1), ("_id", 1)], return_document=ReturnDocument.AFTER,
            collation={"locale": "simple"})
        return _decode(document) if document is not None else None

    async def _owned_update(self, job_id, token, pipeline):
        query = _ownership(job_id, token)
        await self.readiness()
        document = await self.collection.find_one_and_update(
            query, pipeline, return_document=ReturnDocument.AFTER, collation={"locale": "simple"},
        )
        if document is None:
            raise OutboxLeaseLostError("lease not owned or expired")
        return _decode(document)

    async def renew(self, job_id, token, *, lease_seconds):
        bounded_int(lease_seconds, 1, 3600)
        return await self._owned_update(job_id, token, [{"$set": {
            "updated_at": "$$NOW", "lease_until": {"$add": ["$$NOW", lease_seconds * 1000]},
        }}])

    async def retry(self, job_id, token):
        # All operands come from the immutable persisted, validated policy.
        exhausted = {"$gte": ["$attempt_count", "$retry_policy.max_attempts"]}
        delay_ms = {"$multiply": [1000, {"$toLong": {"$min": [
            "$retry_policy.max_delay_seconds",
            {"$multiply": ["$retry_policy.initial_delay_seconds",
                            {"$pow": [2, {"$subtract": ["$attempt_count", 1]}]}]},
        ]}}]}
        return await self._owned_update(job_id, token, [
            {"$set": {
                "state": {"$cond": [exhausted, "failed", "pending"]},
                "failure_code": {"$cond": [exhausted, "attempts_exhausted", "transient"]},
                "failed_at": {"$cond": [exhausted, "$$NOW", "$$REMOVE"]},
                "available_at": {"$cond": [exhausted, "$available_at", {"$add": ["$$NOW", delay_ms]}]},
                "updated_at": "$$NOW",
            }}, _clear_lease(),
        ])

    async def fail(self, job_id, token, *, reason):
        if type(reason) is not FailureCode or reason not in (FailureCode.PERMANENT, FailureCode.UNSUPPORTED_PAYLOAD):
            raise ValueError("permanent closed failure reason required")
        return await self._owned_update(job_id, token, [
            {"$set": {"state": "failed", "failure_code": reason.value,
                      "failed_at": "$$NOW", "updated_at": "$$NOW"}}, _clear_lease(),
        ])

    async def complete(self, job_id, token):
        opaque_token(job_id)
        opaque_token(token)
        # Fast read-only acknowledgement: repeated completion does not write.
        existing = await self.collection.find_one({
            "_id": job_id, "state": "completed", "completion_token": token,
        }, collation={"locale": "simple"})
        if existing is not None:
            return _decode(existing)
        try:
            return await self._owned_update(job_id, token, [
                {"$set": {"state": "completed", "completion_token": "$lease_token",
                          "completed_at": "$$NOW", "updated_at": "$$NOW"}}, _clear_lease(),
            ])
        except OutboxLeaseLostError:
            # Another identical completion may have committed after our read.
            existing = await self.collection.find_one({
                "_id": job_id, "state": "completed", "completion_token": token,
            }, collation={"locale": "simple"})
            if existing is not None:
                return _decode(existing)
            raise OutboxLeaseLostError("completion token not owned") from None

    async def terminalize_expired(self):
        """At most one exhausted expired lease per call; no background loop."""
        await self.readiness()
        document = await self.collection.find_one_and_update({
            "schema_version": ENVELOPE_SCHEMA_VERSION, "state": "leased",
            "$expr": {"$and": [
                {"$lte": ["$lease_until", "$$NOW"]},
                {"$gte": ["$attempt_count", "$retry_policy.max_attempts"]},
            ]},
        }, [
            {"$set": {"state": "failed", "failure_code": "attempts_exhausted",
                      "failed_at": "$$NOW", "updated_at": "$$NOW"}}, _clear_lease(),
        ], sort=[("lease_until", 1), ("_id", 1)], return_document=ReturnDocument.AFTER,
            collation={"locale": "simple"})
        return _decode(document) if document is not None else None
