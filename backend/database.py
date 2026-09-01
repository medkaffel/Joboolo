from motor.motor_asyncio import AsyncIOMotorClient
from typing import Optional
import os

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
    #
    # Déploiement sûr en DEUX PHASES : le script EXPLICITE et idempotent
    # `scripts/migrate_p0007_identity_indexes.py` déduplique d'abord les jobs
    # existants (consolidation applications/saved_jobs/events, recomputation des
    # compteurs) puis pose le marqueur `p0007_identity_indexes`. Ce startup ne
    # fait JAMAIS de migration destructive : il matérialise simplement l'index
    # unique lorsqu'une migration antérieure (ou l'opérateur) a posé le marqueur.
    # Avant ce marqueur, les créations de jobs de campagne sont fail-closed (503)
    # dans partner_feed.import_feed -> aucune fenêtre de doublons concurrents.
    marker = await db.migration_flags.find_one({"_id": "p0007_identity_indexes"})
    if marker:
        await db.jobs.create_index(
            [("partner_id", 1), ("campaign_id", 1), ("external_ref", 1)],
            name="p0007_identity_unique",
            unique=True,
            partialFilterExpression={"campaign_id": {"$type": "string"}},
        )
