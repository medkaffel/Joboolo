"""TS-B10.1 hermetic contracts and pure contact-request helpers."""
import ast
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
import inspect
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from async_outbox.models import JobEnvelope, JobReference, RetryPolicy
from domains.shared.ids import (
    CandidateId,
    HiringCompanyId,
    IdempotencyKey,
    MandateId,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.talent_stream.anonymous_talent_adapter import (
    derive_anonymous_talent_card_ref,
)
from domains.talent_stream.contact_request_models import (
    CONTACT_REQUEST_AGGREGATE_VERSION,
    CONTACT_REQUEST_HANDOFF_JOB_TYPE,
    CONTACT_REQUEST_HANDOFF_PAYLOAD_SCHEMA_VERSION,
    CONTACT_REQUEST_HANDOFF_REFERENCE_TYPE,
    CONTACT_REQUEST_SCHEMA_VERSION,
    ContactRequest,
    ContactRequestCreateOutcome,
    ContactRequestState,
    CreateContactRequestCommand,
    CreateContactRequestResult,
    build_contact_request_handoff_envelope,
    create_contact_request,
    derive_contact_request_fingerprint,
    derive_contact_request_handoff_job_id,
    derive_contact_request_id,
    validate_governor_reservation_binding,
    verify_anonymous_card_lineage,
)
from domains.talent_stream.contracts import RecruitingActorContext
from domains.trust.contact_governor_models import (
    ContactGovernorRequest,
    GovernorReservationState,
    derive_request_fingerprint as derive_governor_request_fingerprint,
    derive_reservation_id as derive_governor_reservation_id,
)


NOW = datetime(2026, 9, 22, 12, 0, 0, 123000, tzinfo=timezone.utc)
CARD_KEY = b"b10-card-lineage-test-key-32-bytes-minimum"
SOURCE = (
    Path(__file__).resolve().parents[1]
    / "domains"
    / "talent_stream"
    / "contact_request_models.py"
)


def actor(
    *,
    recruiter="recruiter-1",
    requesting="organization-1",
    hiring="company-1",
    mandate="mandate-1",
):
    return RecruitingActorContext(
        recruiter_user_id=RecruiterUserId(recruiter),
        requesting_organization_id=OrganizationId(requesting),
        hiring_company_id=HiringCompanyId(hiring),
        mandate_id=None if mandate is None else MandateId(mandate),
    )


def governor_request(**changes):
    values = {
        "idempotency_key": IdempotencyKey("shared-key-1"),
        "candidate_id": CandidateId("candidate-sensitive-1"),
        "stream_id": TalentStreamId("stream-sensitive-1"),
        "generation_id": "generation-sensitive-1",
        "projection_state_version": 3,
        "stream_version": 4,
        "requirement_version": 5,
        "role_dna_id": RoleDNAId("role-sensitive-1"),
        "role_dna_version": 6,
        "opportunity_spec_id": OpportunitySpecId("opportunity-sensitive-1"),
        "opportunity_spec_version": 7,
        "recruiting_actor": actor(),
    }
    values.update(changes)
    return ContactGovernorRequest(**values)


def binding(request=None, **changes):
    request = request or governor_request()
    values = {
        "reservation_id": derive_governor_reservation_id(request),
        "request_fingerprint": derive_governor_request_fingerprint(request),
        "idempotency_key": str(request.idempotency_key),
        "candidate_id": str(request.candidate_id),
        "stream_id": str(request.stream_id),
        "generation_id": request.generation_id,
        "projection_state_version": request.projection_state_version,
        "stream_version": request.stream_version,
        "requirement_version": request.requirement_version,
        "role_dna_id": str(request.role_dna_id),
        "role_dna_version": request.role_dna_version,
        "opportunity_spec_id": str(request.opportunity_spec_id),
        "opportunity_spec_version": request.opportunity_spec_version,
        "recruiter_user_id": str(request.recruiting_actor.recruiter_user_id),
        "requesting_organization_id": str(
            request.recruiting_actor.requesting_organization_id
        ),
        "hiring_company_id": str(request.recruiting_actor.hiring_company_id),
        "mandate_id": (
            None
            if request.recruiting_actor.mandate_id is None
            else str(request.recruiting_actor.mandate_id)
        ),
        "policy_version": "contact-governor-v1-test",
        "activity_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
        "status": GovernorReservationState.RESERVED,
        "contact_request_id": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


def command(reservation=None, **changes):
    reservation = reservation or binding()
    values = {
        "idempotency_key": IdempotencyKey(reservation.idempotency_key),
        "reservation_id": reservation.reservation_id,
        "governor_request_fingerprint": reservation.request_fingerprint,
        "anonymous_card_ref": derive_anonymous_talent_card_ref(
            key=CARD_KEY,
            stream_id=reservation.stream_id,
            generation_id=reservation.generation_id,
            candidate_id=reservation.candidate_id,
        ),
        "recruiting_actor": actor(
            recruiter=reservation.recruiter_user_id,
            requesting=reservation.requesting_organization_id,
            hiring=reservation.hiring_company_id,
            mandate=reservation.mandate_id,
        ),
    }
    values.update(changes)
    return CreateContactRequestCommand(**values)


def contact_request(*, created_at=NOW + timedelta(seconds=1), reservation=None):
    reservation = reservation or binding()
    return create_contact_request(
        command(reservation),
        reservation,
        card_ref_key=CARD_KEY,
        created_at=created_at,
    )


class TestCommandAndIdentity:
    def test_command_has_only_caller_fields_and_no_policy_state_or_time(self):
        assert [item.name for item in fields(CreateContactRequestCommand)] == [
            "idempotency_key",
            "reservation_id",
            "governor_request_fingerprint",
            "anonymous_card_ref",
            "recruiting_actor",
        ]
        signature = inspect.signature(CreateContactRequestCommand)
        assert all(
            parameter.default is inspect.Parameter.empty
            for parameter in signature.parameters.values()
        )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("idempotency_key", ""),
            ("reservation_id", "reservation-1"),
            ("reservation_id", "ts-b9-reservation-v1:" + "A" * 64),
            ("governor_request_fingerprint", "fingerprint-1"),
            ("anonymous_card_ref", "candidate-sensitive-1"),
            ("anonymous_card_ref", "ts-b8-card-v1:" + "g" * 64),
            ("recruiting_actor", None),
            ("recruiting_actor", actor(recruiter="")),
            ("recruiting_actor", actor(requesting=" ")),
            ("recruiting_actor", actor(hiring="")),
            ("recruiting_actor", actor(mandate="")),
        ],
    )
    def test_command_validation_is_strict(self, field, value):
        with pytest.raises(ValueError):
            command(**{field: value})

    def test_identity_is_deterministic_and_a14_opaque_compatible(self):
        value = derive_contact_request_id(command())
        assert value == derive_contact_request_id(command())
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value)
        assert ":" not in value

    @pytest.mark.parametrize("field", ["recruiter", "requesting"])
    def test_minimum_actor_scope_changes_request_identity(self, field):
        original = command()
        changed_actor = actor(**{field: f"different-{field}"})
        changed = replace(original, recruiting_actor=changed_actor)
        assert derive_contact_request_id(changed) != derive_contact_request_id(original)

    @pytest.mark.parametrize("field", ["hiring", "mandate"])
    def test_full_actor_is_fingerprinted_even_outside_minimum_identity_scope(self, field):
        original = command()
        changed_actor = actor(**{field: f"different-{field}"})
        changed = replace(original, recruiting_actor=changed_actor)
        assert derive_contact_request_id(changed) == derive_contact_request_id(original)
        assert derive_contact_request_fingerprint(changed) != (
            derive_contact_request_fingerprint(original)
        )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("idempotency_key", IdempotencyKey("different-key")),
            ("reservation_id", "ts-b9-reservation-v1:" + "1" * 64),
            (
                "governor_request_fingerprint",
                "ts-b9-request-v1:" + "2" * 64,
            ),
            ("anonymous_card_ref", "ts-b8-card-v1:" + "3" * 64),
        ],
    )
    def test_every_material_command_field_changes_fingerprint(self, field, value):
        original = command()
        changed = replace(original, **{field: value})
        assert derive_contact_request_fingerprint(changed) != (
            derive_contact_request_fingerprint(original)
        )

    def test_identity_and_fingerprint_have_no_clock_input(self):
        signature = inspect.signature(derive_contact_request_fingerprint)
        assert tuple(signature.parameters) == ("command",)
        assert derive_contact_request_fingerprint(command()) == (
            derive_contact_request_fingerprint(command())
        )

    def test_contracts_are_frozen_and_repr_redacted(self):
        value = command()
        with pytest.raises(FrozenInstanceError):
            value.reservation_id = "changed"
        rendered = repr(value)
        assert all(
            secret not in rendered
            for secret in (
                value.reservation_id,
                value.anonymous_card_ref,
                "recruiter-1",
                "organization-1",
                "company-1",
            )
        )


