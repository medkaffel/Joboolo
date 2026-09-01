from fastapi import APIRouter, HTTPException, Depends
from typing import List
from models import SavedJob, JobResponse, User, UserType
from database import get_database
from auth import get_current_active_user
from routes.jobs import populate_job_response
from campaign_lifecycle import is_job_publicly_visible, get_job_campaign, fetch_public_job_filter
from datetime import datetime

router = APIRouter(prefix="/saved-jobs", tags=["saved-jobs"])

@router.post("/{job_id}")
async def save_job(
    job_id: str,
    current_user: User = Depends(get_current_active_user)
):
    """Save a job for later (candidates only)"""
    if current_user.user_type != UserType.CANDIDATE:
        raise HTTPException(
            status_code=403,
            detail="Only candidates can save jobs"
        )
    
    db = await get_database()
    
    # Check if job exists and is publicly visible (P0-006)
    job = await db.jobs.find_one({"_id": job_id})
    if not job or not is_job_publicly_visible(job, await get_job_campaign(db, job)):
        raise HTTPException(
            status_code=404,
            detail="Job not found or no longer active"
        )
    
    # Check if already saved
    existing_saved = await db.saved_jobs.find_one({
        "user_id": current_user.id,
        "job_id": job_id
    })
    if existing_saved:
        raise HTTPException(
            status_code=400,
            detail="Job already saved"
        )
    
    # Save job
    saved_job_doc = {
        "_id": f"saved_{datetime.utcnow().timestamp()}",
        "user_id": current_user.id,
        "job_id": job_id,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    await db.saved_jobs.insert_one(saved_job_doc)
    
    return {"message": "Job saved successfully"}

@router.delete("/{job_id}")
async def unsave_job(
    job_id: str,
    current_user: User = Depends(get_current_active_user)
):
    """Remove a job from saved jobs"""
    if current_user.user_type != UserType.CANDIDATE:
        raise HTTPException(
            status_code=403,
            detail="Only candidates can manage saved jobs"
        )
    
    db = await get_database()
    
    # Remove saved job
    result = await db.saved_jobs.delete_one({
        "user_id": current_user.id,
        "job_id": job_id
    })
    
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Saved job not found"
        )
    
    return {"message": "Job removed from saved jobs"}

@router.get("", response_model=List[JobResponse])
async def get_saved_jobs(current_user: User = Depends(get_current_active_user)):
    """Get user's saved jobs"""
    if current_user.user_type != UserType.CANDIDATE:
        raise HTTPException(
            status_code=403,
            detail="Only candidates can view saved jobs"
        )
    
    db = await get_database()
    
    # Get saved job IDs
    cursor = db.saved_jobs.find({
        "user_id": current_user.id
    }).sort([("created_at", -1)])
    
    saved_jobs_docs = await cursor.to_list(length=100)
    job_ids = [saved_job["job_id"] for saved_job in saved_jobs_docs]
    
    if not job_ids:
        return []
    
    # Get actual jobs (publicly visible only — P0-006)
    query = await fetch_public_job_filter(db)
    query["_id"] = {"$in": job_ids}
    jobs_cursor = db.jobs.find(query)
    jobs_docs = await jobs_cursor.to_list(length=100)
    
    # Populate responses
    jobs = []
    for job_doc in jobs_docs:
        job_response = await populate_job_response(job_doc, db)
        jobs.append(job_response)
    
    return jobs

@router.get("/{job_id}/check")
async def check_job_saved(
    job_id: str,
    current_user: User = Depends(get_current_active_user)
):
    """Check if a job is saved by the current user"""
    if current_user.user_type != UserType.CANDIDATE:
        return {"is_saved": False}
    
    db = await get_database()
    
    saved_job = await db.saved_jobs.find_one({
        "user_id": current_user.id,
        "job_id": job_id
    })
    
    return {"is_saved": saved_job is not None}