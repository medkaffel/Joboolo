"""P0-006 : source de vérité unique du lifecycle des campagnes partenaires et
de la visibilité publique des offres qui leur sont rattachées.

Règles de diffusibilité d'une campagne (champs réellement stockés) :
- `status` doit être "active" ;
- si `start_date` (YYYY-MM-DD) est défini, la campagne n'est pas diffusible
  avant ce jour (UTC) ;
- si `end_date` (YYYY-MM-DD) est défini, la journée est entièrement incluse :
  la campagne expire au jour suivant 00:00 UTC, donc n'est plus diffusible dès
  que `now.date() > end_date` ;
- le budget ne bloque la diffusibilité que si `billing_mode == "per_click"`
  ET que `budget_limit` est défini : dès que `spent >= budget_limit` la
  campagne n'est plus diffusible. Un `budget_limit` résiduel sur une campagne
  `per_posting` ne bloque jamais.

Visibilité publique d'une offre :
- `is_active == True` ;
- non expirée (`expires_at` absent => jamais expirée ; sinon expirée dès
  `now >= expires_at`) ;
- si l'offre est rattachée à une campagne (`campaign_id`), celle-ci doit être
  effectivement diffusible. Les offres sans `campaign_id` (legacy) restent
  visibles tant qu'elles sont actives et non expirées.
"""
from datetime import datetime
from typing import Optional


def _parse_date(value) -> Optional[datetime]:
    """Parse une date 'YYYY-MM-DD' stockée en chaîne. Retourne None si absente
    ou invalide (une date invalide ne doit jamais rendre une campagne
    bloquée par erreur : le champ est simplement ignoré)."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip()[:10], "%Y-%m-%d")
        except (ValueError, TypeError):
            return None
    return None


def is_campaign_diffusible(campaign: Optional[dict], now: Optional[datetime] = None) -> bool:
    """Une campagne est « effectivement diffusible » (règle unique)."""
    if not campaign:
        return False
    ts = now or datetime.utcnow()
    today = ts.date()

    if campaign.get("status") != "active":
        return False

    start = _parse_date(campaign.get("start_date"))
    if start is not None and today < start.date():
        return False  # campagne future

    end = _parse_date(campaign.get("end_date"))
    if end is not None and today > end.date():
        return False  # campagne expirée (le jour end_date est inclus)

    # Budget bloquant uniquement en per_click avec un budget_limit défini.
    if campaign.get("billing_mode") == "per_click" and campaign.get("budget_limit") is not None:
        spent = float(campaign.get("spent", 0.0) or 0.0)
        limit = float(campaign.get("budget_limit") or 0.0)
        if spent >= limit:
            return False  # budget épuisé (ou limite nulle)

    return True


def _as_datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def is_job_expired(job: dict, now: Optional[datetime] = None) -> bool:
    """Une offre est expirée dès `now >= expires_at`. Absence => jamais expirée."""
    exp_raw = job.get("expires_at")
    if not exp_raw:
        return False
    exp = _as_datetime(exp_raw)
    if exp is None:
        return False
    return (now or datetime.utcnow()) >= exp


def is_job_publicly_visible(job: dict, campaign: Optional[dict] = None,
                            now: Optional[datetime] = None) -> bool:
    """Garde public complet d'une offre : is_active + expiration + campagne
    diffusible. `campaign` doit être fourni si l'offre a un `campaign_id` :
    sans campagne résolue, l'offre rattachée est considérée non visible."""
    if not job:
        return False
    if not job.get("is_active", True):
        return False
    if is_job_expired(job, now):
        return False
    cid = job.get("campaign_id")
    if cid:
        if not is_campaign_diffusible(campaign, now):
            return False
    return True


def _plausible_campaigns_filter(now: Optional[datetime] = None):
    """Préfiltre Mongo (large) vers les campagnes plausiblement diffusibles.
    La sémantique exacte est ensuite tranchée par `is_campaign_diffusible`
    (Python), qui reste la seule source de vérité."""
    ts = now or datetime.utcnow()
    today_iso = ts.date().isoformat()
    return {
        "status": "active",
        "$or": [
            {"start_date": {"$exists": False}},
            {"start_date": {"$in": [None, ""]}},
            {"start_date": {"$lte": today_iso}},
        ],
        "$and": [
            {"$or": [
                {"end_date": {"$exists": False}},
                {"end_date": {"$in": [None, ""]}},
                {"end_date": {"$gte": today_iso}},
            ]},
        ],
    }


async def fetch_public_job_filter(db, now: Optional[datetime] = None) -> dict:
    """Filtre Mongo « offres publiquement visibles », réutilisant exactement la
    même sémantique que `is_job_publicly_visible`.

    Stratégie : on préfiltre les campagnes plausiblement diffusibles (Mongo,
    approximation date/statut), on applique `is_campaign_diffusible` (Python)
    pour obtenir l'ensemble EXACT des campagnes diffusibles, puis on construit
    le filtre sur les offres : actives + non expirées + (campagne diffusible
    OU pas de campagne du tout).
    """
    ts = now or datetime.utcnow()
    camps = await db.campaigns.find(
        _plausible_campaigns_filter(ts),
        {"_id": 1, "status": 1, "start_date": 1, "end_date": 1,
         "billing_mode": 1, "budget_limit": 1, "spent": 1},
    ).to_list(length=100000)
    diffusible_ids = [c["_id"] for c in camps if is_campaign_diffusible(c, ts)]

    return {
        "is_active": True,
        "expires_at": {"$not": {"$lte": ts}},
        "$or": [
            {"campaign_id": {"$in": diffusible_ids}},
            {"campaign_id": {"$exists": False}},
        ],
    }


async def get_job_campaign(db, job: dict):
    """Résout la campagne d'une offre si elle y est rattachée (None sinon)."""
    cid = job.get("campaign_id")
    if not cid:
        return None
    return await db.campaigns.find_one({"_id": cid})
