import logging
from fastapi import APIRouter, HTTPException, Depends

from database import get_database
from auth import get_current_active_user
from models import User, UserType
from routes.jobs import populate_job_response
import ai_service

router = APIRouter(prefix="/ai", tags=["ai"])
logger = logging.getLogger(__name__)


def _local_relevance(job: dict, skills: list, terms: list) -> int:
    text = " ".join([
        job.get("title", ""), job.get("description", ""),
        " ".join(job.get("requirements", []) or []),
        " ".join(job.get("tags", []) or []),
    ]).lower()
    score = 0
    for s in skills:
        if s and s.lower() in text:
            score += 3
    for t in terms:
        if t and len(t) > 3 and t.lower() in text:
            score += 1
    return score


def _job_slim(job: dict) -> dict:
    return {
        "title": job.get("title", ""),
        "description": job.get("description", ""),
        "requirements": job.get("requirements", []) or [],
        "location": job.get("location", ""),
        "job_type": job.get("job_type", ""),
        "tags": job.get("tags", []) or [],
    }


@router.get("/recommendations")
async def recommendations(current_user: User = Depends(get_current_active_user)):
    """Recommandations d'offres personnalisées selon le profil/CV du candidat."""
    if current_user.user_type != UserType.CANDIDATE:
        raise HTTPException(status_code=403, detail="Réservé aux candidats")
    db = await get_database()
    user_doc = await db.users.find_one({"_id": current_user.id}) or {}
    skills = user_doc.get("skills", []) or []
    bio = user_doc.get("bio", "") or ""
    profile_complete = bool(skills or bio or user_doc.get("experience_years"))

    applied = await db.applications.distinct("job_id", {"candidate_id": current_user.id})
    query = {"is_active": True}
    if applied:
        query["_id"] = {"$nin": applied}
    jobs = await db.jobs.find(query).sort([("created_at", -1)]).limit(60).to_list(length=60)
    if not jobs:
        return {"profile_complete": profile_complete, "recommendations": [], "ai": False}

    terms = (bio + " " + " ".join(skills)).split()
    ranked_local = sorted(jobs, key=lambda j: _local_relevance(j, skills, terms), reverse=True)
    shortlist = ranked_local[:12]

    profile = ai_service.build_profile(user_doc)
    slim_jobs = [{
        "id": j["_id"], "title": j.get("title", ""), "location": j.get("location", ""),
        "job_type": j.get("job_type", ""), "requirements": j.get("requirements", []) or [],
        "description": j.get("description", ""),
    } for j in shortlist]

    ai_recs = []
    try:
        ai_recs = await ai_service.rank_jobs(profile, slim_jobs)
    except Exception as e:
        logger.warning(f"AI rank failed: {e}")

    job_by_id = {j["_id"]: j for j in shortlist}
    results = []
    if ai_recs:
        for r in ai_recs:
            jd = job_by_id.get(r["id"])
            if not jd:
                continue
            jr = await populate_job_response(jd, db)
            results.append({"job": jr.dict(), "score": r["score"], "reason": r["reason"]})
    else:
        for jd in shortlist[:8]:
            jr = await populate_job_response(jd, db)
            results.append({"job": jr.dict(), "score": None, "reason": None})

    return {"profile_complete": profile_complete, "recommendations": results, "ai": bool(ai_recs)}


@router.post("/match/{job_id}")
async def match_job(job_id: str, current_user: User = Depends(get_current_active_user)):
    """Analyse IA de compatibilité entre le profil du candidat et une offre."""
    if current_user.user_type != UserType.CANDIDATE:
        raise HTTPException(status_code=403, detail="Réservé aux candidats")
    db = await get_database()
    job = await db.jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    user_doc = await db.users.find_one({"_id": current_user.id}) or {}
    profile = ai_service.build_profile(user_doc)
    try:
        return await ai_service.analyze_match(profile, _job_slim(job))
    except Exception as e:
        logger.warning(f"AI match failed: {e}")
        raise HTTPException(status_code=502, detail=f"Analyse IA indisponible: {e}")


@router.get("/match/application/{application_id}")
async def match_application(application_id: str, current_user: User = Depends(get_current_active_user)):
    """Analyse IA d'un candidat par rapport à l'offre (côté recruteur)."""
    if current_user.user_type not in (UserType.EMPLOYER, UserType.ADMIN):
        raise HTTPException(status_code=403, detail="Réservé aux recruteurs")
    db = await get_database()
    app_doc = await db.applications.find_one({"_id": application_id})
    if not app_doc:
        raise HTTPException(status_code=404, detail="Candidature introuvable")
    job = await db.jobs.find_one({"_id": app_doc["job_id"]})
    if not job or (job.get("employer_id") != current_user.id and current_user.user_type != UserType.ADMIN):
        raise HTTPException(status_code=403, detail="Non autorisé")
    cand = await db.users.find_one({"_id": app_doc["candidate_id"]})
    if not cand:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    profile = ai_service.build_profile(cand)
    if app_doc.get("cover_letter"):
        profile["lettre_motivation"] = app_doc["cover_letter"][:1500]
    try:
        return await ai_service.analyze_match(profile, _job_slim(job))
    except Exception as e:
        logger.warning(f"AI match (application) failed: {e}")
        raise HTTPException(status_code=502, detail=f"Analyse IA indisponible: {e}")