class TestExactGovernorAndCardBinding:
    def test_valid_binding_reconstructs_exact_governor_request(self):
        reservation = binding()
        result = validate_governor_reservation_binding(
            command(reservation), reservation
        )
        assert result == governor_request()

    @pytest.mark.parametrize(
        "field,value",
        [
            ("candidate_id", "different-candidate"),
            ("stream_id", "different-stream"),
            ("generation_id", "different-generation"),
            ("projection_state_version", 99),
            ("stream_version", 99),
            ("requirement_version", 99),
            ("role_dna_id", "different-role"),
            ("role_dna_version", 99),
            ("opportunity_spec_id", "different-opportunity"),
            ("opportunity_spec_version", 99),
            ("recruiter_user_id", "different-recruiter"),
            ("requesting_organization_id", "different-organization"),
            ("hiring_company_id", "different-company"),
            ("mandate_id", "different-mandate"),
        ],
    )
    def test_every_governor_subject_field_is_bound_by_b9_fingerprint(
        self, field, value
    ):
        reservation = binding(**{field: value})
        with pytest.raises(ValueError):
            validate_governor_reservation_binding(command(), reservation)

    def test_b10_must_reuse_exact_b9_idempotency_key(self):
        with pytest.raises(ValueError, match="reuse the governor idempotency key"):
            validate_governor_reservation_binding(
                command(idempotency_key=IdempotencyKey("independent-b10-key")),
                binding(),
            )

    @pytest.mark.parametrize(
        "changed_actor",
        [
            actor(recruiter="other"),
            actor(requesting="other"),
            actor(hiring="other"),
            actor(mandate="other"),
            actor(mandate=None),
        ],
    )
    def test_full_command_actor_must_equal_governor_actor(self, changed_actor):
        with pytest.raises(ValueError):
            validate_governor_reservation_binding(
                command(recruiting_actor=changed_actor), binding()
            )

    @pytest.mark.parametrize(
        "changes",
        [
            {"reservation_id": "ts-b9-reservation-v1:" + "1" * 64},
            {"request_fingerprint": "ts-b9-request-v1:" + "2" * 64},
            {"status": GovernorReservationState.RELEASED},
            {"status": GovernorReservationState.CONSUMED},
            {"contact_request_id": "ts-b10-request-v1-" + "3" * 64},
            {"policy_version": ""},
            {"activity_at": NOW.replace(tzinfo=None)},
            {"activity_at": NOW.replace(microsecond=123001)},
            {"expires_at": NOW},
        ],
    )
    def test_unavailable_or_malformed_governor_binding_fails_closed(self, changes):
        with pytest.raises(ValueError):
            validate_governor_reservation_binding(command(), binding(**changes))

    def test_valid_b8_hmac_lineage_is_accepted(self):
        verify_anonymous_card_lineage(command(), binding(), card_ref_key=CARD_KEY)

    @pytest.mark.parametrize(
        "mutation",
        [
            {"anonymous_card_ref": "ts-b8-card-v1:" + "0" * 64},
            {"card_ref_key": b"different-card-lineage-key-32-bytes-minimum"},
        ],
    )
    def test_card_tampering_or_wrong_key_is_rejected(self, mutation):
        supplied = mutation.get("anonymous_card_ref", command().anonymous_card_ref)
        key = mutation.get("card_ref_key", CARD_KEY)
        with pytest.raises(ValueError, match="lineage mismatch"):
            verify_anonymous_card_lineage(
                command(anonymous_card_ref=supplied), binding(), card_ref_key=key
            )

    def test_lineage_contract_explicitly_disclaims_exposure_and_permission(self):
        module_doc = ast.get_docstring(ast.parse(SOURCE.read_text(encoding="utf-8")))
        helper_doc = inspect.getdoc(verify_anonymous_card_lineage)
        text = f"{module_doc} {helper_doc}".lower()
        assert "historically shown" in text
        assert "recruiter" in text
        assert "grants no permission" in text
        assert "lineage" in text


