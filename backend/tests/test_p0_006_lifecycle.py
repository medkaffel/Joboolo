"""P0-006 : tests déterministes du lifecycle des campagnes (source de vérité).

Couvre sans Mongo (fonctions pures) :
- bornes de dates (start_date, end_date inclusive jour UTC) ;
- expiration exacte (now >= expires_at) ;
- budget per_click vs per_posting ;
- garde public (is_active + expiration + campagne diffusible) ;
- legacy sans campaign_id / sans expires_at ;
- génération du filtre Mongo réutilisant exactement la même sémantique.

Ces tests ne dépendent d'aucun service externe et sont donc déterministes.
"""
import asyncio
from datetime import datetime, timedelta

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
    return datetime.utcnow().date().isoformat()


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
    yesterday = (datetime.utcnow() - timedelta(days=1)).date().isoformat()
    assert is_campaign_diffusible(_camp(end_date=yesterday)) is False


def test_end_date_today_still_diffusible_inclusive():
    # Le jour end_date est ENTIÈREMENT inclus (UTC) ; il expire au jour suivant
    # 00:00 UTC. Donc end_date = aujourd'hui => toujours diffusible aujourd'hui.
    assert is_campaign_diffusible(_camp(end_date=_today_iso())) is True


def test_end_date_invalid_ignored():
    # Une date invalide ne doit jamais bloquer la campagne par erreur.
    assert is_campaign_diffusible(_camp(end_date="pas-une-date")) is True
    assert is_campaign_diffusible(_camp(start_date="pas-une-date")) is True


def test_parse_date_handles_iso_stored():
    assert _parse_date("2026-09-01").date().isoformat() == "2026-09-01"
    assert _parse_date("2026-09-01T10:00:00") is not None
    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("garbage") is None
    assert _parse_date(12345) is None


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
    now = datetime.utcnow()
    assert is_job_expired({"expires_at": now - timedelta(seconds=1)}, now) is True
    assert is_job_expired({"expires_at": now + timedelta(seconds=1)}, now) is False
    assert is_job_expired({"expires_at": now}, now) is True  # now >= expires_at


def test_no_expires_at_never_expired():
    assert is_job_expired({}) is False
    assert is_job_expired({"expires_at": None}) is False


def test_expires_at_string_boundary():
    future = (datetime.utcnow() + timedelta(days=365)).isoformat()
    past = (datetime.utcnow() - timedelta(days=365)).isoformat()
    assert is_job_expired({"expires_at": future}) is False
    assert is_job_expired({"expires_at": past}) is True


# --------------------------------------------------------------------------- #
# Garde public                                                                #
# --------------------------------------------------------------------------- #
def _job(**kw):
    d = {"_id": "j1", "is_active": True}
    d.update(kw)
    return d


def test_legacy_job_no_campaign_visible_when_active():
    assert is_job_publicly_visible(_job(), None) is True


def test_inactive_job_not_visible():
    assert is_job_publicly_visible(_job(is_active=False), None) is False


def test_expired_job_not_visible():
    assert is_job_publicly_visible(
        _job(expires_at="2000-01-01T00:00:00"), None) is False


def test_not_yet_expired_job_visible():
    assert is_job_publicly_visible(
        _job(expires_at="2999-01-01T00:00:00"), None) is True


def test_campaign_job_needs_diffusible_campaign():
    assert is_job_publicly_visible(_job(campaign_id="c1"),
                                   _camp(status="paused")) is False
    assert is_job_publicly_visible(_job(campaign_id="c1"), _camp()) is True


def test_campaign_job_without_resolved_campaign_not_visible():
    # Une offre rattachée à une campagne, sans campagne résolue => non visible.
    assert is_job_publicly_visible(_job(campaign_id="c1"), None) is False


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
    now = datetime.utcnow()
    today = _today_iso()
    pf = _plausible_campaigns_filter(now)
    assert pf["status"] == "active"


def test_fetch_public_filter_includes_only_diffusible_campaigns():
    now = datetime.utcnow()
    docs = [
        # diffusible
        {"_id": "ok1", "status": "active", "start_date": None, "end_date": None,
         "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
        # paused -> non diffusible
        {"_id": "paused", "status": "paused", "start_date": None, "end_date": None,
         "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
        # future -> non diffusible
        {"_id": "future", "status": "active", "start_date": "2099-01-01",
         "end_date": None, "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
        # expired -> non diffusible
        {"_id": "expired", "status": "active", "start_date": None,
         "end_date": "2000-01-01", "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
        # budget exhausted per_click -> non diffusible
        {"_id": "budget", "status": "active", "start_date": None, "end_date": None,
         "billing_mode": "per_click", "budget_limit": 10.0, "spent": 10.0},
        # per_posting with residual budget_limit -> DIFFUSIBLE
        {"_id": "posting", "status": "active", "start_date": None, "end_date": None,
         "billing_mode": "per_posting", "budget_limit": 10.0, "spent": 10.0},
    ]
    db = _DB(docs)
    filt = asyncio.get_event_loop().run_until_complete(fetch_public_job_filter(db, now))

    assert filt["is_active"] is True
    assert "expires_at" in filt
    # $or : campagne diffusible OU pas de campagne du tout
    or_ = filt["$or"]
    in_camp = [o for o in or_ if "campaign_id" in o and "$in" in o["campaign_id"]][0]
    assert set(in_camp["campaign_id"]["$in"]) == {"ok1", "posting"}
    assert "paused" not in in_camp["campaign_id"]["$in"]
    assert "future" not in in_camp["campaign_id"]["$in"]
    assert "expired" not in in_camp["campaign_id"]["$in"]
    assert "budget" not in in_camp["campaign_id"]["$in"]


def test_fetch_public_filter_end_date_inclusive_today():
    now = datetime.utcnow()
    today = _today_iso()
    docs = [
        {"_id": "ending-today", "status": "active", "start_date": None,
         "end_date": today, "billing_mode": "per_click", "budget_limit": None, "spent": 0.0},
    ]
    db = _DB(docs)
    filt = asyncio.get_event_loop().run_until_complete(fetch_public_job_filter(db, now))
    in_camp = [o for o in filt["$or"] if "$in" in o.get("campaign_id", {})][0]
    assert "ending-today" in in_camp["campaign_id"]["$in"]
