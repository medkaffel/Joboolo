"""Role DNA application service; revisions append immutable versions."""
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from database import get_client
from domains.shared.ids import RoleDNAId
from domains.shared.versioning import EntityVersion
from .models import RoleDNA, RoleDNARevision
from .repository import RoleDNARepository, _serialize


class RoleDNAConflictError(RuntimeError):
    pass


class RoleDNAService:
    def __init__(self, db):
        self.db = db
        self.repo = RoleDNARepository(db)

    async def create(self, role: RoleDNA) -> dict:
        if int(role.version) != 1:
            raise ValueError("new Role DNA must start at version 1")
        doc = {
            "_id": f"{role.role_dna_id}:v1",
            "role_dna_id": str(role.role_dna_id),
            **{k: _serialize(v) for k, v in role.__dict__.items() if k != "role_dna_id"},
        }
        try:
            return await self.repo.insert_version(doc)
        except DuplicateKeyError as exc:
            raise RoleDNAConflictError("Role DNA already exists") from exc

    async def revise(
        self,
        role_dna_id: RoleDNAId,
        expected_version: EntityVersion,
        revision: RoleDNARevision,
    ) -> dict:
        changes = self.repo.serialize_revision(revision)
        if not changes:
            raise ValueError("Role DNA revision must contain at least one business change")

        client = get_client()
        if client is None:
            raise RuntimeError("Mongo client unavailable")
        now = datetime.now(timezone.utc)
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    current = await self.repo.get_latest(str(role_dna_id), session=session)
                    if current is None:
                        raise LookupError("Role DNA not found")
                    if int(current["version"]) != int(expected_version):
                        raise RoleDNAConflictError(
                            f"role version mismatch: expected {int(expected_version)}, current {current['version']}"
                        )
                    next_version = int(expected_version) + 1
                    new_doc = dict(current)
                    new_doc.update(changes)
                    new_doc["_id"] = f"{role_dna_id}:v{next_version}"
                    new_doc["version"] = next_version
                    new_doc["updated_at"] = now
                    return await self.repo.insert_version(new_doc, session=session)
        except DuplicateKeyError as exc:
            raise RoleDNAConflictError("role revised concurrently; retry") from exc
