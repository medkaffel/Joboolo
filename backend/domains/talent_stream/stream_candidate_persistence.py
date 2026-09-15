"""Strict BSON persistence contracts for the B7 Stream Candidate read model.

Pure module: no Mongo I/O. A B7.1 StreamCandidate remains the canonical
in-memory contract; the BSON document schema is explicit, closed and immutable.
Sensitive identity, authorization, reveal, contact and CV data are structurally
impossible to serialize or accept. UTC-naive datetimes legitimately returned by
Mongo are normalized to UTC-aware only at this persistence boundary; genuinely
malformed dates are always rejected.
"""
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256

from bson.int64 import Int64

from domains.matching.opportunity_fit_models import HardEligibilityState, OpportunityFitState
from domains.shared.ids import OpportunitySpecId, RoleDNAId, TalentStreamId
from domains.talent_stream.stream_candidate_models import (
    ApplicationEvidence,
    DeclaredInterestEvidence,
    DiscoveryEvidence,
    OpportunityFitSummary,
    ProfessionalMatchSummary,
    SharedFavoriteEvidence,
    StreamCandidate,
)
from domains.talent_stream.stream_models import (
    nonblank_identifier,
    positive_entity_version,
    utc_millisecond,
)

TALENT_STREAM_CANDIDATE_SCHEMA_VERSION = "talent-stream-candidate-v1"
TALENT_STREAM_CANDIDATE_PROJECTION_STATE_SCHEMA_VERSION = (
    "talent-stream-candidate-projection-state-v1"
)
TALENT_STREAM_CANDIDATE_GENERATIONS_SCHEMA_VERSION = (
    "talent-stream-candidate-generation-v1"
)
TS_B7_CANDIDATE_PREFIX = "ts-b7-candidate-v1"
TS_B7_GENERATION_RECORD_PREFIX = "ts-b7-generation-record-v1"

CANDIDATE_REQUIRED = {
    "_id",
    "schema_version",
    "stream_id",
    "stream_version",
    "requirement_version",
    "generation_id",
    "candidate_id",
    "role_dna_id",
    "role_dna_version",
    "opportunity_spec_id",
    "opportunity_spec_version",
    "computed_at",
}
CANDIDATE_OPTIONAL = {
    "application_evidence",
    "declared_interest_evidence",
    "shared_favorite_evidence",
    "discovery_evidence",
    "professional_match_summary",
    "opportunity_fit_summary",
}

PROJECTION_STATE_FIELDS = {
    "_id",
    "schema_version",
    "stream_id",
    "state_version",
    "active_generation_id",
    "stream_version",
    "requirement_version",
    "role_dna_id",
    "role_dna_version",
    "opportunity_spec_id",
    "opportunity_spec_version",
    "candidate_count",
    "published_at",
}

GENERATION_RECORD_FIELDS = {
    "_id",
    "schema_version",
    "stream_id",
    "generation_id",
    "stream_version",
    "requirement_version",
    "role_dna_id",
    "role_dna_version",
    "opportunity_spec_id",
    "opportunity_spec_version",
    "state",
}


class GenerationState(Enum):
    """Closed lifecycle for one registered B7 generation.

    BUILDING records may accumulate candidate documents. SEALING is the
    persisted transitional lock recorded atomically with the promised
    candidate_count; it is strictly internal, refuses all staging and is only
    resumable by an exact seal retry that reproduces the same count. SEALED is
    permanent and immutable; a sealed generation is never reopened.
    """

    BUILDING = "building"
    SEALING = "sealing"
    SEALED = "sealed"

_APPLICATION_FIELDS = {"application_id", "status", "applied_at"}
_DECLARED_FIELDS = {"event_id", "occurred_at"}
_SHARED_FIELDS = {"event_id", "correlation_id", "occurred_at"}
_DISCOVERY_FIELDS = {"candidate_preferences_version", "updated_at"}
_PROFESSIONAL_MATCH_FIELDS = {
    "candidate_profile_version",
    "role_dna_version",
    "match_engine_version",
    "professional_match_score",
    "evidence_coverage",
    "computed_at",
}
_OPPORTUNITY_FIT_FIELDS = {
    "candidate_preferences_version",
    "opportunity_spec_version",
    "fit_engine_version",
    "hard_eligibility_state",
    "opportunity_fit_state",
    "evidence_coverage",
    "computed_at",
}


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")


