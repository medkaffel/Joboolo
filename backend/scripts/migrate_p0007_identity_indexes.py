#!/usr/bin/env python3
"""Migration EXPLICITE P0-007 — identité des offres de feed par `campaign_id`.

Déploiement en DEUX PHASES (la migration n'est JAMAIS exécutée au startup :
elle est lancée explicitement par un opérateur, idempotente et auditable) :

  Phase 1 (CE script) :
    - déduplique les jobs de campagne partageant la même identité
      `(partner_id, campaign_id, external_ref)` avec `campaign_id` de type
      string (le WINNER est le job au `created_at` le plus ancien et VALIDE ;
      les `created_at` absents/invalides passent après les dates valides ;
      tie-break `_id` croissant — `_id` n'est JAMAIS un proxy d'âge) ;
    - consolide vers le winner les références réellement vérifiées dans le
      code : `applications` (unicité `(job_id, candidate_id)`), `saved_jobs`
      (unicité `(user_id, job_id)`) avec DÉDUP des collisions avant repointage,
      `click_events` et `impression_events` (attribution, sans fausser les
      compteurs) et `messages` (schéma `job_id` confirmé dans
      routes/messages.py) ;
    - recalcule `applications_count` du winner et applique la règle unique
      `views_count` : compteurs STOCKÉS fusionnés uniquement (winner + losers),
      jamais dérivés des événements — aucun double comptage ;
    - NE modifie AUCUN agrégat partenaire (`partner_profiles`).
    - crée ENSURTE l'index unique partiel `p0007_identity_unique`, PUIS pose le
      marqueur `p0007_identity_indexes` (précondition des créations d'import).
      Le marqueur n'est JAMAIS posé si l'index n'a pas été créé avec succès
      (le script vérifie l'existence physique ET le flag `unique`).

  Phase 2 : `database.create_indexes()` (startup) matérialise le même index
  unique dès que le marqueur existe et qu'il n'y a aucun doublon éligible — il
  ne fait jamais de dédup/destruction au startup.

Idempotent : si le marqueur ET l'index unique sont déjà présents (et sans
`--force`), le script ne fait AUCUNE écriture. Un marqueur incohérent (posé
sans index, ex. suite à un état partiel) n'est pas considéré migré : le script
régénère alors l'index (et re-vérifie les doublons éligibles).

Usage :
  python scripts/migrate_p0007_identity_indexes.py [--dry-run]
      [--mongo-url mongodb://127.0.0.1:27017] [--db-name indeed_clone] [--force]
"""
import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

P0007_MARKER = "p0007_identity_indexes"
INDEX_NAME = "p0007_identity_unique"


def _is_valid_created_at(value) -> bool:
    """`created_at` VALIDE = instance datetime. Toute autre valeur (absente,
    None, texte non parseable, nombre) est invalide et passe après les dates
    valides lors du choix du winner."""
    return isinstance(value, datetime)


def _identity_sort_key(doc):
    """Clé de tri pour choisir le winner.

    - bucket 0 : `created_at` VALIDE (datetime) -> le plus ancien gagne ;
    - bucket 1 : `created_at` absent/invalide -> passe après les dates valides ;
    - tie-break final : `_id` croissant (jamais un proxy d'âge).
    """
    created = doc.get("created_at")
    if _is_valid_created_at(created):
        return (0, created, doc.get("_id") or "")
    return (1, None, doc.get("_id") or "")


def _pick_winner(docs):
    """Winner = le job le plus ancien `created_at` VALIDE (tie-break `_id`)."""
    if not docs:
        return None
    return min(docs, key=_identity_sort_key)


