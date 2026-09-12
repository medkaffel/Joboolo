"""A14-only metadata requirements; provisioning is never a runtime operation."""
from mongo_index_safety import CollectionRequirement, IndexRequirement

OUTBOX_REQUIREMENT = CollectionRequirement(
    name="async_outbox",
    indexes=(
        IndexRequirement(
            "a14_outbox_dedup_unique", (("job_type", 1), ("idempotency_key", 1)),
            critical=True, unique=True, collation={"locale": "simple"},
        ),
        IndexRequirement(
            "a14_outbox_pending_lookup", (("state", 1), ("available_at", 1), ("_id", 1)),
            critical=False, collation={"locale": "simple"},
        ),
        IndexRequirement(
            "a14_outbox_lease_lookup", (("state", 1), ("lease_until", 1), ("_id", 1)),
            critical=False, collation={"locale": "simple"},
        ),
    ),
    ordinary=True, simple_collation=True, forbid_ttl=True,
)
