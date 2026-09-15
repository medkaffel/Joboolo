"""TS-B7 STEP 3: in-memory, read-only Stream Candidate aggregation.

Builds one immutable BuiltStreamCandidateGeneration from the exact B1 Stream
scope, the B3 exact Opportunity specification and Applications, the canonical
B4/B5 reducer over A11 Intent event documents, the B5 SavedJob-cycle
verification and the B6 Discovery Pool. No writes, no staging, no publishing,
no Permission/Trust/Grant/CV/Contact Governor reads. Every stored-source
deviation fails closed. No candidate identity, Job identity or event value is
ever echoed into an error message.
"""
from dataclasses import dataclass
from datetime import datetime, timezone

from domains.shared.versioning import EntityVersion
from domains.talent_stream.application_source_models import ApplicationSourceCursor
from domains.talent_stream.application_source_repository import (
    ApplicationSourceReadinessError,
    ApplicationSourceRepositoryError,
)
from domains.talent_stream.application_source_service import (
    ApplicationSourceAccessError,
    ApplicationSourceConflictError,
    ApplicationSourceService,
    ApplicationSourceStoredDataError,
    MAX_APPLICATION_SOURCE_PAGE_SIZE,
)
from domains.talent_stream.discovery_pool_repository import (
    DiscoveryPoolReadinessError,
    DiscoveryPoolRepositoryError,
)
from domains.talent_stream.discovery_pool_service import (
    DiscoveryPoolAccessError,
    DiscoveryPoolConflictError,
    DiscoveryPoolService,
    DiscoveryPoolStoredDataError,
    MAX_DISCOVERY_POOL_SCAN_PAGE_SIZE,
)
from domains.talent_stream.shared_favorite_repository import (
    SAVED_JOB_FIELDS,
    SharedFavoriteReadinessError,
    SharedFavoriteRepositoryError,
    SharedFavoriteRepository,
    SharedFavoriteRepositoryError,
)
from domains.talent_stream.stream_candidate_intent_source import (
    B4_EVENT_TYPE,
    B5_SHARE_EVENT_TYPE,
    B5_WITHDRAW_EVENT_TYPE,
    reduce_intent_sources,
)
from domains.talent_stream.stream_candidate_models import (
    ApplicationEvidence,
    DeclaredInterestEvidence,
    DiscoveryEvidence,
    OpportunityFitSummary,
    ProfessionalMatchSummary,
    StreamCandidate,
)
from domains.talent_stream.stream_candidate_source_repository import (
    INTENT_EVENT_PAGE_LIMIT,
    StreamCandidateSourceReadinessError,
    StreamCandidateSourceRepository,
    StreamCandidateSourceRepositoryError,
    StreamCandidateSourceStoredDataError,
)
from domains.talent_stream.stream_models import (
    TalentStreamState,
    nonblank_identifier,
    positive_entity_version,
    utc_millisecond,
)
from domains.talent_stream.stream_repository import (
    TalentStreamReadinessError,
    TalentStreamRepository,
    TalentStreamRepositoryError,
    TalentStreamStoredDataError,
)


class StreamCandidateAggregationAccessError(LookupError):
    pass


class StreamCandidateAggregationReadinessError(RuntimeError):
    pass


class StreamCandidateAggregationStoredDataError(RuntimeError):
    pass


class StreamCandidateAggregationConflictError(RuntimeError):
    pass


_AGGREGATION_ACCESS_MSG = "stream candidate aggregation not authorized"
_AGGREGATION_READINESS_MSG = "stream candidate aggregation storage is not ready"
_AGGREGATION_STORED_MSG = "invalid stored stream candidate source"
_AGGREGATION_CONFLICT_MSG = "stream candidate aggregation scope changed"

_INTENT_EVENT_TYPES = (
    str(B4_EVENT_TYPE),
    str(B5_SHARE_EVENT_TYPE),
    str(B5_WITHDRAW_EVENT_TYPE),
)


