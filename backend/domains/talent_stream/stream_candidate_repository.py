"""B7 Stream Candidate projection persistence: staging, CAS publications, reads.

Owns exactly the three B7 collections. No Applications/A11/SavedJob/Discovery
reads, no runtime index creation, no auto repair, and a fixed redacted repository
error. A generation is only ever written through its registered lifecycle
record: begin registers a BUILDING record, staging accumulates candidate
documents strictly before sealing under a persistent fingerprinted batch lock,
sealing is a compare-and-swap on the record (refusing any reserved batch and
recording the exact promised count atomically) that permanently freezes the
generation, and publication requires the SEALED record whose candidate_count
matches the actual staged document set. A published generation is immutable
unless a retry reproduces an already identical document.
"""
from pymongo import ReadPreference
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.write_concern import WriteConcern

from domains.talent_stream.index_requirements import (
    TALENT_STREAM_CANDIDATE_GENERATIONS_REQUIREMENT,
    TALENT_STREAM_CANDIDATE_PROJECTION_STATES_REQUIREMENT,
    TALENT_STREAM_CANDIDATES_REQUIREMENT,
)
from domains.talent_stream.stream_candidate_models import StreamCandidate
from domains.talent_stream.stream_candidate_persistence import (
    GenerationState,
    ProjectionState,
    StreamCandidateGenerationRecord,
    candidate_document_id,
    generation_record_document_id,
    generation_record_from_document,
    generation_record_to_document,
    projection_state_from_document,
    projection_state_to_document,
    staging_batch_fingerprint,
    stream_candidate_from_document,
    stream_candidate_to_document,
)
from domains.talent_stream.stream_models import (
    nonblank_identifier,
    positive_entity_version,
    utc_millisecond,
)
from mongo_index_safety import verify_metadata

_B7_REQUIREMENTS = (
    TALENT_STREAM_CANDIDATES_REQUIREMENT,
    TALENT_STREAM_CANDIDATE_PROJECTION_STATES_REQUIREMENT,
    TALENT_STREAM_CANDIDATE_GENERATIONS_REQUIREMENT,
)

_PROJECTION_PUBLISH_CONFLICT_MSG = "b7 projection publish conflict"
_PROJECTION_STATE_MISMATCH_MSG = "b7 expected projection state mismatch"
_STAGING_BATCH_STATE_CONFLICT_MSG = "b7 staging batch is already reserved"
_STAGING_BATCH_RESERVE_FAILED_MSG = "b7 staging reserve failed"
_STAGING_BATCH_VERIFICATION_MSG = "b7 staging batch verification failed"
_STAGING_BATCH_RELEASE_MSG = "b7 staging release failed"
_SEAL_CONFLICT_MSG = "b7 generation seal conflict"


class StreamCandidateRepositoryError(RuntimeError):
    pass


class StreamCandidateReadinessError(StreamCandidateRepositoryError):
    pass


class StreamCandidateConflictError(StreamCandidateRepositoryError):
    pass


