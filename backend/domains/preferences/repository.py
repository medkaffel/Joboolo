"""Mongo repository for authoritative Candidate Preferences."""
from datetime import datetime
from typing import Optional

from pymongo import ReturnDocument

from domains.shared.versioning import EntityVersion
from .models import CandidatePreferencesPatch


def _serialize(value):
    if hasattr(value, "value"):
        return value.value
    if hasattr(value, "__dict__"):
        return {k: _serialize(v) for k, v in value.__dict__.items()}
    if isinstance(value, (tuple, frozenset)):
        return [_serialize(v) for v in value]
    return value


def patch_to_set(patch: CandidatePreferencesPatch) -> dict:
    out = {}
    for key, value in patch.__dict__.items():
        if key == "clear_fields":
            continue
        if value is not None:
            out[key] = _serialize(value)
    for key in patch.clear_fields:
        out[key] = None
    return out


class CandidatePreferencesRepository:
    def __init__(self, db):
        self.collection = db.candidate_preferences

    async def get(self, candidate_id: str, session=None) -> Optional[dict]:
        return await self.collection.find_one({"candidate_id": candidate_id}, session=session)

    async def insert_initial(self, doc: dict, session=None) -> dict:
        await self.collection.insert_one(doc, session=session)
        return doc

    async def update_with_version(
        self,
        candidate_id: str,
        expected_version: EntityVersion,
        patch: CandidatePreferencesPatch,
        now: datetime,
        session=None,
    ) -> Optional[dict]:
        changes = patch_to_set(patch)
        changes["updated_at"] = now
        return await self.collection.find_one_and_update(
            {"candidate_id": candidate_id, "version": int(expected_version)},
            {"$set": changes, "$inc": {"version": 1}},
            return_document=ReturnDocument.AFTER,
            session=session,
        )