def candidate_document_id(stream_id: str, generation_id: str, candidate_id: str) -> str:
    """Deterministic B7 candidate document identity; never normalizes IDs."""
    nonblank_identifier(stream_id, "stream_id")
    nonblank_identifier(generation_id, "generation_id")
    nonblank_identifier(candidate_id, "candidate_id")
    digest = sha256(
        _canonical_json([TS_B7_CANDIDATE_PREFIX, stream_id, generation_id, candidate_id])
    ).hexdigest()
    return f"{TS_B7_CANDIDATE_PREFIX}:sha256:{digest}"


def generation_record_document_id(stream_id: str, generation_id: str) -> str:
    """Deterministic B7 generation record identity; never normalizes IDs."""
    nonblank_identifier(stream_id, "stream_id")
    nonblank_identifier(generation_id, "generation_id")
    digest = sha256(
        _canonical_json(
            [TS_B7_GENERATION_RECORD_PREFIX, stream_id, generation_id]
        )
    ).hexdigest()
    return f"{TS_B7_GENERATION_RECORD_PREFIX}:sha256:{digest}"


def _shape(value, required, optional, field):
    if type(value) is not dict:
        raise ValueError(f"{field} must be a BSON object")
    if value.keys() - required - optional:
        raise ValueError(f"{field} has unknown fields")
    if not required <= value.keys():
        raise ValueError(f"{field} is missing required fields")


def _storage_datetime(value, field):
    if type(value) is not datetime:
        raise ValueError(f"{field} must be a datetime")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return utc_millisecond(value, field)


def _positive_int(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, Int64)) or value < 1:
        raise ValueError(f"{field} must be a positive int")
    return int(value)


def _nonnegative_int(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, Int64)) or value < 0:
        raise ValueError(f"{field} must be a non-negative int")
    return int(value)


def _score(value, field):
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError(f"{field} must be an int between 0 and 100")
    return value


def _safe_enum(enum, value, field):
    if type(value) is not str:
        raise ValueError(f"{field} must be a string")
    try:
        return enum(value)
    except ValueError:
        raise ValueError(f"unknown {field}") from None


def _application_to_document(evidence):
    if type(evidence) is not ApplicationEvidence:
        raise ValueError("invalid application evidence")
    return {
        "application_id": evidence.application_id,
        "status": evidence.status,
        "applied_at": utc_millisecond(evidence.applied_at, "applied_at"),
    }


def _declared_to_document(evidence):
    if type(evidence) is not DeclaredInterestEvidence:
        raise ValueError("invalid declared interest evidence")
    return {
        "event_id": evidence.event_id,
        "occurred_at": utc_millisecond(evidence.occurred_at, "occurred_at"),
    }


def _shared_to_document(evidence):
    if type(evidence) is not SharedFavoriteEvidence:
        raise ValueError("invalid shared favorite evidence")
    return {
        "event_id": evidence.event_id,
        "correlation_id": evidence.correlation_id,
        "occurred_at": utc_millisecond(evidence.occurred_at, "occurred_at"),
    }


def _discovery_to_document(evidence):
    if type(evidence) is not DiscoveryEvidence:
        raise ValueError("invalid discovery evidence")
    return {
        "candidate_preferences_version": int(evidence.candidate_preferences_version),
        "updated_at": utc_millisecond(evidence.updated_at, "updated_at"),
    }


def _professional_match_to_document(summary):
    if type(summary) is not ProfessionalMatchSummary:
        raise ValueError("invalid professional match summary")
    return {
        "candidate_profile_version": int(summary.candidate_profile_version),
        "role_dna_version": int(summary.role_dna_version),
        "match_engine_version": summary.match_engine_version,
        "professional_match_score": summary.professional_match_score,
        "evidence_coverage": summary.evidence_coverage,
        "computed_at": utc_millisecond(summary.computed_at, "computed_at"),
    }