class StreamCandidateRepository:
    def __init__(self, db):
        self.db = db
        self.candidates = db.talent_stream_candidates.with_options(
            read_preference=ReadPreference.PRIMARY, write_concern=WriteConcern(w="majority")
        )
        self.states = db.talent_stream_candidate_projection_states.with_options(
            read_preference=ReadPreference.PRIMARY, write_concern=WriteConcern(w="majority")
        )
        self.generations = db.talent_stream_candidate_generations.with_options(
            read_preference=ReadPreference.PRIMARY, write_concern=WriteConcern(w="majority")
        )

    async def readiness(self):
        """Verify only the three A13 B7 requirements; never repair or migrate."""
        names = {requirement.name for requirement in _B7_REQUIREMENTS}
        try:
            collections = {}
            cursor = await self.db.list_collections(filter={"name": {"$in": sorted(names)}})
            async for record in cursor:
                collections[record["name"]] = record
            indexes = {}
            for name in names:
                if collections.get(name, {}).get("type") == "collection":
                    indexes[name] = await self.db[name].index_information()
            report = verify_metadata(_B7_REQUIREMENTS, collections, indexes)
        except Exception:
            raise StreamCandidateReadinessError(
                "b7 candidate projection storage metadata unavailable"
            ) from None
        if not report.ok:
            raise StreamCandidateReadinessError(
                "b7 candidate projection storage is not ready"
            )
        return report

    async def _read_state(self, stream_id):
        try:
            document = await self.states.find_one(
                {"_id": stream_id}, collation={"locale": "simple"}
            )
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 projection state read failed"
            ) from None
        if document is None:
            return None
        try:
            return projection_state_from_document(document)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise StreamCandidateRepositoryError(
                "b7 projection state is malformed"
            ) from None

    async def _read_generation_record(self, stream_id, generation_id):
        try:
            document = await self.generations.find_one(
                {"_id": generation_record_document_id(stream_id, generation_id)},
                collation={"locale": "simple"},
            )
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 generation record read failed"
            ) from None
        if document is None:
            return None
        try:
            return generation_record_from_document(document)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise StreamCandidateRepositoryError(
                "b7 generation record is malformed"
            ) from None

    async def get_projection_state(self, stream_id):
        """Return the current ProjectionState or None. No candidate data."""
        await self.readiness()
        return await self._read_state(stream_id)

    async def get_generation_candidate(self, stream_id, generation_id, candidate_id):
        """Read one exact candidate from one generation without a fallback scan."""
        await self.readiness()
        try:
            document = await self.candidates.find_one(
                {
                    "stream_id": stream_id,
                    "generation_id": generation_id,
                    "candidate_id": candidate_id,
                },
                collation={"locale": "simple"},
            )
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 generation candidate read failed"
            ) from None
        if document is None:
            return None
        try:
            candidate = stream_candidate_from_document(document)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise StreamCandidateRepositoryError(
                "b7 generation candidate is malformed"
            ) from None
        if (
            candidate.stream_id != stream_id
            or candidate.generation_id != generation_id
            or candidate.candidate_id != candidate_id
        ):
            raise StreamCandidateRepositoryError(
                "b7 generation candidate is malformed"
            )
        return candidate

    async def _read_generation_documents(self, stream_id, generation_id):
        try:
            cursor = self.candidates.find(
                {"stream_id": stream_id, "generation_id": generation_id},
                collation={"locale": "simple"},
            ).sort([("candidate_id", 1)])
            return await cursor.to_list(length=None)
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 generation read failed"
            ) from None

    async def find_generation(
        self, stream_id, generation_id, *, after_candidate_id=None, limit
    ):
        """Read exactly one generation, ordered by candidate_id ASC."""
        await self.readiness()
        if type(limit) is not int or limit < 1 or limit > 500:
            raise StreamCandidateRepositoryError(
                "b7 pagination limit must be a strict int in 1..500"
            )
        if after_candidate_id is not None:
            try:
                nonblank_identifier(after_candidate_id, "after_candidate_id")
            except ValueError:
                raise StreamCandidateRepositoryError(
                    "b7 invalid after_candidate_id"
                ) from None
        query = {"stream_id": stream_id, "generation_id": generation_id}
        if after_candidate_id is not None:
            query["candidate_id"] = {"$gt": after_candidate_id}
        try:
            cursor = self.candidates.find(
                query, collation={"locale": "simple"}
            ).sort([("candidate_id", 1)]).limit(limit)
            documents = await cursor.to_list(length=limit)
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 generation read failed"
            ) from None
        try:
            return [stream_candidate_from_document(document) for document in documents]
        except (ValueError, TypeError, KeyError, OverflowError):
            raise StreamCandidateRepositoryError(
                "b7 generation document is malformed"
            ) from None

    async def stage_candidates(self, candidates):
        """Persist one immutable generation batch under a fingerprinted lock.

        The protocol is atomic around a persistent staging_batch_id lock on the
        generation record: the deterministic fingerprint of the full canonical
        batch is CAS-reserved on the BUILDING record before any write, every
        requested document is inserted or reconciled, ALL requested documents
        are verified to exist and rehydrate identically, and only then is the
        lock CAS-released. On a SEALING or SEALED record nothing is ever
        inserted: the batch is validated only, exact replays are idempotent and
        any new, missing or different document is a conflict.
        """
        await self.readiness()
        if type(candidates) not in (list, tuple) or not candidates:
            raise StreamCandidateRepositoryError("b7 staging requires a non-empty batch")
        if any(type(candidate) is not StreamCandidate for candidate in candidates):
            raise StreamCandidateRepositoryError("b7 staging received an invalid candidate")
        first = candidates[0]
        scope = (
            first.stream_id,
            first.stream_version,
            first.requirement_version,
            first.generation_id,
            first.role_dna_id,
            first.role_dna_version,
            first.opportunity_spec_id,
            first.opportunity_spec_version,
        )
        for candidate in candidates[1:]:
            candidate_scope = (
                candidate.stream_id,
                candidate.stream_version,
                candidate.requirement_version,
                candidate.generation_id,
                candidate.role_dna_id,
                candidate.role_dna_version,
                candidate.opportunity_spec_id,
                candidate.opportunity_spec_version,
            )
            if candidate_scope != scope:
                raise StreamCandidateRepositoryError(
                    "b7 batch must share one exact generation scope"
                )
        documents = [stream_candidate_to_document(candidate) for candidate in candidates]
        ids = [document["_id"] for document in documents]
        if len(set(ids)) != len(ids):
            raise StreamCandidateRepositoryError("b7 batch has duplicate candidate ids")
        try:
            fingerprint = staging_batch_fingerprint(candidates)
        except ValueError:
            raise StreamCandidateRepositoryError(
                "b7 staging received an invalid batch"
            ) from None

        record = await self._read_generation_record(first.stream_id, first.generation_id)
        if record is None:
            raise StreamCandidateConflictError("b7 generation is not registered")
        if not self._generation_scope_matches(
            record,
            stream_id=first.stream_id,
            generation_id=first.generation_id,
            stream_version=first.stream_version,
            requirement_version=first.requirement_version,
            role_dna_id=first.role_dna_id,
            role_dna_version=first.role_dna_version,
            opportunity_spec_id=first.opportunity_spec_id,
            opportunity_spec_version=first.opportunity_spec_version,
        ):
            raise StreamCandidateConflictError("b7 generation scope mismatch")
        if record.state is not GenerationState.BUILDING:
            return await self._stage_validation_only(first, documents, candidates, record)

        record_id = generation_record_document_id(first.stream_id, first.generation_id)
        reserved = False
        for _ in range(3):
            try:
                result = await self.generations.update_one(
                    {
                        "_id": record_id,
                        "state": GenerationState.BUILDING.value,
                        "staging_batch_id": {"$exists": False},
                    },
                    {"$set": {"staging_batch_id": fingerprint}},
                )
            except PyMongoError:
                raise StreamCandidateRepositoryError(
                    _STAGING_BATCH_RESERVE_FAILED_MSG
                ) from None
            if result.matched_count:
                reserved = True
                break
            current = await self._read_generation_record(
                first.stream_id, first.generation_id
            )
            if current is None:
                raise StreamCandidateConflictError("b7 generation is not registered")
            if not self._generation_scope_matches(
                current,
                stream_id=first.stream_id,
                generation_id=first.generation_id,
                stream_version=first.stream_version,
                requirement_version=first.requirement_version,
                role_dna_id=first.role_dna_id,
                role_dna_version=first.role_dna_version,
                opportunity_spec_id=first.opportunity_spec_id,
                opportunity_spec_version=first.opportunity_spec_version,
            ):
                raise StreamCandidateConflictError("b7 generation scope mismatch")
            if current.state is not GenerationState.BUILDING:
                return await self._stage_validation_only(
                    first, documents, candidates, current
                )
            if current.staging_batch_id == fingerprint:
                reserved = True
                break
            if current.staging_batch_id is not None:
                raise StreamCandidateConflictError(_STAGING_BATCH_STATE_CONFLICT_MSG)
        if not reserved:
            raise StreamCandidateRepositoryError(_STAGING_BATCH_RESERVE_FAILED_MSG)

        existing = {}
        try:
            cursor = self.candidates.find(
                {"_id": {"$in": ids}}, collation={"locale": "simple"}
            )
            for document in await cursor.to_list(length=len(ids)):
                existing[document["_id"]] = document
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 staging read failed"
            ) from None

        staged = 0
        idempotent = 0
        for candidate, document in zip(candidates, documents):
            document_id = document["_id"]
            stored = existing.get(document_id)
            if stored is not None:
                try:
                    if stream_candidate_from_document(stored) != candidate:
                        raise StreamCandidateConflictError(
                            "b7 staging conflicts with an existing candidate document"
                        )
                except (ValueError, TypeError, KeyError, OverflowError):
                    raise StreamCandidateRepositoryError(
                        "b7 existing candidate document is malformed"
                    ) from None
                idempotent += 1
                continue
            try:
                await self.candidates.insert_one(document)
                staged += 1
            except DuplicateKeyError:
                try:
                    winner = await self.candidates.find_one(
                        {"_id": document_id}, collation={"locale": "simple"}
                    )
                except PyMongoError:
                    raise StreamCandidateRepositoryError(
                        "b7 staging read failed"
                    ) from None
                if winner is None or stream_candidate_from_document(winner) != candidate:
                    raise StreamCandidateConflictError(
                        "b7 staging conflicts with an existing candidate document"
                    )
                idempotent += 1
            except PyMongoError:
                raise StreamCandidateRepositoryError(
                    "b7 staging write failed"
                ) from None

        try:
            cursor = self.candidates.find(
                {"_id": {"$in": ids}}, collation={"locale": "simple"}
            )
            stored_documents = await cursor.to_list(length=len(ids))
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 staging read failed"
            ) from None
        stored_by_id = {document["_id"]: document for document in stored_documents}
        if len(stored_by_id) != len(ids):
            raise StreamCandidateRepositoryError(_STAGING_BATCH_VERIFICATION_MSG)
        for candidate, document in zip(candidates, documents):
            stored = stored_by_id.get(document["_id"])
            try:
                if stored is None or stream_candidate_from_document(stored) != candidate:
                    raise StreamCandidateRepositoryError(
                        _STAGING_BATCH_VERIFICATION_MSG
                    )
            except (ValueError, TypeError, KeyError, OverflowError):
                raise StreamCandidateRepositoryError(
                    _STAGING_BATCH_VERIFICATION_MSG
                ) from None

        try:
            result = await self.generations.update_one(
                {
                    "_id": record_id,
                    "state": GenerationState.BUILDING.value,
                    "staging_batch_id": fingerprint,
                },
                {"$unset": {"staging_batch_id": ""}},
            )
        except PyMongoError:
            raise StreamCandidateRepositoryError(_STAGING_BATCH_RELEASE_MSG) from None
        if result.matched_count:
            return {
                "stream_id": first.stream_id,
                "generation_id": first.generation_id,
                "staged": staged,
                "idempotent_retries": idempotent,
            }
        current = await self._read_generation_record(first.stream_id, first.generation_id)
        if current is not None and current.state is not GenerationState.BUILDING:
            return {
                "stream_id": first.stream_id,
                "generation_id": first.generation_id,
                "staged": staged,
                "idempotent_retries": idempotent,
            }
        if current is None or current.staging_batch_id not in (None, fingerprint):
            raise StreamCandidateRepositoryError(_STAGING_BATCH_RELEASE_MSG)
        return {
            "stream_id": first.stream_id,
            "generation_id": first.generation_id,
            "staged": staged,
            "idempotent_retries": idempotent,
        }

    async def _stage_validation_only(self, first, documents, candidates, record):
        """Exact replay validation for SEALING/SEALED records; never inserts."""
        message = (
            "b7 generation is sealing"
            if record.state is GenerationState.SEALING
            else "b7 generation is sealed"
        )
        existing = {}
        try:
            cursor = self.candidates.find(
                {"_id": {"$in": [document["_id"] for document in documents]}},
                collation={"locale": "simple"},
            )
            for document in await cursor.to_list(length=len(documents)):
                existing[document["_id"]] = document
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 staging read failed"
            ) from None
        verified = 0
        for candidate, document in zip(candidates, documents):
            stored = existing.get(document["_id"])
            try:
                if stored is None or stream_candidate_from_document(stored) != candidate:
                    raise StreamCandidateConflictError(message)
            except (ValueError, TypeError, KeyError, OverflowError):
                raise StreamCandidateConflictError(message) from None
            verified += 1
        return {
            "stream_id": first.stream_id,
            "generation_id": first.generation_id,
            "staged": 0,
            "idempotent_retries": verified,
        }

    async def begin_generation(
        self,
        stream_id,
        *,
        generation_id,
        stream_version,
        requirement_version,
        role_dna_id,
        role_dna_version,
        opportunity_spec_id,
        opportunity_spec_version,
    ):
        """Register one immutable generation scope before any staging write.

        Idempotent: a retry of the same scope returns the existing record and a
        sealed generation is never reopened, but reuse of the same generation
        identity with a different scope is always a conflict.
        """
        await self.readiness()
        nonblank_identifier(stream_id, "stream_id")
        nonblank_identifier(generation_id, "generation_id")
        nonblank_identifier(role_dna_id, "role_dna_id")
        nonblank_identifier(opportunity_spec_id, "opportunity_spec_id")
        positive_entity_version(stream_version, "stream_version")
        positive_entity_version(requirement_version, "requirement_version")
        positive_entity_version(role_dna_version, "role_dna_version")
        positive_entity_version(opportunity_spec_version, "opportunity_spec_version")
        record = StreamCandidateGenerationRecord(
            stream_id=stream_id,
            generation_id=generation_id,
            stream_version=stream_version,
            requirement_version=requirement_version,
            role_dna_id=role_dna_id,
            role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
            state=GenerationState.BUILDING,
            candidate_count=None,
        )
        try:
            await self.generations.insert_one(generation_record_to_document(record))
            return record
        except DuplicateKeyError:
            pass
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 generation begin failed"
            ) from None
        existing = await self._read_generation_record(stream_id, generation_id)
        if existing is not None and self._generation_scope_matches(
            existing,
            stream_id=stream_id,
            generation_id=generation_id,
            stream_version=stream_version,
            requirement_version=requirement_version,
            role_dna_id=role_dna_id,
            role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
        ):
            return existing
        raise StreamCandidateConflictError("b7 generation scope mismatch")

    async def seal_generation(
        self,
        stream_id,
        *,
        generation_id,
        stream_version,
        requirement_version,
        role_dna_id,
        role_dna_version,
        opportunity_spec_id,
        opportunity_spec_version,
        candidate_count,
    ):
        """Permanently seal one registered generation after verifying its docs.

        The seal is a compare-and-swap on the generation record: BUILDING
        records are atomically promoted to SEALING only when no staging batch is
        reserved, preventing any staging write from racing with the seal. A
        retry resumes an interrupted seal only by reproducing the exact same
        count. SEALED records are immutable and never reopened.
        """
        await self.readiness()
        nonblank_identifier(stream_id, "stream_id")
        nonblank_identifier(generation_id, "generation_id")
        nonblank_identifier(role_dna_id, "role_dna_id")
        nonblank_identifier(opportunity_spec_id, "opportunity_spec_id")
        positive_entity_version(stream_version, "stream_version")
        positive_entity_version(requirement_version, "requirement_version")
        positive_entity_version(role_dna_version, "role_dna_version")
        positive_entity_version(opportunity_spec_version, "opportunity_spec_version")
        if isinstance(candidate_count, bool) or type(candidate_count) is not int or candidate_count < 0:
            raise StreamCandidateRepositoryError(
                "b7 seal requires a non-negative int candidate_count"
            )

        record = await self._read_generation_record(stream_id, generation_id)
        if record is None:
            raise StreamCandidateConflictError("b7 generation is not registered")
        if not self._generation_scope_matches(
            record,
            stream_id=stream_id,
            generation_id=generation_id,
            stream_version=stream_version,
            requirement_version=requirement_version,
            role_dna_id=role_dna_id,
            role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
        ):
            raise StreamCandidateConflictError("b7 generation scope mismatch")
        if record.state is GenerationState.SEALED:
            if record.candidate_count == candidate_count:
                return record
            raise StreamCandidateConflictError(
                "b7 sealed generation candidate count mismatch"
            )
        record_id = generation_record_document_id(stream_id, generation_id)
        if record.state is GenerationState.SEALING:
            if record.candidate_count != candidate_count:
                raise StreamCandidateConflictError(
                    "b7 interrupted seal retry count mismatch"
                )
        else:
            acquired = False
            for _ in range(2):
                try:
                    result = await self.generations.update_one(
                        {
                            "_id": record_id,
                            "state": GenerationState.BUILDING.value,
                            "staging_batch_id": {"$exists": False},
                        },
                        {
                            "$set": {
                                "state": GenerationState.SEALING.value,
                                "candidate_count": int(candidate_count),
                            }
                        },
                    )
                except PyMongoError:
                    raise StreamCandidateRepositoryError(
                        "b7 generation seal failed"
                    ) from None
                if result.matched_count:
                    acquired = True
                    break
                current = await self._read_generation_record(stream_id, generation_id)
                if current is None:
                    raise StreamCandidateConflictError("b7 generation is not registered")
                if not self._generation_scope_matches(
                    current,
                    stream_id=stream_id,
                    generation_id=generation_id,
                    stream_version=stream_version,
                    requirement_version=requirement_version,
                    role_dna_id=role_dna_id,
                    role_dna_version=role_dna_version,
                    opportunity_spec_id=opportunity_spec_id,
                    opportunity_spec_version=opportunity_spec_version,
                ):
                    raise StreamCandidateConflictError("b7 generation scope mismatch")
                if current.state is GenerationState.SEALED:
                    if current.candidate_count == candidate_count:
                        return current
                    raise StreamCandidateConflictError(
                        "b7 sealed generation candidate count mismatch"
                    )
                if current.state is GenerationState.SEALING:
                    if current.candidate_count != candidate_count:
                        raise StreamCandidateConflictError(
                            "b7 interrupted seal retry count mismatch"
                        )
                    acquired = True
                    break
                if current.staging_batch_id is not None:
                    raise StreamCandidateConflictError(_SEAL_CONFLICT_MSG)
            if not acquired:
                raise StreamCandidateConflictError(_SEAL_CONFLICT_MSG)

        documents = await self._read_generation_documents(stream_id, generation_id)
        self._verify_generation_documents(
            documents,
            stream_id=stream_id,
            generation_id=generation_id,
            stream_version=stream_version,
            requirement_version=requirement_version,
            role_dna_id=role_dna_id,
            role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
            expected_candidate_count=candidate_count,
        )

        try:
            result = await self.generations.update_one(
                {"_id": record_id, "state": GenerationState.SEALING.value},
                {"$set": {"state": GenerationState.SEALED.value}},
            )
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 generation seal failed"
            ) from None
        if result.matched_count == 0:
            current = await self._read_generation_record(stream_id, generation_id)
            if (
                current is not None
                and current.state is GenerationState.SEALED
                and current.candidate_count == candidate_count
            ):
                return current
            raise StreamCandidateConflictError(_SEAL_CONFLICT_MSG)
        sealed = await self._read_generation_record(stream_id, generation_id)
        if sealed is None or sealed.state is not GenerationState.SEALED:
            raise StreamCandidateRepositoryError("b7 generation seal failed")
        return sealed

    @staticmethod
    def _same_publication(
        state,
        *,
        target_state_version,
        generation_id,
        stream_version,
        requirement_version,
        role_dna_id,
        role_dna_version,
        opportunity_spec_id,
        opportunity_spec_version,
        candidate_count,
        published_at,
    ):
        return (
            state.active_generation_id == generation_id
            and state.state_version == target_state_version
            and state.stream_version == stream_version
            and state.requirement_version == requirement_version
            and state.role_dna_id == role_dna_id
            and state.role_dna_version == role_dna_version
            and state.opportunity_spec_id == opportunity_spec_id
            and state.opportunity_spec_version == opportunity_spec_version
            and state.candidate_count == candidate_count
            and state.published_at == published_at
        )

    def _scope_matches(self, candidate, *, stream_id, generation_id, stream_version,
                       requirement_version, role_dna_id, role_dna_version,
                       opportunity_spec_id, opportunity_spec_version):
        return (
            candidate.stream_id == stream_id
            and candidate.generation_id == generation_id
            and candidate.stream_version == stream_version
            and candidate.requirement_version == requirement_version
            and candidate.role_dna_id == role_dna_id
            and candidate.role_dna_version == role_dna_version
            and candidate.opportunity_spec_id == opportunity_spec_id
            and candidate.opportunity_spec_version == opportunity_spec_version
        )

    @staticmethod
    def _generation_scope_matches(record, *, stream_id, generation_id,
                                  stream_version, requirement_version,
                                  role_dna_id, role_dna_version,
                                  opportunity_spec_id, opportunity_spec_version):
        return (
            record.stream_id == stream_id
            and record.generation_id == generation_id
            and record.stream_version == stream_version
            and record.requirement_version == requirement_version
            and record.role_dna_id == role_dna_id
            and record.role_dna_version == role_dna_version
            and record.opportunity_spec_id == opportunity_spec_id
            and record.opportunity_spec_version == opportunity_spec_version
        )

    def _verify_generation_documents(
        self, documents, *, stream_id, generation_id, stream_version,
        requirement_version, role_dna_id, role_dna_version,
        opportunity_spec_id, opportunity_spec_version, expected_candidate_count,
    ):
        candidates = []
        for document in documents:
            try:
                candidate = stream_candidate_from_document(document)
            except (ValueError, TypeError, KeyError, OverflowError):
                raise StreamCandidateRepositoryError(
                    "b7 staged generation has a malformed candidate document"
                ) from None
            if not self._scope_matches(
                candidate,
                stream_id=stream_id,
                generation_id=generation_id,
                stream_version=stream_version,
                requirement_version=requirement_version,
                role_dna_id=role_dna_id,
                role_dna_version=role_dna_version,
                opportunity_spec_id=opportunity_spec_id,
                opportunity_spec_version=opportunity_spec_version,
            ):
                raise StreamCandidateConflictError("b7 staged generation scope mismatch")
            candidates.append(candidate)
        if len(candidates) != expected_candidate_count:
            raise StreamCandidateConflictError("b7 generation candidate count mismatch")
        if len({candidate.candidate_id for candidate in candidates}) != len(candidates):
            raise StreamCandidateConflictError("b7 generation has duplicate candidates")

    async def publish_generation(
        self,
        stream_id,
        *,
        generation_id,
        stream_version,
        requirement_version,
        role_dna_id,
        role_dna_version,
        opportunity_spec_id,
        opportunity_spec_version,
        expected_candidate_count,
        expected_state,
        published_at,
    ):
        """Atomically publish one complete generation; exactly one writer wins.

        The caller MUST provide an explicit UTC/millisecond-precision
        publication timestamp; the repository never reads a clock.
        """
        await self.readiness()
        nonblank_identifier(stream_id, "stream_id")
        nonblank_identifier(generation_id, "generation_id")
        nonblank_identifier(role_dna_id, "role_dna_id")
        nonblank_identifier(opportunity_spec_id, "opportunity_spec_id")
        positive_entity_version(stream_version, "stream_version")
        positive_entity_version(requirement_version, "requirement_version")
        positive_entity_version(role_dna_version, "role_dna_version")
        positive_entity_version(opportunity_spec_version, "opportunity_spec_version")
        if expected_state is not None and expected_state.stream_id != stream_id:
            raise StreamCandidateConflictError(_PROJECTION_STATE_MISMATCH_MSG)
        try:
            published_at = utc_millisecond(published_at, "published_at")
        except ValueError:
            raise ValueError(
                "invalid stream candidate publication timestamp"
            ) from None

        record = await self._read_generation_record(stream_id, generation_id)
        if record is None:
            raise StreamCandidateConflictError("b7 generation is not registered")
        if not self._generation_scope_matches(
            record,
            stream_id=stream_id,
            generation_id=generation_id,
            stream_version=stream_version,
            requirement_version=requirement_version,
            role_dna_id=role_dna_id,
            role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
        ):
            raise StreamCandidateConflictError("b7 generation scope mismatch")
        if record.state is not GenerationState.SEALED:
            raise StreamCandidateConflictError("b7 generation is not sealed")
        if record.candidate_count != expected_candidate_count:
            raise StreamCandidateConflictError(
                "b7 sealed generation candidate count mismatch"
            )

        documents = await self._read_generation_documents(stream_id, generation_id)
        self._verify_generation_documents(
            documents,
            stream_id=stream_id,
            generation_id=generation_id,
            stream_version=stream_version,
            requirement_version=requirement_version,
            role_dna_id=role_dna_id,
            role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
            expected_candidate_count=expected_candidate_count,
        )

        current = await self._read_state(stream_id)
        metadata = {
            "generation_id": generation_id,
            "stream_version": stream_version,
            "requirement_version": requirement_version,
            "role_dna_id": role_dna_id,
            "role_dna_version": role_dna_version,
            "opportunity_spec_id": opportunity_spec_id,
            "opportunity_spec_version": opportunity_spec_version,
            "candidate_count": expected_candidate_count,
        }
        if current is None and expected_state is not None:
            raise StreamCandidateConflictError(_PROJECTION_STATE_MISMATCH_MSG)
        if current is None:
            target = ProjectionState(
                stream_id=stream_id,
                state_version=1,
                active_generation_id=generation_id,
                stream_version=stream_version,
                requirement_version=requirement_version,
                role_dna_id=role_dna_id,
                role_dna_version=role_dna_version,
                opportunity_spec_id=opportunity_spec_id,
                opportunity_spec_version=opportunity_spec_version,
                candidate_count=expected_candidate_count,
                published_at=published_at,
            )
            try:
                await self.states.insert_one(projection_state_to_document(target))
                return target
            except DuplicateKeyError:
                pass
            except PyMongoError:
                raise StreamCandidateRepositoryError(
                    "b7 projection publish insert failed"
                ) from None
            winner = await self._read_state(stream_id)
            if winner is not None and self._same_publication(
                winner,
                target_state_version=1,
                **metadata,
                published_at=published_at,
            ):
                return winner
            raise StreamCandidateConflictError(_PROJECTION_PUBLISH_CONFLICT_MSG)
        if current.active_generation_id == generation_id:
            if self._same_publication(
                current,
                target_state_version=current.state_version,
                **metadata,
                published_at=published_at,
            ):
                return current
            raise StreamCandidateConflictError(_PROJECTION_PUBLISH_CONFLICT_MSG)
        if expected_state is None or expected_state != current:
            raise StreamCandidateConflictError(_PROJECTION_STATE_MISMATCH_MSG)
        target = ProjectionState(
            stream_id=stream_id,
            state_version=current.state_version + 1,
            active_generation_id=generation_id,
            stream_version=stream_version,
            requirement_version=requirement_version,
            role_dna_id=role_dna_id,
            role_dna_version=role_dna_version,
            opportunity_spec_id=opportunity_spec_id,
            opportunity_spec_version=opportunity_spec_version,
            candidate_count=expected_candidate_count,
            published_at=published_at,
        )
        filter_document = {
            "_id": stream_id,
            "state_version": current.state_version,
            "active_generation_id": current.active_generation_id,
            "stream_version": current.stream_version,
            "requirement_version": current.requirement_version,
            "role_dna_id": current.role_dna_id,
            "opportunity_spec_id": current.opportunity_spec_id,
        }
        try:
            result = await self.states.update_one(
                filter_document,
                {
                    "$set": {
                        key: value
                        for key, value in projection_state_to_document(target).items()
                        if key != "_id"
                    }
                },
            )
        except PyMongoError:
            raise StreamCandidateRepositoryError(
                "b7 projection publish update failed"
            ) from None
        if result.matched_count == 0:
            winner = await self._read_state(stream_id)
            if winner is not None and self._same_publication(
                winner,
                target_state_version=current.state_version + 1,
                **metadata,
                published_at=published_at,
            ):
                return winner
            raise StreamCandidateConflictError(_PROJECTION_PUBLISH_CONFLICT_MSG)
        return target
