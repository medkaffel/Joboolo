from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from datetime import datetime
import uuid
import xml.etree.ElementTree as ET
import httpx
from pydantic import BaseModel

from database import get_database
from auth import require_admin, get_password_hash, get_user_by_email
from email_utils import canonical_email, lookup_user_by_email
from models import (
    User, AdminUserUpdate, PartnerCreate, PartnerConfigUpdate, PartnerBillingMode
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _user_out(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "email": doc.get("email"),
        "first_name": doc.get("first_name"),
        "last_name": doc.get("last_name"),
        "user_type": doc.get("user_type"),
        "phone": doc.get("phone"),
        "location": doc.get("location"),
        "is_active": doc.get("is_active", True),
        "signup_source": doc.get("signup_source"),
        "signup_referrer": doc.get("signup_referrer"),
        "utm_source": doc.get("utm_source"),
        "utm_campaign": doc.get("utm_campaign"),
        "created_at": doc.get("created_at"),
    }


@router.get("/stats")
async def admin_stats(admin: User = Depends(require_admin)):
    db = await get_database()
    return {
        "candidates": await db.users.count_documents({"user_type": "candidate"}),
        "employers": await db.users.count_documents({"user_type": "employer"}),
        "partners": await db.users.count_documents({"user_type": "partner"}),
        "jobs": await db.jobs.count_documents({}),
        "active_jobs": await db.jobs.count_documents({"is_active": True}),
        "applications": await db.applications.count_documents({}),
    }


# ---------- Users ----------
@router.get("/users")
async def list_users(
    user_type: str = Query(...),
    search: Optional[str] = None,
    admin: User = Depends(require_admin),
):
    db = await get_database()
    query = {"user_type": user_type}
    if search:
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"first_name": {"$regex": search, "$options": "i"}},
            {"last_name": {"$regex": search, "$options": "i"}},
        ]
    docs = await db.users.find(query).sort([("created_at", -1)]).limit(500).to_list(length=500)
    return [_user_out(d) for d in docs]


@router.put("/users/{user_id}")
async def update_user(user_id: str, data: AdminUserUpdate, admin: User = Depends(require_admin)):
    db = await get_database()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="Aucune donnée à mettre à jour")
    fields["updated_at"] = datetime.utcnow()
    res = await db.users.update_one({"_id": user_id}, {"$set": fields})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return _user_out(await db.users.find_one({"_id": user_id}))


