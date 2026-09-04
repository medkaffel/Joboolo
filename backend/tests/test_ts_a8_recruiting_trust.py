from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest

from domains.shared.ids import HiringCompanyId, MandateId, MembershipId, OrganizationId, RecruiterUserId
from domains.shared.versioning import EntityVersion, PolicyVersion
from domains.talent_stream.contracts import RecruitingActorContext
from domains.trust.recruiting_models import (
    MandateCreate, MandateReasonCode, MandateState, MandateTransition,
    MembershipCreate, MembershipReasonCode, MembershipRole, MembershipState, MembershipTransition,
    RecruiterVerificationCreate, RecruiterVerificationReasonCode, RecruiterVerificationState, RecruiterVerificationTransition,
    RecruitingMandate, RecruitingTrustReasonCode,
)
from domains.trust.recruiting_service import RecruitingTrustConflictError, RecruitingTrustEligibilityError, RecruitingTrustService

NOW = datetime(2026, 9, 4, 21, 0, tzinfo=timezone.utc)
POLICY = PolicyVersion("trust-v1")

class FakeSession:
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    def start_transaction(self): return self
class FakeClient:
    async def start_session(self): return FakeSession()
class FakeRepo:
    def __init__(self):
        self.users={}; self.orgs={}; self.memberships={}; self.verifications={}; self.mandates={}; self.events=[]
    async def get_user(self, i, session=None): return self.users.get(i)
    async def get_organization(self, i, session=None): return self.orgs.get(i)
    async def get_membership(self, i, session=None): return self.memberships.get(i)
    async def get_membership_by_pair(self, r, o, session=None):
        return next((x for x in self.memberships.values() if x["recruiter_user_id"]==r and x["organization_id"]==o),None)
    async def get_recruiter_verification(self, i, session=None): return self.verifications.get(i)
    async def get_mandate(self, i, session=None): return self.mandates.get(i)
    async def insert_membership(self,d,session=None):
        if d["_id"] in self.memberships or any(x["recruiter_user_id"]==d["recruiter_user_id"] and x["organization_id"]==d["organization_id"] for x in self.memberships.values()): raise RuntimeError("duplicate")
        self.memberships[d["_id"]]=dict(d); return d
    async def insert_recruiter_verification(self,d,session=None): self.verifications[d["_id"]]=dict(d); return d
    async def insert_mandate(self,d,session=None): self.mandates[d["_id"]]=dict(d); return d
    async def insert_event(self,d,session=None): self.events.append(dict(d)); return d
    async def _update(self,store,i,v,c):
        d=store.get(i)
        if d is None or d["version"] != v: return None
        d.update(c); d["version"] += 1; return dict(d)
    async def update_membership(self,i,v,c,session=None): return await self._update(self.memberships,i,v,c)
    async def update_recruiter_verification(self,i,v,c,session=None): return await self._update(self.verifications,i,v,c)
    async def update_mandate(self,i,v,c,session=None): return await self._update(self.mandates,i,v,c)

def service():
    db=SimpleNamespace(organization_memberships=None,recruiter_verifications=None,recruiting_mandates=None,recruiting_trust_events=None,organizations=None,users=None)
    s=RecruitingTrustService(db, client_provider=lambda: FakeClient()); s.repo=FakeRepo(); return s

def seed(s, *, requesting="org1", hiring="org1", user_type="employer", active=True, org_state="verified"):
    s.repo.users["r1"]={"_id":"r1","user_type":user_type,"is_active":active}
    s.repo.orgs[requesting]={"_id":requesting,"version":2,"verification_state":org_state}
    if hiring != requesting:
        s.repo.orgs[hiring]={"_id":hiring,"version":3,"verification_state":"verified"}
    s.repo.memberships["m1"]={"_id":"m1","membership_id":"m1","recruiter_user_id":"r1","organization_id":requesting,"version":2,"role":"recruiter","state":"active","policy_version":"trust-v1","reason_codes":["relation_confirmed"],"evidence_refs":["employment-proof"],"actor_id":"admin","decided_at":NOW,"created_at":NOW,"updated_at":NOW}
    s.repo.verifications["r1"]={"_id":"r1","recruiter_user_id":"r1","version":3,"state":"verified","policy_version":"trust-v1","reason_codes":["identity_confirmed"],"evidence_refs":["id-proof"],"actor_id":"admin","decided_at":NOW,"created_at":NOW,"updated_at":NOW}

