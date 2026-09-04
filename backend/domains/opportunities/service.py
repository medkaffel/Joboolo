"""Application service for append-only Opportunity Specification versions."""
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from database import get_client
from domains.shared.ids import OpportunitySpecId
from domains.shared.versioning import EntityVersion
from .models import OpportunitySpecRevision, OpportunitySpecification
from .repository import OpportunitySpecRepository, _serialize


class OpportunitySpecConflictError(RuntimeError):
    pass


class OpportunitySpecService:
    def __init__(self, db):
        self.db = db
        self.repo = OpportunitySpecRepository(db)

    async def create(self, spec: OpportunitySpecification) -> dict:
        if int(spec.version) != 1:
            raise ValueError("new Opportunity Specification must start at version 1")
        doc = {
            "_id": f"{spec.opportunity_spec_id}:v1",
            "opportunity_spec_id": str(spec.opportunity_spec_id),
            **{
                key: _serialize(value)
                for key, value in spec.__dict__.items()
                if key != "opportunity_spec_id"
            },
        }
        try:
            return await self.repo.insert_version(doc)
        except DuplicateKeyError as exc:
            raise OpportunitySpecConflictError("Opportunity Specification already exists") from exc

    async def revise(
        self,
        opportunity_spec_id: OpportunitySpecId,
        expected_version: EntityVersion,
        revision: OpportunitySpecRevision,
    ) -> dict:
        serialized = self.repo.serialize_revision(revision)
        business_changes = {
            key: value
            for key, value in serialized.items()
            if key not in {"version_provenance", "version_provenance_ref"}
        }
        if not business_changes:
            raise ValueError("Opportunity Specification revision requires a business change")

        client = get_client()
        if client is None:
            raise RuntimeError("Mongo client unavailable")

        now = datetime.now(timezone.utc)
        try:
            async with await client.start_session() as session:
                async with session.start_transaction():
                    current = await self.repo.get_latest(
                        str(opportunity_spec_id), session=session
                    )
                    if current is None:
                        raise LookupError("Opportunity Specification not found")
                    if int(current["version"]) != int(expected_version):
                        raise OpportunitySpecConflictError(
                            "opportunity specification version mismatch: "
                            f"expected {int(expected_version)}, current {current['version']}"
                        )
                    next_version = int(expected_version) + 1
                    new_doc = dict(current)
                    new_doc.update(business_changes)
                    new_doc["version_provenance"] = serialized["version_provenance"]
                    new_doc["version_provenance_ref"] = serialized.get(
                        "version_provenance_ref"
                    )
                    new_doc["_id"] = f"{opportunity_spec_id}:v{next_version}"
                    new_doc["version"] = next_version
                    new_doc["updated_at"] = now
                    return await self.repo.insert_version(new_doc, session=session)
        except DuplicateKeyError as exc:
            raise OpportunitySpecConflictError(
                "Opportunity Specification revised concurrently; retry"
            ) from exc
