#!/usr/bin/env python3
"""P0-002 — Seed de DONNÉES DE DÉMONSTRATION, EXPLICITE et réservé dev/test.

Ce script est la SEULE porte d'entrée recommandée pour renseigner la base avec
les comptes/offres/entreprises de démonstration. Il ne doit JAMAIS être exécuté
en production : config.ensure_seeding_allowed() (source unique APP_ENV) refuse
avant toute écriture DB.

Usage (explicite par un développeur, sans mettre le mot de passe dans la ligne
de commande ni dans l'historique shell) :
    read -rsp "Seed demo password: " SEED_DEMO_PASSWORD && echo
    export SEED_DEMO_PASSWORD
    APP_ENV=development python scripts/seed_dev.py
    # ou : APP_ENV=test python scripts/seed_dev.py
    unset SEED_DEMO_PASSWORD

Le mot de passe de seed doit être fourni via la variable d'environnement
SEED_DEMO_PASSWORD. Aucun mot de passe par défaut n'est fourni.
Ne contient aucun secret et ne crée jamais d'administrateur.
"""

import asyncio
import sys
from pathlib import Path

# Rendre le module backend importable quel que soit le répertoire de travail.
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    from config import ConfigurationError, ensure_seeding_allowed, get_settings

    try:
        settings = get_settings()
        ensure_seeding_allowed()  # refuse la production avant toute écriture.
    except ConfigurationError as exc:
        sys.stderr.write(f"Refus: {exc}\n")
        return 2

    from seed_data import seed_database

    print(f"APP_ENV détecté : {settings.APP_ENV}")
    asyncio.run(seed_database())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())