def context(requesting="org1", hiring="org1", mandate=None):
    return RecruitingActorContext(RecruiterUserId("r1"), OrganizationId(requesting), HiringCompanyId(hiring), None if mandate is None else MandateId(mandate))


def test_active_membership_requires_evidence():
    with pytest.raises(ValueError):
        MembershipTransition(MembershipState.ACTIVE,(MembershipReasonCode.RELATION_CONFIRMED,),(),POLICY,"admin")

def test_verified_recruiter_requires_evidence():
    with pytest.raises(ValueError):
        RecruiterVerificationTransition(RecruiterVerificationState.VERIFIED,(RecruiterVerificationReasonCode.IDENTITY_CONFIRMED,),(),POLICY,"admin")

def test_reason_code_must_match_target_state():
    with pytest.raises(ValueError):
        MembershipTransition(MembershipState.ACTIVE,(MembershipReasonCode.RELATION_SUSPENDED,),("e",),POLICY,"admin")

def test_self_mandate_refused():
    with pytest.raises(ValueError):
        MandateCreate(MandateId("x"),OrganizationId("o"),HiringCompanyId("o"),NOW,NOW+timedelta(days=1),POLICY,"admin")

def test_mandate_window_is_half_open():
    m=RecruitingMandate(MandateId("x"),OrganizationId("a"),HiringCompanyId("b"),EntityVersion(1),MandateState.ACTIVE,NOW,NOW+timedelta(days=1),POLICY,(MandateReasonCode.MANDATE_CONFIRMED,),("proof",),"admin",NOW,NOW,NOW)
    assert m.is_temporally_valid_at(NOW)
    assert not m.is_temporally_valid_at(NOW+timedelta(days=1))

@pytest.mark.asyncio
async def test_membership_create_is_pending_and_audited():
    s=service(); seed(s)
    s.repo.memberships={}
    out=await s.create_membership(MembershipCreate(MembershipId("m2"),RecruiterUserId("r1"),OrganizationId("org1"),MembershipRole.RECRUITER,POLICY,"admin"),now=NOW)
    assert out.state is MembershipState.PENDING and out.version==1
    assert s.repo.events[-1]["subject_version"]==1 and s.repo.events[-1]["new_state"]=="pending"

@pytest.mark.asyncio
async def test_membership_activation_and_cas():
    s=service(); seed(s); s.repo.memberships["m1"].update({"state":"pending","role":"recruiter","policy_version":"trust-v1","reason_codes":["membership_requested"],"evidence_refs":[],"actor_id":"admin","decided_at":NOW,"created_at":NOW,"updated_at":NOW})
    out=await s.transition_membership(MembershipId("m1"),EntityVersion(2),MembershipTransition(MembershipState.ACTIVE,(MembershipReasonCode.RELATION_CONFIRMED,),("employment-proof",),POLICY,"admin"),now=NOW)
    assert out.state is MembershipState.ACTIVE and out.version==3
    with pytest.raises(RecruitingTrustConflictError):
        await s.transition_membership(MembershipId("m1"),EntityVersion(2),MembershipTransition(MembershipState.SUSPENDED,(MembershipReasonCode.RELATION_SUSPENDED,),(),POLICY,"admin"),now=NOW)

@pytest.mark.asyncio
async def test_partner_cannot_create_membership():
    s=service(); seed(s,user_type="partner"); s.repo.memberships={}
    with pytest.raises(RecruitingTrustEligibilityError):
        await s.create_membership(MembershipCreate(MembershipId("m2"),RecruiterUserId("r1"),OrganizationId("org1"),MembershipRole.RECRUITER,POLICY,"admin"),now=NOW)

