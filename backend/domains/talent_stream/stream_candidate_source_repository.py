"""TS-B7 STEP 3 read-only source repository.

Reads exactly the Opportunity Specification (B3 exact scope) and A11 Intent
event documents (B4/B5 sources). Never reads Applications, Discovery or
SavedJob documents here. No write API, no runtime index creation, no repair.
All stored-source deviations fail closed with the single fixed redacted
repository error message.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from pymongo.errors import PyMongoError

from domains.talent_stream.index_requirements import (
    TALENT_INTENT_EVENTS_REQUIREMENT,
    TS_B7_INTENT_JOB_EVENT_SCAN,
)
from domains.talent_stream.stream_models import (
    nonblank_identifier,
    utc_millisecond,
)
from mongo_index_safety import verify_metadata


class StreamCandidateSourceRepositoryError(RuntimeError):
    pass


class StreamCandidateSourceReadinessError(StreamCandidateSourceRepositoryError):
    pass


class StreamCandidateSourceStoredDataError(StreamCandidateSourceRepositoryError):
    pass


INTENT_EVENT_PAGE_LIMIT = 500

OPPORTUNITY_FIELDS = {
    "_id": 1,
    "opportunity_spec_id": 1,
    "version": 1,
    "provenance": 1,
    "source_job_id": 1,
    "source_ref": 1,
    "version_provenance": 1,
    "version_provenance_ref": 1,
}


@dataclass(frozen=True, slots=True, repr=False)
class OpportunitySpecificationSource:
    """Exact opportunity specification identity leading to the source Job."""

    opportunity_spec_id: str
    version: int
    source_job_id: str
    source_ref: str | None
    version_provenance_ref: str

    def __post_init__(self) -> None:
        nonblank_identifier(self.opportunity_spec_id, "opportunity_spec_id")
        if isinstance(self.version, bool) or type(self.version) is not int or self.version < 1:
            raise ValueError("opportunity spec version must be a positive integer")
        nonblank_identifier(self.source_job_id, "source_job_id")
        if self.source_ref is not None:
            nonblank_identifier(self.source_ref, "source_ref")
        nonblank_identifier(self.version_provenance_ref, "version_provenance_ref")


@dataclass(frozen=True, slots=True, repr=False)
class IntentEventCursor:
    """Internal A11 continuation position, strictly ordered by (occurred_at, _id)."""

    occurred_at: datetime
    event_id: str

    def __post_init__(self) -> None:
        nonblank_identifier(self.event_id, "event_id")
        utc_millisecond(self.occurred_at, "cursor.occurred_at")


def _opportunity_from_document(document, opportunity_spec_id, version):
    if type(document) is not dict or set(document) != set(OPPORTUNITY_FIELDS):
        raise ValueError("invalid stored opportunity specification")
    stored_id = nonblank_identifier(document["opportunity_spec_id"], "opportunity_spec_id")
    if (
        isinstance(document["version"], bool)
        or type(document["version"]) is not int
        or document["version"] < 1
    ):
        raise ValueError("invalid stored opportunity specification")
    source_job_id = nonblank_identifier(document["source_job_id"], "source_job_id")
    source_ref = None
    if document["source_ref"] is not None:
        source_ref = nonblank_identifier(document["source_ref"], "source_ref")
    version_ref = None
    if document["version_provenance_ref"] is not None:
        version_ref = nonblank_identifier(
            document["version_provenance_ref"], "version_provenance_ref"
        )
    if (
        stored_id != opportunity_spec_id
        or int(document["version"]) != version
        or document["_id"] != f"{opportunity_spec_id}:v{version}"
        or document["provenance"] != "internal_job"
        or document["version_provenance"] != "internal_job"
        or version_ref is None
        or (source_ref is not None and source_ref != version_ref)
    ):
        raise ValueError("invalid stored opportunity specification")
    return OpportunitySpecificationSource(
        opportunity_spec_id=opportunity_spec_id,
        version=version,
        source_job_id=source_job_id,
        source_ref=source_ref,
        version_provenance_ref=version_ref,
    )


class StreamCandidateSourceRepository:
    def __init__(self, db):
        self.db = db

    async def readiness_intent(self):
        """Require the A11 metadata with the B7 Intent scan as a blocking guard.

        The B7 scan is declared performance-only for A13, but the STEP 3 reader
        refuses to run a full scan without it. No repair is ever attempted.
        """
        name = TALENT_INTENT_EVENTS_REQUIREMENT.name
        indexes = tuple(
            replace(item, critical=True)
            if item.name == TS_B7_INTENT_JOB_EVENT_SCAN.name
            else item
            for item in TALENT_INTENT_EVENTS_REQUIREMENT.indexes
        )
        requirement = replace(TALENT_INTENT_EVENTS_REQUIREMENT, indexes=indexes)
        try:
            collections = {}
            cursor = await self.db.list_collections(filter={"name": name})
            async for record in cursor:
                collections[record["name"]] = record
            index_metadata = {}
            if collections.get(name, {}).get("type") == "collection":
                index_metadata[name] = await self.db[name].index_information()
            report = verify_metadata((requirement,), collections, index_metadata)
        except Exception:
            raise StreamCandidateSourceReadinessError("b7 intent event metadata unavailable") from None
        if not report.ok:
            raise StreamCandidateSourceReadinessError("b7 intent event storage is not ready")
        return report

    async def get_opportunity(self, opportunity_spec_id, version):
        opportunity_spec_id = nonblank_identifier(opportunity_spec_id, "opportunity_spec_id")
        if isinstance(version, bool) or type(version) is not int or version < 1:
            raise ValueError("opportunity spec version must be a positive integer")
        try:
            document = await self.db.opportunity_specs.find_one(
                {"opportunity_spec_id": opportunity_spec_id, "version": version},
                OPPORTUNITY_FIELDS,
            )
        except PyMongoError:
            raise StreamCandidateSourceRepositoryError("b7 opportunity read failed") from None
        if document is None:
            raise StreamCandidateSourceStoredDataError("invalid stored b7 opportunity spec")
        try:
            return _opportunity_from_document(document, opportunity_spec_id, version)
        except (KeyError, TypeError, ValueError, OverflowError):
            raise StreamCandidateSourceStoredDataError(
                "invalid stored b7 opportunity spec"
            ) from None

    def _stored_position(self, document):
        if type(document) is not dict:
            raise StreamCandidateSourceStoredDataError("invalid stored b7 intent event")
        if "occurred_at" not in document or "_id" not in document:
            raise StreamCandidateSourceStoredDataError("invalid stored b7 intent event")
        try:
            event_id = nonblank_identifier(document["_id"], "_id")
        except (KeyError, TypeError, ValueError):
            raise StreamCandidateSourceStoredDataError("invalid stored b7 intent event") from None
        occurred_at = document["occurred_at"]
        if type(occurred_at) is not datetime:
            raise StreamCandidateSourceStoredDataError("invalid stored b7 intent event")
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        try:
            occurred_at = occurred_at.astimezone(timezone.utc)
        except (OverflowError, TypeError, ValueError):
            raise StreamCandidateSourceStoredDataError("invalid stored b7 intent event") from None
        if occurred_at.microsecond % 1000:
            raise StreamCandidateSourceStoredDataError("invalid stored b7 intent event")
        return occurred_at, event_id

    async def list_intent_events(self, job_id, event_type, *, after_event=None,
                                 limit=INTENT_EVENT_PAGE_LIMIT):
        """Page the exact (job_id, event_type) window; full documents only."""
        job_id = nonblank_identifier(job_id, "job_id")
        event_type = nonblank_identifier(event_type, "event_type")
        if isinstance(limit, bool) or type(limit) is not int or not 1 <= limit <= INTENT_EVENT_PAGE_LIMIT:
            raise ValueError("b7 intent event limit must be a strict int in 1..500")
        if after_event is not None and type(after_event) is not IntentEventCursor:
            raise ValueError("invalid b7 intent event cursor")

        query = {"job_id": job_id, "event_type": event_type}
        if after_event is not None:
            query["$or"] = [
                {"occurred_at": {"$gt": after_event.occurred_at}},
                {
                    "occurred_at": after_event.occurred_at,
                    "_id": {"$gt": after_event.event_id},
                },
            ]
        try:
            documents = await (
                self.db.talent_intent_events.find(query)
                .sort([("occurred_at", 1), ("_id", 1)])
                .limit(limit + 1)
                .to_list(length=limit + 1)
            )
        except PyMongoError:
            raise StreamCandidateSourceRepositoryError("b7 intent event read failed") from None

        if after_event is not None and documents:
            first_position = self._stored_position(documents[0])
            if first_position <= (after_event.occurred_at, after_event.event_id):
                raise StreamCandidateSourceStoredDataError("invalid stored b7 intent event order")

        consumed = documents[:limit]
        events = tuple(consumed)
        for document in consumed:
            self._stored_position(document)
        if len(documents) <= limit:
            return events, None
        if not consumed:
            raise StreamCandidateSourceStoredDataError("invalid stored b7 intent event cursor")
        last_position = self._stored_position(consumed[-1])
        return events, IntentEventCursor(
            occurred_at=last_position[0], event_id=last_position[1],
        )