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
    "company_intent_is_distinct_from_role_intent",
    "company_intent_is_not_automatically_competitive_signal",
    "absence_of_observed_intent_is_not_absence_of_potential_interest",
    "discovery_pool_supports_opt_in_without_recent_activity",
    "paused_search_can_coexist_with_enabled_discovery",
)

AUTHORIZATION_INVARIANTS = (
    "current_authorization_checked_before_sensitive_action",
    "projection_is_not_authorization_source_of_truth",
    "high_match_cannot_override_denied_permission",
    "high_match_cannot_override_denied_trust",
    "high_match_cannot_override_source_protection",
    "cv_requires_specific_scoped_grant_or_existing_acl",
    "application_to_company_a_is_not_authorization_for_company_b",
    "current_employer_exclusion_applies_before_exposure",
    "specific_company_exclusions_apply_before_exposure",
    "talent_stream_opt_in_is_not_required_to_apply",
    "talent_stream_refusal_cannot_penalize_application_or_matching",
    "no_broad_recruiter_cv_acl_bypass",
)

CROSS_OFFER_INVARIANTS = (
    "internal_relevance_is_not_recruiter_exposure",
    "competitor_source_provenance_is_not_recruiter_visible",
    "no_precise_competitor_activity_exposure",
    "independent_signal_rule_precedes_nominative_cross_offer_exposure",
    "source_protection_precedes_nominative_cross_offer_exposure",
)

PRIVACY_INVARIANTS = (
    "anonymous_talent_requires_anti_reidentification_policy",
    "pseudonymous_identity_is_not_recruiter_identity_access",
    "no_generalized_cross_site_surveillance",
    "no_fake_jobs_for_intent_harvesting",
)

DATA_INVARIANTS = (
    "authoritative_data_can_rebuild_projections",
    "ttl_cleanup_is_not_authorization",
    "cpc_billing_events_are_not_intent_events",
    "stream_requirement_snapshot_pins_source_versions",
    "match_intent_trust_permission_must_not_be_merged_into_opaque_score",
)

ALL_INVARIANTS = (
    SEPARATION_INVARIANTS
    + AUTHORIZATION_INVARIANTS
    + CROSS_OFFER_INVARIANTS
    + PRIVACY_INVARIANTS
    + DATA_INVARIANTS
)