@router.post("/users/{user_id}/toggle")
async def toggle_user(user_id: str, admin: User = Depends(require_admin)):
    db = await get_database()
    doc = await db.users.find_one({"_id": user_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    new_state = not doc.get("is_active", True)
    await db.users.update_one({"_id": user_id}, {"$set": {"is_active": new_state}})
    return {"id": user_id, "is_active": new_state}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: User = Depends(require_admin)):
    db = await get_database()
    res = await db.users.delete_one({"_id": user_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    await db.partner_profiles.delete_many({"user_id": user_id})
    return {"message": "Compte supprimé"}


# ---------- Partners ----------
async def _partner_out(db, user_doc: dict) -> dict:
    profile = await db.partner_profiles.find_one({"user_id": user_doc["_id"]}) or {}
    out = _user_out(user_doc)
    out["profile"] = {
        "company_name": profile.get("company_name"),
        "billing_mode": profile.get("billing_mode", "per_click"),
        "default_cpc": profile.get("default_cpc", 0.0),
        "posting_price": profile.get("posting_price", 0.0),
        "xml_feed_url": profile.get("xml_feed_url"),
        "postings_remaining": profile.get("postings_remaining", 0),
        "balance": profile.get("balance", 0.0),
        "total_clicks": profile.get("total_clicks", 0),
        "total_spent": profile.get("total_spent", 0.0),
    }
    return out


@router.get("/partners")
async def list_partners(search: Optional[str] = None, admin: User = Depends(require_admin)):
    db = await get_database()
    query = {"user_type": "partner"}
    if search:
        # Search by email, contact name OR company_name (needs a join through partner_profiles)
        profile_matches = await db.partner_profiles.find(
            {"company_name": {"$regex": search, "$options": "i"}}
        ).to_list(length=500)
        matching_user_ids = [p.get("user_id") for p in profile_matches if p.get("user_id")]
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"first_name": {"$regex": search, "$options": "i"}},
            {"last_name": {"$regex": search, "$options": "i"}},
            {"_id": {"$in": matching_user_ids}},
        ]
    docs = await db.users.find(query).sort([("created_at", -1)]).limit(500).to_list(length=500)
    return [await _partner_out(db, d) for d in docs]


@router.get("/partners/pending")
async def list_pending_partners(search: Optional[str] = None, admin: User = Depends(require_admin)):
    db = await get_database()
    query = {"user_type": "partner", "is_active": False}
    if search:
        profile_matches = await db.partner_profiles.find(
            {"company_name": {"$regex": search, "$options": "i"}}
        ).to_list(length=500)
        matching_user_ids = [p.get("user_id") for p in profile_matches if p.get("user_id")]
        query["$or"] = [
            {"email": {"$regex": search, "$options": "i"}},
            {"first_name": {"$regex": search, "$options": "i"}},
            {"last_name": {"$regex": search, "$options": "i"}},
            {"_id": {"$in": matching_user_ids}},
        ]
    docs = await db.users.find(query).sort([("created_at", -1)]).limit(500).to_list(length=500)
    return [await _partner_out(db, d) for d in docs]


@router.post("/partners/{user_id}/validate")
async def validate_partner(user_id: str, admin: User = Depends(require_admin)):
    db = await get_database()
    user = await db.users.find_one({"_id": user_id, "user_type": "partner"})
    if not user:
        raise HTTPException(status_code=404, detail="Partenaire introuvable")
    now = datetime.utcnow()
    await db.users.update_one({"_id": user_id}, {"$set": {"is_active": True, "pending_validation": False, "updated_at": now}})
    await db.partner_profiles.update_one({"user_id": user_id}, {"$set": {"is_active": True, "pending_validation": False, "updated_at": now}})
    # Email de bienvenue (best-effort)
    try:
        import os
        from email_service import build_partner_welcome_email, send_alert_email
        profile = await db.partner_profiles.find_one({"user_id": user_id}) or {}
        app_url = os.environ.get("FRONTEND_URL", "https://joboolo.fr")
        if user.get("email"):
            subject, html = build_partner_welcome_email(profile.get("company_name") or "Partenaire", app_url)
            await send_alert_email(user["email"], subject, html)
    except Exception:
        pass
    return {"message": "Partenaire validé et activé", "is_active": True}


@router.post("/partners")
async def create_partner(data: PartnerCreate, admin: User = Depends(require_admin)):
    db = await get_database()
    # P0-009: canonicalize email
    email = canonical_email(data.email)
    if await lookup_user_by_email(email):
        raise HTTPException(status_code=400, detail="Email déjà utilisé")

    user_id = f"partner_{uuid.uuid4()}"
    now = datetime.utcnow()
    user_doc = {
        "_id": user_id,
        "email": email,
        "first_name": data.first_name,
        "last_name": data.last_name,
        "user_type": "partner",
        "hashed_password": get_password_hash(data.password),
        "phone": None, "location": None, "bio": None, "skills": [], "experience_years": None,
        "is_active": True, "is_verified": True,
        "created_at": now, "updated_at": now,
    }
    try:
        await db.users.insert_one(user_doc)
    except Exception:
        existing = await lookup_user_by_email(email)
        if existing:
            raise HTTPException(status_code=400, detail="Email déjà utilisé")
        raise HTTPException(status_code=409, detail="Email déjà utilisé")

    profile = {
        "_id": str(uuid.uuid4()),
        "user_id": user_id,
        "company_name": data.company_name,
        "billing_mode": data.billing_mode,
        "default_cpc": data.default_cpc,
        "posting_price": data.posting_price,
        "xml_feed_url": data.xml_feed_url,
        "postings_remaining": 0,
        "balance": 0.0,
        "total_clicks": 0,
        "total_spent": 0.0,
        "is_active": True,
        "created_at": now, "updated_at": now,
    }
    await db.partner_profiles.insert_one(profile)
    return await _partner_out(db, user_doc)


@router.put("/partners/{user_id}/config")
async def update_partner_config(user_id: str, data: PartnerConfigUpdate, admin: User = Depends(require_admin)):
    db = await get_database()
    profile = await db.partner_profiles.find_one({"user_id": user_id})
    if not profile:
        raise HTTPException(status_code=404, detail="Partenaire introuvable")

    updates = {}
    for field in ("company_name", "billing_mode", "default_cpc", "posting_price", "xml_feed_url"):
        val = getattr(data, field)
        if val is not None:
            updates[field] = val
    inc = {}
    if data.add_pack:
        inc["postings_remaining"] = data.add_pack
    if data.add_balance:
        inc["balance"] = data.add_balance
    if data.is_active is not None:
        updates["is_active"] = data.is_active
        await db.users.update_one({"_id": user_id}, {"$set": {"is_active": data.is_active}})

    ops = {}
    if updates:
        updates["updated_at"] = datetime.utcnow()
        ops["$set"] = updates
    if inc:
        ops["$inc"] = inc
    if ops:
        await db.partner_profiles.update_one({"user_id": user_id}, ops)

    user_doc = await db.users.find_one({"_id": user_id})
    return await _partner_out(db, user_doc)


# ---------- General settings (admin) ----------
DEFAULT_SETTINGS = {"pack_validity_days": 30, "low_balance_threshold": 10.0, "feed_refresh_hours": 24, "recruiter_premium_price": 299.0}


async def get_settings(db) -> dict:
    doc = await db.settings.find_one({"_id": "global"}) or {}
    return {**DEFAULT_SETTINGS, **{k: v for k, v in doc.items() if k != "_id"}}


class SettingsUpdate(BaseModel):
    pack_validity_days: Optional[int] = None
    low_balance_threshold: Optional[float] = None
    feed_refresh_hours: Optional[int] = None
    recruiter_premium_price: Optional[float] = None


@router.get("/settings")
async def read_settings(admin: User = Depends(require_admin)):
    db = await get_database()
    return await get_settings(db)


@router.put("/settings")
async def update_settings(data: SettingsUpdate, admin: User = Depends(require_admin)):
    db = await get_database()
    fields = {k: v for k, v in data.dict().items() if v is not None}
    if fields:
        await db.settings.update_one({"_id": "global"}, {"$set": fields}, upsert=True)
    return await get_settings(db)


# ---------- XML feed campaigns (admin) ----------
class XmlFeedCreate(BaseModel):
    source_name: str
    url: str
    billing_mode: PartnerBillingMode = PartnerBillingMode.PER_CLICK
    cpc: float = 0.0
    pack_price: float = 0.0
    # Assign to an existing partner OR create a new (login-less) partner
    partner_id: Optional[str] = None
    new_partner_email: Optional[str] = None
    new_partner_company: Optional[str] = None


async def _feed_out(db, doc: dict) -> dict:
    profile = await db.partner_profiles.find_one({"user_id": doc.get("partner_id")}) or {}
    return {
        "id": doc["_id"],
        "source_name": doc.get("source_name"),
        "url": doc.get("url"),
        "billing_mode": doc.get("billing_mode"),
        "cpc": doc.get("cpc", 0.0),
        "pack_price": doc.get("pack_price", 0.0),
        "partner_id": doc.get("partner_id"),
        "company_name": profile.get("company_name"),
        "last_import_at": doc.get("last_import_at"),
        "last_result": doc.get("last_result"),
        "created_at": doc.get("created_at"),
    }


@router.get("/xml-feeds")
async def list_xml_feeds(admin: User = Depends(require_admin)):
    db = await get_database()
    docs = await db.xml_feeds.find().sort([("created_at", -1)]).limit(200).to_list(length=200)
    return [await _feed_out(db, d) for d in docs]


@router.post("/xml-feeds")
async def create_xml_feed(data: XmlFeedCreate, admin: User = Depends(require_admin)):
    db = await get_database()
    now = datetime.utcnow()

    partner_id = data.partner_id
    if not partner_id:
        # Create a login-less partner
        if not data.new_partner_company:
            raise HTTPException(status_code=400, detail="Nom du partenaire requis")
        # P0-009: canonicalize email
        email = canonical_email(data.new_partner_email or f"feed-{uuid.uuid4().hex[:8]}@partenaire.joboolo")
        if await lookup_user_by_email(email):
            raise HTTPException(status_code=400, detail="Email déjà utilisé")
        partner_id = f"partner_{uuid.uuid4()}"
        try:
            await db.users.insert_one({
                "_id": partner_id, "email": email, "first_name": data.new_partner_company, "last_name": None,
                "user_type": "partner", "hashed_password": None,  # login-less
                "is_active": True, "is_verified": True, "created_at": now, "updated_at": now,
            })
        except Exception:
            existing = await lookup_user_by_email(email)
            if existing:
                raise HTTPException(status_code=400, detail="Email déjà utilisé")
            raise HTTPException(status_code=409, detail="Email déjà utilisé")
        await db.partner_profiles.insert_one({
            "_id": str(uuid.uuid4()), "user_id": partner_id, "company_name": data.new_partner_company,
            "billing_mode": data.billing_mode, "default_cpc": data.cpc, "posting_price": data.pack_price,
            "xml_feed_url": data.url, "postings_remaining": 0, "balance": 0.0,
            "total_clicks": 0, "total_spent": 0.0, "is_active": True, "no_login": True,
            "created_at": now, "updated_at": now,
        })
    else:
        # Sync feed config into the existing partner profile
        await db.partner_profiles.update_one(
            {"user_id": partner_id},
            {"$set": {"xml_feed_url": data.url, "billing_mode": data.billing_mode,
                      "default_cpc": data.cpc, "posting_price": data.pack_price, "updated_at": now}},
        )

    feed_doc = {
        "_id": f"feed_{uuid.uuid4()}", "source_name": data.source_name, "url": data.url,
        "billing_mode": data.billing_mode, "cpc": data.cpc, "pack_price": data.pack_price,
        "partner_id": partner_id, "last_import_at": None, "last_result": None, "created_at": now,
    }
    await db.xml_feeds.insert_one(feed_doc)
    return await _feed_out(db, feed_doc)


@router.post("/xml-feeds/{feed_id}/import")
async def import_xml_feed(feed_id: str, admin: User = Depends(require_admin)):
    db = await get_database()
    feed = await db.xml_feeds.find_one({"_id": feed_id})
    if not feed:
        raise HTTPException(status_code=404, detail="Flux introuvable")
    from partner_feed import import_feed
    result = await import_feed(db, feed["partner_id"], None)  # fetch from configured URL
    await db.xml_feeds.update_one({"_id": feed_id}, {"$set": {"last_import_at": datetime.utcnow(), "last_result": result}})
    return result


@router.delete("/xml-feeds/{feed_id}")
async def delete_xml_feed(feed_id: str, admin: User = Depends(require_admin)):
    db = await get_database()
    res = await db.xml_feeds.delete_one({"_id": feed_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Flux introuvable")
    return {"message": "Flux supprimé"}


class XmlFeedUpdate(BaseModel):
    source_name: Optional[str] = None
    url: Optional[str] = None
    billing_mode: Optional[str] = None
    cpc: Optional[float] = None
    pack_price: Optional[float] = None


@router.put("/xml-feeds/{feed_id}")
async def update_xml_feed(feed_id: str, data: XmlFeedUpdate, admin: User = Depends(require_admin)):
    db = await get_database()
    feed = await db.xml_feeds.find_one({"_id": feed_id})
    if not feed:
        raise HTTPException(status_code=404, detail="Flux introuvable")
    payload = {k: v for k, v in data.dict(exclude_none=True).items()}
    if payload:
        await db.xml_feeds.update_one({"_id": feed_id}, {"$set": payload})
        # Also sync into the partner profile so the feed URL/config stays coherent
        sync = {}
        if "url" in payload:
            sync["xml_feed_url"] = payload["url"]
        if "billing_mode" in payload:
            sync["billing_mode"] = payload["billing_mode"]
        if "cpc" in payload:
            sync["default_cpc"] = payload["cpc"]
        if "pack_price" in payload:
            sync["posting_price"] = payload["pack_price"]
        if sync:
            sync["updated_at"] = datetime.utcnow()
            await db.partner_profiles.update_one({"user_id": feed["partner_id"]}, {"$set": sync})
    feed = await db.xml_feeds.find_one({"_id": feed_id})
    return await _feed_out(db, feed)


# ---------- Alerts management (admin) ----------
@router.get("/alerts")
async def list_alerts(search: Optional[str] = None, active: Optional[str] = None, admin: User = Depends(require_admin)):
    db = await get_database()
    query = {}
    if active == "true":
        query["is_active"] = True
    elif active == "false":
        query["is_active"] = False
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"search": {"$regex": search, "$options": "i"}},
            {"location": {"$regex": search, "$options": "i"}},
        ]
    docs = await db.alerts.find(query).sort([("created_at", -1)]).limit(500).to_list(length=500)
    # join user email
    user_ids = list({d.get("user_id") for d in docs if d.get("user_id")})
    users = {u["_id"]: u for u in await db.users.find({"_id": {"$in": user_ids}}).to_list(length=len(user_ids) or 1)}
    out = []
    for d in docs:
        u = users.get(d.get("user_id"), {})
        out.append({
            "id": d["_id"], "name": d.get("name"), "search": d.get("search"), "location": d.get("location"),
            "frequency": d.get("frequency"), "is_active": d.get("is_active", True),
            "user_email": u.get("email"), "search_mode": d.get("search_mode", "simple"),
            "result_count": d.get("result_count"), "origin": d.get("origin"),
            "last_sent_at": d.get("last_sent_at"), "last_viewed_at": d.get("last_viewed_at"),
            "created_at": d.get("created_at"),
        })
    return out


@router.put("/alerts/{alert_id}/toggle")
async def admin_toggle_alert(alert_id: str, admin: User = Depends(require_admin)):
    db = await get_database()
    doc = await db.alerts.find_one({"_id": alert_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    new_state = not doc.get("is_active", True)
    await db.alerts.update_one({"_id": alert_id}, {"$set": {"is_active": new_state}})
    return {"id": alert_id, "is_active": new_state}


@router.delete("/alerts/{alert_id}")
async def admin_delete_alert(alert_id: str, admin: User = Depends(require_admin)):
    db = await get_database()
    res = await db.alerts.delete_one({"_id": alert_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    return {"message": "Alerte supprimée"}


# ---------- Jobs ----------
def _job_out(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "title": doc.get("title"),
        "location": doc.get("location"),
        "job_type": doc.get("job_type"),
        "company_id": doc.get("company_id"),
        "employer_id": doc.get("employer_id"),
        "partner_id": doc.get("partner_id"),
        "is_active": doc.get("is_active", True),
        "views_count": doc.get("views_count", 0),
        "applications_count": doc.get("applications_count", 0),
        "created_at": doc.get("created_at"),
    }


@router.get("/jobs")
async def search_jobs(
    search: Optional[str] = None,
    location: Optional[str] = None,
    only_active: Optional[bool] = None,
    admin: User = Depends(require_admin),
):
    db = await get_database()
    query = {}
    if search:
        query["title"] = {"$regex": search, "$options": "i"}
    if location:
        query["location"] = {"$regex": location, "$options": "i"}
    if only_active is not None:
        query["is_active"] = only_active
    docs = await db.jobs.find(query).sort([("created_at", -1)]).limit(500).to_list(length=500)
    return [_job_out(d) for d in docs]


@router.post("/jobs/{job_id}/toggle")
async def toggle_job(job_id: str, admin: User = Depends(require_admin)):
    db = await get_database()
    doc = await db.jobs.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    new_state = not doc.get("is_active", True)
    await db.jobs.update_one({"_id": job_id}, {"$set": {"is_active": new_state}})
    return {"id": job_id, "is_active": new_state}


class JobAdminUpdate(BaseModel):
    title: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[str] = None
    description: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    is_active: Optional[bool] = None


@router.put("/jobs/{job_id}")
async def update_job(job_id: str, data: JobAdminUpdate, admin: User = Depends(require_admin)):
    db = await get_database()
    doc = await db.jobs.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    payload = {k: v for k, v in data.dict(exclude_none=True).items()}
    if payload:
        payload["updated_at"] = datetime.utcnow()
        await db.jobs.update_one({"_id": job_id}, {"$set": payload})
    doc = await db.jobs.find_one({"_id": job_id})
    return {"id": doc["_id"], **{k: doc.get(k) for k in ("title","location","job_type","description","salary_min","salary_max","is_active")}}


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, admin: User = Depends(require_admin)):
    db = await get_database()
    res = await db.jobs.delete_one({"_id": job_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    return {"message": "Offre supprimée"}


class XmlImportRequest(BaseModel):
    xml_content: Optional[str] = None


@router.post("/partners/{user_id}/import-xml")
async def import_partner_xml(user_id: str, body: XmlImportRequest, admin: User = Depends(require_admin)):
    db = await get_database()
    from partner_feed import import_feed
    return await import_feed(db, user_id, body.xml_content)


# ---------- Footer international country links ----------
def _country_out(d: dict) -> dict:
    return {
        "id": d["_id"],
        "code": d.get("code"),
        "label": d.get("label"),
        "url": d.get("url"),
        "order": d.get("order", 0),
        "is_active": d.get("is_active", True),
    }


class CountryCreate(BaseModel):
    code: str
    label: str
    url: str = "#"
    order: Optional[int] = None
    is_active: bool = True


class CountryUpdate(BaseModel):
    code: Optional[str] = None
    label: Optional[str] = None
    url: Optional[str] = None
    order: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("/footer-countries")
async def list_footer_countries(admin: User = Depends(require_admin)):
    db = await get_database()
    docs = await db.footer_countries.find({}).sort([("order", 1)]).to_list(length=500)
    return [_country_out(d) for d in docs]


@router.post("/footer-countries")
async def create_footer_country(data: CountryCreate, admin: User = Depends(require_admin)):
    db = await get_database()
    if data.order is None:
        last = await db.footer_countries.find({}).sort([("order", -1)]).limit(1).to_list(length=1)
        order = (last[0].get("order", 0) + 1) if last else 0
    else:
        order = data.order
    now = datetime.utcnow()
    code = data.code.strip().lower()
    url = (data.url or "").strip()
    if not url or url == "#":
        url = f"https://{code}.joboolo.com"
    doc = {
        "_id": str(uuid.uuid4()),
        "code": code,
        "label": data.label.strip(),
        "url": url,
        "order": order,
        "is_active": data.is_active,
        "created_at": now, "updated_at": now,
    }
    await db.footer_countries.insert_one(doc)
    return _country_out(doc)


@router.put("/footer-countries/{country_id}")
async def update_footer_country(country_id: str, data: CountryUpdate, admin: User = Depends(require_admin)):
    db = await get_database()
    patch = {k: v for k, v in data.dict(exclude_unset=True).items() if v is not None}
    if "code" in patch:
        patch["code"] = patch["code"].strip().lower()
    if not patch:
        raise HTTPException(status_code=400, detail="Aucune modification")
    patch["updated_at"] = datetime.utcnow()
    res = await db.footer_countries.update_one({"_id": country_id}, {"$set": patch})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Pays introuvable")
    doc = await db.footer_countries.find_one({"_id": country_id})
    return _country_out(doc)


@router.delete("/footer-countries/{country_id}")
async def delete_footer_country(country_id: str, admin: User = Depends(require_admin)):
    db = await get_database()
    res = await db.footer_countries.delete_one({"_id": country_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Pays introuvable")
    return {"message": "Pays supprimé"}

