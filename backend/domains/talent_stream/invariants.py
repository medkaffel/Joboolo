"""Business invariants that must hold across all Talent Stream lots."""

# These constants are documentation-friendly machine-readable contracts. They
# intentionally contain no runtime authorization logic; later bounded contexts
# must implement and test them at their own boundaries.

SEPARATION_INVARIANTS = (
    "professional_match_is_not_intent",
    "discovery_is_not_intent",
    "intent_is_not_permission",
    "permission_is_not_trust",
    "opportunity_fit_is_not_professional_match",
    "reference_job_is_not_audience_ownership",
    "private_favorite_is_not_sharing_consent",
    "click_is_not_sharing_consent",
    "profile_access_is_not_cv_access",
)

AUTHORIZATION_INVARIANTS = (
    "current_authorization_checked_before_sensitive_action",
    "projection_is_not_authorization_source_of_truth",
    "high_match_cannot_override_denied_permission",
    "high_match_cannot_override_denied_trust",
    "high_match_cannot_override_source_protection",
    "cv_requires_specific_scoped_grant_or_existing_acl",
    "current_employer_exclusion_applies_before_exposure",
)

CROSS_OFFER_INVARIANTS = (
    "internal_relevance_is_not_recruiter_exposure",
    "competitor_source_provenance_is_not_recruiter_visible",
    "independent_signal_rule_precedes_nominative_cross_offer_exposure",
    "source_protection_precedes_nominative_cross_offer_exposure",
)

DATA_INVARIANTS = (
    "authoritative_data_can_rebuild_projections",
    "ttl_cleanup_is_not_authorization",
    "cpc_billing_events_are_not_intent_events",
    "stream_requirement_snapshot_pins_source_versions",
)
