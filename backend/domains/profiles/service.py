"""Application service owning all A1 professional-profile mutations."""
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from database import get_client
from domains.shared.versioning import EntityVersion
from .legacy import profile_from_legacy_user
from .models import CandidateProfilePatch, FactSource, SkillFact
from .repository import CandidateProfileRepository


class ProfileConflictError(RuntimeError):
    pass


class ProfileNotFoundError(RuntimeError):
    pass


class ProfileService:
    """Single logical writer for professional facts during A1 migration.

    `candidate_profiles` is authoritative. Selected legacy fields are mirrored to
    `users` in the same Mongo transaction only to keep current UI/legacy AI alive
    until their dedicated migration lots consume CandidateProfileId + version.
    """

    LEGACY_MIRROR_FIELDS = {
        "summary": "bio",
        "current_location": "location",
        "experience_years": "experience_years",
    }

    def __init__(self, db):
        self.db = db
        self.repo = CandidateProfileRepository(db)

    async def get_current(self, candidate_id: str) -> dict:
        doc = await self.repo.get(candidate_id)
        if not doc:
            raise ProfileNotFoundError(candidate_id)
        return doc

    async def _materialize_if_missing(self, candidate_id: str, session) -> dict:
        current = await self.repo.get(candidate_id, session=session)
        if current:
            return current
        user_doc = await self.db.users.find_one(
            {"_id": candidate_id, "user_type": "candidate"}, session=session
        )
        if not user_doc:
            raise ProfileNotFoundError(candidate_id)
        initial = profile_from_legacy_user(user_doc)
        return await self.repo.insert_initial(initial, session=session)

    @staticmethod
    def legacy_patch(*, bio=None, location=None, experience_years=None, skills=None) -> CandidateProfilePatch:
        skill_facts = None
        if skills is not None:
            skill_facts = tuple(
                SkillFact(name=str(skill).strip(), source=FactSource.CANDIDATE_DECLARED)
                for skill in skills
                if str(skill).strip()
            )
        return CandidateProfilePatch(
            summary=bio,
            current_location=location,
            experience_years=experience_years,
            skills=skill_facts,
        )

    async def update(
        self,
        candidate_id: str,
        patch: CandidateProfilePatch,
        expected_version: EntityVersion | None,
        legacy_user_fields: dict | None = None,
    ) -> dict:
        client = get_client()
        if client is None:
            raise RuntimeError("Mongo client unavailable")
        now = datetime.now(timezone.utc)
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    current = await self._materialize_if_missing(candidate_id, session)
                    current_version = EntityVersion(int(current["version"]))
                    if expected_version is not None and current_version != expected_version:
                        raise ProfileConflictError(
                            f"profile version mismatch: expected {int(expected_version)}, "
                            f"current {int(current_version)}"
                        )
                    updated = await self.repo.update_with_version(
                        candidate_id,
                        current_version,
                        patch,
                        now,
                        session=session,
                    )
                    if not updated:
                        raise ProfileConflictError("profile changed concurrently")

                    mirror = dict(legacy_user_fields or {})
                    patch_dict = patch.__dict__
                    for profile_field, user_field in self.LEGACY_MIRROR_FIELDS.items():
                        value = patch_dict.get(profile_field)
                        if value is not None:
                            mirror[user_field] = value
                    if patch.skills is not None:
                        mirror["skills"] = [fact.name for fact in patch.skills]
                    if mirror:
                        mirror["updated_at"] = now
                        result = await self.db.users.update_one(
                            {"_id": candidate_id, "user_type": "candidate"},
                            {"$set": mirror},
                            session=session,
                        )
                        if result.matched_count != 1:
                            raise ProfileNotFoundError(candidate_id)
                    return updated
        except DuplicateKeyError as exc:
            # A deterministic profile _id + eventual unique candidate_id index
            # turns concurrent first-materialization into a retryable conflict.
            # Never continue using the transaction after DuplicateKeyError: Mongo
            # considers that transaction aborted.
            raise ProfileConflictError("profile materialized concurrently; retry") from exc
