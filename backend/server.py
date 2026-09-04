from fastapi import FastAPI, APIRouter
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path

# Load env BEFORE importing modules that read env at import time (email_service, storage, ...)
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Import database
from database import connect_to_mongo, close_mongo_connection

# Import routes
from routes import auth, jobs, applications, companies, saved_jobs, alerts, files, admin, payments, geo, content, recruiter, ai, messages, analytics, candidate_profiles

# Create the main app without a prefix
app = FastAPI(title="Joboolo API", version="1.0.0", redirect_slashes=False)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")

# Add health check endpoint
@api_router.get("/")
async def root():
    return {"message": "Indeed Clone API is running!"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "service": "indeed-clone-api"}

# A1 transitional façade MUST be registered before legacy auth so PUT /auth/me
# has one runtime writer for candidate professional facts.
api_router.include_router(candidate_profiles.compat_router)

# Include all route modules
api_router.include_router(auth.router)
api_router.include_router(candidate_profiles.router)
api_router.include_router(jobs.router)
api_router.include_router(applications.router)
api_router.include_router(companies.router)
api_router.include_router(saved_jobs.router)
api_router.include_router(alerts.router)
api_router.include_router(files.router)
api_router.include_router(admin.router)
api_router.include_router(payments.router)
api_router.include_router(geo.router)
api_router.include_router(content.router)
api_router.include_router(recruiter.router)
api_router.include_router(ai.router)
api_router.include_router(messages.router)
api_router.include_router(analytics.router)

# Include the router in the main app
app.include_router(api_router)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database event handlers
@app.on_event("startup")
async def startup_db_client():
    # P0-001 : fail-fast config AVANT toute connexion, seed ou scheduler.
    from config import validate_startup_config
    validate_startup_config()

    await connect_to_mongo()
    # Ensure geospatial index for distance-radius search
    try:
        from database import get_database
        db = await get_database()
        await db.jobs.create_index([("loc", "2dsphere")])
    except Exception as e:
        logging.warning(f"Geo index creation failed: {e}")
    # P0-002 : plus aucune création automatique de seed de démonstration ni de
    # compte administrateur au démarrage. Le seed et la création d'un admin
    # initial se font explicitement via des scripts dédiés (scripts/seed_dev.py,
    # scripts/create_admin.py), jamais silencieusement et jamais en production.
    # Seed default footer international country links (idempotent)
    try:
        from database import get_database
        from datetime import datetime
        import uuid as _uuid
        db = await get_database()
        if await db.footer_countries.count_documents({}) == 0:
            defaults = [
                ("es", "Empleo en España"), ("de", "Stellenangebote in Deutschland"),
                ("it", "Lavoro in Italia"), ("pt", "Emprego em Portugal"),
                ("ie", "Jobs in Ireland"), ("be", "Emplois en Belgique"),
                ("gb", "Jobs in the United Kingdom"), ("ch", "Stellenangebote in der Schweiz"),
                ("ru", "Работа в России"), ("br", "Emprego no Brasil"),
                ("au", "Jobs in Australia"), ("mx", "Empleo en México"),
                ("at", "Jobs in Österreich"),
            ]
            now = datetime.utcnow()
            await db.footer_countries.insert_many([{
                "_id": str(_uuid.uuid4()), "code": code, "label": label,
                "url": f"https://{code}.joboolo.com",
                "order": i, "is_active": True, "created_at": now, "updated_at": now,
            } for i, (code, label) in enumerate(defaults)])
            logging.info("Default footer countries seeded")
        # Migration : remplace les liens "#" par les sous-domaines
        stale = await db.footer_countries.find({"$or": [{"url": "#"}, {"url": ""}, {"url": None}]}).to_list(length=500)
        for c in stale:
            await db.footer_countries.update_one(
                {"_id": c["_id"]},
                {"$set": {"url": f"https://{c.get('code','')}.joboolo.com"}},
            )
    except Exception as e:
        logging.warning(f"Footer countries seeding failed: {e}")
    # Start job-alert email scheduler
    try:
        from scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        logging.warning(f"Scheduler start failed: {e}")
    # Initialize object storage (CV uploads)
    try:
        from storage import init_storage
        init_storage()
        logging.info("Object storage initialized")
    except Exception as e:
        logging.warning(f"Storage init failed: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    await close_mongo_connection()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
