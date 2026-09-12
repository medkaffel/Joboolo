"""Narrow Mongo repository for the authoritative TS-B1 aggregate."""
from datetime import datetime, timezone

from pymongo import ReadPreference, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.write_concern import WriteConcern

from domains.shared.ids import (
    HiringCompanyId,
    MandateId,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import SchemaVersion
from domains.talent_stream.contracts import (
    OpportunitySpecificationRef,
    RecruitingActorContext,
    RoleDNARef,
    StreamRequirementSnapshot,
)
from mongo_index_safety import verify_metadata
from .index_requirements import TALENT_STREAM_REQUIREMENT
from .stream_models import (
    TALENT_STREAM_SCHEMA_VERSION,
    StreamCommandHistoryEntry,
    StreamCommandKind,
    TalentStream,
    TalentStreamState,
    nonblank_identifier,
    positive_entity_version,
    utc_millisecond,
)


class TalentStreamRepositoryError(RuntimeError):
    pass


class TalentStreamReadinessError(TalentStreamRepositoryError):
    pass


class TalentStreamStoredDataError(TalentStreamRepositoryError):
    pass


class TalentStreamConflictError(TalentStreamRepositoryError):
    pass


def _exact_mapping(value, fields, name):
    if type(value) is not dict or set(value) != set(fields):
        raise ValueError(f"invalid {name} fields")
    return value


def _stored_utc(value, name):
    if type(value) is not datetime:
        raise ValueError(f"invalid {name}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return utc_millisecond(value, name)


def _history_to_document(entry):
    return {
        "command_id": entry.command_id,
        "command_fingerprint": entry.command_fingerprint,
        "command_kind": entry.command_kind.value,
        "from_state": None if entry.from_state is None else entry.from_state.value,
        "to_state": entry.to_state.value,
        "resulting_version": int(entry.resulting_version),
        "occurred_at": entry.occurred_at,
    }


def stream_to_document(stream):
    if type(stream) is not TalentStream:
        raise ValueError("invalid Talent Stream aggregate")
    actor = stream.recruiting_actor_context
    requirement = stream.requirement_snapshot
    return {
        "_id": str(stream.stream_id),
        "schema_version": str(stream.schema_version),
        "version": int(stream.version),
        "recruiting_actor_context": {
            "recruiter_user_id": str(actor.recruiter_user_id),
            "requesting_organization_id": str(actor.requesting_organization_id),
            "hiring_company_id": str(actor.hiring_company_id),
            "mandate_id": None if actor.mandate_id is None else str(actor.mandate_id),
        },
        "requirement_snapshot": {
            "role_dna": {
                "role_dna_id": str(requirement.role_dna.role_dna_id),
                "version": int(requirement.role_dna.version),
            },
            "opportunity_spec": {
                "opportunity_spec_id": str(requirement.opportunity_spec.opportunity_spec_id),
                "version": int(requirement.opportunity_spec.version),
            },
            "requirement_version": int(requirement.requirement_version),
            "captured_at": requirement.captured_at,
        },
        "state": stream.state.value,
        "created_at": stream.created_at,
        "updated_at": stream.updated_at,
        "history": [_history_to_document(entry) for entry in stream.history],
    }


def _stream_from_document(document):
    document = _exact_mapping(document, {
        "_id", "schema_version", "version", "recruiting_actor_context",
        "requirement_snapshot", "state", "created_at", "updated_at", "history",
    }, "Talent Stream")
    stream_id = nonblank_identifier(document["_id"], "stream_id")
    actor = _exact_mapping(document["recruiting_actor_context"], {
        "recruiter_user_id", "requesting_organization_id", "hiring_company_id", "mandate_id",
    }, "recruiting actor context")
    requirement = _exact_mapping(document["requirement_snapshot"], {
        "role_dna", "opportunity_spec", "requirement_version", "captured_at",
    }, "requirement snapshot")
    role = _exact_mapping(requirement["role_dna"], {
        "role_dna_id", "version",
    }, "Role DNA reference")
    opportunity = _exact_mapping(requirement["opportunity_spec"], {
        "opportunity_spec_id", "version",
    }, "Opportunity Specification reference")
    raw_history = document["history"]
    if type(raw_history) is not list:
        raise ValueError("invalid Stream history")
    history = []
    for raw in raw_history:
        raw = _exact_mapping(raw, {
            "command_id", "command_fingerprint", "command_kind", "from_state", "to_state",
            "resulting_version", "occurred_at",
        }, "Stream history entry")
        prior = raw["from_state"]
        history.append(StreamCommandHistoryEntry(
            command_id=raw["command_id"],
            command_fingerprint=raw["command_fingerprint"],
            command_kind=StreamCommandKind(raw["command_kind"]),
            from_state=None if prior is None else TalentStreamState(prior),
            to_state=TalentStreamState(raw["to_state"]),
            resulting_version=positive_entity_version(
                raw["resulting_version"], "history.resulting_version",
            ),
            occurred_at=_stored_utc(raw["occurred_at"], "history.occurred_at"),
        ))
    mandate = actor["mandate_id"]
    return TalentStream(
        stream_id=TalentStreamId(stream_id),
        schema_version=SchemaVersion(document["schema_version"]),
        version=positive_entity_version(document["version"], "version"),
        recruiting_actor_context=RecruitingActorContext(
            recruiter_user_id=RecruiterUserId(nonblank_identifier(
                actor["recruiter_user_id"], "recruiter_user_id",
            )),
            requesting_organization_id=OrganizationId(nonblank_identifier(
                actor["requesting_organization_id"], "requesting_organization_id",
            )),
            hiring_company_id=HiringCompanyId(nonblank_identifier(
                actor["hiring_company_id"], "hiring_company_id",
            )),
            mandate_id=None if mandate is None else MandateId(
                nonblank_identifier(mandate, "mandate_id")
            ),
        ),
        requirement_snapshot=StreamRequirementSnapshot(
            role_dna=RoleDNARef(
                role_dna_id=RoleDNAId(nonblank_identifier(role["role_dna_id"], "role_dna_id")),
                version=positive_entity_version(role["version"], "role_dna.version"),
            ),
            opportunity_spec=OpportunitySpecificationRef(
                opportunity_spec_id=OpportunitySpecId(nonblank_identifier(
                    opportunity["opportunity_spec_id"], "opportunity_spec_id",
                )),
                version=positive_entity_version(
                    opportunity["version"], "opportunity_spec.version",
                ),
            ),
            requirement_version=positive_entity_version(
                requirement["requirement_version"], "requirement_version",
            ),
            captured_at=_stored_utc(requirement["captured_at"], "requirement.captured_at"),
        ),
        state=TalentStreamState(document["state"]),
        created_at=_stored_utc(document["created_at"], "created_at"),
        updated_at=_stored_utc(document["updated_at"], "updated_at"),
        history=tuple(history),
    )


def stream_from_document(document):
    """Strictly rehydrate stored BSON without exposing malformed contents."""
    try:
        return _stream_from_document(document)
    except (KeyError, TypeError, ValueError, OverflowError):
        raise TalentStreamStoredDataError("invalid stored Talent Stream") from None


def _same_create(current, requested):
    existing = current.history[0]
    wanted = requested.history[0]
    return (
        current.stream_id == requested.stream_id
        and current.schema_version == requested.schema_version
        and current.recruiting_actor_context == requested.recruiting_actor_context
        and current.requirement_snapshot == requested.requirement_snapshot
        and existing.command_kind is StreamCommandKind.CREATE
        and existing.command_id == wanted.command_id
        and existing.command_fingerprint == wanted.command_fingerprint
    )


class TalentStreamRepository:
    def __init__(self, db):
        self.db = db
        self.collection = db[TALENT_STREAM_REQUIREMENT.name].with_options(
            read_preference=ReadPreference.PRIMARY,
            write_concern=WriteConcern(w="majority"),
        )

    async def readiness(self):
        try:
            collections = {}
            cursor = await self.db.list_collections(filter={"name": TALENT_STREAM_REQUIREMENT.name})
            async for record in cursor:
                collections[record["name"]] = record
            indexes = {}
            if collections.get(TALENT_STREAM_REQUIREMENT.name, {}).get("type") == "collection":
                indexes[TALENT_STREAM_REQUIREMENT.name] = await self.collection.index_information()
            report = verify_metadata((TALENT_STREAM_REQUIREMENT,), collections, indexes)
        except Exception:
            raise TalentStreamReadinessError("Talent Stream metadata unavailable") from None
        if not report.ok:
            raise TalentStreamReadinessError("Talent Stream storage is not ready")
        return report

    async def get(self, stream_id):
        stream_id = nonblank_identifier(stream_id, "stream_id")
        try:
            document = await self.collection.find_one(
                {"_id": stream_id}, collation={"locale": "simple"},
            )
        except PyMongoError:
            raise TalentStreamRepositoryError("Talent Stream read failed") from None
        return None if document is None else stream_from_document(document)

    async def create(self, stream):
        if type(stream) is not TalentStream or stream.version != 1 or len(stream.history) != 1:
            raise ValueError("repository create requires an initial Talent Stream")
        await self.readiness()
        try:
            await self.collection.insert_one(stream_to_document(stream))
            return stream
        except DuplicateKeyError:
            current = await self.get(str(stream.stream_id))
            if current is not None and _same_create(current, stream):
                return current
            raise TalentStreamConflictError("Talent Stream create conflict") from None
        except PyMongoError:
            raise TalentStreamRepositoryError("Talent Stream create failed") from None

    async def transition(self, current, entry):
        if type(current) is not TalentStream or type(entry) is not StreamCommandHistoryEntry:
            raise ValueError("invalid Talent Stream transition")
        candidate = TalentStream(
            stream_id=current.stream_id,
            schema_version=current.schema_version,
            version=entry.resulting_version,
            recruiting_actor_context=current.recruiting_actor_context,
            requirement_snapshot=current.requirement_snapshot,
            state=entry.to_state,
            created_at=current.created_at,
            updated_at=entry.occurred_at,
            history=current.history + (entry,),
        )
        await self.readiness()
        try:
            document = await self.collection.find_one_and_update(
                {
                    "_id": str(current.stream_id),
                    "schema_version": TALENT_STREAM_SCHEMA_VERSION,
                    "version": int(current.version),
                    "state": current.state.value,
                    "history.2": {"$exists": False},
                },
                {
                    "$set": {"state": candidate.state.value, "updated_at": candidate.updated_at},
                    "$inc": {"version": 1},
                    "$push": {"history": _history_to_document(entry)},
                },
                return_document=ReturnDocument.AFTER,
                collation={"locale": "simple"},
            )
        except PyMongoError:
            raise TalentStreamRepositoryError("Talent Stream transition failed") from None
        return None if document is None else stream_from_document(document)

