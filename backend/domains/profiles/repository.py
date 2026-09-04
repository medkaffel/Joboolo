"""Mongo repository for authoritative Candidate Professional Profiles."""
from datetime import datetime
from typing import Optional

from pymongo import ReturnDocument

from domains.shared.versioning import EntityVersion
from .models import CandidateProfessionalProfile, CandidateProfilePatch, FactSource


def _enum_value(value):
    return value.value if hasattr(value, "value") else value


def profile_to_document(profile: CandidateProfessionalProfile) -> dict:
    def items(values):
        return [
            {k: (_enum_value(v) if k == "source" else v) for k, v in value.__dict__.items()}
            for value in values
        ]

    return {
        "_id": str(profile.profile_id),
        "candidate_id": str(profile.candidate_id),
        "version": int(profile.version),
        "headline": profile.headline,
        "summary": profile.summary,
        "current_location": profile.current_location,
        "experience_years": profile.experience_years,
        "seniority": profile.seniority,
        "occupations": items(profile.occupations),
        "experiences": items(profile.experiences),
        "skills": items(profile.skills),
        "certifications": items(profile.certifications),
        "languages": items(profile.languages),
        "industries": list(profile.industries),
        "management_experience": profile.management_experience,
        "education": items(profile.education),
        "portfolio": items(profile.portfolio),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def patch_to_mongo_set(patch: CandidateProfilePatch) -> dict:
    raw = patch.__dict__
    out = {}
    sequence_fields = {
        "occupations", "experiences", "skills", "certifications",
        "languages", "education", "portfolio",
    }
    for key, value in raw.items():
        if value is None:
            continue
        if key in sequence_fields:
            out[key] = [
                {k: (_enum_value(v) if k == "source" else v) for k, v in item.__dict__.items()}
                for item in value
            ]
        elif key == "industries":
            out[key] = list(value)
        else:
            out[key] = value
    return out


class CandidateProfileRepository:
    def __init__(self, db):
        self.collection = db.candidate_profiles

    async def get(self, candidate_id: str, session=None) -> Optional[dict]:
        return await self.collection.find_one({"candidate_id": candidate_id}, session=session)

    async def insert_initial(self, profile: CandidateProfessionalProfile, session=None) -> dict:
        doc = profile_to_document(profile)
        await self.collection.insert_one(doc, session=session)
        return doc

    async def update_with_version(
        self,
        candidate_id: str,
        expected_version: EntityVersion,
        patch: CandidateProfilePatch,
        now: datetime,
        session=None,
    ) -> Optional[dict]:
        changes = patch_to_mongo_set(patch)
        changes["updated_at"] = now
        return await self.collection.find_one_and_update(
            {"candidate_id": candidate_id, "version": int(expected_version)},
            {"$set": changes, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
