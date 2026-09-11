#!/usr/bin/env python3
"""Explicit A11 preflight/index migration. Run without --apply for read-only checks.

Require an explicit MONGO_URL and DB_NAME. Run with A11 writers stopped, before
connecting any producer. Never repairs data, drops indexes, backfills or adds TTL.
"""
import argparse
import asyncio
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor.motor_asyncio import AsyncIOMotorClient
from domains.intent.serialization import event_from_document

INDEX_NAME = 'ts_a11_idempotency_key_unique'
INDEX_KEY = [('idempotency_key', 1)]
PARTIAL = {'idempotency_key': {'$type': 'string'}}


class IntentMigrationError(RuntimeError):
    pass


async def preflight(db):
    collection = db.talent_intent_events
    options = await collection.options()
    if options.get('collation', {}).get('locale', 'simple') != 'simple':
        raise IntentMigrationError('Intent collection must use simple collation')
    if options.get('capped') or options.get('timeseries'):
        raise IntentMigrationError('Intent requires an ordinary non-expiring collection')
    indexes = await collection.index_information()
    for name, index in indexes.items():
        if 'expireAfterSeconds' in index:
            raise IntentMigrationError('TTL is forbidden for canonical Intent events')
        if name == '_id_':
            if list(index['key']) != [('_id', 1)]:
                raise IntentMigrationError('Incompatible native identity index')
        elif name == INDEX_NAME:
            if (list(index['key']) != INDEX_KEY or index.get('unique') is not True
                    or index.get('partialFilterExpression') != PARTIAL
                    or index.get('sparse') or index.get('hidden')
                    or index.get('collation', {}).get('locale', 'simple') != 'simple'):
                raise IntentMigrationError('Incompatible Intent idempotency index')
        else:
            raise IntentMigrationError('Unexpected index: review explicitly before A11 migration')
    identities, keys = set(), set()
    count = 0
    async for document in collection.find({}):
        try:
            event = event_from_document(document)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            # Do not print personal identifiers/provenance or the invalid payload.
            raise IntentMigrationError('Malformed canonical Intent event; no indexes created') from exc
        if event.event_id in identities:
            raise IntentMigrationError('Duplicate Intent identity; no indexes created')
        identities.add(event.event_id)
        if event.idempotency_key is not None:
            if event.idempotency_key in keys:
                raise IntentMigrationError('Duplicate Intent idempotency key; no indexes created')
            keys.add(event.idempotency_key)
        count += 1
    return {'documents_checked': count, 'idempotency_index_ready': INDEX_NAME in indexes}


async def migrate(db, *, apply=False):
    result = await preflight(db)
    if apply and not result['idempotency_index_ready']:
        await db.talent_intent_events.create_index(
            INDEX_KEY, name=INDEX_NAME, unique=True, partialFilterExpression=PARTIAL,
            collation={'locale': 'simple'})
        result = await preflight(db)
    return result


async def main(apply=False):
    url, name = os.environ.get('MONGO_URL'), os.environ.get('DB_NAME')
    if not url or not name:
        raise SystemExit('MONGO_URL and DB_NAME must be explicitly configured')
    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
    try:
        print(await migrate(client[name], apply=apply))
    finally:
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Create the unique index after successful preflight')
    asyncio.run(main(parser.parse_args().apply))
