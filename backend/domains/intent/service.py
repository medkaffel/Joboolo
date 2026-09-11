"""One insert, retry-safe identity, no transactions or secondary authoritative writes."""
from pymongo.errors import DuplicateKeyError

from .repository import IntentEventRepository
from .serialization import event_from_document, event_to_document


class IntentEventConflictError(RuntimeError):
    pass


class IntentEventService:
    """Use only after the explicit A11 index migration; no runtime producers in A11."""
    def __init__(self, db):
        self.repo = IntentEventRepository(db)

    async def record(self, event):
        document = event_to_document(event)
        try:
            await self.repo.insert(document)
        except DuplicateKeyError:
            return await self._recover(document)
        return event_from_document(document)

    async def _recover(self, expected):
        by_id = await self.repo.get(expected['_id'])
        by_key = None
        if 'idempotency_key' in expected:
            by_key = await self.repo.get_by_idempotency_key(expected['idempotency_key'])
        # With a key both lookups must identify the same complete canonical event.
        if by_id is None or ('idempotency_key' in expected and by_key is None):
            raise IntentEventConflictError('Intent identity or idempotency key conflict')
        existing = None
        for document in (by_id, by_key):
            if document is None:
                continue
            try:
                existing = event_from_document(document)
                same = event_to_document(existing) == expected
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                raise IntentEventConflictError('Stored Intent event is invalid') from exc
            if not same:
                raise IntentEventConflictError('Intent identity/key reused with different payload')
        return existing