class TestAggregateAndTime:
    def test_created_is_the_only_b10_state(self):
        assert list(ContactRequestState) == [ContactRequestState.CREATED]
        assert ContactRequestState.CREATED.value == "created"

    def test_creation_copies_exact_authoritative_binding(self):
        reservation = binding()
        result = create_contact_request(
            command(reservation),
            reservation,
            card_ref_key=CARD_KEY,
            created_at=NOW + timedelta(seconds=1),
        )
        assert result.state is ContactRequestState.CREATED
        assert result.version == CONTACT_REQUEST_AGGREGATE_VERSION == 1
        assert result.schema_version == CONTACT_REQUEST_SCHEMA_VERSION
        assert result.reservation_id == reservation.reservation_id
        assert result.governor_request_fingerprint == reservation.request_fingerprint
        assert result.idempotency_key == reservation.idempotency_key
        assert result.candidate_id == reservation.candidate_id
        assert result.stream_id == reservation.stream_id
        assert result.generation_id == reservation.generation_id
        assert result.recruiting_actor == command(reservation).recruiting_actor
        assert result.governor_policy_version == reservation.policy_version

    def test_nonvolatile_identity_is_stable_across_creation_times(self):
        first = contact_request(created_at=NOW)
        second = contact_request(created_at=NOW + timedelta(seconds=2))
        assert first.contact_request_id == second.contact_request_id
        assert first.command_fingerprint == second.command_fingerprint
        assert first.handoff_job_id == second.handoff_job_id
        assert first.created_at != second.created_at

    def test_lower_lease_boundary_is_inclusive(self):
        assert contact_request(created_at=NOW).created_at == NOW

    @pytest.mark.parametrize(
        "created_at",
        [
            NOW - timedelta(milliseconds=1),
            NOW + timedelta(minutes=5),
            NOW + timedelta(minutes=5, milliseconds=1),
            NOW.replace(tzinfo=None),
            NOW.replace(microsecond=123001),
            "2026-09-22T12:00:00Z",
        ],
    )
    def test_time_is_aware_whole_millisecond_and_lease_is_half_open(
        self, created_at
    ):
        with pytest.raises(ValueError):
            contact_request(created_at=created_at)

    def test_aware_time_is_normalized_to_utc(self):
        offset = timezone(timedelta(hours=2))
        supplied = (NOW + timedelta(seconds=1)).astimezone(offset)
        assert contact_request(created_at=supplied).created_at == (
            NOW + timedelta(seconds=1)
        )

    @pytest.mark.parametrize(
        "field,value",
        [
            ("contact_request_id", "invalid"),
            ("command_fingerprint", "invalid"),
            ("governor_policy_version", ""),
            ("projection_state_version", True),
            ("stream_version", 0),
            ("role_dna_version", 1.0),
            ("handoff_job_id", "invalid"),
            ("state", "created"),
            ("version", True),
            ("version", 2),
            ("schema_version", "future-v2"),
        ],
    )
    def test_aggregate_rejects_noncanonical_or_nonstrict_values(self, field, value):
        with pytest.raises(ValueError):
            replace(contact_request(), **{field: value})

    @pytest.mark.parametrize(
        "field,value",
        [
            ("candidate_id", CandidateId("different")),
            ("stream_id", TalentStreamId("different")),
            ("generation_id", "different"),
            ("opportunity_spec_id", OpportunitySpecId("different")),
            ("recruiting_actor", actor(hiring="different")),
        ],
    )
    def test_aggregate_cannot_drift_from_b9_fingerprint(self, field, value):
        with pytest.raises(ValueError):
            replace(contact_request(), **{field: value})

    def test_aggregate_is_immutable_and_repr_redacts_every_sensitive_binding(self):
        value = contact_request()
        with pytest.raises(FrozenInstanceError):
            value.candidate_id = CandidateId("changed")
        rendered = repr(value)
        assert all(
            secret not in rendered
            for secret in (
                str(value.candidate_id),
                str(value.stream_id),
                value.generation_id,
                value.reservation_id,
                value.anonymous_card_ref,
                str(value.recruiting_actor.recruiter_user_id),
            )
        )


