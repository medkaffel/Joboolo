"""B7.2 G0: hermetic persistence contracts — serialization and ProjectionState."""
import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from hashlib import sha256

import pytest

from domains.matching.opportunity_fit_models import HardEligibilityState, OpportunityFitState
from domains.shared.versioning import EntityVersion
from domains.talent_stream.stream_candidate_models import (
    ApplicationEvidence,
    DeclaredInterestEvidence,
    DiscoveryEvidence,
    OpportunityFitSummary,
    ProfessionalMatchSummary,
    SharedFavoriteEvidence,
    StreamCandidate,
)
from domains.talent_stream.stream_candidate_persistence import (
    TALENT_STREAM_CANDIDATE_PROJECTION_STATE_SCHEMA_VERSION,
    TALENT_STREAM_CANDIDATE_SCHEMA_VERSION,
    TS_B7_CANDIDATE_PREFIX,
    ProjectionState,
    candidate_document_id,
    projection_state_from_document,
    projection_state_to_document,
    stream_candidate_from_document,
    stream_candidate_to_document,
)
from domains.talent_stream.index_requirements import (
    TALENT_INTENT_EVENTS_REQUIREMENT,
    TS_B7_INTENT_JOB_EVENT_SCAN,
)

SENSITIVE = {
    "name", "first_name", "last_name", "email", "phone", "cv", "document",
    "current_employer", "permission", "grant", "trust", "contact_governor",
    "reveal", "recruiter_notes", "cover_letter", "raw_saved_job",
    "raw_candidate_profile", "raw_candidate_preferences", "source_company",
    "source_campaign", "talent_score",
}


def _utc(ms=0):
    return datetime(2026, 1, 1, 12, 0, 0, ms * 1000, tzinfo=timezone.utc)


def _candidate(**overrides):
    values = dict(
        stream_id="stream-123",
        stream_version=3,
        requirement_version=2,
        generation_id="generation-abc",
        candidate_id="candidate-1",
        role_dna_id="role-dna-1",
        role_dna_version=4,
        opportunity_spec_id="spec-1",
        opportunity_spec_version=2,
        application_evidence=ApplicationEvidence("app-1", "active", _utc(1)),
        declared_interest_evidence=DeclaredInterestEvidence("declared-1", _utc(2)),
        shared_favorite_evidence=SharedFavoriteEvidence("shared-1", "corr-1", _utc(3)),
        discovery_evidence=DiscoveryEvidence(5, _utc(4)),
        professional_match_summary=ProfessionalMatchSummary(
            1, 4, "match-engine-v1", 80, 70, _utc(5)
        ),
        opportunity_fit_summary=OpportunityFitSummary(
            5, 2, "fit-engine-v1",
            HardEligibilityState.ELIGIBLE, OpportunityFitState.COMPATIBLE, 75, _utc(6),
        ),
        computed_at=_utc(7),
    )
    values.update(overrides)
    return StreamCandidate(**values)


def _state(**overrides):
    values = dict(
        stream_id="stream-123",
        state_version=1,
        active_generation_id="generation-abc",
        stream_version=3,
        requirement_version=2,
        role_dna_id="role-dna-1",
        role_dna_version=4,
        opportunity_spec_id="spec-1",
        opportunity_spec_version=2,
        candidate_count=7,
        published_at=_utc(9),
        schema_version=TALENT_STREAM_CANDIDATE_PROJECTION_STATE_SCHEMA_VERSION,
    )
    values.update(overrides)
    return ProjectionState(**values)


def test_stream_candidate_round_trip_all_sources():
    candidate = _candidate()
    assert stream_candidate_from_document(stream_candidate_to_document(candidate)) == candidate


@pytest.mark.parametrize("source,name", [
    ("application_evidence", "application"),
    ("declared_interest_evidence", "declared_interest"),
    ("shared_favorite_evidence", "shared_favorite"),
    ("discovery_evidence", "discovery"),
])
def test_stream_candidate_round_trip_single_source_only(source, name):
    kept = _candidate()
    candidate = _candidate(**{
        key: (getattr(kept, key) if key == source else None)
        for key in ("application_evidence", "declared_interest_evidence",
                    "shared_favorite_evidence", "discovery_evidence")
    }, professional_match_summary=None, opportunity_fit_summary=None)
    assert stream_candidate_from_document(stream_candidate_to_document(candidate)) == candidate


def test_stream_candidate_round_trip_multi_source_no_summaries():
    candidate = _candidate(
        professional_match_summary=None, opportunity_fit_summary=None
    )
    assert stream_candidate_from_document(stream_candidate_to_document(candidate)) == candidate


