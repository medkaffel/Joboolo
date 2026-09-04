"""Snapshot orchestration for deterministic Professional Match."""
from datetime import datetime
from typing import Optional

from domains.profiles.models import (
    CandidateProfessionalProfile,
    CertificationFact,
    EducationFact,
    ExperienceFact,
    FactSource,
    LanguageFact,
    OccupationFact,
    PortfolioFact,
    SkillFact,
)
from domains.profiles.repository import CandidateProfileRepository
from domains.roles.models import RoleDNA, RoleDNAStatus, RoleFactSource, RoleSkill
from domains.roles.repository import RoleDNARepository
from domains.shared.ids import CandidateId, CandidateProfileId, RoleDNAId
from domains.shared.versioning import EngineVersion, EntityVersion
from .engine import MATCH_ENGINE_VERSION, calculate_professional_match


class MatchInputNotFoundError(LookupError):
    pass


class MatchSnapshotUnavailableError(RuntimeError):
    pass


def _fact_source(value) -> FactSource:
    return value if isinstance(value, FactSource) else FactSource(value)


def _role_source(value) -> RoleFactSource:
    return value if isinstance(value, RoleFactSource) else RoleFactSource(value)


def _profile_from_document(doc: dict) -> CandidateProfessionalProfile:
    return CandidateProfessionalProfile(
        profile_id=CandidateProfileId(doc["_id"]),
        candidate_id=CandidateId(doc["candidate_id"]),
        version=EntityVersion(int(doc["version"])),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        headline=doc.get("headline"),
        summary=doc.get("summary"),
        current_location=doc.get("current_location"),
        experience_years=doc.get("experience_years"),
        seniority=doc.get("seniority"),
        occupations=tuple(
            OccupationFact(
                title=value["title"],
                source=_fact_source(value["source"]),
                normalized_occupation=value.get("normalized_occupation"),
                normalization_ref=value.get("normalization_ref"),
            )
            for value in doc.get("occupations", [])
        ),
        experiences=tuple(
            ExperienceFact(
                title=value["title"],
                source=_fact_source(value["source"]),
                employer=value.get("employer"),
                started_at=value.get("started_at"),
                ended_at=value.get("ended_at"),
                description=value.get("description"),
            )
            for value in doc.get("experiences", [])
        ),
        skills=tuple(
            SkillFact(
                name=value["name"],
                source=_fact_source(value["source"]),
                normalized_name=value.get("normalized_name"),
                normalization_ref=value.get("normalization_ref"),
                evidence_refs=tuple(value.get("evidence_refs", ())),
            )
            for value in doc.get("skills", [])
        ),
        certifications=tuple(
            CertificationFact(
                label=value["label"],
                source=_fact_source(value["source"]),
                issuer=value.get("issuer"),
            )
            for value in doc.get("certifications", [])
        ),
        languages=tuple(
            LanguageFact(
                language=value["language"],
                source=_fact_source(value["source"]),
                level=value.get("level"),
            )
            for value in doc.get("languages", [])
        ),
        industries=tuple(doc.get("industries", [])),
        management_experience=doc.get("management_experience"),
        education=tuple(
            EducationFact(
                label=value["label"],
                source=_fact_source(value["source"]),
                institution=value.get("institution"),
                completed_at=value.get("completed_at"),
            )
            for value in doc.get("education", [])
        ),
        portfolio=tuple(
            PortfolioFact(
                label=value["label"],
                url=value["url"],
                source=_fact_source(value["source"]),
            )
            for value in doc.get("portfolio", [])
        ),
    )


def _role_from_document(doc: dict) -> RoleDNA:
    return RoleDNA(
        role_dna_id=RoleDNAId(doc["role_dna_id"]),
        version=EntityVersion(int(doc["version"])),
        status=RoleDNAStatus(doc["status"]),
        canonical_title=doc["canonical_title"],
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
        family_code=doc.get("family_code"),
        family_label=doc.get("family_label"),
        aliases=tuple(doc.get("aliases", [])),
        skills=tuple(
            RoleSkill(
                label=value["label"],
                source=_role_source(value["source"]),
                normalized_code=value.get("normalized_code"),
                normalization_ref=value.get("normalization_ref"),
            )
            for value in doc.get("skills", [])
        ),
        capabilities=tuple(doc.get("capabilities", [])),
        seniority_band=doc.get("seniority_band"),
        experience_band=doc.get("experience_band"),
        certifications=tuple(doc.get("certifications", [])),
        languages=tuple(doc.get("languages", [])),
        transferable_role_refs=tuple(
            RoleDNAId(value) for value in doc.get("transferable_role_refs", [])
        ),
        adjacent_role_refs=tuple(
            RoleDNAId(value) for value in doc.get("adjacent_role_refs", [])
        ),
        taxonomy_version=doc.get("taxonomy_version"),
        provenance=_role_source(doc.get("provenance", RoleFactSource.MANUAL.value)),
        source_job_id=doc.get("source_job_id"),
        version_provenance=(
            _role_source(doc["version_provenance"])
            if doc.get("version_provenance")
            else None
        ),
        version_provenance_ref=doc.get("version_provenance_ref"),
    )


class ProfessionalMatchService:
    def __init__(self, db, engine_version: EngineVersion = MATCH_ENGINE_VERSION):
        self.profile_repo = CandidateProfileRepository(db)
        self.role_repo = RoleDNARepository(db)
        self.engine_version = engine_version

    async def compute(
        self,
        candidate_id: CandidateId,
        role_dna_id: RoleDNAId,
        role_dna_version: EntityVersion,
        *,
        candidate_profile_version: Optional[EntityVersion] = None,
        computed_at: Optional[datetime] = None,
    ):
        profile_doc = await self.profile_repo.get(str(candidate_id))
        if profile_doc is None:
            raise MatchInputNotFoundError("Candidate Professional Profile not found")

        current_profile_version = EntityVersion(int(profile_doc["version"]))
        if (
            candidate_profile_version is not None
            and current_profile_version != candidate_profile_version
        ):
            raise MatchSnapshotUnavailableError(
                "requested Candidate Professional Profile version is not available; "
                f"requested {int(candidate_profile_version)}, current {int(current_profile_version)}"
            )

        role_doc = await self.role_repo.get(
            str(role_dna_id), int(role_dna_version)
        )
        if role_doc is None:
            raise MatchInputNotFoundError("Role DNA version not found")

        return calculate_professional_match(
            _profile_from_document(profile_doc),
            _role_from_document(role_doc),
            engine_version=self.engine_version,
            computed_at=computed_at,
        )
