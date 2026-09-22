"""Mongo implementation of the B9 Contact Governor reservation ledger.

The repository owns exactly the reservation and per-candidate guard
collections. It never creates metadata, reads a wall clock, repairs data or
persists B10 contact requests. Reservation checks and insertion execute in one
driver-retried Mongo transaction serialized by the candidate guard document.
"""
from __future__ import annotations

from datetime import datetime

from pymongo import ReadPreference, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.write_concern import WriteConcern

from domains.talent_stream.index_requirements import (
    CONTACT_GOVERNOR_CANDIDATE_GUARDS_REQUIREMENT,
    CONTACT_GOVERNOR_RESERVATIONS_REQUIREMENT,
)
from domains.trust.contact_governor_models import (
    ContactGovernorPolicyV1,
    GovernorCompanyCoolingScope,
    GovernorFrequencyScope,
    GovernorReservationCommand,
    GovernorReservationOutcome,
    GovernorReservationResult,
    GovernorReservationState,
    require_governor_time,
)
from domains.trust.contact_governor_persistence import (
    CONTACT_GOVERNOR_CANDIDATE_GUARD_SCHEMA_VERSION,
    ContactGovernorCandidateGuard,
    ContactGovernorReservationRecord,
    guard_from_document,
    reservation_from_document,
    reservation_record_from_command,
    reservation_to_document,
)
from mongo_index_safety import verify_metadata


_B9_REQUIREMENTS = (
    CONTACT_GOVERNOR_RESERVATIONS_REQUIREMENT,
    CONTACT_GOVERNOR_CANDIDATE_GUARDS_REQUIREMENT,
)
_SIMPLE = {"locale": "simple"}
_UNAVAILABLE = "contact governor repository unavailable"
_NOT_READY = "contact governor storage is not ready"
_CONFLICT = "contact governor reservation conflict"


class ContactGovernorRepositoryError(RuntimeError):
    pass


class ContactGovernorReadinessError(ContactGovernorRepositoryError):
    pass


class ContactGovernorConflictError(ContactGovernorRepositoryError):
    pass