@pytest.mark.asyncio
async def test_recruiter_verification_lifecycle():
    s=service(); seed(s); s.repo.verifications={}
    first=await s.create_recruiter_verification(RecruiterVerificationCreate(RecruiterUserId("r1"),POLICY,"admin"),now=NOW)
    assert first.state is RecruiterVerificationState.UNVERIFIED
    pending=await s.transition_recruiter_verification(RecruiterUserId("r1"),EntityVersion(1),RecruiterVerificationTransition(RecruiterVerificationState.PENDING,(RecruiterVerificationReasonCode.VERIFICATION_REQUESTED,),(),POLICY,"admin"),now=NOW)
    verified=await s.transition_recruiter_verification(RecruiterUserId("r1"),EntityVersion(2),RecruiterVerificationTransition(RecruiterVerificationState.VERIFIED,(RecruiterVerificationReasonCode.IDENTITY_CONFIRMED,),("id-proof",),POLICY,"admin"),now=NOW)
    assert pending.version==2 and verified.state is RecruiterVerificationState.VERIFIED

@pytest.mark.asyncio
async def test_rejected_recruiter_can_only_resubmit_pending():
    s=service(); seed(s); s.repo.verifications["r1"].update({"state":"rejected","version":4,"policy_version":"trust-v1","reason_codes":["evidence_insufficient"],"evidence_refs":[],"actor_id":"admin","decided_at":NOW,"created_at":NOW,"updated_at":NOW})
    with pytest.raises(ValueError):
        await s.transition_recruiter_verification(RecruiterUserId("r1"),EntityVersion(4),RecruiterVerificationTransition(RecruiterVerificationState.VERIFIED,(RecruiterVerificationReasonCode.REVERIFICATION_APPROVED,),("proof",),POLICY,"admin"),now=NOW)

@pytest.mark.asyncio
async def test_mandate_activation_requires_verified_organizations():
    s=service(); seed(s,requesting="agency",hiring="client",org_state="pending")
    s.repo.mandates["d1"]={"_id":"d1","mandate_id":"d1","requesting_organization_id":"agency","hiring_company_id":"client","version":1,"state":"pending","valid_from":NOW,"valid_until":NOW+timedelta(days=30),"policy_version":"trust-v1","reason_codes":["mandate_submitted"],"evidence_refs":[],"actor_id":"admin","decided_at":NOW,"created_at":NOW,"updated_at":NOW}
    with pytest.raises(RecruitingTrustEligibilityError):
        await s.transition_mandate(MandateId("d1"),EntityVersion(1),MandateTransition(MandateState.ACTIVE,(MandateReasonCode.MANDATE_CONFIRMED,),("contract",),POLICY,"admin"),now=NOW)

@pytest.mark.asyncio
async def test_expired_mandate_cannot_activate():
    s=service(); seed(s,requesting="agency",hiring="client")
    s.repo.mandates["d1"]={"_id":"d1","mandate_id":"d1","requesting_organization_id":"agency","hiring_company_id":"client","version":1,"state":"pending","valid_from":NOW-timedelta(days=2),"valid_until":NOW-timedelta(days=1),"policy_version":"trust-v1","reason_codes":["mandate_submitted"],"evidence_refs":[],"actor_id":"admin","decided_at":NOW,"created_at":NOW,"updated_at":NOW}
    with pytest.raises(RecruitingTrustEligibilityError):
        await s.transition_mandate(MandateId("d1"),EntityVersion(1),MandateTransition(MandateState.ACTIVE,(MandateReasonCode.MANDATE_CONFIRMED,),("contract",),POLICY,"admin"),now=NOW)

@pytest.mark.asyncio
async def test_direct_employer_trusted_without_mandate():
    s=service(); seed(s)
    d=await s.evaluate_recruiting_actor_trust(context(),policy_version=POLICY,evaluated_at=NOW)
    assert d.allowed and d.reason_codes==(RecruitingTrustReasonCode.RECRUITING_ACTOR_TRUSTED.value,)

