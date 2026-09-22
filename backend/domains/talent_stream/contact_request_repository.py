"""Strict B10 Contact Request persistence primitives.

The repository owns one collection, starts no transaction, creates no
metadata, publishes no outbox record and performs no implicit repair.
"""
from __future__ import annotations

import re

from pymongo import ReadPreference
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern

from domains.talent_stream.contact_request_models import ContactRequest
from domains.talent_stream.contact_request_persistence import (
    contact_request_from_document,
    contact_request_to_document,
)
from domains.talent_stream.index_requirements import (
    TALENT_STREAM_CONTACT_REQUESTS_REQUIREMENT,
)
from mongo_index_safety import verify_metadata


_SIMPLE = {"locale": "simple"}
_REQUEST_ID = re.compile(r"^ts-b10-request-v1-[0-9a-f]{64}$")
_UNAVAILABLE = "contact request repository unavailable"
_MALFORMED = "contact request record is malformed"
_NOT_READY = "contact request storage is not ready"
_CONFLICT = "contact request persistence conflict"
_TRANSACTION_REQUIRED = "active caller transaction required"


class ContactRequestRepositoryError(RuntimeError):
    pass


class ContactRequestReadinessError(ContactRequestRepositoryError):
    pass


class ContactRequestConflictError(ContactRequestRepositoryError):
    pass


class ContactRequestTransactionRequiredError(ContactRequestRepositoryError):
    pass


class ContactRequestRepository:
    def __init__(self, db):
        self.db = db
        self.collection = db.talent_stream_contact_requests.with_options(
            read_preference=ReadPreference.PRIMARY,
            write_concern=WriteConcern(w="majority"),
        )

    async def readiness(self):
        """Verify exact B10 A13 metadata without mutating it."""

        name = TALENT_STREAM_CONTACT_REQUESTS_REQUIREMENT.name
        try:
            collections = {}
            cursor = await self.db.list_collections(filter={"name": name})
            async for record in cursor:
                collections[record["name"]] = record
            indexes = {}
            if collections.get(name, {}).get("type") == "collection":
                indexes[name] = await self.db[name].index_information()
            report = verify_metadata(
                (TALENT_STREAM_CONTACT_REQUESTS_REQUIREMENT,),
                collections,
                indexes,
            )
        except Exception:
            raise ContactRequestReadinessError(
                "contact request storage metadata unavailable"
            ) from None
        if not report.ok or report.diagnostics:
            raise ContactRequestReadinessError(_NOT_READY)
        return report

    async def get(self, contact_request_id: str, *, session=None):
        """Read one exact strict aggregate, optionally in a caller session."""

        try:
            contact_request_id = self._identifier(contact_request_id)
        except (TypeError, ValueError):
            raise ContactRequestRepositoryError(
                "contact request identity invalid"
            ) from None
        await self.readiness()
        try:
            document = await self.collection.find_one(
                {"_id": contact_request_id},
                collation=_SIMPLE,
                session=session,
            )
            if document is None:
                return None
            try:
                return contact_request_from_document(document)
            except (ValueError, TypeError, KeyError, OverflowError):
                raise ContactRequestRepositoryError(_MALFORMED) from None
        except ContactRequestRepositoryError:
            raise
        except Exception:
            raise ContactRequestRepositoryError(_UNAVAILABLE) from None

    async def insert(self, request: ContactRequest, *, session) -> None:
        """Insert only in an active transaction owned by the B10.3 caller."""

        if session is None or getattr(session, "in_transaction", False) is not True:
            raise ContactRequestTransactionRequiredError(_TRANSACTION_REQUIRED)
        try:
            if type(request) is not ContactRequest:
                raise ValueError("invalid aggregate type")
            document = contact_request_to_document(request)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise ContactRequestRepositoryError(
                "contact request aggregate invalid"
            ) from None
        await self.readiness()
        try:
            await self.collection.insert_one(document, session=session)
        except DuplicateKeyError:
            raise ContactRequestConflictError(_CONFLICT) from None
        except Exception:
            raise ContactRequestRepositoryError(_UNAVAILABLE) from None

    @staticmethod
    def _identifier(value):
        if type(value) is not str or _REQUEST_ID.fullmatch(value) is None:
            raise ValueError("invalid contact request identifier")
        return value


__all__ = [
    "ContactRequestRepositoryError",
    "ContactRequestReadinessError",
    "ContactRequestConflictError",
    "ContactRequestTransactionRequiredError",
    "ContactRequestRepository",
]