class TestSafeResultAndHandoff:
    def test_result_has_only_safe_fields(self):
        assert [item.name for item in fields(CreateContactRequestResult)] == [
            "contact_request_id",
            "state",
            "outcome",
            "created_at",
        ]
        result = CreateContactRequestResult.from_contact_request(
            contact_request(), outcome=ContactRequestCreateOutcome.CREATED
        )
        assert result.outcome is ContactRequestCreateOutcome.CREATED
        assert result.state is ContactRequestState.CREATED

    @pytest.mark.parametrize("outcome", list(ContactRequestCreateOutcome))
    def test_created_and_replay_results_are_strict_and_repr_redacted(self, outcome):
        result = CreateContactRequestResult.from_contact_request(
            contact_request(), outcome=outcome
        )
        assert repr(result).startswith("<")
        assert str(result.contact_request_id) not in repr(result)
        with pytest.raises(FrozenInstanceError):
            result.outcome = ContactRequestCreateOutcome.CREATED

    @pytest.mark.parametrize(
        "field,value",
        [
            ("contact_request_id", "invalid"),
            ("state", "created"),
            ("outcome", "created"),
            ("created_at", NOW.replace(tzinfo=None)),
            ("created_at", NOW.replace(microsecond=1)),
        ],
    )
    def test_result_rejects_invalid_values(self, field, value):
        valid = CreateContactRequestResult.from_contact_request(
            contact_request(), outcome=ContactRequestCreateOutcome.CREATED
        )
        with pytest.raises(ValueError):
            replace(valid, **{field: value})

    def test_handoff_identifiers_and_exact_a14_shape_are_frozen(self):
        request = contact_request()
        retry = RetryPolicy(3, 2, 60)
        envelope = build_contact_request_handoff_envelope(
            request, retry_policy=retry
        )
        assert type(envelope) is JobEnvelope
        assert envelope.job_id == request.handoff_job_id
        assert envelope.job_id == derive_contact_request_handoff_job_id(
            request.contact_request_id
        )
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", envelope.job_id)
        assert envelope.job_type == CONTACT_REQUEST_HANDOFF_JOB_TYPE
        assert envelope.idempotency_key == request.contact_request_id
        assert (
            envelope.payload_schema_version
            == CONTACT_REQUEST_HANDOFF_PAYLOAD_SCHEMA_VERSION
        )
        assert envelope.reference == JobReference(
            CONTACT_REQUEST_HANDOFF_REFERENCE_TYPE,
            str(request.contact_request_id),
            1,
        )
        assert envelope.retry_policy is retry
        assert envelope.created_at == request.created_at
        assert envelope.initial_available_at == request.created_at

    def test_retry_policy_is_explicit_and_not_defaulted(self):
        signature = inspect.signature(build_contact_request_handoff_envelope)
        retry = signature.parameters["retry_policy"]
        assert retry.default is inspect.Parameter.empty
        with pytest.raises(TypeError):
            build_contact_request_handoff_envelope(contact_request())
        with pytest.raises(ValueError):
            build_contact_request_handoff_envelope(
                contact_request(), retry_policy=None
            )

    def test_handoff_builder_is_pure_and_deterministic(self):
        request = contact_request()
        retry = RetryPolicy(3, 2, 60)
        first = build_contact_request_handoff_envelope(request, retry_policy=retry)
        second = build_contact_request_handoff_envelope(request, retry_policy=retry)
        assert first == second


