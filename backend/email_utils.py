"""P0-009 — Normalisation canonique des emails (source unique).

Fournit ``canonical_email()`` comme SEULE source de vérité pour la
normalisation email dans le domaine identité/auth.  Tous les chemins
d'entrée (register, login, OAuth, admin, seed, alert) DOIVENT passer
par cette fonction.

``lookup_user_by_email`` effectue une recherche transitionnelle qui
sérialise ``strip() + lower()`` via une aggregation Mongo
(``$trim`` + ``$toLower``), permettant de détecter les doublons
latents avant migration complète.

Typologie des résultats (fail-closed) :
  - ``None``                 → aucun compte ne correspond (email libre).
  - ``User``                 → exactement un compte canonique trouvé.
  - ``LookupAggregationError`` → l'agrégation Mongo a échoué (ancien
    serveur, timeout, réseau…).  Les create-paths DOIVENT refuser
    toute création.
  - ``LookupCollisionError``  → ≥ 2 comptes partagent le même email
    canonique.  Les create-paths DOIVENT refuser toute création.
"""
from __future__ import annotations

import logging
from typing import Optional

from database import get_database
from models import User

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fail-closed typed exceptions
# ---------------------------------------------------------------------------

class LookupAggregationError(Exception):
    """Raised when the Mongo aggregation pipeline fails (infra/version issue).

    Create-paths MUST NOT create or reuse any account when this is raised.
    """


class LookupCollisionError(Exception):
    """Raised when ≥ 2 users share the same canonical email.

    Create-paths MUST NOT create or silently merge any account.
    """


# ---------------------------------------------------------------------------
# Canonical form (source unique)
# ---------------------------------------------------------------------------

def canonical_email(email: str | None) -> str:
    """Return the canonical form of *email*.

    Rules (deterministic, locale-independent):
      1. ``str.strip()``  — remove leading/trailing whitespace
      2. ``str.lower()``  — case-fold (ASCII-safe for all RFC-5321
         local-parts that matter in practice)

    The result is always a **non-empty str** or raises ``ValueError``.
    """
    if not email or not isinstance(email, str):
        raise ValueError("email must be a non-empty string")
    result = email.strip().lower()
    if not result:
        raise ValueError("email must not be empty after normalization")
    return result


# ---------------------------------------------------------------------------
# Transition lookup — Mongo aggregation equivalent to strip+lower
# ---------------------------------------------------------------------------

async def lookup_user_by_email(email: str) -> Optional[User]:
    """Look up a user by email using a transitionnal canonical query.

    The aggregation pipeline computes the canonical form server-side
    (``$trim`` + ``$toLower``) so that legacy non-canonical values are
    matched.  The pipeline also guards non-string ``email`` fields with
    ``$type`` to avoid false-positives on corrupted documents.

    Returns:
        * ``None`` — no matching user (email is free)
        * ``User`` — exactly one canonical match

    Raises:
        * ``LookupAggregationError`` — Mongo aggregation failed (infra).
          Create-paths MUST refuse creation.
        * ``LookupCollisionError`` — ≥ 2 users share the same canonical
          email.  Create-paths MUST refuse creation and MUST NOT silently
          merge.
    """
    db = await get_database()
    if db is None:
        raise LookupAggregationError(
            "Database unavailable — cannot perform transitionnal lookup"
        )

    canonical = canonical_email(email)

    pipeline = [
        {
            "$addFields": {
                "_email_canonical": {
                    "$cond": {
                        "if": {"$eq": [{"$type": "$email"}, "string"]},
                        "then": {"$toLower": {"$trim": {"input": "$email"}}},
                        "else": None,
                    }
                }
            }
        },
        {"$match": {"_email_canonical": canonical}},
        {"$limit": 2},
    ]

    try:
        results = await db.users.aggregate(pipeline).to_list(length=2)
    except Exception:
        # Fail closed: if aggregation is unavailable (e.g. old Mongo version
        # or network error) we cannot safely detect legacy duplicates.
        logger.error("P0-009: aggregation lookup failed — raising LookupAggregationError")
        raise LookupAggregationError(
            "Aggregation pipeline failed — cannot determine email uniqueness"
        )

    if not results:
        return None

    if len(results) > 1:
        logger.error(
            "P0-009 COLLISION: %d users share canonical email %r — "
            "raising LookupCollisionError",
            len(results), canonical,
        )
        raise LookupCollisionError(
            f"{len(results)} users share canonical email {canonical!r}"
        )

    return User(**results[0])
