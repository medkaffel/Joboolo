"""Hermetic B10.3 orchestration tests; no Mongo, network, or wall clock."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from async_outbox.models import (
    JobState,
    OperationalState,
    OutboxRecord,
    RetryPolicy,
)
from domains.shared.ids import (
    CandidateId,
    HiringCompanyId,
    IdempotencyKey,
    OpportunitySpecId,
    OrganizationId,
    RecruiterUserId,
    RoleDNAId,
    TalentStreamId,
)
from domains.shared.versioning import PolicyVersion
from domains.talent_stream.anonymous_talent_adapter import (
    derive_anonymous_talent_card_ref,
)
from domains.talent_stream.contact_request_models import (
    ContactRequestCreateOutcome,
    CreateContactRequestCommand,
)
from domains.talent_stream.contact_request_service import (
    ContactRequestService,
    ContactRequestServiceConflictError,
    ContactRequestServiceUnavailableError,
)
from domains.talent_stream.contracts import RecruitingActorContext
from domains.trust.contact_governor_models import (
    ActiveReservationLimitPolicy,
    CompanyCoolingPolicy,
    ContactGovernorPolicyV1,
    ContactGovernorRequest,
    DuplicateProtectionPolicy,
    FrequencyCapPolicy,
    GovernorReservationCommand,
    GovernorReservationState,
    derive_request_fingerprint,
    derive_reservation_id,
)
from domains.trust.contact_governor_persistence import (
    reservation_record_from_command,
)


NOW = datetime(2026, 9, 22, 14, 0, tzinfo=timezone.utc)
CARD_KEY = b"b10-service-card-key-32-bytes-minimum"


class Database:
    def __init__(self, client, name="test"):
        self.client = client
        self.name = name


class Session:
    def __init__(self, *, raise_after=False):
        self.in_transaction = False
        self.raise_after = raise_after

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.in_transaction = False

    async def with_transaction(self, callback, **options):
        assert options["read_preference"].name == "Primary"
        assert options["write_concern"].document == {"w": "majority"}
        self.in_transaction = True
        result = await callback(self)
        self.in_transaction = False
        if self.raise_after:
            raise RuntimeError("unknown fictional commit outcome")
        return result


class RetryOnceSession(Session):
    async def with_transaction(self, callback, **options):
        assert options["read_preference"].name == "Primary"
        assert options["write_concern"].document == {"w": "majority"}
        self.in_transaction = True
        with pytest.raises(RetryOnce):
            await callback(self)
        result = await callback(self)
        self.in_transaction = False
        return result


class RetryOnce(RuntimeError):
    pass


class Client:
    def __init__(self):
        self.sessions = []

    async def start_session(self):
        session = self.sessions.pop(0) if self.sessions else Session()
        return session


class GovernorRepository:
    def __init__(self, db, binding, calls):
        self.db, self.binding, self.calls = db, binding, calls
        self.consume_count = 0

    async def read_contact_request_binding(self, reservation_id, *, session):
        assert session.in_transaction
        self.calls.append("governor.read")
        return self.binding if self.binding.reservation_id == reservation_id else None

    async def consume(self, reservation_id, contact_request_id, *, evaluated_at, session):
        assert session.in_transaction and reservation_id == self.binding.reservation_id
        self.calls.append("governor.consume")
        self.consume_count += 1
        self.binding = replace(
            self.binding,
            status=GovernorReservationState.CONSUMED,
            contact_request_id=contact_request_id,
        )


class RequestRepository:
    def __init__(self, db, calls):
        self.db, self.calls = db, calls
        self.stored = None
        self.insert_count = 0
        self.failure = None

    async def get(self, contact_request_id, *, session=None):
        assert session.in_transaction
        self.calls.append("request.get")
        if self.failure:
            failure, self.failure = self.failure, None
            raise failure
        if self.stored is None or str(self.stored.contact_request_id) != contact_request_id:
            return None
        return self.stored

    async def insert(self, request, *, session):
        assert session.in_transaction
        self.calls.append("request.insert")
        self.insert_count += 1
        self.stored = request


class OutboxRepository:
    def __init__(self, db, calls):
        self.db, self.calls = db, calls
        self.stored = None
        self.publish_count = 0

    async def publish_in_transaction(self, envelope, *, session):
        assert session.in_transaction
        self.calls.append("outbox.publish")
        self.publish_count += 1
        self.stored = OutboxRecord(
            envelope,
            OperationalState(
                JobState.PENDING,
                0,
                envelope.initial_available_at,
                envelope.created_at,
            ),
        )
        return self.stored

    async def read_publication(self, job_id, job_type, idempotency_key, *, session=None):
        assert session.in_transaction
        self.calls.append("outbox.read")
        if self.stored is None:
            raise RuntimeError("missing publication")
        envelope = self.stored.envelope
        if (envelope.job_id, envelope.job_type, envelope.idempotency_key) != (
            job_id,
            job_type,
            idempotency_key,
        ):
            raise RuntimeError("publication mismatch")
        return self.stored


def actor():
    return RecruitingActorContext(
        recruiter_user_id=RecruiterUserId("recruiter-1"),
        requesting_organization_id=OrganizationId("organization-1"),
        hiring_company_id=HiringCompanyId("company-1"),
        mandate_id=None,
    )


def governor_request():
    return ContactGovernorRequest(
        idempotency_key=IdempotencyKey("request-1"),
        candidate_id=CandidateId("candidate-1"),
        stream_id=TalentStreamId("stream-1"),
        generation_id="generation-1",
        projection_state_version=2,
        stream_version=3,
        requirement_version=4,
        role_dna_id=RoleDNAId("role-1"),
        role_dna_version=5,
        opportunity_spec_id=OpportunitySpecId("opportunity-1"),
        opportunity_spec_version=6,
        recruiting_actor=actor(),
    )


def binding():
    request = governor_request()
    policy = ContactGovernorPolicyV1(
        policy_version=PolicyVersion("contact-governor-v1-test"),
        minimum_professional_match_score=70,
        frequency_cap_policy=FrequencyCapPolicy(enabled=False, caps=None),
        duplicate_protection_policy=DuplicateProtectionPolicy(
            enabled=False,
            scope=None,
            window=None,
        ),
        company_cooling_policy=CompanyCoolingPolicy(
            enabled=False,
            scope=None,
            period=None,
        ),
        active_reservation_limit_policy=ActiveReservationLimitPolicy(
            enabled=False,
            maximum_active_reservations=None,
        ),
        reservation_lease=timedelta(minutes=5),
    )
    command = GovernorReservationCommand(
        request=request,
        policy=policy,
        evaluated_at=NOW,
        reservation_id=derive_reservation_id(request),
        request_fingerprint=derive_request_fingerprint(request),
        reservation_expires_at=NOW + policy.reservation_lease,
    )
    return reservation_record_from_command(command)


def command(value=None):
    value = value or binding()
    return CreateContactRequestCommand(
        idempotency_key=IdempotencyKey(value.idempotency_key),
        reservation_id=value.reservation_id,
        governor_request_fingerprint=value.request_fingerprint,
        anonymous_card_ref=derive_anonymous_talent_card_ref(
            key=CARD_KEY,
            stream_id=value.stream_id,
            generation_id=value.generation_id,
            candidate_id=value.candidate_id,
        ),
        recruiting_actor=actor(),
    )


def fixture(*, clock=lambda: NOW + timedelta(milliseconds=1), retry=None):
    calls = []
    client = Client()
    db = Database(client)
    governor = GovernorRepository(db, binding(), calls)
    requests = RequestRepository(db, calls)
    outbox = OutboxRepository(db, calls)
    service = ContactRequestService(
        governor_repository=governor,
        contact_request_repository=requests,
        outbox_repository=outbox,
        card_ref_key=CARD_KEY,
        retry_policy=retry or RetryPolicy(3, 2, 60),
        clock=clock,
    )
    return service, governor, requests, outbox, calls, client


@pytest.mark.asyncio
async def test_creation_uses_one_session_and_exact_atomic_order():
    service, governor, requests, outbox, calls, _ = fixture()
    result = await service.create(command(governor.binding))
    assert result.outcome is ContactRequestCreateOutcome.CREATED
    assert calls == [
        "request.get",
        "governor.read",
        "request.insert",
        "governor.consume",
        "outbox.publish",
    ]
    assert governor.consume_count == requests.insert_count == outbox.publish_count == 1


@pytest.mark.asyncio
async def test_transaction_callback_retry_obtains_a_fresh_clock_value():
    observed = []
    values = iter(
        (
            NOW + timedelta(milliseconds=1),
            NOW + timedelta(milliseconds=2),
        )
    )

    def clock():
        value = next(values)
        observed.append(value)
        return value

    service, governor, requests, _, _, client = fixture(clock=clock)
    requests.failure = RetryOnce("fictional transient transaction error")
    client.sessions = [RetryOnceSession()]
    result = await service.create(command(governor.binding))

    assert result.outcome is ContactRequestCreateOutcome.CREATED
    assert observed == [
        NOW + timedelta(milliseconds=1),
        NOW + timedelta(milliseconds=2),
    ]
    assert requests.stored.created_at == observed[-1]


@pytest.mark.asyncio
async def test_committed_replay_is_read_only_after_expiry_and_policy_change():
    service, governor, requests, outbox, calls, _ = fixture()
    request_command = command(governor.binding)
    await service.create(request_command)
    counts = (governor.consume_count, requests.insert_count, outbox.publish_count)
    calls.clear()
    replay = ContactRequestService(
        governor_repository=governor,
        contact_request_repository=requests,
        outbox_repository=outbox,
        card_ref_key=CARD_KEY,
        retry_policy=RetryPolicy(8, 7, 120),
        clock=lambda: NOW + timedelta(hours=1),
    )
    result = await replay.create(request_command)
    assert result.outcome is ContactRequestCreateOutcome.IDEMPOTENT_REPLAY
    assert (governor.consume_count, requests.insert_count, outbox.publish_count) == counts
    assert calls == ["request.get", "governor.read", "outbox.read"]
    assert outbox.stored.envelope.retry_policy == RetryPolicy(3, 2, 60)


@pytest.mark.asyncio
async def test_unknown_commit_outcome_recovers_authoritative_triple():
    service, governor, requests, outbox, _, client = fixture()
    client.sessions = [Session(raise_after=True), Session()]
    result = await service.create(command(governor.binding))
    assert result.outcome is ContactRequestCreateOutcome.IDEMPOTENT_REPLAY
    assert governor.consume_count == requests.insert_count == outbox.publish_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["binding", "outbox"])
async def test_replay_missing_or_mismatched_state_fails_closed(broken):
    service, governor, requests, outbox, _, _ = fixture()
    request_command = command(governor.binding)
    await service.create(request_command)
    if broken == "binding":
        governor.binding = replace(governor.binding, contact_request_id="different")
    else:
        outbox.stored = None
    with pytest.raises(ContactRequestServiceConflictError):
        await service.create(request_command)


@pytest.mark.asyncio
async def test_upstream_error_is_redacted():
    service, governor, requests, _, _, _ = fixture()
    requests.failure = RuntimeError("candidate-secret@example.test")
    with pytest.raises(ContactRequestServiceUnavailableError) as raised:
        await service.create(command(governor.binding))
    assert str(raised.value) == "contact request service unavailable"
    assert "candidate-secret" not in str(raised.value)


def test_repositories_must_share_exact_client_and_database():
    service, governor, requests, outbox, _, _ = fixture()
    del service
    outbox.db = Database(Client())
    with pytest.raises(ValueError, match="share one Mongo client/database"):
        ContactRequestService(
            governor_repository=governor,
            contact_request_repository=requests,
            outbox_repository=outbox,
            card_ref_key=CARD_KEY,
            retry_policy=RetryPolicy(3, 2, 60),
            clock=lambda: NOW,
        )


def test_service_has_no_b11_route_reveal_or_authorization_dependencies():
    source = Path(
        "domains/talent_stream/contact_request_service.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "domains.permissions",
        "domains.matching",
        "FastAPI",
        "APIRouter",
        "candidate_decision",
        "cv_grant",
        "messaging",
        "billing",
    )
    assert all(item not in source for item in forbidden)