@dataclass(frozen=True, slots=True, repr=False)
class BuiltStreamCandidateGeneration:
    """Immutable B7 STEP 3 aggregation result; deterministic by contract."""

    stream_id: str
    stream_version: EntityVersion
    requirement_version: EntityVersion
    generation_id: str
    role_dna_id: str
    role_dna_version: EntityVersion
    opportunity_spec_id: str
    opportunity_spec_version: EntityVersion
    candidates: tuple[StreamCandidate, ...]
    computed_at: datetime

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def __post_init__(self) -> None:
        nonblank_identifier(self.stream_id, "stream_id")
        object.__setattr__(
            self,
            "stream_version",
            positive_entity_version(self.stream_version, "stream_version"),
        )
        object.__setattr__(
            self,
            "requirement_version",
            positive_entity_version(self.requirement_version, "requirement_version"),
        )
        nonblank_identifier(self.generation_id, "generation_id")
        nonblank_identifier(self.role_dna_id, "role_dna_id")
        object.__setattr__(
            self,
            "role_dna_version",
            positive_entity_version(self.role_dna_version, "role_dna_version"),
        )
        nonblank_identifier(self.opportunity_spec_id, "opportunity_spec_id")
        object.__setattr__(
            self,
            "opportunity_spec_version",
            positive_entity_version(self.opportunity_spec_version, "opportunity_spec_version"),
        )
        object.__setattr__(
            self,
            "computed_at",
            utc_millisecond(self.computed_at, "computed_at"),
        )
        if type(self.candidates) is not tuple:
            raise ValueError("candidates must be an immutable tuple")
        scope = (
            str(self.stream_id),
            int(self.stream_version),
            int(self.requirement_version),
            self.generation_id,
            str(self.role_dna_id),
            int(self.role_dna_version),
            str(self.opportunity_spec_id),
            int(self.opportunity_spec_version),
        )
        candidate_ids = []
        for candidate in self.candidates:
            if type(candidate) is not StreamCandidate:
                raise ValueError("invalid Stream candidate in generation")
            candidate_scope = (
                str(candidate.stream_id),
                int(candidate.stream_version),
                int(candidate.requirement_version),
                candidate.generation_id,
                str(candidate.role_dna_id),
                int(candidate.role_dna_version),
                str(candidate.opportunity_spec_id),
                int(candidate.opportunity_spec_version),
            )
            if candidate_scope != scope:
                raise ValueError("Stream candidate generation scope mismatch")
            if candidate.computed_at is None or candidate.computed_at != self.computed_at:
                raise ValueError("Stream candidate generation computed_at mismatch")
            candidate_ids.append(str(candidate.candidate_id))
        if len(set(candidate_ids)) != len(self.candidates) or candidate_ids != sorted(candidate_ids):
            raise ValueError("Stream candidate generation must be ordered and unique")