class ContactGovernorRepository:
    def __init__(self, db):
        self.db = db
        options = {
            "read_preference": ReadPreference.PRIMARY,
            "write_concern": WriteConcern(w="majority"),
        }
        self.reservations = db.contact_governor_reservations.with_options(**options)
        self.guards = db.contact_governor_candidate_guards.with_options(**options)

    async def readiness(self):
        """Verify exactly the two B9 A13 requirements; never mutate metadata."""
        names = {item.name for item in _B9_REQUIREMENTS}
        try:
            collections = {}
            cursor = await self.db.list_collections(filter={"name": {"$in": sorted(names)}})
            async for record in cursor:
                collections[record["name"]] = record
            indexes = {}
            for name in names:
                if collections.get(name, {}).get("type") == "collection":
                    indexes[name] = await self.db[name].index_information()
            report = verify_metadata(_B9_REQUIREMENTS, collections, indexes)
        except Exception:
            raise ContactGovernorReadinessError(
                "contact governor storage metadata unavailable"
            ) from None
        # B9 requires every declared access-path index. A13 models absent
        # non-unique indexes as warnings globally, but ledger writes are not
        # ready until this exact two-collection report is entirely green.
        if not report.ok or report.diagnostics:
            raise ContactGovernorReadinessError(_NOT_READY)
        return report

    async def reserve(self, command: GovernorReservationCommand) -> GovernorReservationResult:
        try:
            if type(command) is not GovernorReservationCommand:
                raise ValueError("invalid command type")
            record = reservation_record_from_command(command)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ContactGovernorRepositoryError(
                "contact governor reservation command invalid"
            ) from None
        await self.readiness()

        async def callback(session):
            return await self._reserve_in_transaction(command, record, session)

        try:
            async with await self.db.client.start_session() as session:
                return await session.with_transaction(
                    callback,
                    read_preference=ReadPreference.PRIMARY,
                    write_concern=WriteConcern(w="majority"),
                )
        except ContactGovernorRepositoryError:
            raise
        except DuplicateKeyError:
            return await self._translate_reserve_duplicate(command, record)
        except Exception:
            raise ContactGovernorRepositoryError(_UNAVAILABLE) from None

    async def _reserve_in_transaction(self, command, record, session):
        await self._serialize_candidate(record, command.evaluated_at, session)
        existing = await self._find_reservation(record.reservation_id, session=session)
        if existing is not None:
            return self._existing_reservation_result(command, record, existing)

        activity = await self._read_candidate_activity(record.candidate_id, session)
        outcome = self._apply_policy(command.policy, record, activity, command.evaluated_at)
        if outcome is not None:
            return GovernorReservationResult(outcome=outcome)
        await self.reservations.insert_one(
            reservation_to_document(record),
            session=session,
        )
        return GovernorReservationResult(
            outcome=GovernorReservationOutcome.RESERVED,
            reservation_id=record.reservation_id,
            reservation_expires_at=record.expires_at,
        )

    @staticmethod
    def _existing_reservation_result(command, attempted, existing):
        if existing.request_fingerprint != attempted.request_fingerprint:
            return GovernorReservationResult(
                outcome=GovernorReservationOutcome.IDEMPOTENCY_CONFLICT
            )
        if (
            existing.status
            in {GovernorReservationState.RESERVED, GovernorReservationState.CONSUMED}
            and existing.expires_at > command.evaluated_at
        ):
            return GovernorReservationResult(
                outcome=GovernorReservationOutcome.IDEMPOTENT_REPLAY,
                reservation_id=existing.reservation_id,
                reservation_expires_at=existing.expires_at,
            )
        return GovernorReservationResult(outcome=GovernorReservationOutcome.DUPLICATE)

    async def _translate_reserve_duplicate(self, command, attempted):
        """Translate an aborted transaction's deterministic identity collision."""
        try:
            existing = await self._find_reservation(attempted.reservation_id)
        except ContactGovernorRepositoryError:
            raise
        except Exception:
            raise ContactGovernorRepositoryError(_UNAVAILABLE) from None
        if existing is None:
            raise ContactGovernorConflictError(_CONFLICT)
        return self._existing_reservation_result(command, attempted, existing)

    async def _serialize_candidate(self, record, evaluated_at, session):
        existing = await self.guards.find_one(
            {"_id": record.candidate_id},
            collation=_SIMPLE,
            session=session,
        )
        if existing is not None:
            try:
                current_guard = guard_from_document(existing)
            except (ValueError, TypeError, KeyError, OverflowError):
                raise ContactGovernorRepositoryError(
                    "contact governor candidate guard is malformed"
                ) from None
            if current_guard.updated_at > evaluated_at:
                raise ContactGovernorRepositoryError(_UNAVAILABLE)
        document = await self.guards.find_one_and_update(
            {"_id": record.candidate_id},
            {
                "$setOnInsert": {
                    "schema_version": CONTACT_GOVERNOR_CANDIDATE_GUARD_SCHEMA_VERSION,
                },
                "$inc": {"revision": 1},
                "$set": {"updated_at": evaluated_at},
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
            collation=_SIMPLE,
            session=session,
        )
        try:
            guard = guard_from_document(document)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ContactGovernorRepositoryError(
                "contact governor candidate guard is malformed"
            ) from None
        if guard.candidate_id != record.candidate_id:
            raise ContactGovernorRepositoryError(
                "contact governor candidate guard is malformed"
            )

    async def _find_reservation(self, reservation_id, *, session=None):
        document = await self.reservations.find_one(
            {"_id": reservation_id},
            collation=_SIMPLE,
            session=session,
        )
        if document is None:
            return None
        try:
            return reservation_from_document(document)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ContactGovernorRepositoryError(
                "contact governor reservation is malformed"
            ) from None

    async def _read_candidate_activity(self, candidate_id, session):
        cursor = self.reservations.find(
            {"candidate_id": candidate_id},
            collation=_SIMPLE,
            session=session,
        )
        documents = await cursor.to_list(length=None)
        try:
            return tuple(reservation_from_document(document) for document in documents)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ContactGovernorRepositoryError(
                "contact governor reservation is malformed"
            ) from None

    @staticmethod
    def _counts_as_activity(record, evaluated_at):
        if record.status is GovernorReservationState.CONSUMED:
            return True
        return (
            record.status is GovernorReservationState.RESERVED
            and record.expires_at > evaluated_at
        )

    @classmethod
    def _activity_in_window(cls, record, evaluated_at, window):
        return (
            cls._counts_as_activity(record, evaluated_at)
            and evaluated_at - window <= record.activity_at <= evaluated_at
        )

    @staticmethod
    def _matches_frequency_scope(record, attempted, scope):
        if scope is GovernorFrequencyScope.CANDIDATE_GLOBAL:
            return True
        if scope is GovernorFrequencyScope.RECRUITER_CANDIDATE:
            return record.recruiter_user_id == attempted.recruiter_user_id
        if scope is GovernorFrequencyScope.REQUESTING_ORGANIZATION_CANDIDATE:
            return (
                record.requesting_organization_id
                == attempted.requesting_organization_id
            )
        if scope is GovernorFrequencyScope.HIRING_COMPANY_CANDIDATE:
            return record.hiring_company_id == attempted.hiring_company_id
        raise ValueError("unknown frequency scope")

    @classmethod
    def _apply_policy(
        cls,
        policy: ContactGovernorPolicyV1,
        attempted: ContactGovernorReservationRecord,
        activity: tuple[ContactGovernorReservationRecord, ...],
        evaluated_at,
    ):
        frequency = policy.frequency_cap_policy
        if frequency.enabled:
            for cap in frequency.caps:
                count = sum(
                    1
                    for record in activity
                    if cls._matches_frequency_scope(record, attempted, cap.scope)
                    and cls._activity_in_window(record, evaluated_at, cap.window)
                )
                if count >= cap.maximum_activity_count:
                    return GovernorReservationOutcome.FREQUENCY_CAP_REACHED

        duplicate = policy.duplicate_protection_policy
        if duplicate.enabled:
            if any(
                record.dedup_key == attempted.dedup_key
                and cls._activity_in_window(record, evaluated_at, duplicate.window)
                for record in activity
            ):
                return GovernorReservationOutcome.DUPLICATE

        cooling = policy.company_cooling_policy
        if cooling.enabled:
            if cooling.scope is GovernorCompanyCoolingScope.REQUESTING_ORGANIZATION_CANDIDATE:
                same_company = lambda record: (
                    record.requesting_organization_id
                    == attempted.requesting_organization_id
                )
            elif cooling.scope is GovernorCompanyCoolingScope.HIRING_COMPANY_CANDIDATE:
                same_company = lambda record: (
                    record.hiring_company_id == attempted.hiring_company_id
                )
            else:
                raise ValueError("unknown cooling scope")
            if any(
                same_company(record)
                and cls._counts_as_activity(record, evaluated_at)
                and evaluated_at - cooling.period < record.activity_at <= evaluated_at
                for record in activity
            ):
                return GovernorReservationOutcome.COMPANY_COOLING_ACTIVE

        active_limit = policy.active_reservation_limit_policy
        if active_limit.enabled:
            count = sum(
                1
                for record in activity
                if record.status is GovernorReservationState.RESERVED
                and record.expires_at > evaluated_at
            )
            if count >= active_limit.maximum_active_reservations:
                return GovernorReservationOutcome.ACTIVE_RESERVATION_LIMIT_REACHED
        return None

    async def consume(
        self,
        reservation_id: str,
        contact_request_id: str,
        *,
        evaluated_at: datetime,
        session=None,
    ) -> None:
        try:
            reservation_id = self._identifier(reservation_id)
            contact_request_id = self._identifier(contact_request_id)
            evaluated_at = require_governor_time(evaluated_at, "evaluated_at")
        except (ValueError, TypeError):
            raise ContactGovernorRepositoryError(
                "contact governor lifecycle command invalid"
            ) from None
        await self.readiness()
        try:
            if session is not None:
                await self._consume(reservation_id, contact_request_id, evaluated_at, session)
                return

            async def callback(owned_session):
                await self._consume(
                    reservation_id,
                    contact_request_id,
                    evaluated_at,
                    owned_session,
                )

            async with await self.db.client.start_session() as owned_session:
                await owned_session.with_transaction(
                    callback,
                    read_preference=ReadPreference.PRIMARY,
                    write_concern=WriteConcern(w="majority"),
                )
        except ContactGovernorRepositoryError:
            raise
        except DuplicateKeyError:
            raise ContactGovernorConflictError(_CONFLICT) from None
        except Exception:
            raise ContactGovernorRepositoryError(_UNAVAILABLE) from None

    async def _consume(self, reservation_id, contact_request_id, evaluated_at, session):
        current = await self._find_reservation(reservation_id, session=session)
        if current is None:
            raise ContactGovernorConflictError(_CONFLICT)
        if current.status is GovernorReservationState.CONSUMED:
            if current.contact_request_id == contact_request_id:
                return
            raise ContactGovernorConflictError(_CONFLICT)
        if current.status is GovernorReservationState.RELEASED:
            raise ContactGovernorConflictError(_CONFLICT)
        if evaluated_at >= current.expires_at:
            raise ContactGovernorConflictError(_CONFLICT)
        result = await self.reservations.update_one(
            {
                "_id": reservation_id,
                "status": GovernorReservationState.RESERVED.value,
                "contact_request_id": {"$exists": False},
            },
            {
                "$set": {
                    "status": GovernorReservationState.CONSUMED.value,
                    "contact_request_id": contact_request_id,
                }
            },
            collation=_SIMPLE,
            session=session,
        )
        if result.matched_count != 1:
            raise ContactGovernorConflictError(_CONFLICT)

    async def release(self, reservation_id: str, *, session=None) -> None:
        try:
            reservation_id = self._identifier(reservation_id)
        except (ValueError, TypeError):
            raise ContactGovernorRepositoryError(
                "contact governor lifecycle command invalid"
            ) from None
        await self.readiness()
        try:
            if session is not None:
                await self._release(reservation_id, session)
                return

            async def callback(owned_session):
                await self._release(reservation_id, owned_session)

            async with await self.db.client.start_session() as owned_session:
                await owned_session.with_transaction(
                    callback,
                    read_preference=ReadPreference.PRIMARY,
                    write_concern=WriteConcern(w="majority"),
                )
        except ContactGovernorRepositoryError:
            raise
        except Exception:
            raise ContactGovernorRepositoryError(_UNAVAILABLE) from None

    async def _release(self, reservation_id, session):
        current = await self._find_reservation(reservation_id, session=session)
        if current is None:
            raise ContactGovernorConflictError(_CONFLICT)
        if current.status is GovernorReservationState.RELEASED:
            return
        if current.status is GovernorReservationState.CONSUMED:
            raise ContactGovernorConflictError(_CONFLICT)
        result = await self.reservations.update_one(
            {"_id": reservation_id, "status": GovernorReservationState.RESERVED.value},
            {"$set": {"status": GovernorReservationState.RELEASED.value}},
            collation=_SIMPLE,
            session=session,
        )
        if result.matched_count != 1:
            raise ContactGovernorConflictError(_CONFLICT)

    @staticmethod
    def _identifier(value):
        if type(value) is not str or not value.strip():
            raise ValueError("identifier must be non-blank")
        return value
