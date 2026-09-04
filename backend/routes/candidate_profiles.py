"""Thin HTTP adapters for TS-A1 Candidate Professional Profile."""
from datetime import datetime
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from auth import get_current_active_user
from database import get_database
from domains.profiles.models import CandidateProfilePatch, FactSource, OccupationFact, SkillFact
from domains.profiles.service import ProfileConflictError, ProfileNotFoundError, ProfileService
from domains.shared.versioning import EntityVersion
from models import User, UserResponse, UserType, UserUpdate


router = APIRouter(prefix="/candidate-profile", tags=["candidate-profile"])
compat_router = APIRouter(tags=["candidate-profile-compat"])


class SkillInput(BaseModel):
    name: str


class OccupationInput(BaseModel):
    title: str


class CandidateProfileUpdate(BaseModel):
    headline: Optional[str] = None
    summary: Optional[str] = None
    current_location: Optional[str] = None
    experience_years: Optional[int] = None
    seniority: Optional[str] = None
    skills: Optional[List[SkillInput]] = None
    occupations: Optional[List[OccupationInput]] = None
    industries: Optional[List[str]] = None
    management_experience: Optional[bool] = None


def _public_profile(doc: dict) -> dict:
    return {
        "profile_id": doc["_id"], "candidate_id": doc["candidate_id"], "version": doc["version"],
        "headline": doc.get("headline"), "summary": doc.get("summary"),
        "current_location": doc.get("current_location"), "experience_years": doc.get("experience_years"),
        "seniority": doc.get("seniority"), "skills": doc.get("skills", []),
        "occupations": doc.get("occupations", []), "experiences": doc.get("experiences", []),
        "certifications": doc.get("certifications", []), "languages": doc.get("languages", []),
        "industries": doc.get("industries", []), "management_experience": doc.get("management_experience"),
        "education": doc.get("education", []), "portfolio": doc.get("portfolio", []),
        "created_at": doc["created_at"], "updated_at": doc["updated_at"],
    }


def _candidate_only(current_user: User) -> None:
    if current_user.user_type != UserType.CANDIDATE:
        raise HTTPException(status_code=403, detail="Réservé aux candidats")


def _user_response(doc: dict) -> UserResponse:
    return UserResponse(
        id=doc["_id"], email=doc["email"], first_name=doc["first_name"], last_name=doc["last_name"],
        user_type=doc["user_type"], phone=doc.get("phone"), location=doc.get("location"),
        bio=doc.get("bio"), skills=doc.get("skills", []), experience_years=doc.get("experience_years"),
        is_active=doc.get("is_active", True), is_verified=doc.get("is_verified", False),
        created_at=doc["created_at"], profile_photo_url=doc.get("profile_photo_url"),
        social_link_1=doc.get("social_link_1"), social_link_2=doc.get("social_link_2"),
        social_link_3=doc.get("social_link_3"),
    )


def _provided_payload(payload: BaseModel) -> dict:
    if hasattr(payload, "model_dump"):
        return payload.model_dump(exclude_unset=True)
    return payload.dict(exclude_unset=True)


@router.get("/me")
async def get_candidate_profile(current_user: User = Depends(get_current_active_user)):
    _candidate_only(current_user)
    db = await get_database()
    try:
        doc = await ProfileService(db).get_current(current_user.id)
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="Profil professionnel non matérialisé")
    return _public_profile(doc)


@router.put("/me")
async def update_candidate_profile(
    payload: CandidateProfileUpdate,
    current_user: User = Depends(get_current_active_user),
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
):
    _candidate_only(current_user)
    provided = _provided_payload(payload)
    if not provided or not any(value is not None for value in provided.values()):
        raise HTTPException(status_code=400, detail="At least one professional profile field is required")
    if if_match is None:
        raise HTTPException(status_code=428, detail="If-Match profile version required")
    try:
        expected_version = EntityVersion(int(if_match.strip('"')))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid If-Match profile version")

    skills = None if payload.skills is None else tuple(
        SkillFact(name=item.name, source=FactSource.CANDIDATE_DECLARED)
        for item in payload.skills
    )
    occupations = None if payload.occupations is None else tuple(
        OccupationFact(title=item.title, source=FactSource.CANDIDATE_DECLARED)
        for item in payload.occupations
    )
    patch = CandidateProfilePatch(
        headline=payload.headline, summary=payload.summary, current_location=payload.current_location,
        experience_years=payload.experience_years, seniority=payload.seniority, skills=skills,
        occupations=occupations, industries=None if payload.industries is None else tuple(payload.industries),
        management_experience=payload.management_experience,
    )
    db = await get_database()
    try:
        doc = await ProfileService(db).update(current_user.id, patch, expected_version)
    except ProfileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    return _public_profile(doc)


@compat_router.put("/auth/me", response_model=UserResponse)
async def update_current_user_compat(
    update_data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
):
    """A1 compatibility façade preserving the legacy endpoint contract.

    Candidate professional fields have one logical writer (`ProfileService`).
    Identity/photo/social-only edits do not create or version a professional
    profile. Non-candidate users retain the previous users-only behavior.
    """
    db = await get_database()
    raw = {k: v for k, v in update_data.dict().items() if v is not None}

    if current_user.user_type != UserType.CANDIDATE:
        if raw:
            raw["updated_at"] = datetime.utcnow()
            await db.users.update_one({"_id": current_user.id}, {"$set": raw})
        updated_user = await db.users.find_one({"_id": current_user.id})
        return _user_response(updated_user)

    professional_keys = {"bio", "location", "skills", "experience_years"}
    professional = {k: raw.pop(k) for k in list(raw) if k in professional_keys}
    if not professional:
        if raw:
            raw["updated_at"] = datetime.utcnow()
            await db.users.update_one({"_id": current_user.id}, {"$set": raw})
        updated_user = await db.users.find_one({"_id": current_user.id})
        return _user_response(updated_user)

    patch = ProfileService.legacy_patch(
        bio=professional.get("bio"), location=professional.get("location"),
        experience_years=professional.get("experience_years"), skills=professional.get("skills"),
    )
    try:
        await ProfileService(db).update(current_user.id, patch, expected_version=None, legacy_user_fields=raw)
    except ProfileConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
    updated_user = await db.users.find_one({"_id": current_user.id})
    return _user_response(updated_user)