@pytest.mark.asyncio
@pytest.mark.parametrize("user_patch,reason",[
    ({"is_active":False},RecruitingTrustReasonCode.RECRUITER_USER_INACTIVE),
    ({"user_type":"partner"},RecruitingTrustReasonCode.RECRUITER_USER_TYPE_UNSUPPORTED),
])
async def test_user_current_state_blocks_trust(user_patch,reason):
    s=service(); seed(s); s.repo.users["r1"].update(user_patch)
    d=await s.evaluate_recruiting_actor_trust(context(),policy_version=POLICY,evaluated_at=NOW)
    assert not d.allowed and d.reason_codes==(reason.value,)

@pytest.mark.asyncio
async def test_unverified_requesting_org_blocks_trust():
    s=service(); seed(s,org_state="suspended")
    d=await s.evaluate_recruiting_actor_trust(context(),policy_version=POLICY,evaluated_at=NOW)
    assert d.reason_codes==(RecruitingTrustReasonCode.REQUESTING_ORGANIZATION_NOT_VERIFIED.value,)

@pytest.mark.asyncio
async def test_suspended_membership_blocks_trust():
    s=service(); seed(s); s.repo.memberships["m1"]["state"]="suspended"
    d=await s.evaluate_recruiting_actor_trust(context(),policy_version=POLICY,evaluated_at=NOW)
    assert d.reason_codes==(RecruitingTrustReasonCode.MEMBERSHIP_NOT_ACTIVE.value,)

@pytest.mark.asyncio
async def test_suspended_recruiter_verification_blocks_trust():
    s=service(); seed(s); s.repo.verifications["r1"]["state"]="suspended"
    d=await s.evaluate_recruiting_actor_trust(context(),policy_version=POLICY,evaluated_at=NOW)
    assert d.reason_codes==(RecruitingTrustReasonCode.RECRUITER_NOT_VERIFIED.value,)

@pytest.mark.asyncio
async def test_cross_company_requires_mandate():
    s=service(); seed(s,requesting="agency",hiring="client")
    d=await s.evaluate_recruiting_actor_trust(context("agency","client"),policy_version=POLICY,evaluated_at=NOW)
    assert d.reason_codes==(RecruitingTrustReasonCode.MANDATE_REQUIRED.value,)

@pytest.mark.asyncio
async def test_cross_company_wrong_mandate_pair_denied():
    s=service(); seed(s,requesting="agency",hiring="client")
    s.repo.mandates["d1"]={"_id":"d1","mandate_id":"d1","requesting_organization_id":"other","hiring_company_id":"client","version":2,"state":"active","valid_from":NOW-timedelta(days=1),"valid_until":NOW+timedelta(days=1),"policy_version":"trust-v1","reason_codes":["mandate_confirmed"],"evidence_refs":["contract"],"actor_id":"admin","decided_at":NOW,"created_at":NOW,"updated_at":NOW}
    d=await s.evaluate_recruiting_actor_trust(context("agency","client","d1"),policy_version=POLICY,evaluated_at=NOW)
    assert d.reason_codes==(RecruitingTrustReasonCode.MANDATE_PARTIES_MISMATCH.value,)

@pytest.mark.asyncio
@pytest.mark.parametrize("patch,reason",[
    ({"state":"suspended"},RecruitingTrustReasonCode.MANDATE_NOT_ACTIVE),
    ({"valid_from":NOW+timedelta(hours=1)},RecruitingTrustReasonCode.MANDATE_NOT_YET_VALID),
    ({"valid_until":NOW},RecruitingTrustReasonCode.MANDATE_EXPIRED),
])
async def test_mandate_current_state_and_time_block_trust(patch,reason):
    s=service(); seed(s,requesting="agency",hiring="client")
    m={"_id":"d1","mandate_id":"d1","requesting_organization_id":"agency","hiring_company_id":"client","version":2,"state":"active","valid_from":NOW-timedelta(days=1),"valid_until":NOW+timedelta(days=1),"policy_version":"trust-v1","reason_codes":["mandate_confirmed"],"evidence_refs":["contract"],"actor_id":"admin","decided_at":NOW,"created_at":NOW,"updated_at":NOW}; m.update(patch); s.repo.mandates["d1"]=m
    d=await s.evaluate_recruiting_actor_trust(context("agency","client","d1"),policy_version=POLICY,evaluated_at=NOW)
    assert d.reason_codes==(reason.value,)