def _opportunity_fit_to_document(summary):
    if type(summary) is not OpportunityFitSummary:
        raise ValueError("invalid opportunity fit summary")
    return {
        "candidate_preferences_version": int(summary.candidate_preferences_version),
        "opportunity_spec_version": int(summary.opportunity_spec_version),
        "fit_engine_version": summary.fit_engine_version,
        "hard_eligibility_state": summary.hard_eligibility_state.value,
        "opportunity_fit_state": summary.opportunity_fit_state.value,
        "evidence_coverage": summary.evidence_coverage,
        "computed_at": utc_millisecond(summary.computed_at, "computed_at"),
    }


def stream_candidate_to_document(candidate: StreamCandidate) -> dict:
    """Explicit canonical BSON document; never a blind dataclasses.asdict."""
    if type(candidate) is not StreamCandidate:
        raise ValueError("expected the exact B7 StreamCandidate contract")
    doc = {
        "_id": candidate_document_id(
            candidate.stream_id,
            candidate.generation_id,
            candidate.candidate_id,
        ),
        "schema_version": TALENT_STREAM_CANDIDATE_SCHEMA_VERSION,
        "stream_id": candidate.stream_id,
        "stream_version": int(candidate.stream_version),
        "requirement_version": int(candidate.requirement_version),
        "generation_id": candidate.generation_id,
        "candidate_id": candidate.candidate_id,
        "role_dna_id": candidate.role_dna_id,
        "role_dna_version": int(candidate.role_dna_version),
        "opportunity_spec_id": candidate.opportunity_spec_id,
        "opportunity_spec_version": int(candidate.opportunity_spec_version),
    }
    if candidate.computed_at is None:
        raise ValueError("computed_at is required")
    doc["computed_at"] = utc_millisecond(candidate.computed_at, "computed_at")
    if candidate.application_evidence is not None:
        doc["application_evidence"] = _application_to_document(candidate.application_evidence)
    if candidate.declared_interest_evidence is not None:
        doc["declared_interest_evidence"] = _declared_to_document(candidate.declared_interest_evidence)
    if candidate.shared_favorite_evidence is not None:
        doc["shared_favorite_evidence"] = _shared_to_document(candidate.shared_favorite_evidence)
    if candidate.discovery_evidence is not None:
        doc["discovery_evidence"] = _discovery_to_document(candidate.discovery_evidence)
    if candidate.professional_match_summary is not None:
        doc["professional_match_summary"] = _professional_match_to_document(
            candidate.professional_match_summary
        )
    if candidate.opportunity_fit_summary is not None:
        doc["opportunity_fit_summary"] = _opportunity_fit_to_document(
            candidate.opportunity_fit_summary
        )
    return doc


def _application_from_document(value):
    _shape(value, _APPLICATION_FIELDS, set(), "application_evidence")
    return ApplicationEvidence(
        application_id=nonblank_identifier(value["application_id"], "application_id"),
        status=nonblank_identifier(value["status"], "status"),
        applied_at=_storage_datetime(value["applied_at"], "applied_at"),
    )


def _declared_from_document(value):
    _shape(value, _DECLARED_FIELDS, set(), "declared_interest_evidence")
    return DeclaredInterestEvidence(
        event_id=nonblank_identifier(value["event_id"], "event_id"),
        occurred_at=_storage_datetime(value["occurred_at"], "occurred_at"),
    )


def _shared_from_document(value):
    _shape(value, _SHARED_FIELDS, set(), "shared_favorite_evidence")
    return SharedFavoriteEvidence(
        event_id=nonblank_identifier(value["event_id"], "event_id"),
        correlation_id=nonblank_identifier(value["correlation_id"], "correlation_id"),
        occurred_at=_storage_datetime(value["occurred_at"], "occurred_at"),
    )


def _discovery_from_document(value):
    _shape(value, _DISCOVERY_FIELDS, set(), "discovery_evidence")
    return DiscoveryEvidence(
        candidate_preferences_version=positive_entity_version(
            value["candidate_preferences_version"], "candidate_preferences_version"
        ),
        updated_at=_storage_datetime(value["updated_at"], "updated_at"),
    )


