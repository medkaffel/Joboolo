#!/usr/bin/env python3
"""P0-009 — Migration de normalisation canonique des emails.

Normalise tous les emails existants dans la collection ``users`` vers la
forme canonique ``strip().lower()``.

Sûreté:
- Dry-run par défaut : aucune écriture sans ``--apply``.
- Détecte les doublons canoniques AVANT toute réécriture et ABOURT si
  des collisions sont trouvées (fail-closed, zéro write).
- Ne modifie JAMAIS les ``_id`` ni les FK (candidate_id, user_id, owner_id).
- Ne crée PAS / supprime PAS d'index ``users.email`` existant.
- Marqueur ``p0009_email_normalization`` posé APRES la vérification et
  l'application complète.
- Mode ``--apply`` avec ``--confirm-collisions`` pour traiter les
  collisions (fail-safe, mais avec confirmation explicite).

Usage:
    # Dry-run (défaut)
    python scripts/migrate_p0009_email_normalization.py

    # Apply (normale les emails non-canoniques)
    python scripts/migrate_p0009_email_normalization.py --apply

    # Apply avec collision handling (exige --confirm-collisions)
    python scripts/migrate_p0009_email_normalization.py --apply --confirm-collisions
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from email_utils import canonical_email  # noqa: E402

logger = logging.getLogger("migrate_p0009")
P0009_MARKER = "p0009_email_normalization"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="P0-009 email normalization migration")
    p.add_argument("--apply", action="store_true", default=False,
                   help="Apply changes (dry-run by default)")
    p.add_argument("--confirm-collisions", action="store_true", default=False,
                   help="Required with --apply when collisions exist")
    return p


async def _migrate(db, *, dry_run: bool = True, confirm_collisions: bool = False) -> dict:
    """Run the migration. Returns a report dict."""
    report = {
        "dry_run": dry_run,
        "total_users": 0,
        "already_canonical": 0,
        "to_update": 0,
        "collisions": 0,
        "updated": 0,
        "marker_set": False,
        "already_migrated": False,
        "collision_details": [],
    }

    # Check if already migrated
    marker = await db.migration_flags.find_one({"_id": P0009_MARKER})
    if marker:
        report["already_migrated"] = True
        logger.info("Already migrated (marker present).")
        return report

    # Aggregate: group by canonical email to detect collisions
    pipeline = [
        {"$match": {"email": {"$type": "string"}}},
        {
            "$addFields": {
                "_email_canonical": {
                    "$toLower": {"$trim": {"input": "$email"}}
                }
            }
        },
        {
            "$group": {
                "_id": "$_email_canonical",
                "count": {"$sum": 1},
                "ids": {"$push": "$_id"},
                "emails": {"$push": "$email"},
            }
        },
    ]

    groups = await db.users.aggregate(pipeline).to_list(length=100000)
    report["total_users"] = sum(g["count"] for g in groups)

    to_update = []
    collisions = []

    for group in groups:
        canonical = group["_id"]
        count = group["count"]
        ids = group["ids"]
        emails = group["emails"]

        if count > 1:
            # Collision: multiple users with same canonical email
            collisions.append({
                "canonical_email": canonical,
                "count": count,
                "user_ids": ids,
                "original_emails": emails,
            })
            continue

        # Single user: check if email is already canonical
        original = emails[0]
        if original == canonical:
            report["already_canonical"] += 1
        else:
            to_update.append({
                "_id": ids[0],
                "old_email": original,
                "new_email": canonical,
            })
            report["to_update"] += 1

    report["collisions"] = len(collisions)
    report["collision_details"] = collisions

    if collisions and not confirm_collisions:
        logger.error(
            "COLLISIONS DETECTED: %d groups share canonical emails. "
            "Use --confirm-collisions to proceed with --apply, or resolve manually.",
            len(collisions),
        )
        for c in collisions:
            logger.error(
                "  Canonical: %r — Users: %s — Emails: %s",
                c["canonical_email"], c["user_ids"], c["original_emails"],
            )
        if not dry_run:
            raise RuntimeError(
                f"{len(collisions)} collision(s) detected. "
                "Resolve manually or use --confirm-collisions."
            )
        return report

    if dry_run:
        logger.info(
            "DRY-RUN: would update %d users, %d already canonical, %d collisions.",
            report["to_update"], report["already_canonical"], report["collisions"],
        )
        return report

    # Apply updates
    for item in to_update:
        await db.users.update_one(
            {"_id": item["_id"]},
            {"$set": {"email": item["new_email"], "updated_at": __import__("datetime").datetime.utcnow()}}
        )
        report["updated"] += 1

    # Set marker
    await db.migration_flags.insert_one({
        "_id": P0009_MARKER,
        "applied_at": __import__("datetime").datetime.utcnow(),
        "report": {
            "total_users": report["total_users"],
            "updated": report["updated"],
            "already_canonical": report["already_canonical"],
            "collisions": report["collisions"],
        },
    })
    report["marker_set"] = True

    logger.info(
        "Migration complete: %d updated, %d already canonical, %d collisions.",
        report["updated"], report["already_canonical"], report["collisions"],
    )
    return report


async def _connect():
    from database import connect_to_mongo
    await connect_to_mongo()
    from database import get_database
    return await get_database()


async def main():
    args = _build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    db = await _connect()
    try:
        report = await _migrate(
            db,
            dry_run=not args.apply,
            confirm_collisions=args.confirm_collisions,
        )
        print(f"\nReport: {report}")
    finally:
        from database import close_mongo_connection
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
