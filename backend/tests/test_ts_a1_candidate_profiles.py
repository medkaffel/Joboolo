from datetime import datetime, timezone

import pytest

from domains.profiles.legacy import deterministic_profile_id, profile_from_legacy_user
from domains.profiles.models import CandidateProfilePatch, FactSource, SkillFact
from domains.profiles.repository import patch_to_mongo_set
from domains.shared.versioning import EntityVersion


def test_deterministic_profile_id_is_stable():
    assert deterministic_profile_id("candidate-1") == deterministic_profile_id("candidate-1")
    assert str(deterministic_profile_id("candidate-1")) == "candidate_profile:candidate-1"


def test_legacy_mapping_is_conservative_and_provenanced():
    now = datetime.now(timezone.utc)
    profile = profile_from_legacy_user({
        "_id": "candidate-1",
        "user_type": "candidate",
        "bio": "Backend engineer",
        "location": "Paris",
        "skills": ["Python", "MongoDB"],
        "experience_years": 7,
        "unknown_certification": "DO NOT COPY",
    }, now=now)
    assert profile.version == EntityVersion(1)
    assert profile.summary == "Backend engineer"
    assert profile.current_location == "Paris"
    assert [s.name for s in profile.skills] == ["Python", "MongoDB"]
    assert all(s.source == FactSource.LEGACY_USER for s in profile.skills)
    assert profile.certifications == ()
    assert profile.experiences == ()


def test_profile_contract_contains_no_preferences_discovery_intent_permission_or_cv():
    fields = set(profile_from_legacy_user({"_id": "candidate-1"}).__dict__)
    forbidden = {
        "salary_expectation", "target_salary", "remote_preference", "mobility_radius",
        "discovery_state", "intent", "permission", "cv", "document_id",
    }
    assert not (fields & forbidden)


def test_profile_patch_rejects_negative_experience():
    with pytest.raises(ValueError):
        CandidateProfilePatch(experience_years=-1)


def test_patch_serialization_keeps_declared_source_and_no_hidden_fields():
    patch = CandidateProfilePatch(
        summary="Senior backend engineer",
        skills=(SkillFact(name="Python", source=FactSource.CANDIDATE_DECLARED),),
    )
    mongo = patch_to_mongo_set(patch)
    assert mongo["summary"] == "Senior backend engineer"
    assert mongo["skills"] == [{
        "name": "Python",
        "source": "candidate_declared",
        "normalized_name": None,
        "evidence_refs": (),
    }]
    assert "salary" not in mongo
    assert "permission" not in mongo


def test_entity_version_remains_strictly_positive_for_profiles():
    with pytest.raises(ValueError):
        EntityVersion(0)