def test_stream_candidate_round_trip_a6_enums_and_versions():
    candidate = _candidate()
    document = stream_candidate_to_document(candidate)
    assert document["opportunity_fit_summary"]["hard_eligibility_state"] == "eligible"
    assert document["opportunity_fit_summary"]["opportunity_fit_state"] == "compatible"
    restored = stream_candidate_from_document(document)
    assert restored.opportunity_fit_summary.hard_eligibility_state is HardEligibilityState.ELIGIBLE
    assert restored.opportunity_fit_summary.opportunity_fit_state is OpportunityFitState.COMPATIBLE
    assert restored.stream_version == EntityVersion(3)
    assert restored.discovery_evidence.candidate_preferences_version == EntityVersion(5)


@pytest.mark.parametrize("summary_override", [
    dict(professional_match_score=0, evidence_coverage=100),
    dict(professional_match_score=100, evidence_coverage=0),
])
def test_stream_candidate_round_trip_score_boundaries(summary_override):
    candidate = _candidate(professional_match_summary=ProfessionalMatchSummary(
        1, 4, "match-engine-v1",
        summary_override["professional_match_score"],
        summary_override["evidence_coverage"],
        _utc(5),
    ))
    assert stream_candidate_from_document(stream_candidate_to_document(candidate)) == candidate


def test_candidate_document_id_is_deterministic_prefixed_and_bounded():
    payload = json.dumps(
        [TS_B7_CANDIDATE_PREFIX, "stream-123", "generation-abc", "candidate-1"],
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected = f"{TS_B7_CANDIDATE_PREFIX}:sha256:{sha256(payload).hexdigest()}"
    assert candidate_document_id("stream-123", "generation-abc", "candidate-1") == expected
    assert candidate_document_id("stream-123", "generation-abc", "candidate-2") != expected
    digest = expected.split(":sha256:")[1]
    assert len(digest) == 64 and all(character in "0123456789abcdef" for character in digest)


def test_stream_candidate_round_trip_naive_utc_at_persistence_boundary():
    candidate = _candidate()
    document = stream_candidate_to_document(candidate)
    document["computed_at"] = document["computed_at"].replace(tzinfo=None)
    for field in ("applied_at", "occurred_at", "updated_at"):
        nested = document.get("application_evidence", {}).get(field, None)
        if nested is not None:
            document["application_evidence"][field] = nested.replace(tzinfo=None)
    assert stream_candidate_from_document(document) == candidate


def test_stream_candidate_document_strict_shape_accepts_required_exact_keys():
    document = stream_candidate_to_document(_candidate())
    assert document["schema_version"] == TALENT_STREAM_CANDIDATE_SCHEMA_VERSION
    assert stream_candidate_from_document(document) == _candidate()


def test_stream_candidate_document_has_no_sensitive_fields():
    document = stream_candidate_to_document(_candidate())

    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                assert key not in SENSITIVE
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)


@pytest.mark.parametrize("extra", ["email", "name", "permission", "talent_score", "grant_id"])
def test_stream_candidate_rejects_unknown_or_sensitive_document_field(extra):
    document = stream_candidate_to_document(_candidate())
    document[extra] = "sensitive-value"
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)


@pytest.mark.parametrize("missing", [
    "_id", "schema_version", "stream_id", "stream_version", "requirement_version",
    "generation_id", "candidate_id", "role_dna_id", "role_dna_version",
    "opportunity_spec_id", "opportunity_spec_version", "computed_at",
])
def test_stream_candidate_rejects_missing_required_field(missing):
    document = stream_candidate_to_document(_candidate())
    del document[missing]
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)


def test_stream_candidate_rejects_unknown_schema_version():
    document = stream_candidate_to_document(_candidate())
    document["schema_version"] = "talent-stream-candidate-v9"
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)


def test_stream_candidate_rejects_wrong_deterministic_id():
    document = stream_candidate_to_document(_candidate())
    document["_id"] = f"{TS_B7_CANDIDATE_PREFIX}:sha256:" + "0" * 64
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)


def test_stream_candidate_rejects_malformed_timestamp():
    document = stream_candidate_to_document(_candidate())
    document["computed_at"] = "2026-01-01T12:00:00Z"
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)


def test_stream_candidate_rejects_sub_millisecond_timestamp():
    document = stream_candidate_to_document(_candidate())
    document["computed_at"] = document["computed_at"].replace(microsecond=1500)
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)


