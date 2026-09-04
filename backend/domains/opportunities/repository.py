"""Mongo persistence for immutable Opportunity Specification versions."""
from typing import Optional


def _serialize(value):
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, tuple):
        return [_serialize(v) for v in value]
    if hasattr(value, "__dict__"):
        return {k: _serialize(v) for k, v in value.__dict__.items()}
    return value


class OpportunitySpecRepository:
    def __init__(self, db):
        self.collection = db.opportunity_specs

    async def get(self, opportunity_spec_id: str, version: int, session=None) -> Optional[dict]:
        return await self.collection.find_one(
            {"opportunity_spec_id": opportunity_spec_id, "version": version},
            session=session,
        )

    async def get_latest(self, opportunity_spec_id: str, session=None) -> Optional[dict]:
        return await self.collection.find_one(
            {"opportunity_spec_id": opportunity_spec_id},
            sort=[("version", -1)],
            session=session,
        )

    async def insert_version(self, doc: dict, session=None) -> dict:
        await self.collection.insert_one(doc, session=session)
        return doc

    @staticmethod
    def serialize_revision(revision) -> dict:
        out = {
            key: _serialize(value)
            for key, value in revision.__dict__.items()
            if key != "clear_fields" and value is not None
        }
        for key in revision.clear_fields:
            out[key] = None
        return out
