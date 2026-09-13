"""TS-B6 internal, read-only Discovery Pool orchestration."""
from dataclasses import dataclass
from datetime import datetime, timezone

from bson.int64 import Int64

from domains.matching.models import ProfessionalMatchResult
from domains.matching.opportunity_fit_models import (
    HardEligibilityState,
    OpportunityFitResult,
)
from domains.matching.opportunity_fit_service import (
    OpportunityFitInputNotFoundError,
    OpportunityFitService,
    OpportunityFitSnapshotUnavailableError,
)
from domains.matching.service import (
    MatchInputNotFoundError,
    MatchSnapshotUnavailableError,
    ProfessionalMatchService,
)
from domains.preferences.models import SearchState
from domains.shared.ids import CandidateId
from domains.shared.versioning import EntityVersion
from domains.talent_stream.contracts import DiscoveryState
from domains.talent_stream.discovery_pool_models import (
    DiscoveryPoolCandidate,
    DiscoveryPoolCursor,
    DiscoveryPoolPage,
)
from domains.talent_stream.discovery_pool_repository import DiscoveryPoolRepository
from domains.talent_stream.stream_models import (
    TalentStream,
    TalentStreamState,
    nonblank_identifier,
)
from domains.talent_stream.stream_repository import TalentStreamStoredDataError


MAX_DISCOVERY_POOL_SCAN_PAGE_SIZE = 100


class DiscoveryPoolAccessError(LookupError):
    pass


class DiscoveryPoolStoredDataError(RuntimeError):
    pass


class DiscoveryPoolConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class _StreamScope:
    stream: TalentStream
    fingerprint: tuple


def _stored_identifier(value):
    try:
        return nonblank_identifier(value, "stored identifier")
    except ValueError:
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data") from None


def _stored_version(value):
    if isinstance(value, bool) or not isinstance(value, (int, Int64)) or value < 1:
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data")
    return EntityVersion(int(value))


def _stored_utc(value):
    if type(value) is not datetime:
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    try:
        value = value.astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError):
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data") from None
    if value.microsecond % 1000:
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data")
    return value


def _discovery_from_document(document):
    required = {
        "_id", "candidate_id", "version", "search_state", "discovery",
        "excluded_company_ids", "updated_at",
    }
    if type(document) is not dict or set(document) != required:
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data")
    candidate_id = _stored_identifier(document["candidate_id"])
    if document["_id"] != f"candidate_preferences:{candidate_id}":
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data")
    version = _stored_version(document["version"])
    if type(document["search_state"]) is not str:
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data")
    try:
        SearchState(document["search_state"])
    except ValueError:
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data") from None
    discovery = document["discovery"]
    fields = {
        "enabled", "allow_compatible_opportunities", "ask_before_reveal", "anonymous_only",
    }
    if type(discovery) is not dict or set(discovery) != fields:
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data")
    if any(type(discovery[field]) is not bool for field in fields):
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data")
    excluded = document["excluded_company_ids"]
    if type(excluded) is not list or any(
        type(value) is not str or not value.strip() for value in excluded
    ) or len(excluded) != len(set(excluded)):
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data")
    updated_at = _stored_utc(document["updated_at"])
    try:
        return DiscoveryState(
            candidate_id=CandidateId(candidate_id),
            enabled=discovery["enabled"],
            allow_compatible_opportunities=discovery["allow_compatible_opportunities"],
            ask_before_reveal=discovery["ask_before_reveal"],
            anonymous_only=discovery["anonymous_only"],
            preferences_version=version,
            updated_at=updated_at,
        )
    except ValueError:
        raise DiscoveryPoolStoredDataError("invalid stored Discovery Pool data") from None


def _active_candidate(user, candidate_id):
    return (
        type(user) is dict
        and set(user) == {"_id", "user_type", "is_active"}
        and user["_id"] == candidate_id
        and user["user_type"] == "candidate"
        and user["is_active"] is True
    )


def _scope_fingerprint(stream):
    return (
        str(stream.stream_id),
        int(stream.version),
        stream.state,
        stream.recruiting_actor_context,
        stream.requirement_snapshot,
    )


def _cursor_for(scope, after_candidate_id):
    requirement = scope.stream.requirement_snapshot
    return DiscoveryPoolCursor(
        stream_id=scope.stream.stream_id,
        stream_version=scope.stream.version,
        requirement_version=requirement.requirement_version,
        role_dna_id=requirement.role_dna.role_dna_id,
        role_dna_version=requirement.role_dna.version,
        opportunity_spec_id=requirement.opportunity_spec.opportunity_spec_id,
        opportunity_spec_version=requirement.opportunity_spec.version,
        after_candidate_id=CandidateId(after_candidate_id),
    )


