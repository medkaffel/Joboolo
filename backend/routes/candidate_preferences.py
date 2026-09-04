"""Thin candidate HTTP adapter for TS-A2 preferences."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from auth import get_current_active_user
from database import get_database
from domains.preferences.models import (
    CandidatePreferencesPatch,
    CompensationPreference,
    DiscoverySettings,
    MobilityPreference,
    SearchState,
    WorkMode,
)
from domains.preferences.service import CandidatePreferencesService, PreferencesConflictError
from domains.shared.versioning import EntityVersion
from models import User, UserType

router = APIRouter(prefix="/candidate-preferences", tags=["candidate-preferences"])


class DiscoveryInput(BaseModel):
    enabled: bool
    allow_compatible_opportunities: bool = False
    ask_before_reveal: bool = False
    anonymous_only: bool = False


class CompensationInput(BaseModel):
    minimum: Optional[int] = None
    target: Optional[int] = None
    currency: str = "EUR"


class MobilityInput(BaseModel):
    locations: List[str] = []
    radius_km: Optional[int] = None


class PreferencesInput(BaseModel):
    search_state: Optional[SearchState] = None
    discovery: Optional[DiscoveryInput] = None
    target_roles: Optional[List[str]] = None
    compensation: Optional[CompensationInput] = None
    mobility: Optional[MobilityInput] = None
    work_mode: Optional[WorkMode] = None
    contract_types: Optional[List[str]] = None
    availability: Optional[str] = None
    excluded_company_ids: Optional[List[str]] = None
    current_employer_company_id: Optional[str] = None
    contact_frequency_preference: Optional[str] = None


def _candidate_only(user: User):
    if user.user_type != UserType.CANDIDATE:
        raise HTTPException(status_code=403, detail="Réservé aux candidats")


def _provided(payload: BaseModel) -> set[str]:
    if hasattr(payload, "model_fields_set"):
        return set(payload.model_fields_set)
    return set(payload.__fields_set__)


@router.get("/me")
async def get_preferences(current_user: User = Depends(get_current_active_user)):
    _candidate_only(current_user)
    db = await get_database()
    doc = await CandidatePreferencesService(db).get_declared(current_user.id)
    if doc is None:
        return {
            "persisted": False,
            "version": None,
            "search_state": "passive",
            "discovery": {
                "enabled": False,
                "allow_compatible_opportunities": False,
                "ask_before_reveal": False,
                "anonymous_only": False,
            },
        }
    doc["persisted"] = True
    return doc


@router.put("/me")
async def update_preferences(
    payload: PreferencesInput,
    current_user: User = Depends(get_current_active_user),
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
):
    _candidate_only(current_user)
    provided = _provided(payload)
    if not provided:
        raise HTTPException(status_code=400, detail="At least one preference field is required")

    expected = None
    if if_match is not None:
        try:
            expected = EntityVersion(int(if_match.strip('"')))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid If-Match preferences version")

    clearable = {
        "compensation", "mobility", "availability",
        "current_employer_company_id", "contact_frequency_preference",
    }
    clear_fields = frozenset(
        key for key in clearable if key in provided and getattr(payload, key) is None
    )
    patch = CandidatePreferencesPatch(
        search_state=payload.search_state if "search_state" in provided else None,
        discovery=None if payload.discovery is None else DiscoverySettings(**payload.discovery.dict()),
        target_roles=None if "target_roles" not in provided or payload.target_roles is None else tuple(payload.target_roles),
        compensation=None if payload.compensation is None else CompensationPreference(**payload.compensation.dict()),
        mobility=None if payload.mobility is None else MobilityPreference(
            locations=tuple(payload.mobility.locations), radius_km=payload.mobility.radius_km
        ),
        work_mode=payload.work_mode if "work_mode" in provided else None,
        contract_types=None if "contract_types" not in provided or payload.contract_types is None else tuple(payload.contract_types),
        availability=payload.availability if "availability" in provided else None,
        excluded_company_ids=None if "excluded_company_ids" not in provided or payload.excluded_company_ids is None else tuple(payload.excluded_company_ids),
        current_employer_company_id=(
            payload.current_employer_company_id if "current_employer_company_id" in provided else None
        ),
        contact_frequency_preference=(
            payload.contact_frequency_preference if "contact_frequency_preference" in provided else None
        ),
        clear_fields=clear_fields,
    )
    db = await get_database()
    try:
        return await CandidatePreferencesService(db).update(current_user.id, patch, expected)
    except PreferencesConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except LookupError:
        raise HTTPException(status_code=404, detail="Candidat introuvable")
