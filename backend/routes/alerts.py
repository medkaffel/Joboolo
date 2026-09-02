from fastapi import APIRouter, HTTPException, Depends
from typing import List
from models import (
    JobAlert, JobAlertCreate, JobAlertUpdate, JobAlertResponse, User
)
from database import get_database
from auth import get_current_active_user
from email_utils import canonical_email
from datetime import datetime

router = APIRouter(prefix="/alerts", tags=["alerts"])


from pydantic import BaseModel
from typing import Optional as _Optional


class AlertSubscribe(BaseModel):
    email: str
    search: _Optional[str] = None
    location: _Optional[str] = None
    job_type: _Optional[str] = None
    search_mode: _Optional[str] = "simple"  # simple | advanced
    result_count: _Optional[int] = None
    origin: _Optional[str] = None  # referer / last page


@router.post("/subscribe")
async def subscribe_alert(data: AlertSubscribe):
    """Public: save a search as an alert by email. Creates a lightweight candidate
    account if the email is unknown (same process as an authenticated alert)."""
    db = await get_database()
    # P0-009: canonicalize email
    email = canonical_email(data.email)

    user = await db.users.find_one({"email": email})
    if not user:
        user_id = f"user_{datetime.utcnow().timestamp()}"
        await db.users.insert_one({
            "_id": user_id,
            "email": email,
            "hashed_password": None,
            "first_name": None,
            "last_name": None,
            "user_type": "candidate",
            "is_active": True,
            "profile_complete": False,
            "location": data.location,
            "signup_origin": data.origin or "alert_subscribe",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        })
    else:
        user_id = user["_id"]

    name_parts = [p for p in [data.search, data.location] if p]
    alert_doc = {
        "_id": f"alert_{datetime.utcnow().timestamp()}",
        "user_id": user_id,
        "name": " · ".join(name_parts) if name_parts else "Toutes les offres",
        "search": data.search,
        "location": data.location,
        "job_type": data.job_type,
        "is_remote": None,
        "salary_min": None,
        "frequency": "daily",
        "search_mode": data.search_mode or "simple",
        "result_count": data.result_count,
        "origin": data.origin,
        "is_active": True,
        "last_sent_at": None,
        "last_viewed_at": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }
    await db.alerts.insert_one(alert_doc)
    return {"success": True, "alert_id": alert_doc["_id"], "created_account": not bool(user)}


@router.get("/track/{alert_id}")
async def track_alert_click(alert_id: str, redirect: str = ""):
    """Record an alert open/click (for billing & open-tracking) then redirect.

    P0-008 : la destination n'est jamais utilisée telle quelle. `safe_redirect`
    n'autorise que les destinations internes sûres (relatives commençant par un
    seul '/') ou les absolues dont l'origine est EXACTEMENT celle de l'APP_URL
    canonique ; toute autre destination tombe sur '/'. L'origine autorisée vient
    de la config (FRONTEND_URL / APP_URL), jamais du Host de la requête.
    """
    from fastapi.responses import RedirectResponse
    from scheduler import APP_URL
    from safe_urls import safe_redirect
    db = await get_database()
    now = datetime.utcnow()
    alert = await db.alerts.find_one({"_id": alert_id})
    if alert:
        await db.alerts.update_one({"_id": alert_id}, {"$set": {"last_viewed_at": now}, "$inc": {"click_count": 1}})
        if alert.get("user_id"):
            await db.users.update_one({"_id": alert["user_id"]}, {"$set": {"last_alert_viewed_at": now}})
    target = safe_redirect(redirect, APP_URL)
    return RedirectResponse(url=target, status_code=302)


def _to_response(doc: dict) -> JobAlertResponse:
    return JobAlertResponse(
        id=doc["_id"],
        name=doc.get("name", "Alerte"),
        search=doc.get("search"),
        location=doc.get("location"),
        job_type=doc.get("job_type"),
        is_remote=doc.get("is_remote"),
        salary_min=doc.get("salary_min"),
        frequency=doc.get("frequency", "daily"),
        is_active=doc.get("is_active", True),
        last_sent_at=doc.get("last_sent_at"),
        created_at=doc["created_at"],
    )