def _cursor_matches(cursor, scope):
    expected = _cursor_for(scope, cursor.after_candidate_id)
    return cursor == expected


class DiscoveryPoolService:
    def __init__(self, db):
        self.repository = DiscoveryPoolRepository(db)
        self.match_service = ProfessionalMatchService(db)
        self.fit_service = OpportunityFitService(db)

    async def _scope(self, stream_id):
        stream_id = nonblank_identifier(stream_id, "stream_id")
        try:
            stream = await self.repository.get_stream(stream_id)
        except TalentStreamStoredDataError:
            raise DiscoveryPoolStoredDataError("invalid stored Talent Stream") from None
        if stream is None or stream.state is not TalentStreamState.ACTIVE:
            raise DiscoveryPoolAccessError("Discovery Pool requires an active Stream")
        return _StreamScope(stream=stream, fingerprint=_scope_fingerprint(stream))

    async def list_page(self, stream_id, *, after=None, limit=100):
        if isinstance(limit, bool) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if after is not None and type(after) is not DiscoveryPoolCursor:
            raise ValueError("invalid Discovery Pool cursor")

        await self.repository.readiness()
        before = await self._scope(stream_id)
        if after is not None and not _cursor_matches(after, before):
            raise ValueError("Discovery Pool cursor does not match Stream scope")
        documents = await self.repository.list_preferences(
            after_candidate_id=None if after is None else str(after.after_candidate_id),
            limit=limit + 1,
        )
        consumed_documents = documents[:limit]
        has_more = len(documents) > limit
        items = []
        last_candidate_id = None
        for document in consumed_documents:
            discovery = _discovery_from_document(document)
            candidate_id = str(discovery.candidate_id)
            if last_candidate_id is not None and candidate_id <= last_candidate_id:
                raise DiscoveryPoolStoredDataError("invalid Discovery Pool ordering")
            last_candidate_id = candidate_id
            if not discovery.enabled or not discovery.allow_compatible_opportunities:
                continue
            user = await self.repository.get_user(candidate_id)
            if not _active_candidate(user, candidate_id):
                continue
            requirement = before.stream.requirement_snapshot
            try:
                professional_match = await self.match_service.compute(
                    discovery.candidate_id,
                    requirement.role_dna.role_dna_id,
                    requirement.role_dna.version,
                )
                opportunity_fit = await self.fit_service.compute(
                    discovery.candidate_id,
                    requirement.opportunity_spec.opportunity_spec_id,
                    requirement.opportunity_spec.version,
                    candidate_preferences_version=discovery.preferences_version,
                )
            except (
                MatchInputNotFoundError,
                MatchSnapshotUnavailableError,
                OpportunityFitInputNotFoundError,
                OpportunityFitSnapshotUnavailableError,
                KeyError,
                TypeError,
                ValueError,
            ):
                continue
            if type(professional_match) is not ProfessionalMatchResult or type(opportunity_fit) is not OpportunityFitResult:
                raise DiscoveryPoolStoredDataError("invalid matching service result")
            if opportunity_fit.hard_eligibility_state is not HardEligibilityState.ELIGIBLE:
                continue
            current_document = await self.repository.get_preferences(candidate_id)
            try:
                current_discovery = _discovery_from_document(current_document)
            except DiscoveryPoolStoredDataError:
                continue
            current_user = await self.repository.get_user(candidate_id)
            if (
                current_discovery.candidate_id != discovery.candidate_id
                or current_discovery.preferences_version != discovery.preferences_version
                or not current_discovery.enabled
                or not current_discovery.allow_compatible_opportunities
                or not _active_candidate(current_user, candidate_id)
            ):
                continue
            items.append(DiscoveryPoolCandidate(
                candidate_id=discovery.candidate_id,
                discovery_state=current_discovery,
                professional_match=professional_match,
                opportunity_fit=opportunity_fit,
            ))

        try:
            after_scope = await self._scope(stream_id)
        except (DiscoveryPoolAccessError, DiscoveryPoolStoredDataError):
            raise DiscoveryPoolConflictError("Discovery Pool Stream scope changed") from None
        if before.fingerprint != after_scope.fingerprint:
            raise DiscoveryPoolConflictError("Discovery Pool Stream scope changed")
        next_cursor = (
            _cursor_for(before, last_candidate_id)
            if has_more and last_candidate_id is not None else None
        )
        return DiscoveryPoolPage(
            items=tuple(items),
            next_cursor=next_cursor,
            scanned_count=len(consumed_documents),
        )
