from datetime import datetime, timezone

import pytest

from domains.preferences.models import (
    CandidatePreferences,
    CompensationPreference,
    DiscoverySettings,
    SearchState,
)
from domains.shared.ids import CandidateId, CandidatePreferencesId
from domains.shared.versioning import EntityVersion


def test_discovery_disabled_by_default():
    prefs = CandidatePreferences(
        preferences_id=CandidatePreferencesId("p1"),
        candidate_id=CandidateId("c1"),
        version=EntityVersion(1),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    assert prefs.discovery.enabled is False


def test_paused_search_can_keep_discovery_enabled():
    prefs = CandidatePreferences(
        preferences_id=CandidatePreferencesId("p1"),
        candidate_id=CandidateId("c1"),
        version=EntityVersion(1),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        search_state=SearchState.PAUSED,
        discovery=DiscoverySettings(enabled=True, allow_compatible_opportunities=True),
    )
    assert prefs.search_state is SearchState.PAUSED
    assert prefs.discovery.enabled is True


def test_disabled_discovery_cannot_enable_subcontrols():
    with pytest.raises(ValueError):
        DiscoverySettings(enabled=False, anonymous_only=True)


def test_compensation_target_not_below_minimum():
    with pytest.raises(ValueError):
        CompensationPreference(minimum=60000, target=50000)


def test_preferences_model_contains_no_permission_intent_or_cv_fields():
    fields = CandidatePreferences.__dataclass_fields__
    for forbidden in ("intent", "permission", "grant", "cv", "document_id", "profile"):
        assert forbidden not in fields
