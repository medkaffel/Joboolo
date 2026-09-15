"""B7 Stream Candidate projection persistence: staging, CAS publications, reads.

Owns exactly the two B7 collections. No Applications/A11/SavedJob/Discovery
reads, no runtime index creation, no auto repair, and a fixed redacted repository
error. A published generation is immutable unless a retry reproduces an already
identical document.
"""
from datetime import datetime, timezone

from pymongo import ReadPreference
from pymongo.errors import DuplicateKeyError, PyMongoError
from pymongo.write_concern import WriteConcern

from domains.talent_stream.index_requirements import (
    TALENT_STREAM_CANDIDATE_PROJECTION_STATES_REQUIREMENT,
    TALENT_STREAM_CANDIDATES_REQUIREMENT,
)
from domains.talent_stream.stream_candidate_models import StreamCandidate
from domains.talent_stream.stream_candidate_persistence import (
    ProjectionState,
    candidate_document_id,
    projection_state_from_document,
    projection_state_to_document,
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
)

_PROJECTION_PUBLISH_CONFLICT_MSG = "b7 projection publish conflict"
_PROJECTION_STATE_MISMATCH_MSG = "b7 expected projection state mismatch"


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

    async def readiness(self):
        """Verify only the two A13 B7 requirements; never repair or migrate."""
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

    async def get_projection_state(self, stream_id):
        """Return the current ProjectionState or None. No candidate data."""
        await self.readiness()
        return await self._read_state(stream_id)

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
        """Persist an immutable generation batch; exact retries are idempotent."""
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

        active_generation = None
        state = await self._read_state(first.stream_id)
        if state is not None:
            active_generation = state.active_generation_id

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
            if active_generation == candidate.generation_id:
                raise StreamCandidateConflictError(
                    "b7 cannot mutate an active generation"
                )
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
        return {
            "stream_id": first.stream_id,
            "generation_id": first.generation_id,
            "staged": staged,
            "idempotent_retries": idempotent,
        }

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
        published_at=None,
    ):
        """Atomically publish one complete generation; exactly one writer wins."""
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
        if published_at is None:
            published_at = datetime.now(timezone.utc)
        else:
            try:
                published_at = utc_millisecond(published_at, "published_at")
            except ValueError:
                raise ValueError(
                    "invalid stream candidate publication timestamp"
                ) from None

        documents = await self._read_generation_documents(stream_id, generation_id)
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