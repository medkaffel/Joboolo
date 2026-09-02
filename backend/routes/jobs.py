from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from models import (
    Job, JobCreate, JobUpdate, JobResponse, JobSearchQuery, JobSearchResponse,
    User, UserType
)
from database import get_database
from auth import get_current_active_user, require_employer
from datetime import datetime, timedelta
from geo_service import resolve_location_codes, postcode_regex, geocode_place
from campaign_lifecycle import (
    is_job_publicly_visible,
    get_job_campaign,
    fetch_public_job_filter,
)
import re

router = APIRouter(prefix="/jobs", tags=["jobs"])


class InsufficientPremiumCredits(Exception):
    """Signal interne : la décrémentation conditionnelle du crédit a échoué."""


def _is_unsupported_transaction(exc: Exception) -> bool:
    """Détecte une erreur Mongo signalant que les transactions (replica set) ne
    sont pas supportées par la topologie runtime, pour fail-closed 503."""
    text = str(exc)
    lowered = text.lower()
    markers = (
        "replica set",
        "replicaset",
        "transaction numbers",
        "do not support transactions",
        "not supported on standalone",
        "standalone",
        "no such command: 'commitTransaction'",
        "session support",
        "mongos",
    )
    return any(m in lowered for m in markers)


async def _resolve_logo(job_doc: dict, db):
    """Logo affiché sur l'offre : logo de la campagne, sinon logo du partenaire."""
    if not job_doc.get("is_partner"):
        return None
    if job_doc.get("campaign_id"):
        camp = await db.campaigns.find_one({"_id": job_doc["campaign_id"]})
        if camp and camp.get("logo_url"):
            return camp["logo_url"]
    if job_doc.get("partner_id"):
        prof = await db.partner_profiles.find_one({"user_id": job_doc["partner_id"]})
        if prof and prof.get("logo_url"):
            return prof["logo_url"]
    return None


async def _check_low_balance(db, partner_id: str):
    """Send a one-shot low-balance email when the balance drops below the admin threshold."""
    try:
        from routes.admin import get_settings
        from email_service import build_low_balance_email, send_alert_email
        import os
        settings = await get_settings(db)
        threshold = float(settings.get("low_balance_threshold", 10.0))
        profile = await db.partner_profiles.find_one({"user_id": partner_id})
        if not profile:
            return
        balance = float(profile.get("balance", 0.0))
        if balance < threshold and not profile.get("low_balance_notified"):
            await db.partner_profiles.update_one({"user_id": partner_id}, {"$set": {"low_balance_notified": True}})
            user = await db.users.find_one({"_id": partner_id})
            if user and user.get("email") and not profile.get("no_login"):
                app_url = os.environ.get("APP_PUBLIC_URL", "https://joboolo.fr")
                subject, html = build_low_balance_email(profile.get("company_name", "Partenaire"), balance, threshold, app_url)
                await send_alert_email(user["email"], subject, html)
        elif balance >= threshold and profile.get("low_balance_notified"):
            await db.partner_profiles.update_one({"user_id": partner_id}, {"$set": {"low_balance_notified": False}})
    except Exception:
        pass

async def populate_job_response(job_doc: dict, db) -> JobResponse:
    """Populate job response with company info and computed fields"""
    # Get company info
    company = await db.companies.find_one({"_id": job_doc["company_id"]})
    if not company:
        company = {"name": "Entreprise non trouvée", "location": ""}
    
    # Check if job is new (less than 7 days old)
    created_at = job_doc["created_at"]
    is_new = (datetime.utcnow() - created_at).days < 7

    logo_url = await _resolve_logo(job_doc, db)

    return JobResponse(
        id=job_doc["_id"],
        title=job_doc["title"],
        description=job_doc["description"],
        company={
            "id": company.get("_id", ""),
            "name": company.get("name", "Entreprise"),
            "location": company.get("location", ""),
            "industry": company.get("industry", ""),
            "size": company.get("size", "")
        },
        location=job_doc["location"],
        salary_min=job_doc.get("salary_min"),
        salary_max=job_doc.get("salary_max"),
        salary_currency=job_doc.get("salary_currency", "EUR"),
        job_type=job_doc["job_type"],
        is_remote=job_doc.get("is_remote", False),
        is_urgent=job_doc.get("is_urgent", False),
        requirements=job_doc.get("requirements", []),
        benefits=job_doc.get("benefits", []),
        tags=job_doc.get("tags", []),
        is_active=job_doc.get("is_active", True),
        is_premium=job_doc.get("is_premium", False),
        views_count=job_doc.get("views_count", 0),
        applications_count=job_doc.get("applications_count", 0),
        created_at=job_doc["created_at"],
        is_new=is_new,
        is_partner=job_doc.get("is_partner", False),
        external_url=job_doc.get("external_url"),
        cpc=job_doc.get("cpc"),
        logo_url=logo_url,
    )

