"""TS-B2 orchestration for preparing A3/A4 refs from one owned Job."""
from dataclasses import fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum

from pymongo.errors import DuplicateKeyError

from domains.opportunities.repository import OpportunitySpecRepository
from domains.roles.repository import RoleDNARepository
from .own_job_mapping import (
    OwnJobSourceConflictError,
    deterministic_own_job_ids,
    own_job_source_fingerprint,
    prepare_own_job_requirement,
)
from .own_job_repository import OwnJobRepository


def _now_millisecond():
    now = datetime.now(timezone.utc)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _stored_utc_millisecond(value):
    if type(value) is not datetime:
        raise OwnJobSourceConflictError("invalid existing B2 record")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        value = value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise OwnJobSourceConflictError("invalid existing B2 record") from None
    if value.microsecond % 1000:
        raise OwnJobSourceConflictError("invalid existing B2 record")
    return value


def _role_document(role):
    return {
        "_id": f"{role.role_dna_id}:v1",
        "role_dna_id": str(role.role_dna_id),
        **{key: _serialize(value) for key, value in role.__dict__.items() if key != "role_dna_id"},
    }


def _opportunity_document(opportunity):
    return {
        "_id": f"{opportunity.opportunity_spec_id}:v1",
        "opportunity_spec_id": str(opportunity.opportunity_spec_id),
        **{
            key: _serialize(value)
            for key, value in opportunity.__dict__.items()
            if key != "opportunity_spec_id"
        },
    }


def _serialize(value):
    """Serialize nominal ints before dataclass/object handling.

    EntityVersion is an int subclass with an empty ``__dict__``. The generic
    legacy A3/A4 serializer would therefore persist it as ``{}``; B2 keeps its
    output valid without changing those existing services.
    """
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if is_dataclass(value):
        return {field.name: _serialize(getattr(value, field.name)) for field in fields(value)}
    return value


def _canonical(value):
    if type(value) is datetime:
        return _stored_utc_millisecond(value).isoformat(timespec="milliseconds")
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _require_exact(actual, expected):
    try:
        same = _canonical(actual) == _canonical(expected)
    except OwnJobSourceConflictError:
        same = False
    if not same:
        raise OwnJobSourceConflictError("existing B2 record conflicts with source command")


class OwnJobRequirementService:
    def __init__(self, db):
        self.source_repository = OwnJobRepository(db)
        self.role_repository = RoleDNARepository(db)
        self.opportunity_repository = OpportunitySpecRepository(db)

    async def _role(self, preparation):
        role = preparation.role_dna
        existing = await self.role_repository.get(str(role.role_dna_id), 1)
        if existing is None:
            try:
                existing = _role_document(role)
                await self.role_repository.insert_version(existing)
            except DuplicateKeyError:
                existing = await self.role_repository.get(str(role.role_dna_id), 1)
        if existing is None:
            raise OwnJobSourceConflictError("B2 Role DNA create did not converge")
        return existing

    async def _opportunity(self, preparation):
        opportunity = preparation.opportunity_specification
        existing = await self.opportunity_repository.get(
            str(opportunity.opportunity_spec_id), 1,
        )
        if existing is None:
            try:
                existing = _opportunity_document(opportunity)
                await self.opportunity_repository.insert_version(existing)
            except DuplicateKeyError:
                existing = await self.opportunity_repository.get(
                    str(opportunity.opportunity_spec_id), 1,
                )
        if existing is None:
            raise OwnJobSourceConflictError("B2 Opportunity Specification create did not converge")
        return existing

    async def prepare(self, recruiter_id, job_id, *, command_id, captured_at=None):
        """Persist/reuse an exact draft pair, then return its immutable refs."""
        role_id, _ = deterministic_own_job_ids(recruiter_id, job_id, command_id)
        raw_job = await self.source_repository.get_owned_source(recruiter_id, job_id)
        await self.source_repository.readiness()

        existing_role = await self.role_repository.get(str(role_id), 1)
        stable_time = (
            _now_millisecond() if existing_role is None
            else _stored_utc_millisecond(existing_role.get("created_at"))
        )
        if captured_at is not None:
            supplied = _stored_utc_millisecond(captured_at)
            if existing_role is not None and supplied != stable_time:
                raise OwnJobSourceConflictError("captured_at conflicts with existing B2 command")
            stable_time = supplied

        preparation = prepare_own_job_requirement(
            raw_job, recruiter_id, command_id, stable_time,
        )
        role_doc = existing_role if existing_role is not None else await self._role(preparation)

        persisted_time = _stored_utc_millisecond(role_doc.get("created_at"))
        preparation = prepare_own_job_requirement(
            raw_job, recruiter_id, command_id, persisted_time,
        )
        _require_exact(role_doc, _role_document(preparation.role_dna))

        opportunity_doc = await self._opportunity(preparation)
        _require_exact(
            opportunity_doc,
            _opportunity_document(preparation.opportunity_specification),
        )

        current_job = await self.source_repository.get_owned_source(recruiter_id, job_id)
        if own_job_source_fingerprint(current_job, recruiter_id, job_id) != preparation.source_fingerprint:
            raise OwnJobSourceConflictError("own-job source changed during preparation")
        return preparation
