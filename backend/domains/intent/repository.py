"""Only canonical event insertion and identity reads; migration is a prerequisite."""
from pymongo import ReadPreference
from pymongo.write_concern import WriteConcern


class IntentEventRepository:
    def __init__(self, db):
        self.collection = db.talent_intent_events.with_options(
            read_preference=ReadPreference.PRIMARY, write_concern=WriteConcern(w='majority'))

    async def insert(self, document):
        await self.collection.insert_one(document)

    async def get(self, event_id):
        return await self.collection.find_one({'_id': event_id}, collation={'locale': 'simple'})

    async def get_by_idempotency_key(self, key):
        return await self.collection.find_one({'idempotency_key': key}, collation={'locale': 'simple'})