def _professional_match_from_document(value):
    _shape(value, _PROFESSIONAL_MATCH_FIELDS, set(), "professional_match_summary")
    return ProfessionalMatchSummary(
        candidate_profile_version=positive_entity_version(
            value["candidate_profile_version"], "candidate_profile_version"
        ),
        role_dna_version=positive_entity_version(value["role_dna_version"], "role_dna_version"),
        match_engine_version=nonblank_identifier(value["match_engine_version"], "match_engine_version"),
        professional_match_score=_score(value["professional_match_score"], "professional_match_score"),
        evidence_coverage=_score(value["evidence_coverage"], "evidence_coverage"),
        computed_at=_storage_datetime(value["computed_at"], "computed_at"),
    )


def _opportunity_fit_from_document(value):
    _shape(value, _OPPORTUNITY_FIT_FIELDS, set(), "opportunity_fit_summary")
    return OpportunityFitSummary(
        candidate_preferences_version=positive_entity_version(
            value["candidate_preferences_version"], "candidate_preferences_version"
        ),
        opportunity_spec_version=positive_entity_version(
            value["opportunity_spec_version"], "opportunity_spec_version"
        ),
        fit_engine_version=nonblank_identifier(value["fit_engine_version"], "fit_engine_version"),
        hard_eligibility_state=_safe_enum(
            HardEligibilityState, value["hard_eligibility_state"], "hard_eligibility_state"
        ),
        opportunity_fit_state=_safe_enum(
            OpportunityFitState, value["opportunity_fit_state"], "opportunity_fit_state"
        ),
        evidence_coverage=_score(value["evidence_coverage"], "evidence_coverage"),
        computed_at=_storage_datetime(value["computed_at"], "computed_at"),
    )


def stream_candidate_from_document(document: dict) -> StreamCandidate:
    """Strict de-serialization; every deviation from the closed schema fails."""
    _shape(document, CANDIDATE_REQUIRED, CANDIDATE_OPTIONAL, "stream candidate")
    if document["schema_version"] != TALENT_STREAM_CANDIDATE_SCHEMA_VERSION:
        raise ValueError("unsupported stream candidate schema version")
    stream_id = nonblank_identifier(document["stream_id"], "stream_id")
    generation_id = nonblank_identifier(document["generation_id"], "generation_id")
    candidate_id = nonblank_identifier(document["candidate_id"], "candidate_id")
    expected_id = candidate_document_id(stream_id, generation_id, candidate_id)
    if document["_id"] != expected_id:
        raise ValueError("deterministic stream candidate identity mismatch")
    kwargs = {
        "stream_id": stream_id,
        "stream_version": positive_entity_version(document["stream_version"], "stream_version"),
        "requirement_version": positive_entity_version(
            document["requirement_version"], "requirement_version"
        ),
        "generation_id": generation_id,
        "candidate_id": candidate_id,
        "role_dna_id": nonblank_identifier(document["role_dna_id"], "role_dna_id"),
        "role_dna_version": positive_entity_version(document["role_dna_version"], "role_dna_version"),
        "opportunity_spec_id": nonblank_identifier(
            document["opportunity_spec_id"], "opportunity_spec_id"
        ),
        "opportunity_spec_version": positive_entity_version(
            document["opportunity_spec_version"], "opportunity_spec_version"
        ),
        "computed_at": _storage_datetime(document["computed_at"], "computed_at"),
    }
    if "application_evidence" in document:
        kwargs["application_evidence"] = _application_from_document(document["application_evidence"])
    if "declared_interest_evidence" in document:
        kwargs["declared_interest_evidence"] = _declared_from_document(
            document["declared_interest_evidence"]
        )
    if "shared_favorite_evidence" in document:
        kwargs["shared_favorite_evidence"] = _shared_from_document(
            document["shared_favorite_evidence"]
        )
    if "discovery_evidence" in document:
        kwargs["discovery_evidence"] = _discovery_from_document(document["discovery_evidence"])
    if "professional_match_summary" in document:
        kwargs["professional_match_summary"] = _professional_match_from_document(
            document["professional_match_summary"]
        )
    if "opportunity_fit_summary" in document:
        kwargs["opportunity_fit_summary"] = _opportunity_fit_from_document(
            document["opportunity_fit_summary"]
        )
    return StreamCandidate(**kwargs)


