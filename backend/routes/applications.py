from fastapi import APIRouter, HTTPException, Depends
from typing import List, Optional
from pydantic import BaseModel
from models import (
    Application, ApplicationCreate, ApplicationResponse, User, UserType
)
from database import get_database, get_client
from auth import get_current_active_user, require_employer
from datetime import datetime
from campaign_lifecycle import is_job_publicly_visible, get_job_campaign
from pymongo.errors import DuplicateKeyError

router = APIRouter(prefix="/applications", tags=["applications"])


def _is_unsupported_transaction(exc: Exception) -> bool:
    lowered = str(exc).lower()
    markers = (
        "transaction numbers are only allowed on a replica set",
        "transactions are not supported",
        "do not support transactions",
        "not supported on standalone",
        "not a replica set",
        "standalone",
        "replica set",
        "replicaset",
        "session support",
        "no such command: 'committransaction'",
    )
    return any(marker in lowered for marker in markers)


async def populate_application_response(app_doc: dict, db, include_candidate: bool = False) -> ApplicationResponse:
    """Populate application response with job and candidate info"""
    job = await db.jobs.find_one({"_id": app_doc["job_id"]})
    if not job:
        job = {"title": "Job not found", "company_id": ""}

    company = await db.companies.find_one({"_id": job.get("company_id", "")})
    if not company:
        company = {"name": "Company not found"}

    job_info = {
        "id": job.get("_id", ""),
        "title": job.get("title", "Job not found"),
        "employer_id": job.get("employer_id", ""),
        "company": {
            "name": company.get("name", "Company"),
            "location": company.get("location", "")
        },
        "location": job.get("location", ""),
        "job_type": job.get("job_type", "CDI")
    }

    candidate_info = {}
    if include_candidate:
        candidate = await db.users.find_one({"_id": app_doc["candidate_id"]})
        if candidate:
            candidate_info = {
                "id": candidate["_id"],
                "first_name": candidate.get("first_name", ""),
                "last_name": candidate.get("last_name", ""),
                "email": candidate.get("email", ""),
                "location": candidate.get("location", ""),
                "bio": candidate.get("bio", ""),
                "skills": candidate.get("skills", []),
                "experience_years": candidate.get("experience_years", 0)
            }

    return ApplicationResponse(
        id=app_doc["_id"],
        job=job_info,
        candidate=candidate_info,
        cover_letter=app_doc.get("cover_letter"),
        cv_url=app_doc.get("cv_url"),
        status=app_doc["status"],
        employer_notes=app_doc.get("employer_notes"),
        created_at=app_doc["created_at"],
        reviewed_at=app_doc.get("reviewed_at")
    )


@router.post("", response_model=ApplicationResponse)
async def apply_to_job(
    application_data: ApplicationCreate,
    current_user: User = Depends(get_current_active_user)
):
    """Apply to a job (candidates only) — atomic and idempotent (P0-014)."""
    if current_user.user_type != UserType.CANDIDATE:
        raise HTTPException(
            status_code=403,
            detail="Only candidates can apply to jobs"
        )

    db = await get_database()
    job_id = application_data.job_id
    candidate_id = current_user.id

    # Retry / uncertain-commit fast path: an already committed application is
    # returned without executing another transaction or incrementing the counter.
    existing_application = await db.applications.find_one({
        "job_id": job_id,
        "candidate_id": candidate_id,
    })
    if existing_application:
        return await populate_application_response(existing_application, db)

    # Best-effort pre-check. The authoritative visibility check is repeated in
    # the transaction using the same Mongo session for both job and campaign.
    job = await db.jobs.find_one({"_id": job_id})
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found or no longer active"
        )
    campaign = await get_job_campaign(db, job)
    if not is_job_publicly_visible(job, campaign):
        raise HTTPException(
            status_code=404,
            detail="Job not found or no longer active"
        )

    now = datetime.utcnow()
    app_doc = {
        "_id": f"app_{now.timestamp()}",
        **application_data.dict(),
        "candidate_id": candidate_id,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }

    client = get_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="Les transactions MongoDB ne sont pas disponibles. Candidature momentanément indisponible.",
        )

    async def _apply_transaction(session):
        job_tx = await db.jobs.find_one(
            {"_id": job_id, "is_active": True},
            session=session,
        )
        if not job_tx:
            raise HTTPException(
                status_code=404,
                detail="Job not found or no longer active"
            )

        campaign_tx = None
        campaign_id = job_tx.get("campaign_id")
        if campaign_id:
            campaign_tx = await db.campaigns.find_one(
                {"_id": campaign_id},
                session=session,
            )

        # Preserve P0-006 exactly, including fail-closed empty/invalid expires_at.
        if not is_job_publicly_visible(job_tx, campaign_tx):
            raise HTTPException(
                status_code=404,
                detail="Job not found or no longer active"
            )

        # The unique (job_id, candidate_id) index is the at-most-once guard.
        await db.applications.insert_one(app_doc, session=session)

        result = await db.jobs.update_one(
            {"_id": job_id, "is_active": True},
            {"$inc": {"applications_count": 1}},
            session=session,
        )
        if result.matched_count != 1:
            # Raising aborts the transaction: no application and no increment.
            raise HTTPException(
                status_code=404,
                detail="Job not found or no longer active"
            )

        return app_doc

    try:
        async with await client.start_session() as session:
            committed_app = await session.with_transaction(_apply_transaction)
    except DuplicateKeyError:
        # Concurrent loser: its transaction is aborted. Re-read outside the
        # failed transaction and return the winner idempotently.
        existing = await db.applications.find_one({
            "job_id": job_id,
            "candidate_id": candidate_id,
        })
        if existing:
            return await populate_application_response(existing, db)
        raise HTTPException(
            status_code=409,
            detail="Concurrent application conflict"
        )
    except HTTPException:
        raise
    except Exception as exc:
        if _is_unsupported_transaction(exc):
            raise HTTPException(
                status_code=503,
                detail="Les transactions MongoDB ne sont pas disponibles. Candidature momentanément indisponible.",
            )
        raise

    # Best-effort notification emails only after a successful commit.
    try:
        from email_service import (
            build_application_confirmation_email, build_new_application_email, send_alert_email
        )
        from scheduler import APP_URL
        company = await db.companies.find_one({"_id": job.get("company_id")})
        company_name = (company or {}).get("name", "l'entreprise")
        cand_name = current_user.first_name or "candidat(e)"

        if current_user.email:
            subj, html = build_application_confirmation_email(
                cand_name, job.get("title", "l'offre"), company_name, APP_URL
            )
            await send_alert_email(current_user.email, subj, html)

        employer = await db.users.find_one({"_id": job.get("employer_id")})
        if employer and employer.get("email"):
            emp_name = employer.get("first_name") or "recruteur"
            full_cand = f"{current_user.first_name or ''} {current_user.last_name or ''}".strip() or "Un candidat"
            subj2, html2 = build_new_application_email(
                emp_name, full_cand, job.get("title", "l'offre"), job_id, APP_URL
            )
            await send_alert_email(employer["email"], subj2, html2)
    except Exception:
        pass

    return await populate_application_response(committed_app, db)


