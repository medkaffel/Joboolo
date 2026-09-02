#!/usr/bin/env python3
"""P0-002 — Amorce sécurisée du PREMIER administrateur (création explicite).

Ce script est l'unique mécanisme pour créer le compte administrateur initial en
production. Il n'est JAMAIS appelé automatiquement : un opérateur l'exécute
explicitement, une seule fois, au déploiement.

Exigences de sécurité :
- email administrateur fourni explicitement (pas de valeur par défaut) ;
- le mot de passe est OBLIGATOIRE via la variable d'environnement
  ADMIN_INITIAL_PASSWORD (aucun mot de passe par défaut, jamais en ligne de
  commande, jamais dans Git) ;
- le mot de passe est hashé AVANT stockage (get_password_hash) ;
- aucun secret n'est loggé ;
- comportement idempotent et sûr : si un admin existe déjà pour cet email,
  le script ne fait rien et quitte proprement (aucune réécriture du hash).

Usage (opérateur production) :
    ADMIN_INITIAL_PASSWORD='<mot-de-passe-fort>' \\
        python scripts/create_admin.py --email admin@exemple.fr

Aucun mot de passe n'est stocké en clair ni affiché. APP_ENV n'est jamais lu
directement ici : il provient de config.get_settings() (source unique).
"""

import asyncio
import os
import sys
from pathlib import Path

# Rendre le module backend importable quel que soit le répertoire de travail.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

_ADMIN_PASSWORD_ENV = "ADMIN_INITIAL_PASSWORD"


def _parse_args(argv):
    email = None
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--email":
            if not args:
                sys.stderr.write("Erreur: --email attend une valeur.\n")
                return None
            email = args.pop(0)
        else:
            sys.stderr.write(f"Argument inconnu: {arg}\n")
            return None
    return email


async def _ensure_admin(email: str, password: str) -> str:
    from database import get_database
    from auth import get_password_hash
    from email_utils import canonical_email

    db = await get_database()
    # P0-009: canonicalize email
    email = canonical_email(email)
    existing = await db.users.find_one({"email": email})
    if existing:
        return "exists"

    hashed = get_password_hash(password)
    now = __import__("datetime").datetime.utcnow()
    await db.users.insert_one({
        "email": email,
        "first_name": "Admin",
        "last_name": "Principal",
        "user_type": "admin",
        "hashed_password": hashed,
        "phone": None,
        "location": None,
        "bio": None,
        "skills": [],
        "experience_years": None,
        "is_active": True,
        "is_verified": True,
        "created_at": now,
        "updated_at": now,
    })
    return "created"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    email = _parse_args(argv)
    if not email:
        sys.stderr.write(
            "Usage: ADMIN_INITIAL_PASSWORD=... python scripts/create_admin.py --email <admin@email>\n"
        )
        return 2

    # Source unique d'APP_ENV : on valide simplement la config. Ce script reste
    # autorisé en production (création volontaire du premier admin par un opérateur),
    # mais ne duplique aucune lecture d'APP_ENV.
    from config import ConfigurationError, get_settings

    try:
        get_settings()
    except ConfigurationError as exc:
        sys.stderr.write(f"Refus: {exc}\n")
        return 2

    password = os.environ.get(_ADMIN_PASSWORD_ENV)
    if not password:
        sys.stderr.write(
            f"Erreur: la variable d'environnement {_ADMIN_PASSWORD_ENV} est obligatoire "
            "(aucun mot de passe par défaut).\n"
        )
        return 2

    result = asyncio.run(_ensure_admin(email, password))
    if result == "exists":
        sys.stdout.write("Un administrateur existe déjà pour cet email. Aucune modification.\n")
        return 0
    sys.stdout.write("Administrateur initial créé (mot de passe jamais affiché ni stocké en clair).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())