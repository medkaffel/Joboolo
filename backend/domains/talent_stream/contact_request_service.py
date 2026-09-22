"""B10 Contact Request orchestration across B9, B10 persistence, and A14.

Creation is one Mongo transaction on one client/database.  Exact committed
replay is read-only and requires the authoritative B10 aggregate, consumed B9
binding, and original strict A14 publication to agree.  This service sends no
invitation and grants/reveals nothing.
"""
from __future__ import annotations

from dataclasses import replace

from pymongo import ReadPreference
from pymongo.write_concern import WriteConcern

from async_outbox.models import RetryPolicy
from domains.talent_stream.contact_request_models import (
    CONTACT_REQUEST_HANDOFF_JOB_TYPE,
    ContactRequest,
    ContactRequestCreateOutcome,
    CreateContactRequestCommand,
    CreateContactRequestResult,
    build_contact_request_handoff_envelope,
    create_contact_request,
    derive_contact_request_fingerprint,
    derive_contact_request_id,
)
from domains.talent_stream.anonymous_talent_adapter import (
    derive_anonymous_talent_card_ref,
)
from domains.trust.contact_governor_models import (
    GovernorReservationState,
    require_governor_time,
)


_UNAVAILABLE = "contact request service unavailable"
_CONFLICT = "contact request state conflict"
_COMMITTED_READ_ATTEMPTS = 5


class ContactRequestServiceError(RuntimeError):
    pass


class ContactRequestServiceConflictError(ContactRequestServiceError):
    pass


class ContactRequestServiceUnavailableError(ContactRequestServiceError):
    pass


class _StateConflict(RuntimeError):
    pass


class _MissingCommittedState(_StateConflict):
    pass


def _database_identity(repository):
    try:
        database = repository.db
        return database.client, database.name
    except AttributeError:
        raise ValueError("repository must expose its Mongo database") from None


