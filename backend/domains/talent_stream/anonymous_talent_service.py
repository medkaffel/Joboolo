"""TS-B8-003: Active Generation Anonymous Talent Page Service.

Provides privacy-safe paginated AnonymousTalentCard pages from the active
B7 generation, using exact-version A1/B7 adapter and B8.1 privacy renderer.
Level 1 — Anonymous Talent only.
"""
from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass
from typing import Optional, Protocol, Tuple, List

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from domains.privacy.anonymous_talent import (
    AnonymousTalentCard,
    AnonymousTalentFacts,
    render_anonymous_talent_card,
)
from domains.talent_stream.anonymous_talent_adapter import (
    AnonymousTalentAdapterError,
    AnonymousTalentFactsAdapter,
    AnonymousTalentProjectionUnavailableError,
)
from domains.talent_stream.stream_candidate_models import StreamCandidate
from domains.talent_stream.stream_candidate_persistence import ProjectionState
from domains.talent_stream.stream_models import nonblank_identifier


class AnonymousTalentServiceError(RuntimeError):
    """Generic service failure."""


class AnonymousTalentPageUnavailableError(AnonymousTalentServiceError):
    """Active generation page cannot be produced."""


class AnonymousTalentCursorError(AnonymousTalentServiceError):
    """Opaque cursor is invalid, tampered, or cross-context."""


class StreamCandidatePageReader(Protocol):
    """Minimal structural contract for reading B7 pages."""

    async def get_projection_state(
        self,
        stream_id: str,
    ) -> Optional[ProjectionState]:
        ...

    async def find_generation(
        self,
        stream_id: str,
        generation_id: str,
        *,
        after_candidate_id: Optional[str],
        limit: int,
    ) -> List[StreamCandidate]:
        ...


class AnonymousTalentFactsBuilder(Protocol):
    """Minimal structural contract for building anonymous talent facts."""

    async def build(
        self,
        candidate: StreamCandidate,
    ) -> AnonymousTalentFacts:
        ...


CURSOR_VERSION = "ts-b8-cursor-v1"
CURSOR_AAD = b"ts-b8-cursor-v1"
CURSOR_NONCE_SIZE = 12


@dataclass(frozen=True, slots=True, repr=False)
class AnonymousTalentPage:
    """Privacy-safe page of anonymous talent cards for recruiter-facing exposure."""

    cards: Tuple[AnonymousTalentCard, ...]
    next_cursor: Optional[str]

    def __post_init__(self) -> None:
        if type(self.cards) is not tuple:
            raise ValueError("cards must be a tuple")
        if not all(type(c) is AnonymousTalentCard for c in self.cards):
            raise ValueError("all cards must be AnonymousTalentCard instances")
        if self.next_cursor is not None and type(self.next_cursor) is not str:
            raise ValueError("next_cursor must be a string or None")