@dataclass(frozen=True, slots=True, repr=False)
class ProjectionState:
    """Immutable B7 projection pointer; holds no candidate data."""

    stream_id: TalentStreamId
    state_version: int
    active_generation_id: str
    stream_version: int
    requirement_version: int
    role_dna_id: RoleDNAId
    role_dna_version: int
    opportunity_spec_id: OpportunitySpecId
    opportunity_spec_version: int
    candidate_count: int
    published_at: datetime
    schema_version: str = TALENT_STREAM_CANDIDATE_PROJECTION_STATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        nonblank_identifier(self.stream_id, "stream_id")
        object.__setattr__(self, "state_version", _positive_int(self.state_version, "state_version"))
        nonblank_identifier(self.active_generation_id, "active_generation_id")
        for field in ("stream_version", "requirement_version", "role_dna_version", "opportunity_spec_version"):
            object.__setattr__(self, field, _positive_int(getattr(self, field), field))
        nonblank_identifier(self.role_dna_id, "role_dna_id")
        nonblank_identifier(self.opportunity_spec_id, "opportunity_spec_id")
        object.__setattr__(
            self,
            "candidate_count",
            _nonnegative_int(self.candidate_count, "candidate_count"),
        )
        object.__setattr__(
            self,
            "published_at",
            utc_millisecond(self.published_at, "published_at"),
        )
        if (
            type(self.schema_version) is not str
            or self.schema_version != TALENT_STREAM_CANDIDATE_PROJECTION_STATE_SCHEMA_VERSION
        ):
            raise ValueError("unsupported projection state schema version")


def projection_state_to_document(state: ProjectionState) -> dict:
    if type(state) is not ProjectionState:
        raise ValueError("expected the exact B7 ProjectionState contract")
    return {
        "_id": state.stream_id,
        "schema_version": state.schema_version,
        "stream_id": state.stream_id,
        "state_version": int(state.state_version),
        "active_generation_id": state.active_generation_id,
        "stream_version": int(state.stream_version),
        "requirement_version": int(state.requirement_version),
        "role_dna_id": state.role_dna_id,
        "role_dna_version": int(state.role_dna_version),
        "opportunity_spec_id": state.opportunity_spec_id,
        "opportunity_spec_version": int(state.opportunity_spec_version),
        "candidate_count": int(state.candidate_count),
        "published_at": utc_millisecond(state.published_at, "published_at"),
    }


def projection_state_from_document(document: dict) -> ProjectionState:
    _shape(document, PROJECTION_STATE_FIELDS, set(), "projection state")
    stream_id = nonblank_identifier(document["stream_id"], "stream_id")
    if document["_id"] != stream_id:
        raise ValueError("projection state identity must equal stream_id")
    return ProjectionState(
        stream_id=stream_id,
        state_version=document["state_version"],
        active_generation_id=nonblank_identifier(
            document["active_generation_id"], "active_generation_id"
        ),
        stream_version=document["stream_version"],
        requirement_version=document["requirement_version"],
        role_dna_id=nonblank_identifier(document["role_dna_id"], "role_dna_id"),
        role_dna_version=document["role_dna_version"],
        opportunity_spec_id=nonblank_identifier(
            document["opportunity_spec_id"], "opportunity_spec_id"
        ),
        opportunity_spec_version=document["opportunity_spec_version"],
        candidate_count=document["candidate_count"],
        published_at=_storage_datetime(document["published_at"], "published_at"),
        schema_version=document["schema_version"],
    )