def test_stream_candidate_rejects_bool_where_int_expected():
    document = stream_candidate_to_document(_candidate())
    document["stream_version"] = True
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)
    document = stream_candidate_to_document(_candidate())
    document["professional_match_summary"]["professional_match_score"] = True
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)
    document = stream_candidate_to_document(_candidate())
    document["opportunity_fit_summary"]["evidence_coverage"] = True
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)


def test_stream_candidate_rejects_unknown_a6_enum():
    document = stream_candidate_to_document(_candidate())
    document["opportunity_fit_summary"]["hard_eligibility_state"] = "sometimes"
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)
    document = stream_candidate_to_document(_candidate())
    document["opportunity_fit_summary"]["opportunity_fit_state"] = "maybe"
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)


def test_stream_candidate_rejects_unknown_nested_field():
    document = stream_candidate_to_document(_candidate())
    document["application_evidence"]["recruiter_notes"] = "notes"
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)


def test_stream_candidate_rejects_incoherent_no_source_document():
    document = stream_candidate_to_document(_candidate())
    for key in (
        "application_evidence",
        "declared_interest_evidence",
        "shared_favorite_evidence",
        "discovery_evidence",
    ):
        document.pop(key, None)
    with pytest.raises(ValueError):
        stream_candidate_from_document(document)


def test_projection_state_round_trip():
    state = _state()
    document = projection_state_to_document(state)
    assert document["_id"] == "stream-123"
    assert projection_state_from_document(document) == state


def test_projection_state_is_immutable():
    state = _state()
    with pytest.raises(FrozenInstanceError):
        state.stream_id = "mutated"
    with pytest.raises(FrozenInstanceError):
        state.candidate_count = 1


def test_projection_state_rejects_bool_state_version():
    with pytest.raises(ValueError):
        _state(state_version=True)


def test_projection_state_rejects_bool_candidate_count():
    with pytest.raises(ValueError):
        _state(candidate_count=True)


def test_projection_state_rejects_negative_candidate_count():
    with pytest.raises(ValueError):
        _state(candidate_count=-1)


def test_projection_state_accepts_zero_candidate_count():
    assert _state(candidate_count=0).candidate_count == 0


def test_projection_state_rejects_id_not_equal_stream():
    document = projection_state_to_document(_state())
    document["_id"] = "another-stream"
    with pytest.raises(ValueError):
        projection_state_from_document(document)


def test_projection_state_rejects_unknown_schema():
    with pytest.raises(ValueError):
        _state(schema_version="projection-state-v9")
    document = projection_state_to_document(_state())
    document["schema_version"] = "projection-state-v9"
    with pytest.raises(ValueError):
        projection_state_from_document(document)


def test_projection_state_rejects_malformed_timestamp():
    document = projection_state_to_document(_state())
    document["published_at"] = "not-a-date"
    with pytest.raises(ValueError):
        projection_state_from_document(document)


def test_projection_state_round_trip_naive_utc_at_persistence_boundary():
    document = projection_state_to_document(_state())
    document["published_at"] = document["published_at"].replace(tzinfo=None)
    assert projection_state_from_document(document) == _state()


def test_projection_state_rejects_missing_and_unknown_fields():
    document = projection_state_to_document(_state())
    del document["candidate_count"]
    with pytest.raises(ValueError):
        projection_state_from_document(document)
    document = projection_state_to_document(_state())
    document["grant_id"] = "not-allowed"
    with pytest.raises(ValueError):
        projection_state_from_document(document)


def test_projection_state_rejects_bool_versions():
    with pytest.raises(ValueError):
        _state(stream_version=True)
    with pytest.raises(ValueError):
        _state(requirement_version=True)
    with pytest.raises(ValueError):
        _state(role_dna_version=True)
    with pytest.raises(ValueError):
        _state(opportunity_spec_version=True)


def test_b7_intent_job_event_scan_is_declared_for_step_three_reader():
    a11 = TALENT_INTENT_EVENTS_REQUIREMENT
    assert a11.name == "talent_intent_events"
    assert a11.simple_collation and a11.forbid_extra_indexes
    assert [index.name for index in a11.indexes] == [
        "ts_a11_idempotency_key_unique", "ts_b7_intent_job_event_scan",
    ]
    scan = TS_B7_INTENT_JOB_EVENT_SCAN
    assert scan.name == "ts_b7_intent_job_event_scan"
    assert scan.keys == (
        ("job_id", 1), ("event_type", 1), ("occurred_at", 1), ("_id", 1),
    )
    assert scan.unique is False and scan.critical is False
    assert scan.partial_filter is None
    assert not scan.sparse and not scan.hidden and scan.expire_after_seconds is None
    assert scan.collation is None