class ContactRequestService:
    def __init__(
        self,
        *,
        governor_repository,
        contact_request_repository,
        outbox_repository,
        card_ref_key: bytes,
        retry_policy: RetryPolicy,
        clock,
    ):
        identities = tuple(
            _database_identity(repository)
            for repository in (
                governor_repository,
                contact_request_repository,
                outbox_repository,
            )
        )
        client, database_name = identities[0]
        if any(
            other_client is not client or other_name != database_name
            for other_client, other_name in identities[1:]
        ):
            raise ValueError("B9, B10, and A14 must share one Mongo client/database")
        if type(card_ref_key) is not bytes or not card_ref_key:
            raise ValueError("card_ref_key must be non-empty bytes")
        if type(retry_policy) is not RetryPolicy:
            raise ValueError("retry_policy must be explicitly provided")
        if not callable(clock):
            raise ValueError("clock must be callable")

        self.governor_repository = governor_repository
        self.contact_request_repository = contact_request_repository
        self.outbox_repository = outbox_repository
        self.card_ref_key = card_ref_key
        self.retry_policy = retry_policy
        self.clock = clock
        self.db = contact_request_repository.db
        self.client = client

    async def create(
        self,
        command: CreateContactRequestCommand,
    ) -> CreateContactRequestResult:
        try:
            if type(command) is not CreateContactRequestCommand:
                raise ValueError("invalid command")
            contact_request_id = derive_contact_request_id(command)
            derive_contact_request_fingerprint(command)
        except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
            raise ContactRequestServiceConflictError(_CONFLICT) from None

        async def create_attempt(session):
            evaluated_at = self._time()
            return await self._execute(
                command,
                str(contact_request_id),
                evaluated_at,
                session,
            )

        try:
            async with await self.client.start_session() as session:
                return await session.with_transaction(
                    create_attempt,
                    read_preference=ReadPreference.PRIMARY,
                    write_concern=WriteConcern(w="majority"),
                )
        except Exception as error:
            try:
                return await self._recover_committed(command, str(contact_request_id))
            except _StateConflict:
                if isinstance(error, _StateConflict):
                    raise ContactRequestServiceConflictError(_CONFLICT) from None
                raise ContactRequestServiceUnavailableError(_UNAVAILABLE) from None
            except Exception:
                raise ContactRequestServiceUnavailableError(_UNAVAILABLE) from None

    def _time(self):
        try:
            return require_governor_time(self.clock(), "evaluated_at")
        except (OverflowError, TypeError, ValueError):
            raise _StateConflict("invalid evaluation time") from None

    async def _execute(self, command, contact_request_id, evaluated_at, session):
        existing = await self.contact_request_repository.get(
            contact_request_id,
            session=session,
        )
        binding = await self.governor_repository.read_contact_request_binding(
            command.reservation_id,
            session=session,
        )
        if existing is not None:
            return await self._verify_replay(
                command,
                existing,
                binding,
                session=session,
            )
        if binding is None:
            raise _StateConflict("missing governor reservation")
        try:
            request = create_contact_request(
                command,
                binding,
                card_ref_key=self.card_ref_key,
                created_at=evaluated_at,
            )
            envelope = build_contact_request_handoff_envelope(
                request,
                retry_policy=self.retry_policy,
            )
        except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
            raise _StateConflict("invalid creation binding") from None

        # The unique B10 identity is the transaction's serialization point for
        # concurrent identical commands.  It remains invisible until commit
        # and is rolled back if B9 consumption or A14 publication fails.
        await self.contact_request_repository.insert(request, session=session)
        await self.governor_repository.consume(
            command.reservation_id,
            str(request.contact_request_id),
            evaluated_at=evaluated_at,
            session=session,
        )
        await self.outbox_repository.publish_in_transaction(
            envelope,
            session=session,
        )
        return CreateContactRequestResult.from_contact_request(
            request,
            outcome=ContactRequestCreateOutcome.CREATED,
        )

    async def _recover_committed(self, command, contact_request_id):
        async def recover_attempt(session):
            existing = await self.contact_request_repository.get(
                contact_request_id,
                session=session,
            )
            if existing is None:
                raise _MissingCommittedState("missing committed request")
            binding = await self.governor_repository.read_contact_request_binding(
                command.reservation_id,
                session=session,
            )
            return await self._verify_replay(
                command,
                existing,
                binding,
                session=session,
            )

        missing = None
        for _ in range(_COMMITTED_READ_ATTEMPTS):
            try:
                async with await self.client.start_session() as session:
                    return await session.with_transaction(
                        recover_attempt,
                        read_preference=ReadPreference.PRIMARY,
                        write_concern=WriteConcern(w="majority"),
                    )
            except _MissingCommittedState as error:
                # A competing transaction with the same identity may be between
                # its final write and commit.  New PRIMARY transactions provide
                # bounded, read-only reconciliation without repairing state.
                missing = error
        raise missing

    async def _verify_replay(self, command, request, binding, *, session):
        try:
            if type(request) is not ContactRequest or binding is None:
                raise _StateConflict("missing replay state")
            if request.contact_request_id != derive_contact_request_id(command):
                raise _StateConflict("request identity mismatch")
            if request.command_fingerprint != derive_contact_request_fingerprint(command):
                raise _StateConflict("request fingerprint mismatch")
            self._verify_binding(request, binding)
            expected_card_ref = derive_anonymous_talent_card_ref(
                key=self.card_ref_key,
                stream_id=str(request.stream_id),
                generation_id=request.generation_id,
                candidate_id=str(request.candidate_id),
            )
            if (
                request.anonymous_card_ref != command.anonymous_card_ref
                or request.anonymous_card_ref != expected_card_ref
            ):
                raise _StateConflict("anonymous card lineage mismatch")
            publication = await self.outbox_repository.read_publication(
                request.handoff_job_id,
                CONTACT_REQUEST_HANDOFF_JOB_TYPE,
                str(request.contact_request_id),
                session=session,
            )
            expected_envelope = build_contact_request_handoff_envelope(
                request,
                retry_policy=self.retry_policy,
            )
            expected_original = replace(
                expected_envelope,
                retry_policy=publication.envelope.retry_policy,
            )
            if publication.envelope != expected_original:
                raise _StateConflict("handoff publication mismatch")
        except _StateConflict:
            raise
        except Exception:
            raise _StateConflict("invalid replay state") from None
        return CreateContactRequestResult.from_contact_request(
            request,
            outcome=ContactRequestCreateOutcome.IDEMPOTENT_REPLAY,
        )

    @staticmethod
    def _verify_binding(request, binding):
        actor = request.recruiting_actor
        expected = {
            "reservation_id": request.reservation_id,
            "request_fingerprint": request.governor_request_fingerprint,
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
            "recruiter_user_id": str(actor.recruiter_user_id),
            "requesting_organization_id": str(actor.requesting_organization_id),
            "hiring_company_id": str(actor.hiring_company_id),
            "mandate_id": None if actor.mandate_id is None else str(actor.mandate_id),
            "policy_version": request.governor_policy_version,
            "activity_at": request.reservation_activity_at,
            "expires_at": request.reservation_expires_at,
            "status": GovernorReservationState.CONSUMED,
            "contact_request_id": str(request.contact_request_id),
        }
        try:
            if any(getattr(binding, field) != value for field, value in expected.items()):
                raise _StateConflict("governor binding mismatch")
        except AttributeError:
            raise _StateConflict("invalid governor binding") from None


__all__ = [
    "ContactRequestServiceError",
    "ContactRequestServiceConflictError",
    "ContactRequestServiceUnavailableError",
    "ContactRequestService",
]
