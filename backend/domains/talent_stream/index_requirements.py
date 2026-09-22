"""Shipped A1-B10 metadata contracts, owned by Talent Stream.

20 authoritative collections, 41 secondary indexes. Unique identities/version
constraints are correctness-critical; lookup indexes are performance-only.
All index provisioning remains explicit-migration-only. No derived collections,
legacy startup indexes, or A14 storage is included. A5/A6/A12 add none.
Absent explicit collation inherits the collection default, exactly as the
existing migrations do; A11, the B7 candidates collection, the B7 projection
states collection, the B7 generation registry and the B7 Intent job event scan
require simple collation throughout. Expiry lookup indexes are not TTL or
authorization rules.
"""
from mongo_index_safety import CollectionRequirement, IndexRequirement


def _index(name: str, *fields: str, unique: bool = False,
           strings: tuple[str, ...] = (), simple: bool = False) -> IndexRequirement:
    return IndexRequirement(
        name=name, keys=tuple((field, 1) for field in fields),
        critical=unique, unique=unique,
        partial_filter={field: {"$type": "string"} for field in strings} if strings else None,
        collation={"locale": "simple"} if simple else None,
    )


TALENT_STREAM_REQUIREMENT = CollectionRequirement(
    "talent_streams", (), simple_collation=True, forbid_extra_indexes=True,
)


CANDIDATE_PREFERENCES_REQUIREMENT = CollectionRequirement(
    "candidate_preferences",
    (
        _index("ts_a2_candidate_preferences_candidate_unique", "candidate_id", unique=True),
        IndexRequirement(
            name="ts_b6_discovery_pool_scan",
            keys=(
                ("discovery.enabled", 1),
                ("discovery.allow_compatible_opportunities", 1),
                ("candidate_id", 1),
            ),
            critical=False,
            partial_filter={
                "discovery.enabled": True,
                "discovery.allow_compatible_opportunities": True,
            },
        ),
    ),
)


TALENT_STREAM_CANDIDATES_REQUIREMENT = CollectionRequirement(
    "talent_stream_candidates",
    (
        _index(
            "ts_b7_stream_generation_candidate_unique",
            "stream_id",
            "generation_id",
            "candidate_id",
            unique=True,
        ),
    ),
    simple_collation=True,
    forbid_extra_indexes=True,
)


TALENT_STREAM_CANDIDATE_PROJECTION_STATES_REQUIREMENT = CollectionRequirement(
    "talent_stream_candidate_projection_states",
    (),
    simple_collation=True,
    forbid_extra_indexes=True,
)


TALENT_STREAM_CANDIDATE_GENERATIONS_REQUIREMENT = CollectionRequirement(
    "talent_stream_candidate_generations",
    (),
    simple_collation=True,
    forbid_extra_indexes=True,
)


# B7.2 performance index provisioned by migrate_ts_b7_stream_candidate_projection.py.
# Non-critical for A13: absent, it only produces an A13 warning and never blocks
# B4/B5 writers. It is the mandatory B7 intent lookup contract for the STEP 3
# Intent event reader, which may require it as a blocking B7 readiness guard.
TS_B7_INTENT_JOB_EVENT_SCAN = _index(
    "ts_b7_intent_job_event_scan",
    "job_id",
    "event_type",
    "occurred_at",
    "_id",
)


TALENT_INTENT_EVENTS_REQUIREMENT = CollectionRequirement(
    "talent_intent_events",
    (
        _index(
            "ts_a11_idempotency_key_unique",
            "idempotency_key",
            unique=True,
            strings=("idempotency_key",),
            simple=True,
        ),
        TS_B7_INTENT_JOB_EVENT_SCAN,
    ),
    simple_collation=True,
    forbid_extra_indexes=True,
)


CONTACT_GOVERNOR_RESERVATIONS_REQUIREMENT = CollectionRequirement(
    "contact_governor_reservations",
    (
        _index(
            "ts_b9_candidate_activity",
            "candidate_id",
            "status",
            "activity_at",
        ),
        _index(
            "ts_b9_requesting_org_activity",
            "candidate_id",
            "requesting_organization_id",
            "status",
            "activity_at",
        ),
        _index(
            "ts_b9_hiring_company_activity",
            "candidate_id",
            "hiring_company_id",
            "status",
            "activity_at",
        ),
        _index(
            "ts_b9_dedup_activity",
            "candidate_id",
            "dedup_key",
            "status",
            "activity_at",
        ),
        _index(
            "ts_b9_contact_request_unique",
            "contact_request_id",
            unique=True,
            strings=("contact_request_id",),
        ),
    ),
    simple_collation=True,
    forbid_extra_indexes=True,
)


CONTACT_GOVERNOR_CANDIDATE_GUARDS_REQUIREMENT = CollectionRequirement(
    "contact_governor_candidate_guards",
    (),
    simple_collation=True,
    forbid_extra_indexes=True,
)


TALENT_STREAM_CONTACT_REQUESTS_REQUIREMENT = CollectionRequirement(
    "talent_stream_contact_requests",
    (
        _index(
            "ts_b10_contact_request_reservation_unique",
            "reservation_id",
            unique=True,
        ),
    ),
    simple_collation=True,
    forbid_extra_indexes=True,
)