def _encode_cursor(
    *,
    cursor_key: bytes,
    stream_id: str,
    generation_id: str,
    state_version: int,
    after_candidate_id: str,
) -> str:
    """Encode and encrypt an opaque cursor. Determinism not required."""
    if type(cursor_key) is not bytes or len(cursor_key) != 32:
        raise ValueError("cursor_key must be 32 bytes")
    if not stream_id or not generation_id or not after_candidate_id:
        raise ValueError("cursor payload requires non-empty fields")

    payload = json.dumps(
        [CURSOR_VERSION, stream_id, generation_id, state_version, after_candidate_id],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    nonce = os.urandom(CURSOR_NONCE_SIZE)
    aesgcm = AESGCM(cursor_key)
    ciphertext = aesgcm.encrypt(nonce, payload, CURSOR_AAD)
    token = nonce + ciphertext
    b64 = base64.urlsafe_b64encode(token).decode("ascii").rstrip("=")
    return f"{CURSOR_VERSION}:{b64}"


def _decode_cursor(
    *,
    cursor_key: bytes,
    token: str,
    expected_stream_id: str,
    expected_generation_id: str,
    expected_state_version: int,
) -> str:
    """Decrypt and validate an opaque cursor. Returns after_candidate_id."""
    if type(cursor_key) is not bytes or len(cursor_key) != 32:
        raise ValueError("cursor_key must be 32 bytes")

    if not token.startswith(f"{CURSOR_VERSION}:"):
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")

    b64 = token[len(CURSOR_VERSION) + 1:]
    padding = "=" * ((4 - len(b64) % 4) % 4)
    try:
        token_bytes = base64.urlsafe_b64decode(b64 + padding)
    except Exception:
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")

    if len(token_bytes) < CURSOR_NONCE_SIZE + 1:
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")

    nonce = token_bytes[:CURSOR_NONCE_SIZE]
    ciphertext = token_bytes[CURSOR_NONCE_SIZE:]

    try:
        aesgcm = AESGCM(cursor_key)
        payload = aesgcm.decrypt(nonce, ciphertext, CURSOR_AAD)
    except Exception:
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")

    try:
        decoded = json.loads(payload.decode("utf-8"))
    except Exception:
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")

    if (
        type(decoded) is not list
        or len(decoded) != 5
        or decoded[0] != CURSOR_VERSION
    ):
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")

    _, stream_id, generation_id, state_version, after_candidate_id = decoded

    if stream_id != expected_stream_id:
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")
    if generation_id != expected_generation_id:
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")
    if type(state_version) is not int or state_version != expected_state_version:
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")
    if type(after_candidate_id) is not str or not after_candidate_id:
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")

    return after_candidate_id


def _validate_page_size(page_size) -> int:
    if type(page_size) is not int or page_size < 1 or page_size > 100:
        raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable")
    return page_size


def _validate_stream_id(stream_id) -> str:
    if type(stream_id) is not str or not stream_id:
        raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable")
    return stream_id


def _validate_cursor(cursor) -> Optional[str]:
    if cursor is None:
        return None
    if type(cursor) is not str or not cursor:
        raise AnonymousTalentCursorError("anonymous talent cursor invalid")
    return cursor


def _scope_key(candidate: StreamCandidate) -> Tuple:
    return (
        candidate.stream_id,
        candidate.generation_id,
        candidate.stream_version,
        candidate.requirement_version,
        candidate.role_dna_id,
        candidate.role_dna_version,
        candidate.opportunity_spec_id,
        candidate.opportunity_spec_version,
    )


@dataclass(frozen=True, slots=True, repr=False)
class AnonymousTalentPageService:
    """Serve active-generation anonymous talent pages with exact-version privacy."""

    repository: StreamCandidatePageReader
    facts_builder: AnonymousTalentFactsBuilder
    cursor_key: bytes

    def __post_init__(self) -> None:
        if not callable(getattr(self.repository, "get_projection_state", None)):
            raise ValueError("repository must provide get_projection_state")
        if not callable(getattr(self.repository, "find_generation", None)):
            raise ValueError("repository must provide find_generation")
        if not callable(getattr(self.facts_builder, "build", None)):
            raise ValueError("facts_builder must provide build")
        if type(self.cursor_key) is not bytes or len(self.cursor_key) != 32:
            raise ValueError("cursor_key must be 32 bytes")

    async def get_page(
        self,
        stream_id: str,
        page_size: int,
        cursor: Optional[str] = None,
    ) -> AnonymousTalentPage:
        """Return a privacy-safe page of anonymous talent cards from the active generation."""
        stream_id = _validate_stream_id(stream_id)
        page_size = _validate_page_size(page_size)
        cursor = _validate_cursor(cursor)

        initial_state = await self.repository.get_projection_state(stream_id)
        if initial_state is None:
            raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable")

        generation_id = initial_state.active_generation_id

        after_candidate_id = None
        if cursor is not None:
            try:
                after_candidate_id = _decode_cursor(
                    cursor_key=self.cursor_key,
                    token=cursor,
                    expected_stream_id=stream_id,
                    expected_generation_id=generation_id,
                    expected_state_version=initial_state.state_version,
                )
            except AnonymousTalentCursorError:
                raise
            except Exception:
                raise AnonymousTalentCursorError("anonymous talent cursor invalid")

        try:
            candidates = await self.repository.find_generation(
                stream_id=stream_id,
                generation_id=generation_id,
                after_candidate_id=after_candidate_id,
                limit=page_size + 1,
            )
        except Exception:
            raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable") from None

        expected_scope = _scope_key(StreamCandidate(
            stream_id=initial_state.stream_id,
            generation_id=generation_id,
            stream_version=initial_state.stream_version,
            requirement_version=initial_state.requirement_version,
            role_dna_id=initial_state.role_dna_id,
            role_dna_version=initial_state.role_dna_version,
            opportunity_spec_id=initial_state.opportunity_spec_id,
            opportunity_spec_version=initial_state.opportunity_spec_version,
        ))

        has_next = len(candidates) > page_size
        page_candidates = candidates[:page_size]

        for candidate in page_candidates:
            if _scope_key(candidate) != expected_scope:
                raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable")

        cards = []
        for candidate in page_candidates:
            try:
                facts = await self.facts_builder.build(candidate)
            except (AnonymousTalentAdapterError, AnonymousTalentProjectionUnavailableError):
                raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable") from None
            except Exception:
                raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable") from None
            card = render_anonymous_talent_card(facts)
            cards.append(card)

        final_state = await self.repository.get_projection_state(stream_id)
        if final_state is None:
            raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable")
        if final_state.state_version != initial_state.state_version:
            raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable")
        if final_state.active_generation_id != initial_state.active_generation_id:
            raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable")

        if initial_state.candidate_count == 0:
            if len(page_candidates) != 0:
                raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable")
            return AnonymousTalentPage(cards=(), next_cursor=None)

        if len(page_candidates) == 0 and initial_state.candidate_count > 0:
            raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable")

        if initial_state.candidate_count == 0:
            if len(page_candidates) > 0:
                raise AnonymousTalentPageUnavailableError("anonymous talent page unavailable")
            return AnonymousTalentPage(cards=(), next_cursor=None)

        next_cursor = None
        if has_next:
            last_candidate = page_candidates[-1]
            next_cursor = _encode_cursor(
                cursor_key=self.cursor_key,
                stream_id=stream_id,
                generation_id=generation_id,
                state_version=initial_state.state_version,
                after_candidate_id=str(last_candidate.candidate_id),
            )

        return AnonymousTalentPage(cards=tuple(cards), next_cursor=next_cursor)


__all__ = [
    "AnonymousTalentServiceError",
    "AnonymousTalentPageUnavailableError",
    "AnonymousTalentCursorError",
    "AnonymousTalentPage",
    "AnonymousTalentPageService",
    "StreamCandidatePageReader",
    "AnonymousTalentFactsBuilder",
    "CURSOR_VERSION",
]