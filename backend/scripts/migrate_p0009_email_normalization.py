#!/usr/bin/env python3
"""P0-009 — Migration de normalisation canonique des emails.

Normalise tous les emails existants dans la collection ``users`` vers la
forme canonique ``strip().lower()``.

Sûreté:
- Dry-run par défaut : aucune écriture sans ``--apply``.
- Inventaire COMPLET de TOUS les users (y compris email absent/non-string).
  Tout email non-string, absent, vide ou whitespace-only est un BLOCKER.
- Détecte les doublons canoniques AVANT toute réécriture et ABOURT si
  des collisions sont trouvées (fail-closed, zéro write).
- Chaque update utilise CAS (compare-and-set) : filtre
  ``{"_id": id, "email": old_email}`` et vérifie ``matched_count == 1``.
- POST-VERIFY complet avant de poser le marker.
- Ne modifie JAMAIS les ``_id`` ni les FK (candidate_id, user_id, owner_id).
- Ne crée PAS / supprime PAS d'index ``users.email`` existant.
- Marqueur ``p0009_email_normalization`` posé APRES la vérification et
  l'application complète.
- Aucun flag ne peut bypasser le fail-closed sur collisions.
- L'inventaire couvre TOUS les users via un curseur streaming (pas de
  troncation).
- Le marker existant ne masque pas une base incohérente : un postverify
  complet est effectué avant de retourner ``already_migrated``. Si le marker
  est présent mais la base incohérente, la migration échoue explicitement
  SANS supprimer le marker (dry-run comme apply : zéro mutation).
- La source de vérité de canonicalisation est ``canonical_email()`` côté
  Python pour CHAQUE user (inventaire et post-verify), via un curseur de
  streaming ``find({})`` non tronqué.

Usage:
    # Dry-run (défaut)
    python scripts/migrate_p0009_email_normalization.py

    # Apply (normale les emails non-canoniques)
    python scripts/migrate_p0009_email_normalization.py --apply
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
    return p


def _is_invalid_email(email_value):
    """Check if an email value is invalid (not a string, missing, empty, or whitespace-only)."""
    if email_value is None:
        return True
    if not isinstance(email_value, str):
        return True
    if not email_value.strip():
        return True
    return False


def _is_already_canonical(email_value):
    """Check if an email is already in canonical form."""
    if _is_invalid_email(email_value):
        return False
    canonical = canonical_email(email_value)
    return email_value == canonical


def _compute_canonical(email_value):
    """Compute canonical form, returning None for invalid emails."""
    if _is_invalid_email(email_value):
        return None
    return canonical_email(email_value)


async def _inventory_all_users(db):
    """Inventory ALL users via a streaming cursor ``find({})`` (non-truncated).

    Source of truth for canonicalisation is ``canonical_email()`` (Python) for
    EACH user — never Mongo ``$trim/$toLower``.

    Returns:
    - invalid_users: list of docs with non-string/absent/empty/whitespace emails
    - canonical_groups: dict of canonical_email -> list of {id, email} docs
    - total_users: total count
    """
    invalid_users = []
    canonical_groups = {}
    total_users = 0

    cursor = db.users.find({}, {"email": 1})
    async for doc in cursor:
        total_users += 1
        uid = doc.get("_id")
        email_val = doc.get("email")

        if _is_invalid_email(email_val):
            invalid_users.append({"_id": uid, "email": email_val})
            continue

        canonical = canonical_email(email_val)
        canonical_groups.setdefault(canonical, []).append({"_id": uid, "email": email_val})

    return invalid_users, canonical_groups, total_users


async def _post_verify(db):
    """Post-verify: re-run complete inventory using the SAME Python
    ``canonical_email()`` logic and confirm everything is clean.
    Returns (ok, errors_list).
    """
    errors = []
    seen = {}

    cursor = db.users.find({}, {"email": 1})
    async for doc in cursor:
        uid = doc.get("_id")
        email_val = doc.get("email")

        if _is_invalid_email(email_val):
            errors.append(f"Invalid email on user {uid}: {email_val!r}")
            continue

        canonical = canonical_email(email_val)

        # Check non-canonical (should be canonical after migration)
        if email_val != canonical:
            errors.append(f"Non-canonical email on user {uid}: {email_val!r} != {canonical!r}")

        seen.setdefault(canonical, []).append(uid)

    # Check collisions at the very end
    for canonical, ids in seen.items():
        if len(ids) > 1:
            errors.append(
                f"Collision on canonical email {canonical!r}: "
                f"{len(ids)} users ({ids})"
            )

    return len(errors) == 0, errors


async def _migrate(db, *, dry_run: bool = True) -> dict:
    """Run the migration. Returns a report dict."""
    import datetime as _dt

    report = {
        "dry_run": dry_run,
        "total_users": 0,
        "already_canonical": 0,
        "to_update": 0,
        "collisions": 0,
        "invalid_emails": 0,
        "updated": 0,
        "marker_set": False,
        "already_migrated": False,
        "collision_details": [],
        "invalid_email_details": [],
    }

    # Check if already migrated — BUT do a full postverify first
    marker = await db.migration_flags.find_one({"_id": P0009_MARKER})
    if marker:
        ok, errors = await _post_verify(db)
        if ok:
            report["already_migrated"] = True
            logger.info("Already migrated (marker present, postverify OK).")
            return report
        else:
            # Marker present but base is inconsistent — FAIL explicitly.
            # NEVER delete the marker (dry-run as apply): the diagnosis must
            # not mutate the database. The marker alone is not proof of a
            # consistent base.
            for e in errors:
                logger.error("  %s", e)
            raise RuntimeError(
                f"Marker '{P0009_MARKER}' present but post-verify failed with "
                f"{len(errors)} inconsistency(ies). "
                "The marker is NOT a proof of a consistent database. "
                "Fix the base manually, then relaunch. No changes were made "
                "and the marker was left untouched."
            )

    # Phase 1: Full inventory of ALL users (streaming, no truncation)
    invalid_users, canonical_groups, total_users = await _inventory_all_users(db)
    report["total_users"] = total_users
    report["invalid_emails"] = len(invalid_users)
    report["invalid_email_details"] = [
        {"_id": u["_id"], "email": u["email"]} for u in invalid_users
    ]

    # BLOCKER: any invalid email means ZERO writes and ZERO marker
    if invalid_users:
        logger.error(
            "INVALID EMAILS DETECTED: %d users with non-string/absent/empty/whitespace emails.",
            len(invalid_users),
        )
        for u in invalid_users:
            logger.error("  User %s: email=%r", u["_id"], u["email"])
        if not dry_run:
            raise RuntimeError(
                f"{len(invalid_users)} user(s) have invalid emails. "
                "Fix manually then relaunch."
            )
        return report

    # Phase 2: Detect collisions and build update list
    to_update = []
    collisions = []

    for canonical, group in canonical_groups.items():
        count = len(group)
        if count > 1:
            collisions.append({
                "canonical_email": canonical,
                "count": count,
                "user_ids": [d["_id"] for d in group],
                "original_emails": [d["email"] for d in group],
            })
            continue

        # Single user: check if email is already canonical
        doc = group[0]
        original = doc["email"]
        if original == canonical:
            report["already_canonical"] += 1
        else:
            to_update.append({
                "_id": doc["_id"],
                "old_email": original,
                "new_email": canonical,
            })
            report["to_update"] += 1

    report["collisions"] = len(collisions)
    report["collision_details"] = collisions

    # Fail-closed: ANY collision means ZERO writes and ZERO marker.
    if collisions:
        logger.error(
            "COLLISIONS DETECTED: %d groups share canonical emails. "
            "Resolve manually then relaunch.",
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
                "Resolve manually then relaunch."
            )
        return report

    if dry_run:
        logger.info(
            "DRY-RUN: would update %d users, %d already canonical.",
            report["to_update"], report["already_canonical"],
        )
        return report

    # Phase 3: Apply updates with CAS (compare-and-set)
    for item in to_update:
        result = await db.users.update_one(
            {"_id": item["_id"], "email": item["old_email"]},
            {"$set": {"email": item["new_email"], "updated_at": _dt.datetime.utcnow()}}
        )
        if result.matched_count != 1:
            # CAS mismatch: abort — email changed since inventory
            logger.error(
                "CAS MISMATCH: user %s email changed from %r during update. "
                "Aborting.",
                item["_id"], item["old_email"],
            )
            raise RuntimeError(
                f"CAS mismatch for user {item['_id']}: email changed during migration."
            )
        report["updated"] += 1

    # Phase 4: Post-verify BEFORE marker
    ok, errors = await _post_verify(db)
    if not ok:
        logger.error(
            "POST-VERIFY FAILED: %d inconsistencies after update. "
            "NOT setting marker.",
            len(errors),
        )
        for e in errors:
            logger.error("  %s", e)
        raise RuntimeError(
            f"Post-verify failed with {len(errors)} inconsistencies. "
            "No marker set."
        )

    # Phase 5: Set marker (LAST write)
    await db.migration_flags.insert_one({
        "_id": P0009_MARKER,
        "applied_at": _dt.datetime.utcnow(),
        "report": {
            "total_users": report["total_users"],
            "updated": report["updated"],
            "already_canonical": report["already_canonical"],
            "collisions": report["collisions"],
            "invalid_emails": report["invalid_emails"],
        },
    })
    report["marker_set"] = True

    logger.info(
        "Migration complete: %d updated, %d already canonical.",
        report["updated"], report["already_canonical"],
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
        )
        print(f"\nReport: {report}")
    finally:
        from database import close_mongo_connection
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
