"""P0-006 : tests déterministes du lifecycle des campagnes (source de vérité).

Couvre sans Mongo (fonctions pures de `campaign_lifecycle`) :
- bornes de dates (start_date, end_date inclusive jour UTC) ;
- fail-closed sur une date non vide mais invalide (format STRICT YYYY-MM-DD,
  pas de `s[:10]`) ;
- expiration exacte (now >= expires_at) et comparaisons naive/aware UTC ;
- expires_at absent OU None => jamais expiré / toujours visible ;
- budget per_click vs per_posting (per_posting jamais bloqué par budget) ;
- garde public (is_active + expiration + campagne diffusible) ;
- legacy sans campaign_id (absent OU None) ;
- génération du filtre Mongo réutilisant exactement la même sémantique.

Ces tests ne dépendent d'aucun service externe et sont donc déterministes.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from campaign_lifecycle import (
    is_campaign_diffusible,
    is_job_expired,
    is_job_publicly_visible,
    _parse_date,
    _plausible_campaigns_filter,
    fetch_public_job_filter,
)


def _camp(**kw):
    d = {"_id": "c1", "status": "active", "billing_mode": "per_click",
         "spent": 0.0, "budget_limit": None}
    d.update(kw)
    return d


def _today_iso():
    return datetime.now(timezone.utc).date().isoformat()


# --------------------------------------------------------------------------- #
# Diffusibilité — statut                                                      #
# --------------------------------------------------------------------------- #
def test_active_campaign_diffusible():
    assert is_campaign_diffusible(_camp()) is True


def test_paused_campaign_not_diffusible():
    assert is_campaign_diffusible(_camp(status="paused")) is False


def test_missing_campaign_not_diffusible():
    assert is_campaign_diffusible(None) is False


# --------------------------------------------------------------------------- #
# Diffusibilité — dates                                                       #
# --------------------------------------------------------------------------- #
def test_future_start_date_not_diffusible():
    assert is_campaign_diffusible(_camp(start_date="2099-01-01")) is False


def test_start_date_today_diffusible():
    assert is_campaign_diffusible(_camp(start_date=_today_iso())) is True


def test_end_date_yesterday_not_diffusible():
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
    assert is_campaign_diffusible(_camp(end_date=yesterday)) is False


def test_end_date_today_still_diffusible_inclusive():
    # Le jour end_date est ENTIÈREMENT inclus (UTC) ; il expire au jour suivant
    # 00:00 UTC. Donc end_date = aujourd'hui => toujours diffusible aujourd'hui.
    assert is_campaign_diffusible(_camp(end_date=_today_iso())) is True


def test_nonempty_invalid_dates_fail_closed():
    # FAIL-CLOSED : une date non vide mais non parseable ne doit jamais rendre
    # la campagne publique (ni start ni end).
    assert is_campaign_diffusible(_camp(start_date="pas-une-date")) is False
    assert is_campaign_diffusible(_camp(end_date="pas-une-date")) is False
    assert is_campaign_diffusible(_camp(start_date="2026/13/40")) is False
    assert is_campaign_diffusible(_camp(end_date="2026-02-30")) is False


def test_empty_or_none_dates_no_constraint():
    # Une date vide / absente n'impose aucune contrainte.
    assert is_campaign_diffusible(_camp(start_date=None, end_date=None)) is True
    assert is_campaign_diffusible(_camp(start_date="", end_date="")) is True


# --------------------------------------------------------------------------- #
# _parse_date STRICT — pas de `s[:10]`                                        #
# --------------------------------------------------------------------------- #
def test_parse_date_strict_accepts_only_full_yyyy_mm_dd():
    assert _parse_date("2026-09-01").date().isoformat() == "2026-09-01"
    assert _parse_date(None) is None
    assert _parse_date("") is None


def test_parse_date_strict_rejects_non_exact_values():
    # Toute valeur non vide différente EXACTEMENT de YYYY-MM-DD est invalide.
    for bad in ("2026-09-01junk", "2026-09-01T10:00:00", "2026-09-01 ",
                "2026-09-01 09:00", "2026-09 01", "01/09/2026",
                "2026-1-1", "2026-13-01", "2026-02-30", "20260101",
                " 2026-09-01", "2026-09-01\n", "pas-une-date", 12345, 0):
        assert _parse_date(bad) is None, bad


# --------------------------------------------------------------------------- #
# Diffusibilité — budget                                                      #
# --------------------------------------------------------------------------- #
def test_per_click_budget_exhausted_not_diffusible():
    assert is_campaign_diffusible(_camp(billing_mode="per_click",
                                        budget_limit=10.0, spent=10.0)) is False


def test_per_click_budget_under_limit_diffusible():
    assert is_campaign_diffusible(_camp(billing_mode="per_click",
                                        budget_limit=10.0, spent=9.9)) is True


def test_per_posting_budget_limit_never_blocks():
    # Un budget_limit résiduel sur une campagne per_posting ne doit JAMAIS
    # bloquer la diffusibilité.
    assert is_campaign_diffusible(_camp(billing_mode="per_posting",
                                        budget_limit=10.0, spent=10.0)) is True


def test_per_click_budget_zero_limit_blocks():
    # budget_limit = 0 => dès que spent >= 0 => épuisé.
    assert is_campaign_diffusible(_camp(billing_mode="per_click",
                                        budget_limit=0.0, spent=0.0)) is False


def test_no_budget_limit_no_block():
    assert is_campaign_diffusible(_camp(billing_mode="per_click",
                                        budget_limit=None, spent=100.0)) is True


# --------------------------------------------------------------------------- #
# Expiration d'une offre                                                      #
# --------------------------------------------------------------------------- #
def test_expires_at_exact_boundary():
    now = datetime.now(timezone.utc)
    assert is_job_expired({"expires_at": now - timedelta(seconds=1)}, now) is True
    assert is_job_expired({"expires_at": now + timedelta(seconds=1)}, now) is False
    assert is_job_expired({"expires_at": now}, now) is True  # now >= expires_at


def test_no_expires_at_never_expired():
    assert is_job_expired({}) is False
    assert is_job_expired({"expires_at": None}) is False
    assert is_job_expired({"expires_at": ""}) is False


def test_expires_at_string_boundary():
    future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    assert is_job_expired({"expires_at": future}) is False
    assert is_job_expired({"expires_at": past}) is True


def test_expires_at_naive_vs_aware_comparison():
    # Une expires_at naive est traitée comme UTC ; pas de comparaison naive/aware.
    naive_now = datetime.utcnow()
    aware_now = naive_now.replace(tzinfo=timezone.utc)
    # expires_at naive = maintenant - 1s => expiré
    assert is_job_expired({"expires_at": naive_now - timedelta(seconds=1)}) is True
    # expires_at naive = maintenant + 1s => non expiré
    assert is_job_expired({"expires_at": naive_now + timedelta(seconds=1)}) is False
    # expires_at aware identique point temporel => même résultat
    assert is_job_expired({"expires_at": aware_now + timedelta(seconds=1)}) is False


# --------------------------------------------------------------------------- #
# Garde public (accès direct — fail-closed sur expires_at invalide)           #
# --------------------------------------------------------------------------- #
def _job(**kw):
    d = {"_id": "j1", "is_active": True}
    d.update(kw)
    return d


def test_legacy_job_no_campaign_visible_when_active():
    assert is_job_publicly_visible(_job(), None) is True


def test_job_with_campaign_id_none_visible():
    # campaign_id absent OU None : legacy / job non partenaire préservé.
    assert is_job_publicly_visible(_job(campaign_id=None), None) is True


def test_inactive_job_not_visible():
    assert is_job_publicly_visible(_job(is_active=False), None) is False


def test_expired_job_not_visible():
    assert is_job_publicly_visible(
        _job(expires_at="2000-01-01T00:00:00"), None) is False


def test_not_yet_expired_job_visible():
    assert is_job_publicly_visible(
        _job(expires_at="2999-01-01T00:00:00"), None) is True


def test_expires_at_none_visible():
    # Régression : expires_at=None (legacy) => offre toujours visible tant que
    # active et non expirée.
    assert is_job_publicly_visible(_job(expires_at=None), None) is True


def test_expires_at_unparseable_fail_closed():
    # FAIL-CLOSED : expires_at non vide mais non parseable => offre non visible.
    assert is_job_publicly_visible(_job(expires_at="garbage"), None) is False
    assert is_job_publicly_visible(_job(expires_at="2026-09-01junk"), None) is False
    assert is_job_publicly_visible(_job(expires_at=123456), None) is False


def test_campaign_job_needs_diffusible_campaign():
    assert is_job_publicly_visible(_job(campaign_id="c1"),
                                   _camp(status="paused")) is False
    assert is_job_publicly_visible(_job(campaign_id="c1"), _camp()) is True


def test_campaign_job_without_resolved_campaign_not_visible():
    # Une offre rattachée à une campagne, sans campagne résolue => non visible.
    assert is_job_publicly_visible(_job(campaign_id="c1"), None) is False


def test_campaign_job_with_budget_exhausted_campaign_not_visible():
    assert is_job_publicly_visible(
        _job(campaign_id="c1"),
        _camp(billing_mode="per_click", budget_limit=10.0, spent=10.0)) is False


# --------------------------------------------------------------------------- #
# Filtre Mongo — réutilise exactement la même sémantique                      #
# --------------------------------------------------------------------------- #
class _Campaigns:
    def __init__(self, docs):
        self._docs = docs

    def find(self, query, projection=None):
        class _Curs:
            def __init__(self, docs):
                self._docs = docs

            async def to_list(self, length):
                return self._docs
        return _Curs(self._docs)


class _DB:
    def __init__(self, campaigns_docs):
        self.campaigns = _Campaigns(campaigns_docs)


def test_plausible_filter_reuses_semantics():
    now = datetime.now(timezone.utc)
    pf = _plausible_campaigns_filter(now)
    assert pf["status"] == "active"


def _campaign_branches(filt):
    """Le $and du filtre public contient la clause campagne et la clause
    expiration. Retourne (branches_campagne, branches_expiration)."""
    assert "$and" in filt
    conds = filt["$and"]
    assert len(conds) == 2
    camp_or, exp_or = conds
    assert "$or" in camp_or and "$or" in exp_or
    return camp_or["$or"], exp_or["$or"]


def _in_campaign_ids(filt):
    camp_branches, _ = _campaign_branches(filt)
    in_camp = [o for o in camp_branches if isinstance(o, dict)
               and isinstance(o.get("campaign_id"), dict)
               and "$in" in o["campaign_id"]]
    assert in_camp, "missing campaign_id $in branch in $or"
    return set(in_camp[0]["campaign_id"]["$in"])


def test_fetch_public_filter_includes_only_diffusible_campaigns():
    now = datetime.now(timezone.utc)
    docs = [
        {"_id": "ok1", "status": "active", "start_date": None, "end_date": None,
         "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
        {"_id": "paused", "status": "paused", "start_date": None, "end_date": None,
         "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
        {"_id": "future", "status": "active", "start_date": "2099-01-01",
         "end_date": None, "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
        {"_id": "expired", "status": "active", "start_date": None,
         "end_date": "2000-01-01", "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
        {"_id": "budget", "status": "active", "start_date": None, "end_date": None,
         "billing_mode": "per_click", "budget_limit": 10.0, "spent": 10.0},
        {"_id": "posting", "status": "active", "start_date": None, "end_date": None,
         "billing_mode": "per_posting", "budget_limit": 10.0, "spent": 10.0},
        {"_id": "invdate", "status": "active", "start_date": "xxxxx", "end_date": None,
         "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
    ]
    db = _DB(docs)
    filt = asyncio.run(fetch_public_job_filter(db, now))

    assert filt["is_active"] is True
    ids = _in_campaign_ids(filt)
    assert ids == {"ok1", "posting"}
    assert "paused" not in ids
    assert "future" not in ids
    assert "expired" not in ids
    assert "budget" not in ids
    assert "invdate" not in ids


def test_fetch_public_filter_preserves_legacy_and_none_campaign():
    # Le filtre public doit préserver les offres sans campagne : campaign_id
    # absent OU None, en plus des offres rattachées à des campagnes diffusibles.
    now = datetime.now(timezone.utc)
    docs = [
        {"_id": "activec", "status": "active", "start_date": None, "end_date": None,
         "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
    ]
    db = _DB(docs)
    filt = asyncio.run(fetch_public_job_filter(db, now))
    camp_branches, _ = _campaign_branches(filt)
    branches = set()
    for o in camp_branches:
        if isinstance(o, dict) and "campaign_id" in o:
            cid = o["campaign_id"]
            if isinstance(cid, dict) and "$in" in cid:
                branches.add("in")
            if isinstance(cid, dict) and "$exists" in cid:
                branches.add("exists")
            if cid is None:
                branches.add("none")
    assert "in" in branches
    assert "exists" in branches
    assert "none" in branches


def test_fetch_public_filter_preserves_expires_at_absent_none_and_future():
    # L'expiration doit préserver explicitement (absent OU None) et n'autoriser
    # un expires_at présent que s'il est > now.
    now = datetime.now(timezone.utc)
    docs = [{"_id": "ok1", "status": "active", "start_date": None, "end_date": None,
             "billing_mode": "per_click", "budget_limit": None, "spent": 0.0}]
    db = _DB(docs)
    filt = asyncio.run(fetch_public_job_filter(db, now))
    _, exp_branches = _campaign_branches(filt)
    keys = []
    for o in exp_branches:
        if isinstance(o, dict) and "expires_at" in o:
            v = o["expires_at"]
            if v is None:
                keys.append("none")
            elif isinstance(v, dict) and "$exists" in v:
                keys.append("absent")
            elif isinstance(v, dict) and "$gt" in v:
                keys.append("future")
    assert "absent" in keys
    assert "none" in keys
    assert "future" in keys


def test_fetch_public_filter_end_date_inclusive_today():
    now = datetime.now(timezone.utc)
    today = _today_iso()
    docs = [
        {"_id": "ending-today", "status": "active", "start_date": None,
         "end_date": today, "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
    ]
    db = _DB(docs)
    filt = asyncio.run(fetch_public_job_filter(db, now))
    assert "ending-today" in _in_campaign_ids(filt)


def test_fetch_public_filter_composes_without_clobbering_or():
    # Le filtre public expose ses clauses via $and, ce qui permet aux appelants
    # (recherche / alertes) d'ajouter leurs propres clauses sans écraser le $or
    # de visibilité de campagne.
    now = datetime.now(timezone.utc)
    docs = [{"_id": "ok1", "status": "active", "start_date": None, "end_date": None,
             "billing_mode": "per_click", "budget_limit": None, "spent": 0.0}]
    db = _DB(docs)
    filt = asyncio.run(fetch_public_job_filter(db, now))
    assert filt["is_active"] is True
    assert isinstance(filt["$and"], list) and len(filt["$and"]) == 2
