"""Application service for Candidate Preferences + Discovery State."""
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from database import get_client
from domains.shared.ids import CandidatePreferencesId
from domains.shared.versioning import EntityVersion
from .models import CandidatePreferencesPatch
from .repository import CandidatePreferencesRepository, patch_to_set


class PreferencesConflictError(RuntimeError):
    pass


class CandidatePreferencesService:
    def __init__(self, db):
        self.db = db
        self.repo = CandidatePreferencesRepository(db)

    @staticmethod
    def deterministic_preferences_id(candidate_id: str) -> CandidatePreferencesId:
        return CandidatePreferencesId(f"candidate_preferences:{candidate_id}")

    async def get_declared(self, candidate_id: str):
        return await self.repo.get(candidate_id)

    async def update(
        self,
        candidate_id: str,
        patch: CandidatePreferencesPatch,
        expected_version: EntityVersion | None,
    ) -> dict:
        user = await self.db.users.find_one({"_id": candidate_id, "user_type": "candidate"})
        if not user:
            raise LookupError("candidate not found")
        client = get_client()
        if client is None:
            raise RuntimeError("Mongo client unavailable")
        now = datetime.now(timezone.utc)
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    current = await self.repo.get(candidate_id, session=session)
                    if current is None:
                        if expected_version is not None:
                            raise PreferencesConflictError("preferences do not exist yet")
                        doc = {
                            "_id": str(self.deterministic_preferences_id(candidate_id)),
                            "candidate_id": candidate_id,
                            "version": 1,
                            "search_state": "passive",
                            "discovery": {
                                "enabled": False,
                                "allow_compatible_opportunities": False,
                                "ask_before_reveal": False,
                                "anonymous_only": False,
                            },
                            "target_roles": [],
                            "work_mode": "any",
                            "contract_types": [],
                            "excluded_company_ids": [],
                            "created_at": now,
                            "updated_at": now,
                        }
                        doc.update(patch_to_set(patch))
                        return await self.repo.insert_initial(doc, session=session)

                    current_version = EntityVersion(int(current["version"]))
                    if expected_version is None or current_version != expected_version:
                        raise PreferencesConflictError(
                            f"preferences version mismatch: expected {expected_version}, current {int(current_version)}"
                        )
                    updated = await self.repo.update_with_version(
                        candidate_id, current_version, patch, now, session=session
                    )
                    if not updated:
                        raise PreferencesConflictError("preferences changed concurrently")
                    return updated
        except DuplicateKeyError as exc:
            raise PreferencesConflictError("preferences created concurrently; retry") from exc
