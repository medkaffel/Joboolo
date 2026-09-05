#!/usr/bin/env python3
"""Migration EXPLICITE STAB-004 — TTL index for account_claim_tokens.

Ce script est lancé EXPLICITEMENT par un opérateur (jamais au startup).
Il est idempotent et ne fait AUCUN backfill, AUCUNE suppression de données,
AUCUNE autorisation dépendante du TTL.

Il crée UNIQUEMENT l'index TTL nommé `stab004_account_claim_expiry_ttl`
sur `account_claim_tokens.expires_at` avec `expireAfterSeconds=0`.

Usage :
  python scripts/migrate_stab004_account_claim_tokens.py [--dry-run]
      [--mongo-url mongodb://127.0.0.1:27017] [--db-name indeed_clone]
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

INDEX_NAME = "stab004_account_claim_expiry_ttl"
COLLECTION_NAME = "account_claim_tokens"
FIELD_NAME = "expires_at"


async def _index_present(db) -> bool:
    """Vérifie si l'index TTL nommé existe physiquement."""
    try:
        info = await db[COLLECTION_NAME].index_information()
    except Exception:
        return False
    if not isinstance(info, dict):
        return False
    spec = info.get(INDEX_NAME)
    return bool(spec and spec.get("expireAfterSeconds") == 0)


async def _migrate(db, *, dry_run=False):
    """Exécute la migration. Retourne un rapport audit JSON-serialisable."""
    report = {
        "dry_run": dry_run,
        "index_name": INDEX_NAME,
        "collection": COLLECTION_NAME,
        "field": FIELD_NAME,
        "index_present_before": False,
        "index_created": False,
        "already_migrated": False,
        "applied_at": datetime.utcnow().isoformat() + "Z",
    }

    present = await _index_present(db)
    report["index_present_before"] = present

    if present:
        report["already_migrated"] = True
        return report

    if dry_run:
        return report

    # Crée l'index TTL
    await db[COLLECTION_NAME].create_index(
        [(FIELD_NAME, 1)],
        name=INDEX_NAME,
        expireAfterSeconds=0,
    )
    report["index_created"] = True

    # Vérification réelle
    if not await _index_present(db):
        raise RuntimeError(
            f"STAB-004 : l'index TTL {INDEX_NAME!r} n'est pas confirmé après "
            "création. Aucune écriture de marqueur (il n'y en a pas pour ce script)."
        )

    return report


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Migration explicite STAB-004 (TTL index account_claim_tokens.expires_at)"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Rapport uniquement, AUCUNE écriture (ni index)")
    parser.add_argument("--mongo-url", default=os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
    parser.add_argument("--db-name", default=os.environ.get("DB_NAME", "indeed_clone"))
    return parser


def _parse_args(args=None):
    return _build_parser().parse_args(args)


async def _main():
    args = _parse_args()
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(args.mongo_url, serverSelectionTimeoutMS=5000)
    try:
        db = client[args.db_name]
        report = await _migrate(db, dry_run=args.dry_run)
        print(json.dumps(report, default=str, ensure_ascii=False, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except Exception as e:  # pragma: no cover
        print(f"Migration failed: {e}", file=sys.stderr)
        sys.exit(1)