@router.get("/suggest")
async def suggest(q: str = Query("", description="prefix"), field: str = Query("title", description="title|location|company")):
    """Autocomplete suggestions from existing job data."""
    db = await get_database()
    q = (q or "").strip()
    if len(q) < 2:
        return {"suggestions": []}
    rx = {"$regex": q, "$options": "i"}
    # P0-006 : seules les offres publiquement visibles participent au suggest.
    public_filter = await fetch_public_job_filter(db)
    if field == "location":
        vals = await db.jobs.distinct("location", {**public_filter, "location": rx})
    elif field == "company":
        comps = await db.companies.find({"name": rx}).limit(8).to_list(length=8)
        return {"suggestions": [c.get("name") for c in comps if c.get("name")][:8]}
    else:
        vals = await db.jobs.distinct("title", {**public_filter, "title": rx})
    vals = [v for v in vals if v][:8]
    return {"suggestions": vals}


@router.get("", response_model=JobSearchResponse)
async def search_jobs(
    search: Optional[str] = Query(None, description="Search in title and description"),
    location: Optional[str] = Query(None, description="Filter by location"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    is_remote: Optional[bool] = Query(None, description="Filter remote jobs"),
    salary_min: Optional[int] = Query(None, description="Minimum salary filter"),
    company_id: Optional[str] = Query(None, description="Filter by company"),
    company: Optional[str] = Query(None, description="Filter by company name"),
    posted_within: Optional[int] = Query(None, description="Only jobs posted within N days"),
    radius: Optional[float] = Query(None, description="Distance radius in km (needs a geocodable location)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    sort: str = Query("created_at", description="Sort field: created_at, salary_min, title")
):
    """Search and filter jobs with pagination"""
    db = await get_database()
    
    # P0-006 : la base du filtre est le garde public (is_active + expiration +
    # campagne diffusible). Les clauses utilisateur sont concaténées au tableau
    # $and existant, sans écraser la visibilité.
    query = await fetch_public_job_filter(db)
    and_clauses = []

    if search:
        # Text search in title and description
        and_clauses.append({"$or": [
            {"title": {"$regex": search, "$options": "i"}},
            {"description": {"$regex": search, "$options": "i"}},
            {"tags": {"$in": [re.compile(search, re.IGNORECASE)]}},
        ]})

    if location:
        geo_applied = False
        # Vrai rayon de distance : géocode le lieu -> filtre géospatial dans le rayon
        if radius:
            center = await geocode_place(location)
            if center:
                query["loc"] = {"$geoWithin": {"$centerSphere": [center, float(radius) / 6378.1]}}
                geo_applied = True
        if not geo_applied:
            codes = await resolve_location_codes(location)
            if codes:
                # Nom exact de département/région -> on restreint aux codes postaux du périmètre
                loc_or = [{"location": {"$regex": postcode_regex(code)}} for code in codes]
            else:
                # Ville / code postal / texte libre -> correspondance texte directe
                loc_or = [{"location": {"$regex": re.escape(location), "$options": "i"}}]
            and_clauses.append({"$or": loc_or})

    if and_clauses:
        # Ne pas écraser le $and de visibilité : concaténer.
        query["$and"] = list(query.get("$and", [])) + and_clauses

    if job_type:
        query["job_type"] = job_type
    
    if is_remote is not None:
        query["is_remote"] = is_remote
    
    if salary_min:
        query["salary_min"] = {"$gte": salary_min}
    
    if company_id:
        query["company_id"] = company_id
    
    if company:
        comp_ids = await db.companies.distinct("_id", {"name": {"$regex": company, "$options": "i"}})
        query["company_id"] = {"$in": comp_ids} if comp_ids else {"$in": ["__none__"]}
    
    if posted_within:
        query["created_at"] = {"$gte": datetime.utcnow() - timedelta(days=posted_within)}
    
    # Count total results
    total = await db.jobs.count_documents(query)
    
    # Build sort criteria
    sort_criteria = []
    if sort == "created_at":
        sort_criteria = [("created_at", -1)]  # Newest first
    elif sort == "salary_min":
        sort_criteria = [("salary_min", -1)]  # Highest salary first
    elif sort == "title":
        sort_criteria = [("title", 1)]  # Alphabetical
    else:
        sort_criteria = [("created_at", -1)]  # Default
    
    # Calculate pagination
    skip = (page - 1) * limit
    total_pages = (total + limit - 1) // limit
    
    # Get jobs
    cursor = db.jobs.find(query).sort(sort_criteria).skip(skip).limit(limit)
    jobs_docs = await cursor.to_list(length=limit)
    
    # Populate responses
    jobs = []
    for job_doc in jobs_docs:
        job_response = await populate_job_response(job_doc, db)
        jobs.append(job_response)
    
    return JobSearchResponse(
        jobs=jobs,
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages
    )

@router.get("/mine", response_model=List[JobResponse])
async def get_my_jobs(current_user: User = Depends(require_employer)):
    """All jobs owned by the current employer (active AND inactive)."""
    db = await get_database()
    docs = await db.jobs.find({"employer_id": current_user.id}).sort([("created_at", -1)]).to_list(length=1000)
    return [await populate_job_response(d, db) for d in docs]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    """Get a specific job by ID (public detail: only publicly visible offers)."""
    db = await get_database()
    
    job_doc = await db.jobs.find_one({"_id": job_id})
    if not job_doc or not is_job_publicly_visible(job_doc, await get_job_campaign(db, job_doc)):
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Increment view count
    await db.jobs.update_one(
        {"_id": job_id},
        {"$inc": {"views_count": 1}}
    )
    job_doc["views_count"] += 1
    
    return await populate_job_response(job_doc, db)

@router.post("", response_model=JobResponse)
async def create_job(
    job_data: JobCreate,
    current_user: User = Depends(require_employer)
):
    """Create a new job posting (employers only)"""
    db = await get_database()
    
    # Verify company belongs to user
    company = await db.companies.find_one({
        "_id": job_data.company_id,
        "owner_id": current_user.id
    })
    if not company:
        raise HTTPException(
            status_code=403,
            detail="You can only post jobs for companies you own"
        )
    
    is_premium = bool(getattr(job_data, "is_premium", False))

    # P0-010: geocode location BEFORE any Mongo write / transaction
    center = await geocode_place(job_data.location)

    # Create job document
    job_doc = {
        "_id": f"job_{datetime.utcnow().timestamp()}",
        **job_data.dict(),
        "employer_id": current_user.id,
        "is_active": True,
        "is_premium": is_premium,
        "premium_granted_at": datetime.utcnow() if is_premium else None,
        "views_count": 0,
        "applications_count": 0,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    if center:
        job_doc["loc"] = {"type": "Point", "coordinates": center}
    if is_premium:
        # P0-005 : la publication Premium consomme exactement 1 crédit recruteur.
        # Consommation et insertion sont atomiques dans une transaction Mongo
        # multi-documents (users + jobs) : commit => les deux réussissent,
        # abort => aucun crédit consommé et aucun job créé. La topologie runtime
        # n'est pas supposée : si elle ne supporte pas les transactions on
        # FAIL CLOSED (503) sans débit ni insertion, jamais de fallback best-effort.
        # Import lazy : n'est résolu qu'au moment d'une création Premium, pour ne
        # pas imposer get_client au chargement du module (les tests existants qui
        # n'utilisent pas de transactions n'ont pas besoin de ce symbole).
        from database import get_client
        client = get_client()
        if client is None:
            raise HTTPException(
                status_code=503,
                detail="Base de données indisponible.",
            )
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    credit = await db.users.update_one(
                        {"_id": current_user.id, "premium_credits": {"$gte": 1}},
                        {"$inc": {"premium_credits": -1}},
                        session=session,
                    )
                    if credit.modified_count == 0:
                        # Lève hors de la transaction : le context manager l'abort,
                        # aucun crédit consommé et aucun job créé.
                        raise InsufficientPremiumCredits()
                    await db.jobs.insert_one(job_doc, session=session)
        except InsufficientPremiumCredits:
            raise HTTPException(
                status_code=402,
                detail="Crédits premium insuffisants. Veuillez acheter un pack d'offres Premium.",
            )
        except Exception as exc:
            if _is_unsupported_transaction(exc):
                raise HTTPException(
                    status_code=503,
                    detail="Les transactions MongoDB ne sont pas disponibles. Publication Premium momentanément indisponible. Aucun crédit n'a été débité.",
                )
            raise
    else:
        # Offre standard : aucune consommation de crédit, comportement inchangé.
        await db.jobs.insert_one(job_doc)

    return await populate_job_response(job_doc, db)

@router.put("/{job_id}", response_model=JobResponse)
async def update_job(
    job_id: str,
    job_data: JobUpdate,
    current_user: User = Depends(require_employer)
):
    """Update a job posting (owner only)"""
    db = await get_database()
    
    # Check if job exists and belongs to user
    job = await db.jobs.find_one({
        "_id": job_id,
        "employer_id": current_user.id
    })
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found or you don't have permission to edit it"
        )
    
    # P0-010: handle location change with geocoding
    update_data = {k: v for k, v in job_data.dict().items() if v is not None}
    new_location = update_data.get("location")
    old_location = job.get("location")
    loc_changed = new_location is not None and new_location != old_location
    
    if loc_changed:
        center = await geocode_place(new_location)
        if center:
            update_data["loc"] = {"type": "Point", "coordinates": center}
        else:
            update_data["loc"] = None  # marker for $unset
    
    # Build mongo update with $set and conditional $unset for loc
    mongo_update = {"$set": {k: v for k, v in update_data.items() if v is not None}}
    if loc_changed and update_data.get("loc") is None:
        mongo_update["$unset"] = {"loc": ""}
    
    await db.jobs.update_one(
        {"_id": job_id},
        mongo_update
    )
    
    # Get updated job
    updated_job = await db.jobs.find_one({"_id": job_id})
    return await populate_job_response(updated_job, db)

@router.post("/{job_id}/toggle")
async def toggle_job(job_id: str, current_user: User = Depends(require_employer)):
    """Activate/deactivate a job posting (owner only)."""
    db = await get_database()
    job = await db.jobs.find_one({"_id": job_id, "employer_id": current_user.id})
    if not job:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    new_state = not job.get("is_active", True)
    await db.jobs.update_one({"_id": job_id}, {"$set": {"is_active": new_state, "updated_at": datetime.utcnow()}})
    return {"id": job_id, "is_active": new_state}


@router.delete("/{job_id}")
async def delete_job(
    job_id: str,
    current_user: User = Depends(require_employer)
):
    """Permanently delete a job posting (owner only)"""
    db = await get_database()
    
    # Check if job exists and belongs to user
    job = await db.jobs.find_one({
        "_id": job_id,
        "employer_id": current_user.id
    })
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found or you don't have permission to delete it"
        )
    
    await db.jobs.delete_one({"_id": job_id})
    return {"message": "Job deleted successfully"}

@router.get("/company/{company_id}", response_model=List[JobResponse])
async def get_company_jobs(company_id: str):
    """Get all jobs for a specific company"""
    db = await get_database()
    
    # Verify company exists
    company = await db.companies.find_one({"_id": company_id})
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    
    # Get public jobs for the company (P0-006 : garde public)
    public_filter = await fetch_public_job_filter(db)
    query = {**public_filter, "company_id": company_id}
    cursor = db.jobs.find(query).sort([("created_at", -1)])
    
    jobs_docs = await cursor.to_list(length=100)
    
    jobs = []
    for job_doc in jobs_docs:
        job_response = await populate_job_response(job_doc, db)
        jobs.append(job_response)
    
    return jobs

@router.post("/{job_id}/click")
async def record_partner_click(job_id: str):
    """Record a click on a partner job, apply per-click billing, return redirect URL."""
    db = await get_database()
    job = await db.jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Offre introuvable")

    # P0-006 : refuser un clic sur une offre non publiquement visible AVANT
    # tout redirect, débit, compteur ou attribution. Job inactif / expiré /
    # campagne non diffusible => 404, aucun clic ni impulsion, et on ne
    # réactive JAMAIS un job (ex. arrêté pour solde CPC insuffisant).
    job_campaign = await get_job_campaign(db, job)
    if not is_job_publicly_visible(job, job_campaign):
        raise HTTPException(status_code=404, detail="Offre introuvable")

    redirect_url = job.get("external_url")
    if not job.get("is_partner") or not redirect_url:
        raise HTTPException(status_code=400, detail="Offre non partenaire")

    profile = await db.partner_profiles.find_one({"user_id": job.get("partner_id")})
    charged = 0.0
    stopped = False
    if profile and profile.get("billing_mode") == "per_click":
        cpc = job.get("cpc") if job.get("cpc") is not None else profile.get("default_cpc", 0.0)
        cpc = float(cpc or 0.0)
        if cpc > 0:
            # Atomic balance check + debit: filter requires balance >= cpc
            result = await db.partner_profiles.update_one(
                {"user_id": job["partner_id"], "balance": {"$gte": cpc}},
                {"$inc": {"total_clicks": 1, "balance": -cpc, "total_spent": cpc}},
            )
            if result.modified_count == 1:
                charged = cpc
                await _check_low_balance(db, job["partner_id"])
            else:
                # Insufficient balance: no debit, but count the click once
                await db.partner_profiles.update_one({"user_id": job["partner_id"]}, {"$inc": {"total_clicks": 1}})
                stopped = True
                await db.jobs.update_one({"_id": job_id}, {"$set": {"is_active": False}})
        else:
            await db.partner_profiles.update_one({"user_id": job["partner_id"]}, {"$inc": {"total_clicks": 1}})
    elif profile:
        await db.partner_profiles.update_one({"user_id": job["partner_id"]}, {"$inc": {"total_clicks": 1}})

    if profile:
        await db.click_events.insert_one({
            "partner_id": job["partner_id"],
            "job_id": job_id,
            "job_title": job.get("title"),
            "campaign_id": job.get("campaign_id"),
            "cost": charged,
            "stopped": stopped,
            "ts": datetime.utcnow(),
        })

    # Attribute the click to its campaign + auto-pause when the budget is exhausted
    if job.get("campaign_id"):
        await db.campaigns.update_one(
            {"_id": job["campaign_id"]},
            {"$inc": {"clicks": 1, "spent": charged}},
        )
        camp = await db.campaigns.find_one({"_id": job["campaign_id"]})
        # P0-006 : la mise en pause automatique à épuisement du budget n'a lieu
        # QUE pour une campagne per_click avec un budget_limit défini :
        # spent >= budget_limit. Un budget_limit résiduel sur per_posting ne
        # met JAMAIS la campagne en pause. Les offres de la campagne ne sont
        # PAS désactivées : la diffusibilité est calculée dynamiquement par
        # campaign_lifecycle, et une reprise ne doit jamais ressusciter un job
        # arrêté pour une autre raison (ex. P0-004 solde CPC insuffisant).
        if (camp
                and camp.get("billing_mode") == "per_click"
                and camp.get("budget_limit") is not None
                and float(camp.get("spent", 0.0)) >= float(camp["budget_limit"])):
            await db.campaigns.update_one({"_id": job["campaign_id"]}, {"$set": {"status": "paused"}})

    await db.jobs.update_one({"_id": job_id}, {"$inc": {"views_count": 1}})
    return {"redirect_url": redirect_url}


from pydantic import BaseModel


class ImpressionBatch(BaseModel):
    job_ids: List[str] = []


@router.post("/impressions")
async def record_impressions(body: ImpressionBatch):
    """Log real impressions for partner jobs shown in the results list.
    Deduplication is handled client-side (per browser session)."""
    db = await get_database()
    ids = [i for i in (body.job_ids or []) if i][:100]
    if not ids:
        return {"recorded": 0}
    # P0-006 : ne journaliser que les impressions d'offres publiquement visibles.
    query = await fetch_public_job_filter(db)
    query["_id"] = {"$in": ids}
    query["is_partner"] = True
    jobs = await db.jobs.find(query).to_list(length=len(ids))
    now = datetime.utcnow()
    events, camp_inc, partner_inc = [], {}, {}
    for j in jobs:
        pid = j.get("partner_id")
        events.append({
            "partner_id": pid,
            "job_id": j["_id"],
            "job_title": j.get("title"),
            "campaign_id": j.get("campaign_id"),
            "ts": now,
        })
        if j.get("campaign_id"):
            camp_inc[j["campaign_id"]] = camp_inc.get(j["campaign_id"], 0) + 1
        if pid:
            partner_inc[pid] = partner_inc.get(pid, 0) + 1
    if events:
        await db.impression_events.insert_many(events)
    for cid, n in camp_inc.items():
        await db.campaigns.update_one({"_id": cid}, {"$inc": {"impressions": n}})
    for pid, n in partner_inc.items():
        await db.partner_profiles.update_one({"user_id": pid}, {"$inc": {"total_impressions": n}})
    return {"recorded": len(events)}
