"""Tableau de bord analytique recruteur : vues, candidatures, statuts, timeline."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from database import get_database
from auth import require_employer
from models import User

router = APIRouter(prefix="/analytics", tags=["analytics"])

STATUS_ORDER = ["pending", "reviewed", "accepted", "rejected"]


def _to_date(v):
    if hasattr(v, "date"):
        return v.date()
    try:
        return datetime.fromisoformat(str(v)).date()
    except Exception:
        return None


@router.get("/recruiter")
async def recruiter_analytics(current_user: User = Depends(require_employer)):
    db = await get_database()
    jobs = await db.jobs.find({"employer_id": current_user.id}).sort([("created_at", -1)]).to_list(length=1000)
    job_ids = [j["_id"] for j in jobs]
    apps = await db.applications.find({"job_id": {"$in": job_ids}}).to_list(length=5000) if job_ids else []

    apps_by_job = {}
    for a in apps:
        apps_by_job.setdefault(a["job_id"], []).append(a)

    status_totals = {s: 0 for s in STATUS_ORDER}
    total_views = 0
    total_apps = 0
    per_job = []
    for j in jobs:
        ja = apps_by_job.get(j["_id"], [])
        sc = {s: 0 for s in STATUS_ORDER}
        for a in ja:
            st = a.get("status", "pending")
            if st in sc:
                sc[st] += 1
            status_totals[st] = status_totals.get(st, 0) + 1
        v = j.get("views_count", 0) or 0
        total_views += v
        total_apps += len(ja)
        per_job.append({
            "id": j["_id"],
            "title": j.get("title"),
            "is_active": j.get("is_active", True),
            "views": v,
            "applications": len(ja),
            "status_counts": sc,
            "conversion": round(len(ja) / v * 100, 1) if v else 0.0,
            "created_at": j["created_at"].isoformat() if hasattr(j["created_at"], "isoformat") else j["created_at"],
        })

    per_job.sort(key=lambda x: x["applications"], reverse=True)

    days = 14
    today = datetime.now(timezone.utc).date()
    counts = {}
    for a in apps:
        d = _to_date(a.get("created_at"))
        if d:
            counts[d] = counts.get(d, 0) + 1
    timeline = [{
        "date": (today - timedelta(days=i)).isoformat(),
        "count": counts.get(today - timedelta(days=i), 0),
    } for i in range(days - 1, -1, -1)]

    return {
        "totals": {
            "jobs": len(jobs),
            "active_jobs": sum(1 for j in jobs if j.get("is_active", True)),
            "views": total_views,
            "applications": total_apps,
        },
        "status_totals": status_totals,
        "per_job": per_job,
        "timeline": timeline,
    }
