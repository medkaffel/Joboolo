"""Shipped A1-A11 metadata contracts, owned by Talent Stream.

13 authoritative collections, 32 secondary indexes. Unique identities/version
constraints are correctness-critical; lookup indexes are performance-only.
All index provisioning remains explicit-migration-only. No derived collections,
legacy startup indexes, or future A14 storage is included. A5/A6/A12 add none.
Absent explicit collation inherits the collection default, exactly as the
existing migrations do; A11 explicitly requires simple collation throughout.
Expiry lookup indexes are not TTL or authorization rules.
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


TS_INDEX_REQUIREMENTS = (
    # migrate_ts_a1_candidate_profiles.py
    CollectionRequirement("candidate_profiles", (
        _index("ts_a1_candidate_id_unique", "candidate_id", unique=True),
    )),
    # migrate_ts_a2_candidate_preferences.py
    CollectionRequirement("candidate_preferences", (
        _index("ts_a2_candidate_preferences_candidate_unique", "candidate_id", unique=True),
    )),
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
    CollectionRequirement("talent_intent_events", (
        _index("ts_a11_idempotency_key_unique", "idempotency_key", unique=True,
               strings=("idempotency_key",), simple=True),
    ), simple_collation=True, forbid_extra_indexes=True),
)