class StreamCandidateAggregationService:
    def __init__(self, db):
        self.streams = TalentStreamRepository(db)
        self.sources = StreamCandidateSourceRepository(db)
        self.applications = ApplicationSourceService(db)
        self.saved_favorites = SharedFavoriteRepository(db)
        self.discovery = DiscoveryPoolService(db)

    @staticmethod
    def _scope_fingerprint(stream):
        return (
            str(stream.stream_id),
            int(stream.version),
            stream.state,
            stream.recruiting_actor_context,
            stream.requirement_snapshot,
        )

    @staticmethod
    def _scope_snapshot(stream):
        actor = stream.recruiting_actor_context
        requirement = stream.requirement_snapshot
        return {
            "stream_id": str(stream.stream_id),
            "stream_version": int(stream.version),
            "recruiter_id": str(actor.recruiter_user_id),
            "requirement_version": int(requirement.requirement_version),
            "role_dna_id": str(requirement.role_dna.role_dna_id),
            "role_dna_version": int(requirement.role_dna.version),
            "opportunity_spec_id": str(requirement.opportunity_spec.opportunity_spec_id),
            "opportunity_spec_version": int(requirement.opportunity_spec.version),
        }

    async def _active_stream(self, stream_id):
        try:
            await self.streams.readiness()
        except TalentStreamReadinessError:
            raise StreamCandidateAggregationReadinessError(
                _AGGREGATION_READINESS_MSG
            ) from None
        except (TalentStreamStoredDataError, TalentStreamRepositoryError):
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        except Exception:
            raise StreamCandidateAggregationReadinessError(
                _AGGREGATION_READINESS_MSG
            ) from None
        try:
            stream = await self.streams.get(stream_id)
        except (TalentStreamStoredDataError, TalentStreamRepositoryError):
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        if stream is None:
            raise StreamCandidateAggregationAccessError(_AGGREGATION_ACCESS_MSG)
        if stream.state is not TalentStreamState.ACTIVE:
            raise StreamCandidateAggregationAccessError(_AGGREGATION_ACCESS_MSG)
        return stream

    @staticmethod
    def _stored_utc(value):
        if type(value) is not datetime:
            raise StreamCandidateAggregationStoredDataError(_AGGREGATION_STORED_MSG)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        try:
            value = value.astimezone(timezone.utc)
        except (OverflowError, TypeError, ValueError):
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        if value.microsecond % 1000:
            raise StreamCandidateAggregationStoredDataError(_AGGREGATION_STORED_MSG)
        return value

    @staticmethod
    def _computed_at_millisecond(value):
        """Floor a live engine timestamp to canonical millisecond precision.

        Professional Skill match and Opportunity Fit engines stamp their results
        with datetime.now(timezone.utc) (arbitrary microseconds). The aggregation
        canonical computed_at invariant is millisecond precision, so the summary
        floors the engine timestamp deterministically instead of failing closed
        on a precision the engine does not control.
        """
        if type(value) is not datetime:
            raise StreamCandidateAggregationStoredDataError(_AGGREGATION_STORED_MSG)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        try:
            value = value.astimezone(timezone.utc)
        except (OverflowError, TypeError, ValueError):
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)

    async def _read_applications(self, scope, source_job_id):
        stream_id = scope["stream_id"]
        recruiter_id = scope["recruiter_id"]
        applications = {}
        seen_application_ids = set()
        expected_after = None
        while True:
            try:
                page = await self.applications.list_page(
                    recruiter_id,
                    stream_id,
                    after=expected_after,
                    limit=MAX_APPLICATION_SOURCE_PAGE_SIZE,
                )
            except ApplicationSourceConflictError:
                raise StreamCandidateAggregationConflictError(
                    _AGGREGATION_CONFLICT_MSG
                ) from None
            except ApplicationSourceReadinessError:
                raise StreamCandidateAggregationReadinessError(
                    _AGGREGATION_READINESS_MSG
                ) from None
            except (
                ApplicationSourceAccessError,
                ApplicationSourceStoredDataError,
                ApplicationSourceRepositoryError,
                TalentStreamStoredDataError,
            ):
                raise StreamCandidateAggregationStoredDataError(
                    _AGGREGATION_STORED_MSG
                ) from None

            boundary = None
            if expected_after is not None:
                boundary = (
                    expected_after.applied_at,
                    str(expected_after.application_id),
                )
            for source in page:
                position = (source.applied_at, str(source.application_id))
                if boundary is not None and position <= boundary:
                    raise StreamCandidateAggregationStoredDataError(
                        _AGGREGATION_STORED_MSG
                    )
                boundary = position
                application_id = str(source.application_id)
                candidate_id = str(source.candidate_id)
                if application_id in seen_application_ids or candidate_id in applications:
                    raise StreamCandidateAggregationStoredDataError(
                        _AGGREGATION_STORED_MSG
                    )
                if str(source.job_id) != source_job_id:
                    raise StreamCandidateAggregationStoredDataError(
                        _AGGREGATION_STORED_MSG
                    )
                seen_application_ids.add(application_id)
                applications[candidate_id] = ApplicationEvidence(
                    application_id=application_id,
                    status=source.status.value,
                    applied_at=source.applied_at,
                )
            if len(page) < MAX_APPLICATION_SOURCE_PAGE_SIZE:
                break
            if not page:
                break
            last = page[-1]
            expected_after = ApplicationSourceCursor(
                stream_id=stream_id,
                job_id=source_job_id,
                applied_at=last.applied_at,
                application_id=str(last.application_id),
            )
        return applications

    async def _read_intent_documents(self, source_job_id):
        try:
            await self.sources.readiness_intent()
        except StreamCandidateSourceReadinessError:
            raise StreamCandidateAggregationReadinessError(
                _AGGREGATION_READINESS_MSG
            ) from None
        except StreamCandidateSourceRepositoryError:
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None

        documents = []
        seen_event_ids = set()
        for event_type in _INTENT_EVENT_TYPES:
            previous = None
            while True:
                try:
                    batch, next_cursor = await self.sources.list_intent_events(
                        source_job_id,
                        event_type,
                        after_event=previous,
                        limit=INTENT_EVENT_PAGE_LIMIT,
                    )
                except StreamCandidateSourceStoredDataError:
                    raise StreamCandidateAggregationStoredDataError(
                        _AGGREGATION_STORED_MSG
                    ) from None
                except StreamCandidateSourceRepositoryError:
                    raise StreamCandidateAggregationStoredDataError(
                        _AGGREGATION_STORED_MSG
                    ) from None
                for document in batch:
                    raw_job = document.get("job_id")
                    if raw_job is None or str(raw_job) != str(source_job_id):
                        raise StreamCandidateAggregationStoredDataError(
                            _AGGREGATION_STORED_MSG
                        )
                    event_id = document["_id"]
                    if event_id in seen_event_ids:
                        raise StreamCandidateAggregationStoredDataError(
                            _AGGREGATION_STORED_MSG
                        )
                    seen_event_ids.add(event_id)
                documents.extend(batch)
                if next_cursor is None:
                    break
                if not batch:
                    raise StreamCandidateAggregationStoredDataError(
                        _AGGREGATION_STORED_MSG
                    )
                previous = next_cursor
        return documents

    async def _read_intent_sources(self, source_job_id):
        documents = await self._read_intent_documents(source_job_id)
        try:
            reduced = reduce_intent_sources(documents, source_job_id)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        declared = {}
        shared = {}
        for candidate_id, sources in reduced.by_candidate:
            candidate = str(candidate_id)
            if sources.declared_interest is not None:
                declared[candidate] = sources.declared_interest
            if sources.shared_favorites:
                shared[candidate] = sources.shared_favorites
        return declared, shared

    def _validate_saved_job(self, saved, candidate_id, job_id, correlation_id):
        if type(saved) is not dict or set(saved) != set(SAVED_JOB_FIELDS):
            raise StreamCandidateAggregationStoredDataError(_AGGREGATION_STORED_MSG)
        try:
            stored_id = nonblank_identifier(saved["_id"], "_id")
            stored_user = nonblank_identifier(saved["user_id"], "user_id")
            stored_job = nonblank_identifier(saved["job_id"], "job_id")
        except (KeyError, TypeError, ValueError):
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        if (
            stored_id != correlation_id
            or stored_user != candidate_id
            or stored_job != job_id
        ):
            raise StreamCandidateAggregationStoredDataError(_AGGREGATION_STORED_MSG)
        created_at = self._stored_utc(saved["created_at"])
        updated_at = self._stored_utc(saved["updated_at"])
        if updated_at < created_at:
            raise StreamCandidateAggregationStoredDataError(_AGGREGATION_STORED_MSG)

    async def _read_shared_favorites(self, shared_by_candidate, source_job_id):
        if not shared_by_candidate:
            return {}
        try:
            await self.saved_favorites.saved_jobs_readiness()
        except SharedFavoriteReadinessError:
            raise StreamCandidateAggregationReadinessError(
                _AGGREGATION_READINESS_MSG
            ) from None
        except SharedFavoriteRepositoryError:
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        except Exception:
            raise StreamCandidateAggregationReadinessError(
                _AGGREGATION_READINESS_MSG
            ) from None

        validated = {}
        for candidate_id, favorites in sorted(shared_by_candidate.items()):
            kept = []
            for favorite in favorites:
                try:
                    saved = await self.saved_favorites.get_saved_job(
                        candidate_id, source_job_id, favorite.correlation_id,
                    )
                except SharedFavoriteRepositoryError:
                    raise StreamCandidateAggregationStoredDataError(
                        _AGGREGATION_STORED_MSG
                    ) from None
                if saved is None:
                    continue
                self._validate_saved_job(
                    saved, candidate_id, source_job_id, favorite.correlation_id
                )
                kept.append(favorite)
            if kept:
                validated[candidate_id] = tuple(
                    sorted(kept, key=lambda ev: (ev.occurred_at, str(ev.event_id)))
                )
        return validated

    @staticmethod
    def _b5_representative(favorites):
        """Reduce multiple validated active shares to the deterministic latest.

        All validated shares are kept in memory only; the StreamCandidate model
        carries a single representative. The reducer order (occurred_at, event_id)
        is authoritative, and the last share is the most recent one.
        """
        if not favorites:
            return None
        return favorites[-1]

    async def _read_discovery(self, stream_id):
        discovery = {}
        expected_after = None
        observed_after = None
        while True:
            try:
                page = await self.discovery.list_page(
                    stream_id,
                    after=expected_after,
                    limit=MAX_DISCOVERY_POOL_SCAN_PAGE_SIZE,
                )
            except DiscoveryPoolConflictError:
                raise StreamCandidateAggregationConflictError(
                    _AGGREGATION_CONFLICT_MSG
                ) from None
            except DiscoveryPoolReadinessError:
                raise StreamCandidateAggregationReadinessError(
                    _AGGREGATION_READINESS_MSG
                ) from None
            except (
                DiscoveryPoolAccessError,
                DiscoveryPoolStoredDataError,
                DiscoveryPoolRepositoryError,
            ):
                raise StreamCandidateAggregationStoredDataError(
                    _AGGREGATION_STORED_MSG
                ) from None
            for item in page.items:
                candidate_id = str(item.candidate_id)
                if candidate_id in discovery:
                    raise StreamCandidateAggregationStoredDataError(
                        _AGGREGATION_STORED_MSG
                    )
                discovery[candidate_id] = item
            if page.next_cursor is None:
                break
            after = str(page.next_cursor.after_candidate_id)
            if observed_after is not None and after <= observed_after:
                raise StreamCandidateAggregationStoredDataError(
                    _AGGREGATION_STORED_MSG
                )
            observed_after = after
            expected_after = page.next_cursor
        return discovery

    def _map_discovery(self, item, scope):
        candidate_id = str(item.candidate_id)
        match = item.professional_match
        fit = item.opportunity_fit
        if (
            str(match.candidate_id) != candidate_id
            or str(fit.candidate_id) != candidate_id
            or str(match.role_dna_id) != scope["role_dna_id"]
            or int(match.role_dna_version) != scope["role_dna_version"]
            or str(fit.opportunity_spec_id) != scope["opportunity_spec_id"]
            or int(fit.opportunity_spec_version) != scope["opportunity_spec_version"]
        ):
            raise StreamCandidateAggregationStoredDataError(_AGGREGATION_STORED_MSG)
        state = item.discovery_state
        discovery_evidence = DiscoveryEvidence(
            candidate_preferences_version=int(state.preferences_version),
            updated_at=self._stored_utc(state.updated_at),
        )
        professional_match_summary = ProfessionalMatchSummary(
            candidate_profile_version=int(match.candidate_profile_version),
            role_dna_version=int(match.role_dna_version),
            match_engine_version=str(match.match_engine_version),
            professional_match_score=int(match.professional_match_score),
            evidence_coverage=int(match.evidence_coverage),
            computed_at=self._computed_at_millisecond(match.computed_at),
        )
        opportunity_fit_summary = OpportunityFitSummary(
            candidate_preferences_version=int(fit.candidate_preferences_version),
            opportunity_spec_version=int(fit.opportunity_spec_version),
            fit_engine_version=str(fit.engine_version),
            hard_eligibility_state=fit.hard_eligibility_state,
            opportunity_fit_state=fit.opportunity_fit_state,
            evidence_coverage=int(fit.evidence_coverage),
            computed_at=self._computed_at_millisecond(fit.computed_at),
        )
        return discovery_evidence, professional_match_summary, opportunity_fit_summary

    def _assemble_candidates(
        self, stream, scope, generation_id, computed_at, applications,
        declared, shared_validated, discovery,
    ):
        discovery_map = {}
        for candidate_id, item in sorted(discovery.items()):
            discovery_map[candidate_id] = self._map_discovery(item, scope)
        candidate_ids = sorted(
            set(applications) | set(declared) | set(shared_validated) | set(discovery_map)
        )
        candidates = []
        for candidate_id in candidate_ids:
            discovery_entry = discovery_map.get(candidate_id)
            favorites = shared_validated.get(candidate_id)
            candidates.append(StreamCandidate(
                stream_id=stream.stream_id,
                stream_version=scope["stream_version"],
                requirement_version=scope["requirement_version"],
                generation_id=generation_id,
                candidate_id=candidate_id,
                role_dna_id=scope["role_dna_id"],
                role_dna_version=scope["role_dna_version"],
                opportunity_spec_id=scope["opportunity_spec_id"],
                opportunity_spec_version=scope["opportunity_spec_version"],
                application_evidence=applications.get(candidate_id),
                declared_interest_evidence=declared.get(candidate_id),
                shared_favorite_evidence=self._b5_representative(favorites),
                discovery_evidence=None if discovery_entry is None else discovery_entry[0],
                professional_match_summary=None if discovery_entry is None else discovery_entry[1],
                opportunity_fit_summary=None if discovery_entry is None else discovery_entry[2],
                computed_at=computed_at,
            ))
        return tuple(candidates)

    async def _revalidate_scope(self, scope, fingerprint, opportunity):
        try:
            reloaded = await self.streams.get(scope["stream_id"])
        except (TalentStreamStoredDataError, TalentStreamRepositoryError):
            raise StreamCandidateAggregationConflictError(
                _AGGREGATION_CONFLICT_MSG
            ) from None
        if reloaded is None or self._scope_fingerprint(reloaded) != fingerprint:
            raise StreamCandidateAggregationConflictError(_AGGREGATION_CONFLICT_MSG)

        try:
            current_opportunity = await self.sources.get_opportunity(
                scope["opportunity_spec_id"], scope["opportunity_spec_version"],
            )
        except StreamCandidateSourceStoredDataError:
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        except StreamCandidateSourceRepositoryError:
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        if (
            current_opportunity.opportunity_spec_id != opportunity.opportunity_spec_id
            or current_opportunity.version != opportunity.version
            or current_opportunity.source_job_id != opportunity.source_job_id
        ):
            raise StreamCandidateAggregationConflictError(_AGGREGATION_CONFLICT_MSG)

        try:
            await self.applications.list_page(scope["recruiter_id"], scope["stream_id"], limit=1)
        except ApplicationSourceConflictError:
            raise StreamCandidateAggregationConflictError(
                _AGGREGATION_CONFLICT_MSG
            ) from None
        except ApplicationSourceReadinessError:
            raise StreamCandidateAggregationReadinessError(
                _AGGREGATION_READINESS_MSG
            ) from None
        except (
            ApplicationSourceAccessError,
            ApplicationSourceStoredDataError,
            ApplicationSourceRepositoryError,
            TalentStreamStoredDataError,
        ):
            raise StreamCandidateAggregationConflictError(_AGGREGATION_CONFLICT_MSG)

    async def build_generation(self, stream_id, *, generation_id, computed_at):
        """Read-only aggregation of the exact B1 scope into one build result."""
        try:
            stream_id = nonblank_identifier(stream_id, "stream_id")
            generation_id = nonblank_identifier(generation_id, "generation_id")
            computed_at = utc_millisecond(computed_at, "computed_at")
        except ValueError:
            raise ValueError("invalid stream candidate generation identity") from None

        try:
            stream = await self._active_stream(stream_id)
        except (
            StreamCandidateAggregationAccessError,
            StreamCandidateAggregationReadinessError,
            StreamCandidateAggregationStoredDataError,
            StreamCandidateAggregationConflictError,
        ):
            raise

        fingerprint = self._scope_fingerprint(stream)
        scope = self._scope_snapshot(stream)
        opportunity = None
        try:
            opportunity = await self.sources.get_opportunity(
                scope["opportunity_spec_id"], scope["opportunity_spec_version"],
            )
        except StreamCandidateSourceStoredDataError:
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        except StreamCandidateSourceRepositoryError:
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        if (
            opportunity.opportunity_spec_id != scope["opportunity_spec_id"]
            or opportunity.version != scope["opportunity_spec_version"]
        ):
            raise StreamCandidateAggregationStoredDataError(_AGGREGATION_STORED_MSG)

        try:
            applications = await self._read_applications(scope, opportunity.source_job_id)
            declared, shared = await self._read_intent_sources(opportunity.source_job_id)
            shared_validated = await self._read_shared_favorites(
                shared, opportunity.source_job_id,
            )
            discovery = await self._read_discovery(stream_id)
            candidates = self._assemble_candidates(
                stream, scope, generation_id, computed_at, applications, declared,
                shared_validated, discovery,
            )
            result = BuiltStreamCandidateGeneration(
                stream_id=scope["stream_id"],
                stream_version=scope["stream_version"],
                requirement_version=scope["requirement_version"],
                generation_id=generation_id,
                role_dna_id=scope["role_dna_id"],
                role_dna_version=scope["role_dna_version"],
                opportunity_spec_id=scope["opportunity_spec_id"],
                opportunity_spec_version=scope["opportunity_spec_version"],
                candidates=candidates,
                computed_at=computed_at,
            )
            await self._revalidate_scope(scope, fingerprint, opportunity)
        except (
            StreamCandidateAggregationAccessError,
            StreamCandidateAggregationReadinessError,
            StreamCandidateAggregationStoredDataError,
            StreamCandidateAggregationConflictError,
        ):
            raise
        except Exception:
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None
        return result

    async def assert_generation_scope_current(self, generation):
        """Read-only revalidation that a built generation still matches the
        active B1 scope. Never rebuilds, never re-scans candidates, and never
        reads application rows beyond the B3 ownership validation. Raises the
        aggregation fail-closed errors (Readiness/Stored/Conflict) on any
        divergence so the refresh orchestrator can map them."""
        if type(generation) is not BuiltStreamCandidateGeneration:
            raise StreamCandidateAggregationStoredDataError(_AGGREGATION_STORED_MSG)
        stream_id = str(generation.stream_id)
        try:
            reloaded = await self.streams.get(stream_id)
        except TalentStreamReadinessError:
            raise StreamCandidateAggregationReadinessError(
                _AGGREGATION_READINESS_MSG
            ) from None
        except (TalentStreamStoredDataError, TalentStreamRepositoryError):
            raise StreamCandidateAggregationConflictError(
                _AGGREGATION_CONFLICT_MSG
            ) from None
        if reloaded is None or reloaded.state is not TalentStreamState.ACTIVE:
            raise StreamCandidateAggregationConflictError(_AGGREGATION_CONFLICT_MSG)
        snapshot = self._scope_snapshot(reloaded)
        if (
            snapshot["stream_version"] != int(generation.stream_version)
            or snapshot["requirement_version"] != int(generation.requirement_version)
            or snapshot["role_dna_id"] != str(generation.role_dna_id)
            or snapshot["role_dna_version"] != int(generation.role_dna_version)
            or snapshot["opportunity_spec_id"] != str(generation.opportunity_spec_id)
            or snapshot["opportunity_spec_version"]
            != int(generation.opportunity_spec_version)
        ):
            raise StreamCandidateAggregationConflictError(_AGGREGATION_CONFLICT_MSG)
        try:
            await self.applications._scope(snapshot["recruiter_id"], stream_id)
        except ApplicationSourceAccessError:
            raise StreamCandidateAggregationConflictError(
                _AGGREGATION_CONFLICT_MSG
            ) from None
        except ApplicationSourceReadinessError:
            raise StreamCandidateAggregationReadinessError(
                _AGGREGATION_READINESS_MSG
            ) from None
        except (
            ApplicationSourceConflictError,
            ApplicationSourceStoredDataError,
            ApplicationSourceRepositoryError,
            TalentStreamStoredDataError,
        ):
            raise StreamCandidateAggregationStoredDataError(
                _AGGREGATION_STORED_MSG
            ) from None