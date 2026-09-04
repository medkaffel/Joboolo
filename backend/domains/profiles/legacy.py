"""Explicit, conservative mapping from legacy `users` fields into A1 facts."""
from datetime import datetime, timezone

from domains.shared.ids import CandidateId, CandidateProfileId
from domains.shared.versioning import EntityVersion
from .models import CandidateProfessionalProfile, FactSource, SkillFact


def deterministic_profile_id(candidate_id: str) -> CandidateProfileId:
    return CandidateProfileId(f"candidate_profile:{candidate_id}")


def profile_from_legacy_user(user_doc: dict, now: datetime | None = None) -> CandidateProfessionalProfile:
    """Map only facts actually present in `users`; never infer missing facts."""
    now = now or datetime.now(timezone.utc)
    candidate_id = str(user_doc["_id"])
    skills = tuple(
        SkillFact(name=str(skill).strip(), source=FactSource.LEGACY_USER)
        for skill in (user_doc.get("skills") or [])
        if str(skill).strip()
    )
    years = user_doc.get("experience_years")
    if years is not None:
        years = int(years)
    return CandidateProfessionalProfile(
        profile_id=deterministic_profile_id(candidate_id),
        candidate_id=CandidateId(candidate_id),
        version=EntityVersion(1),
        created_at=now,
        updated_at=now,
        summary=user_doc.get("bio") or None,
        current_location=user_doc.get("location") or None,
        experience_years=years,
        skills=skills,
    )