@router.get("", response_model=List[ApplicationResponse])
async def get_my_applications(current_user: User = Depends(get_current_active_user)):
    """Get user's applications (candidates)"""
    if current_user.user_type != UserType.CANDIDATE:
        raise HTTPException(
            status_code=403,
            detail="Only candidates can view their applications"
        )

    db = await get_database()

    cursor = db.applications.find({
        "candidate_id": current_user.id
    }).sort([("created_at", -1)])

    apps_docs = await cursor.to_list(length=100)

    applications = []
    for app_doc in apps_docs:
        app_response = await populate_application_response(app_doc, db)
        applications.append(app_response)
    return applications


@router.get("/job/{job_id}", response_model=List[ApplicationResponse])
async def get_job_applications(
    job_id: str,
    current_user: User = Depends(require_employer)
):
    """Get applications for a job (employers only)"""
    db = await get_database()

    job = await db.jobs.find_one({
        "_id": job_id,
        "employer_id": current_user.id
    })
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found or you don't have permission to view its applications"
        )

    cursor = db.applications.find({
        "job_id": job_id
    }).sort([("created_at", -1)])

    apps_docs = await cursor.to_list(length=100)

    applications = []
    for app_doc in apps_docs:
        app_response = await populate_application_response(app_doc, db, include_candidate=True)
        applications.append(app_response)
    return applications


class StatusUpdate(BaseModel):
    status: str
    employer_notes: Optional[str] = None


@router.put("/{application_id}/status")
async def update_application_status(
    application_id: str,
    payload: StatusUpdate,
    current_user: User = Depends(require_employer)
):
    """Update application status (employers only)"""
    status = payload.status
    employer_notes = payload.employer_notes
    if status not in ["pending", "reviewed", "accepted", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid status"
        )

    db = await get_database()

    application = await db.applications.find_one({"_id": application_id})
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    job = await db.jobs.find_one({
        "_id": application["job_id"],
        "employer_id": current_user.id
    })
    if not job:
        raise HTTPException(
            status_code=403,
            detail="You don't have permission to update this application"
        )

    update_data = {
        "status": status,
        "reviewed_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    if employer_notes:
        update_data["employer_notes"] = employer_notes

    await db.applications.update_one(
        {"_id": application_id},
        {"$set": update_data}
    )

    if status in ("reviewed", "accepted", "rejected"):
        try:
            candidate = await db.users.find_one({"_id": application["candidate_id"]})
            company = await db.companies.find_one({"_id": job.get("company_id")})
            if candidate and candidate.get("email"):
                from email_service import build_status_email, send_alert_email
                from scheduler import APP_URL
                cname = f"{candidate.get('first_name','')}".strip() or "candidat(e)"
                subject, html = build_status_email(
                    cname, job.get("title", "l'offre"),
                    (company or {}).get("name", "l'entreprise"), status, APP_URL,
                )
                await send_alert_email(candidate["email"], subject, html)
        except Exception:
            pass

    return {"message": "Application status updated successfully"}