@dataclass(frozen=True, slots=True, repr=False)
class StreamCandidateGenerationRecord:
    """Immutable B7 generation lifecycle record; holds no candidate data.

    A BUILDING record carries no candidate_count; SEALING and SEALED records
    always carry the exact sealed count. The state is the sole write authority:
    candidate documents only ever accumulate during BUILDING, and a SEALED
    generation is permanently immutable.
    """

    stream_id: TalentStreamId
    generation_id: str
    stream_version: int
    requirement_version: int
    role_dna_id: RoleDNAId
    role_dna_version: int
    opportunity_spec_id: OpportunitySpecId
    opportunity_spec_version: int
    state: GenerationState
    candidate_count: int | None
    schema_version: str = TALENT_STREAM_CANDIDATE_GENERATIONS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        nonblank_identifier(self.stream_id, "stream_id")
        nonblank_identifier(self.generation_id, "generation_id")
        for field in ("stream_version", "requirement_version", "role_dna_version", "opportunity_spec_version"):
            object.__setattr__(self, field, _positive_int(getattr(self, field), field))
        nonblank_identifier(self.role_dna_id, "role_dna_id")
        nonblank_identifier(self.opportunity_spec_id, "opportunity_spec_id")
        if type(self.state) is not GenerationState:
            raise ValueError("invalid generation state")
        if self.state is GenerationState.BUILDING:
            if self.candidate_count is not None:
                raise ValueError("building generations must not carry a candidate_count")
        else:
            if self.candidate_count is None:
                raise ValueError("sealing generations require a candidate_count")
            object.__setattr__(
                self,
                "candidate_count",
                _nonnegative_int(self.candidate_count, "candidate_count"),
            )
        if (
            type(self.schema_version) is not str
            or self.schema_version != TALENT_STREAM_CANDIDATE_GENERATIONS_SCHEMA_VERSION
        ):
            raise ValueError("unsupported generation record schema version")


def generation_record_to_document(record: StreamCandidateGenerationRecord) -> dict:
    """Explicit canonical BSON document for one B7 generation lifecycle record."""
    if type(record) is not StreamCandidateGenerationRecord:
        raise ValueError(
            "expected the exact B7 StreamCandidateGenerationRecord contract"
        )
    document = {
        "_id": generation_record_document_id(
            record.stream_id, record.generation_id
        ),
        "schema_version": record.schema_version,
        "stream_id": record.stream_id,
        "generation_id": record.generation_id,
        "stream_version": int(record.stream_version),
        "requirement_version": int(record.requirement_version),
        "role_dna_id": record.role_dna_id,
        "role_dna_version": int(record.role_dna_version),
        "opportunity_spec_id": record.opportunity_spec_id,
        "opportunity_spec_version": int(record.opportunity_spec_version),
        "state": record.state.value,
    }
    if record.candidate_count is not None:
        document["candidate_count"] = int(record.candidate_count)
    return document


def generation_record_from_document(document: dict) -> StreamCandidateGenerationRecord:
    _shape(
        document, GENERATION_RECORD_FIELDS, {"candidate_count"}, "generation record"
    )
    if document["schema_version"] != TALENT_STREAM_CANDIDATE_GENERATIONS_SCHEMA_VERSION:
        raise ValueError("unsupported generation record schema version")
    stream_id = nonblank_identifier(document["stream_id"], "stream_id")
    generation_id = nonblank_identifier(document["generation_id"], "generation_id")
    expected_id = generation_record_document_id(stream_id, generation_id)
    if document["_id"] != expected_id:
        raise ValueError("deterministic generation record identity mismatch")
    state = _safe_enum(GenerationState, document["state"], "generation state")
    kwargs = {
        "stream_id": stream_id,
        "generation_id": generation_id,
        "stream_version": document["stream_version"],
        "requirement_version": document["requirement_version"],
        "role_dna_id": nonblank_identifier(document["role_dna_id"], "role_dna_id"),
        "role_dna_version": document["role_dna_version"],
        "opportunity_spec_id": nonblank_identifier(
            document["opportunity_spec_id"], "opportunity_spec_id"
        ),
        "opportunity_spec_version": document["opportunity_spec_version"],
        "state": state,
        "candidate_count": None,
        "schema_version": document["schema_version"],
    }
    if "candidate_count" in document:
        if state is GenerationState.BUILDING:
            raise ValueError(
                "generation record candidate_count is forbidden while building"
            )
        kwargs["candidate_count"] = document["candidate_count"]
    elif state is not GenerationState.BUILDING:
        raise ValueError("generation record candidate_count is required once sealing")
    return StreamCandidateGenerationRecord(**kwargs)