@pytest.mark.asyncio
async def test_cross_company_active_exact_mandate_allows_trust():
    s=service(); seed(s,requesting="agency",hiring="client")
    s.repo.mandates["d1"]={"_id":"d1","mandate_id":"d1","requesting_organization_id":"agency","hiring_company_id":"client","version":2,"state":"active","valid_from":NOW-timedelta(days=1),"valid_until":NOW+timedelta(days=1),"policy_version":"trust-v1","reason_codes":["mandate_confirmed"],"evidence_refs":["contract"],"actor_id":"admin","decided_at":NOW,"created_at":NOW,"updated_at":NOW}
    d=await s.evaluate_recruiting_actor_trust(context("agency","client","d1"),policy_version=POLICY,evaluated_at=NOW)
    assert d.allowed and any(x.startswith("mandate:d1:v2") for x in d.evidence_refs)

@pytest.mark.asyncio
async def test_hiring_company_current_suspension_blocks_trust():
    s=service(); seed(s,requesting="agency",hiring="client"); s.repo.orgs["client"]["verification_state"]="suspended"
    d=await s.evaluate_recruiting_actor_trust(context("agency","client"),policy_version=POLICY,evaluated_at=NOW)
    assert d.reason_codes==(RecruitingTrustReasonCode.HIRING_COMPANY_NOT_VERIFIED.value,)

@pytest.mark.asyncio
async def test_missing_mandate_id_document_is_denied():
    s=service(); seed(s,requesting="agency",hiring="client")
    d=await s.evaluate_recruiting_actor_trust(context("agency","client","missing"),policy_version=POLICY,evaluated_at=NOW)
    assert d.reason_codes==(RecruitingTrustReasonCode.MANDATE_NOT_FOUND.value,)

@pytest.mark.asyncio
async def test_malformed_active_membership_fails_closed():
    s=service(); seed(s); s.repo.memberships["m1"]["evidence_refs"]=[]
    d=await s.evaluate_recruiting_actor_trust(context(),policy_version=POLICY,evaluated_at=NOW)
    assert d.reason_codes==(RecruitingTrustReasonCode.MEMBERSHIP_NOT_ACTIVE.value,)

@pytest.mark.asyncio
async def test_malformed_verified_recruiter_fails_closed():
    s=service(); seed(s); s.repo.verifications["r1"]["evidence_refs"]=[]
    d=await s.evaluate_recruiting_actor_trust(context(),policy_version=POLICY,evaluated_at=NOW)
    assert d.reason_codes==(RecruitingTrustReasonCode.RECRUITER_NOT_VERIFIED.value,)

def test_naive_mandate_dates_refused():
    with pytest.raises(ValueError):
        MandateCreate(MandateId("x"),OrganizationId("a"),HiringCompanyId("b"),datetime(2026,1,1),datetime(2026,1,2),POLICY,"admin")

@pytest.mark.asyncio
async def test_naive_evaluated_at_refused():
    s=service(); seed(s)
    with pytest.raises(ValueError):
        await s.evaluate_recruiting_actor_trust(context(),policy_version=POLICY,evaluated_at=datetime(2026,1,1))

def test_no_permission_or_candidate_domains_imported():
    text=Path(__file__).parents[1].joinpath("domains/trust/recruiting_service.py").read_text()
    assert "PermissionDecision" not in text and "GrantContract" not in text and "Candidate" not in text

def test_migration_declares_required_unique_indexes_and_no_backfill():
    text=Path(__file__).parents[1].joinpath("scripts/migrate_ts_a8_recruiting_trust_indexes.py").read_text()
    for token in ("membership_pair_unique","recruiter_verification_unique","trust_event_version_unique","no owner/company/partner backfill"):
        assert token in text