TS_INDEX_REQUIREMENTS = (
    # migrate_ts_a1_candidate_profiles.py
    CollectionRequirement("candidate_profiles", (
        _index("ts_a1_candidate_id_unique", "candidate_id", unique=True),
    )),
    # migrate_ts_a2_candidate_preferences.py
    CANDIDATE_PREFERENCES_REQUIREMENT,
    # migrate_ts_a3_role_dna_indexes.py
    CollectionRequirement("role_dnas", (
        _index("ts_a3_role_dna_version_unique", "role_dna_id", "version", unique=True),
    )),
    # migrate_ts_a4_opportunity_spec_indexes.py
    CollectionRequirement("opportunity_specs", (
        _index("ts_a4_opportunity_spec_version_unique", "opportunity_spec_id", "version", unique=True),
    )),
    # migrate_ts_a7_organization_indexes.py
    CollectionRequirement("organizations", (
        _index("ts_a7_organization_id_unique", "organization_id", unique=True),
        _index("ts_a7_verification_state", "verification_state"),
        _index("ts_a7_legacy_company_unique", "legacy_company_id", unique=True, strings=("legacy_company_id",)),
        _index("ts_a7_legal_identity_unique", "registration_country", "registration_id", unique=True,
               strings=("registration_country", "registration_id")),
    )),
    CollectionRequirement("organization_verification_events", (
        _index("ts_a7_verification_event_timeline", "organization_id", "occurred_at"),
        _index("ts_a7_verification_event_version_unique", "organization_id", "organization_version", unique=True),
    )),
    # migrate_ts_a8_recruiting_trust_indexes.py
    CollectionRequirement("organization_memberships", (
        _index("ts_a8_membership_id_unique", "membership_id", unique=True),
        _index("ts_a8_membership_pair_unique", "recruiter_user_id", "organization_id", unique=True),
        _index("ts_a8_membership_state", "state"),
        _index("ts_a8_membership_org", "organization_id"),
        _index("ts_a8_membership_recruiter", "recruiter_user_id"),
    )),
    CollectionRequirement("recruiter_verifications", (
        _index("ts_a8_recruiter_verification_unique", "recruiter_user_id", unique=True),
        _index("ts_a8_recruiter_verification_state", "state"),
    )),
    CollectionRequirement("recruiting_mandates", (
        _index("ts_a8_mandate_id_unique", "mandate_id", unique=True),
        _index("ts_a8_mandate_pair", "requesting_organization_id", "hiring_company_id"),
        _index("ts_a8_mandate_state", "state"),
        _index("ts_a8_mandate_valid_until", "valid_until"),
    )),
    CollectionRequirement("recruiting_trust_events", (
        _index("ts_a8_trust_event_version_unique", "subject_type", "subject_id", "subject_version", unique=True),
        _index("ts_a8_trust_event_timeline", "subject_type", "subject_id", "occurred_at"),
    )),
    # migrate_ts_a9_permission_indexes.py + migrate_ts_a10_privacy_indexes.py
    CollectionRequirement("talent_stream_grants", (
        _index("ts_a9_grant_id_unique", "grant_id", unique=True),
        _index("ts_a9_grant_lookup", "candidate_id", "grantee_organization_id", "stream_id", "scopes"),
        _index("ts_a9_grant_document_lookup", "candidate_id", "grantee_organization_id", "stream_id", "document_id",
               strings=("document_id",)),
        _index("ts_a9_grant_expiry", "expires_at"),
        _index("ts_a10_grant_revocation", "revoked_at"),
    )),
    CollectionRequirement("talent_stream_privacy_events", (
        _index("ts_a10_privacy_command_unique", "command_id", unique=True),
        _index("ts_a10_privacy_grant_timeline", "grant_id", "occurred_at"),
        _index("ts_a10_privacy_candidate_timeline", "candidate_id", "occurred_at"),
    )),
    # migrate_ts_a11_intent_event_indexes.py: strict metadata preflight retained.
    # migrate_ts_b7_stream_candidate_projection.py: B7 Intent job event scan index.
    TALENT_INTENT_EVENTS_REQUIREMENT,
    # TS-B1-001: stable Stream identity is enforced by native _id_ only.
    TALENT_STREAM_REQUIREMENT,
    # migrate_ts_b7_stream_candidate_projection.py
    TALENT_STREAM_CANDIDATES_REQUIREMENT,
    TALENT_STREAM_CANDIDATE_PROJECTION_STATES_REQUIREMENT,
    TALENT_STREAM_CANDIDATE_GENERATIONS_REQUIREMENT,
    # migrate_ts_b9_contact_governor.py
    CONTACT_GOVERNOR_RESERVATIONS_REQUIREMENT,
    CONTACT_GOVERNOR_CANDIDATE_GUARDS_REQUIREMENT,
    # migrate_ts_b10_contact_requests.py
    TALENT_STREAM_CONTACT_REQUESTS_REQUIREMENT,
)
