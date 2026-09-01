from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
import logging
import os

# P0-007 : marqueur posé par la migration explicite
# scripts/migrate_p0007_identity_indexes.py APRÈS création réussie de l'index
# unique p0007_identity_unique. Le marqueur signifie réellement « index présent ».
P0007_MARKER = "p0007_identity_indexes"
P0007_INDEX_NAME = "p0007_identity_unique"

logger = logging.getLogger(__name__)


class Database:
    client: Optional[AsyncIOMotorClient] = None
    database = None

# Database instance
db_instance = Database()

async def get_database():
    return db_instance.database

def get_client() -> Optional[AsyncIOMotorClient]:
    """Retourne le client Mongo sous-jacent (pour ouvrir des sessions/transactions)."""
    return db_instance.client

async def connect_to_mongo():
    """Create database connection"""
    mongo_url = os.environ.get('MONGO_URL')
    db_name = os.environ.get('DB_NAME', 'indeed_clone')
    
    db_instance.client = AsyncIOMotorClient(mongo_url)
    db_instance.database = db_instance.client[db_name]
    
    # Create indexes
    await create_indexes()
    print(f"Connected to MongoDB database: {db_name}")

async def close_mongo_connection():
    """Close database connection"""
    if db_instance.client:
        db_instance.client.close()
        print("Disconnected from MongoDB")

async def _count_p0007_eligible_duplicate_jobs(db) -> int:
    """Nombre de groupes `(partner_id, campaign_id, external_ref)` (campaign_id
    string) ayant plus d'un job. Lecture seule — ne déduplique JAMAIS."""
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
        {"$count": "groups"},
    ]
    res = await db.jobs.aggregate(pipeline).to_list(length=10)
    return int(res[0]["groups"]) if res else 0


async def _p0007_identity_index_present(db) -> bool:
    """Index unique partiel réellement présent ET marqué `unique`."""
    try:
        info = await db.jobs.index_information()
    except Exception:
        return False
    if not isinstance(info, dict):
        return False
    spec = info.get(P0007_INDEX_NAME)
    return bool(spec and spec.get("unique"))


async def _create_p0007_identity_index_if_safe(db):
    """Materialise l'index unique d'identité de campagne SI la migration l'a
    demandé (marqueur présent) ET qu'aucun doublon éligible ne l'empêche.

    Sûreté au startup :
    - marqueur présent mais index déjà présent/unique => rien à faire ;
    - marqueur présent, index absent, ZÉRO doublon éligible => création sûre ;
    - marqueur présent, index absent, DOUBLONS présents (état partiel incohérent)
      => log explicite + AUCUNE création au startup (un create_index(unique=True)
      échouerait et ferait tomber le startup). La dédup n'a JAMAIS lieu au
      startup : elle est la responsabilité de la migration explicite.
    En cas d'erreur imprévue, on log et on ne fait pas tomber le startup."""
    marker = await db.migration_flags.find_one({"_id": P0007_MARKER})
    if not marker:
        return
    try:
        if await _p0007_identity_index_present(db):
            return
        dups = await _count_p0007_eligible_duplicate_jobs(db)
        if dups > 0:
            logger.warning(
                "P0-007 : marqueur %s présent mais index %s absent avec %d doublon(s) "
                "éligible(s). Index unique NON créé au startup (aucune dédup au startup). "
                "L'import de campagne reste fail-closed (503) tant que l'index physique "
                "n'est pas présent. Lancez scripts/migrate_p0007_identity_indexes.py.",
                P0007_MARKER, P0007_INDEX_NAME, dups,
            )
            return
        await db.jobs.create_index(
            [("partner_id", 1), ("campaign_id", 1), ("external_ref", 1)],
            name=P0007_INDEX_NAME,
            unique=True,
            partialFilterExpression={"campaign_id": {"$type": "string"}},
        )
        logger.info("P0-007 : index unique %s matérialisé au startup (marqueur présent, zéro doublon).", P0007_INDEX_NAME)
    except Exception as exc:
        logger.warning("P0-007 : création de l'index %s ignorée au startup : %s", P0007_INDEX_NAME, exc)


async def create_indexes():
    """Create database indexes for better performance"""
    db = db_instance.database
    
    # Jobs collection indexes
    await db.jobs.create_index("title")
    await db.jobs.create_index("location")
    await db.jobs.create_index("company_id")
    await db.jobs.create_index("employer_id")
    await db.jobs.create_index("created_at")
    await db.jobs.create_index("is_active")
    await db.jobs.create_index([("title", "text"), ("description", "text")])
    
    # Users collection indexes
    await db.users.create_index("email", unique=True)
    await db.users.create_index("user_type")
    
    # Companies collection indexes
    await db.companies.create_index("name")
    await db.companies.create_index("owner_id")
    
    # Applications collection indexes
    await db.applications.create_index("job_id")
    await db.applications.create_index("candidate_id")
    await db.applications.create_index([("job_id", 1), ("candidate_id", 1)], unique=True)
    
    # Saved jobs collection indexes
    await db.saved_jobs.create_index([("user_id", 1), ("job_id", 1)], unique=True)

    # P0-007 : identité des offres de feed d'une campagne = triplet
    # (partner_id, campaign_id, external_ref) <=> au plus UN job par campagne
    # et par référence (l'import d'un same external_ref réutilise le même job,
    # jamais un doublon, même sous concurrence).
    await _create_p0007_identity_index_if_safe(db)