class TestArchitectureBoundary:
    def test_models_have_no_persistence_service_route_or_future_lot_imports(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
        forbidden_fragments = (
            "pymongo",
            "motor",
            "repository",
            "persistence",
            "service",
            "routes",
            "domains.matching",
            "stream_candidate",
            "permissions.engine",
            "permissions.service",
            "grants",
            "messaging",
            "billing",
        )
        assert not {
            name
            for name in imports
            if any(fragment in name for fragment in forbidden_fragments)
        }

    def test_models_contain_no_io_or_public_exposure_route_behavior(self):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        forbidden_calls = {
            "insert_one",
            "update_one",
            "find_one",
            "publish",
            "publish_in_transaction",
            "create_index",
            "create_collection",
            "send",
        }
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert calls.isdisjoint(forbidden_calls)
        source = SOURCE.read_text(encoding="utf-8")
        assert "historically shown" in source
        assert "public route" not in source.lower()

    def test_contracts_do_not_contain_b11_or_sensitive_reveal_fields(self):
        all_fields = {
            item.name
            for contract in (
                CreateContactRequestCommand,
                ContactRequest,
                CreateContactRequestResult,
            )
            for item in fields(contract)
        }
        forbidden = {
            "invited_at",
            "delivered_at",
            "accepted_at",
            "declined_at",
            "ignored_at",
            "decision",
            "grant_id",
            "profile",
            "identity",
            "email",
            "phone",
            "cv",
            "message",
            "billing",
            "evidence",
            "provenance",
        }
        assert all_fields.isdisjoint(forbidden)