async def _find_duplicate_groups(db):
    """Groupes `(partner_id, campaign_id, external_ref)` avec `campaign_id`
    string ayant plus d'un job (candidats à la dédup)."""
    pipeline = [
        {"$match": {"campaign_id": {"$type": "string"}}},
        {"$group": {
            "_id": {
                "partner_id": "$partner_id",
                "campaign_id": "$campaign_id",
                "external_ref": "$external_ref",
            },
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]
    return await db.jobs.aggregate(pipeline).to_list(length=100000)


async def _consolidate(db, winner, losers, report):
    """Fusionne un loser vers le winner : références + compteurs, puis delete."""
    winner_id = winner["_id"]
    winner_campaign = winner.get("campaign_id")
    loser_ids = [loser["_id"] for loser in losers]

    # applications : dédup avant repointage (unicité (job_id, candidate_id)).
    for app in await db.applications.find({"job_id": {"$in": loser_ids}}).to_list(length=100000):
        cand = app.get("candidate_id")
        dup = await db.applications.find_one({"job_id": winner_id, "candidate_id": cand})
        if dup:
            await db.applications.delete_one({"_id": app["_id"]})
            report["applications_deduped"] += 1
        else:
            await db.applications.update_one({"_id": app["_id"]}, {"$set": {"job_id": winner_id}})
            report["applications_repointed"] += 1

    # saved_jobs : dédup avant repointage (unicité (user_id, job_id)).
    for sv in await db.saved_jobs.find({"job_id": {"$in": loser_ids}}).to_list(length=100000):
        user = sv.get("user_id")
        dup = await db.saved_jobs.find_one({"user_id": user, "job_id": winner_id})
        if dup:
            await db.saved_jobs.delete_one({"_id": sv["_id"]})
            report["saved_jobs_deduped"] += 1
        else:
            await db.saved_jobs.update_one({"_id": sv["_id"]}, {"$set": {"job_id": winner_id}})
            report["saved_jobs_repointed"] += 1

    # Events d'attribution (pas de contrainte d'unicité) : repointage. Ils ne
    # participent PAS à views_count (règle unique, pas de double comptage).
    res = await db.click_events.update_many(
        {"job_id": {"$in": loser_ids}},
        {"$set": {"job_id": winner_id, "campaign_id": winner_campaign}})
    report["click_events_repointed"] += res.modified_count
    res = await db.impression_events.update_many(
        {"job_id": {"$in": loser_ids}},
        {"$set": {"job_id": winner_id, "campaign_id": winner_campaign}})
    report["impression_events_repointed"] += res.modified_count

    # messages : schéma `job_id` confirmé (routes/messages.py).
    res = await db.messages.update_many({"job_id": {"$in": loser_ids}}, {"$set": {"job_id": winner_id}})
    report["messages_repointed"] += res.modified_count

    # views_count : compteurs STOCKÉS fusionnés uniquement.
    loser_views = sum(int(loser.get("views_count", 0) or 0) for loser in losers)
    app_count = await db.applications.count_documents({"job_id": winner_id})
    await db.jobs.update_one(
        {"_id": winner_id},
        {"$set": {
            "applications_count": app_count,
            "views_count": int(winner.get("views_count", 0) or 0) + loser_views,
            "updated_at": datetime.utcnow(),
        }})

    await db.jobs.delete_many({"_id": {"$in": loser_ids}})
    report["jobs_deleted"] += len(loser_ids)
    report["views_merged"] += loser_views


async def _identity_index_present(db) -> bool:
    """Index unique partiel réellement présent ET marqué `unique`."""
    try:
        info = await db.jobs.index_information()
    except Exception:
        return False
    if not isinstance(info, dict):
        return False
    spec = info.get(INDEX_NAME)
    return bool(spec and spec.get("unique"))


def _index_spec():
    return [("partner_id", 1), ("campaign_id", 1), ("external_ref", 1)]


async def _migrate(db, *, dry_run=False, force=False):
    """Exécute la migration. Retourne un rapport audit JSON-serialisable.

    Commandements :
    - `--dry-run` => AUCUNE écriture (ni dédup, ni index, ni marqueur) ;
    - l'index unique est créé AVANT le marqueur ; le marqueur n'est posé que si
      l'index existe RÉELLEMENT et est `unique` ;
    - idempotent : marqueur + index déjà présents => `already_migrated`, aucune
      écriture (sauf `--force`).
    """
    report = {
        "dry_run": dry_run,
        "groups": 0,
        "jobs_deleted": 0,
        "applications_repointed": 0,
        "applications_deduped": 0,
        "saved_jobs_repointed": 0,
        "saved_jobs_deduped": 0,
        "click_events_repointed": 0,
        "impression_events_repointed": 0,
        "messages_repointed": 0,
        "views_merged": 0,
        "index_present": False,
        "index_created": False,
        "marker_set": False,
        "already_migrated": False,
    }

    marker = await db.migration_flags.find_one({"_id": P0007_MARKER})
    if marker and not force and await _identity_index_present(db):
        report["already_migrated"] = True
        report["index_present"] = True
        return report

    # Dédup des doublons existants (aucune écriture en dry-run).
    groups = await _find_duplicate_groups(db)
    report["groups"] = len(groups)

    for group in groups:
        docs = await db.jobs.find({
            "partner_id": group["_id"]["partner_id"],
            "campaign_id": group["_id"]["campaign_id"],
            "external_ref": group["_id"]["external_ref"],
        }).to_list(length=10000)
        winner = _pick_winner(docs)
        losers = [d for d in docs if d["_id"] != winner["_id"]]
        if dry_run:
            continue
        await _consolidate(db, winner, losers, report)

    if dry_run:
        return report

    # Phase index : l'index unique DOIT être créé AVANT le marqueur.
    if await _identity_index_present(db):
        report["index_present"] = True
    else:
        await db.jobs.create_index(
            _index_spec(),
            name=INDEX_NAME,
            unique=True,
            partialFilterExpression={"campaign_id": {"$type": "string"}},
        )
        report["index_created"] = True

    # Vérification RÉELLE : le marqueur n'est posé qu'index unique physiquement
    # présent et `unique`. En cas de doute, aucune écriture de marqueur.
    if not await _identity_index_present(db):
        raise RuntimeError(
            "P0-007 : l'index unique p0007_identity_unique n'est pas confirmé après "
            "création — le marqueur n'est PAS posé. Aucune écriture de marqueur.",
        )

    # Phase marqueur : posé SEULEMENT après succès de l'index.
    if await db.migration_flags.find_one({"_id": P0007_MARKER}) is None:
        await db.migration_flags.insert_one({
            "_id": P0007_MARKER,
            "applied_at": datetime.utcnow(),
        })
        report["marker_set"] = True
    else:
        report["marker_set"] = True  # déjà présent (ex. --force) : pas d'écriture
    return report


def _build_parser():
    parser = argparse.ArgumentParser(
        description="Migration explicite P0-007 (identité campagne des offres de feed)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Rapport uniquement, AUCUNE écriture (ni dédup ni index ni marqueur)")
    parser.add_argument("--mongo-url", default=os.environ.get("MONGO_URL", "mongodb://127.0.0.1:27017"))
    parser.add_argument("--db-name", default=os.environ.get("DB_NAME", "indeed_clone"))
    parser.add_argument("--force", action="store_true",
                        help="Re-exécuter même si le marqueur et l'index sont déjà présents")
    return parser


def _parse_args(args=None):
    return _build_parser().parse_args(args)


async def _main():
    args = _parse_args()
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(args.mongo_url, serverSelectionTimeoutMS=5000)
    try:
        db = client[args.db_name]
        report = await _migrate(db, dry_run=args.dry_run, force=args.force)
        print(json.dumps(report, default=str, ensure_ascii=False, indent=2))
    finally:
        client.close()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except Exception as e:  # pragma: no cover
        print(f"Migration failed: {e}", file=sys.stderr)
        sys.exit(1)