def _default_name(data: JobAlertCreate) -> str:
    parts = []
    if data.search:
        parts.append(data.search)
    if data.location:
        parts.append(data.location)
    return " · ".join(parts) if parts else "Toutes les offres"


@router.post("", response_model=JobAlertResponse)
async def create_alert(
    data: JobAlertCreate,
    current_user: User = Depends(get_current_active_user),
):
    """Save the current search as an email alert."""
    db = await get_database()

    alert_doc = {
        "_id": f"alert_{datetime.utcnow().timestamp()}",
        "user_id": current_user.id,
        "name": data.name or _default_name(data),
        "search": data.search,
        "location": data.location,
        "job_type": data.job_type,
        "is_remote": data.is_remote,
        "salary_min": data.salary_min,
        "frequency": data.frequency,
        "is_active": True,
        "last_sent_at": None,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
    }

    await db.alerts.insert_one(alert_doc)
    return _to_response(alert_doc)


@router.get("", response_model=List[JobAlertResponse])
async def get_my_alerts(current_user: User = Depends(get_current_active_user)):
    """List the current user's saved searches / alerts."""
    db = await get_database()
    cursor = db.alerts.find({"user_id": current_user.id}).sort([("created_at", -1)])
    docs = await cursor.to_list(length=100)
    return [_to_response(d) for d in docs]


@router.put("/{alert_id}", response_model=JobAlertResponse)
async def update_alert(
    alert_id: str,
    data: JobAlertUpdate,
    current_user: User = Depends(get_current_active_user),
):
    """Update an alert's name, frequency or active state."""
    db = await get_database()

    alert = await db.alerts.find_one({"_id": alert_id, "user_id": current_user.id})
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable")

    fields = {k: v for k, v in data.dict().items() if v is not None}
    fields["updated_at"] = datetime.utcnow()
    await db.alerts.update_one({"_id": alert_id}, {"$set": fields})

    updated = await db.alerts.find_one({"_id": alert_id})
    return _to_response(updated)


@router.delete("/{alert_id}")
async def delete_alert(
    alert_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Delete an alert."""
    db = await get_database()
    result = await db.alerts.delete_one({"_id": alert_id, "user_id": current_user.id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alerte introuvable")
    return {"message": "Alerte supprimée"}


@router.post("/{alert_id}/send-now")
async def send_alert_now(
    alert_id: str,
    current_user: User = Depends(get_current_active_user),
):
    """Immediately email the latest matching jobs for this alert (test / on-demand)."""
    from datetime import timedelta
    from scheduler import _build_job_query, APP_URL
    from email_service import build_alert_html, send_alert_email
    import email_service

    db = await get_database()
    alert = await db.alerts.find_one({"_id": alert_id, "user_id": current_user.id})
    if not alert:
        raise HTTPException(status_code=404, detail="Alerte introuvable")

    since = datetime.utcnow() - timedelta(days=30)
    from campaign_lifecycle import fetch_public_job_filter
    public_filter = await fetch_public_job_filter(db, datetime.utcnow())
    query = _build_job_query(alert, since, public_filter)
    jobs = await db.jobs.find(query).sort([("created_at", -1)]).limit(10).to_list(length=10)

    if not jobs:
        return {"sent": False, "count": 0, "message": "Aucune offre correspondante pour le moment."}

    if not email_service._resend_ready:
        return {"sent": False, "count": len(jobs), "message": "Email non configuré (clé Resend manquante)."}

    html = build_alert_html(alert.get("name", "Alerte"), jobs, APP_URL, alert.get("_id"))
    subject = f"{len(jobs)} offre(s) — {alert.get('name', 'Joboolo')}"
    sent = await send_alert_email(current_user.email, subject, html)
    await db.alerts.update_one({"_id": alert_id}, {"$set": {"last_sent_at": datetime.utcnow()}})

    if not sent:
        return {"sent": False, "count": len(jobs),
                "message": "Échec de l'envoi. En mode test Resend, seul l'email vérifié du compte reçoit les messages. Vérifiez un domaine sur resend.com/domains pour envoyer à tous."}
    return {"sent": True, "count": len(jobs), "message": f"Email envoyé à {current_user.email}."}
