"""P0-006 : source de vérité unique du lifecycle des campagnes partenaires et
de la visibilité publique des offres qui leur sont rattachées.

Règles de diffusibilité d'une campagne (champs réellement stockés) :
- `status` doit être "active" ;
- `start_date` (YYYY-MM-DD) : si renseignée, la campagne n'est pas diffusible
  avant ce jour (UTC) ;
- `end_date` (YYYY-MM-DD) : la journée est ENTIÈREMENT incluse (UTC) ; la
  campagne expire au jour suivant 00:00 UTC, donc n'est plus diffusible dès
  que `now.date() > end_date` ;
- une date `start_date`/`end_date` non vide mais NON parseable (au format
  STRICT `YYYY-MM-DD`) est fail-closed : la campagne n'est jamais rendue
  publique ;
- le budget ne bloque la diffusibilité QUE si `billing_mode == "per_click"` ET
  que `budget_limit` est défini : dès que `spent >= budget_limit` la campagne
  n'est plus diffusible. Un `budget_limit` résiduel sur une campagne
  `per_posting` ne bloque jamais.

Visibilité publique d'une offre :
- `is_active == True` (un champ `is_active` absent ou falsy => jamais
  publique, même règle que le filtre Mongo `{"is_active": True}`) ;
- non expirée : `expires_at` absent OU `None` => jamais expirée ; sinon
  expirée dès `now >= expires_at` (comparaison UTC déterministe, naive traitée
  comme UTC). Un `expires_at` non vide mais non parseable => fail-closed
  (offre jamais rendue publique). Un `expires_at` présent mais vide ou réduit
  à des espaces ("" / "  ") est AUSSI fail-closed : même règle que le filtre
  Mongo (`{"expires_at": {"$gt": now}}` exclut toute valeur non-datetime),
  pour éviter tout cas « visible en détail mais caché en liste » ;
- si l'offre est rattachée à une campagne (`campaign_id`), celle-ci doit être
  effectivement diffusible. Les offres sans `campaign_id` (absent OU `None`,
  ex. legacy) restent visibles tant qu'elles sont actives et non expirées.

Toutes les comparaisons de datetime sont faites en UTC de façon déterministe :
les datetimes naives sont traitées comme UTC, les datetimes aware sont
converties vers UTC.
"""
from datetime import datetime, timezone
from typing import Optional


def _now(now: Optional[datetime] = None) -> datetime:
    """Retourne une datetime UTC normalisée (naive traitée comme UTC)."""
    ts = now if now is not None else datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """Normalise une datetime en UTC aware pour comparaison (naive => UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _as_datetime(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _parse_date(value) -> Optional[datetime]:
    """Parse STRICT d'une date 'YYYY-MM-DD' stockée en chaîne.

    Une valeur non vide différente EXACTEMENT de `YYYY-MM-DD` (format strict,
    vraie date calendrier — ex. `2026-09-01junk`, timestamp, espaces internes,
    ISO datetime) est invalide et retourne None. L'appelant distingue « absent »
    de « invalide » via `_has_nonempty_date` pour fail-closed.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        s = value
        if not s.strip():
            return None
        # STRICT : la chaîne doit être EXACTEMENT YYYY-MM-DD (aucun espace
        # autour, aucun suffixe). Une valeur légèrement différente est invalide.
        try:
            d = datetime.strptime(s, "%Y-%m-%d")
        except (ValueError, TypeError):
            return None
        if d.strftime("%Y-%m-%d") != s:
            return None
        return d
    return None


def _has_nonempty_date(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def is_campaign_diffusible(campaign: Optional[dict], now: Optional[datetime] = None) -> bool:
    """Une campagne est « effectivement diffusible » (règle unique). Fail-closed :
    une date non vide mais invalide ne rend jamais la campagne publique."""
    if not campaign:
        return False
    ts = _now(now)
    today = ts.date()

    if campaign.get("status") != "active":
        return False

    start_raw = campaign.get("start_date")
    if _has_nonempty_date(start_raw):
        start = _parse_date(start_raw)
        if start is None:
            return False  # fail-closed : start_date non vide mais invalide
        if today < start.date():
            return False  # campagne future

    end_raw = campaign.get("end_date")
    if _has_nonempty_date(end_raw):
        end = _parse_date(end_raw)
        if end is None:
            return False  # fail-closed : end_date non vide mais invalide
        if today > end.date():
            return False  # campagne expirée (le jour end_date est inclus)

    # Budget bloquant uniquement en per_click avec un budget_limit défini.
    if campaign.get("billing_mode") == "per_click" and campaign.get("budget_limit") is not None:
        spent = float(campaign.get("spent", 0.0) or 0.0)
        limit = float(campaign.get("budget_limit") or 0.0)
        if spent >= limit:
            return False  # budget épuisé (ou limite nulle)

    return True


def is_job_expired(job: dict, now: Optional[datetime] = None) -> bool:
    """Une offre est expirée dès `now >= expires_at`. Absence, `None` ou une
    chaîne vide/espaces => jamais expirée. Comparaison UTC déterministe
    (naive/aware normalisées).

    NOTE : ce helper n'IMPOSE PAS le fail-closed de visibilité — un
    `expires_at` non vide mais non parseable n'est PAS traité ici comme
    expiré. Le fail-closed (chaîne vide/espaces ET non parseable) est la
    responsabilité de `is_job_publicly_visible` (accès direct) et du filtre
    Mongo `fetch_public_job_filter`, alignés sur une seule règle."""
    exp_raw = job.get("expires_at")
    if exp_raw is None:
        return False
    if isinstance(exp_raw, str) and not exp_raw.strip():
        return False
    exp = _as_datetime(exp_raw)
    if exp is None:
        return False
    return _now(now) >= _as_utc(exp)


def is_job_publicly_visible(job, campaign: Optional[dict] = None,
                            now: Optional[datetime] = None) -> bool:
    """Garde public complet d'une offre pour un accès direct : is_active +
    expiration (fail-closed sur `expires_at` invalide) + campagne diffusible.

    Règle unique alignée sur le filtre Mongo `fetch_public_job_filter` :
    - `is_active` doit être exactement `True` (absent/falsy => non visible) ;
    - `expires_at` absent OU `None` => jamais expirée ; sinon la valeur doit
      être un datetime parseable strictement plus grand que `now`. Toute autre
      valeur (chaîne vide/espaces, non parseable, datetime passé) est
      fail-closed : l'offre n'est jamais visible, en détail comme en liste.

    `campaign` doit être fourni si l'offre a un `campaign_id` : sans campagne
    résolue (ou campagne non diffusible), l'offre rattachée est considérée non
    visible. Les offres sans `campaign_id` (legacy, absent OU `None`) restent
    visibles si actives et non expirées.
    """
    if not job:
        return False
    # Aligné sur le filtre Mongo `{"is_active": True}` : un champ absent ou
    # falsy ne doit jamais être visible en détail alors qu'il le serait caché
    # en liste.
    if not job.get("is_active"):
        return False
    exp_raw = job.get("expires_at")
    if exp_raw is not None:
        # Fail-closed : présent mais vide/espaces OU non parseable => jamais.
        # (Absent OU None => jamais expirée, aucune contrainte ici.)
        if isinstance(exp_raw, str) and not exp_raw.strip():
            return False
        if _as_datetime(exp_raw) is None:
            return False
        if is_job_expired(job, now):
            return False
    cid = job.get("campaign_id")
    if cid:
        if not is_campaign_diffusible(campaign, now):
            return False
    return True


def _plausible_campaigns_filter(now: Optional[datetime] = None) -> dict:
    """Préfiltre Mongo (large, inclusif) vers les campagnes plausibles. La
    sémantique exacte est tranchée ensuite par `is_campaign_diffusible`
    (Python), seule source de vérité. Volontairement minimal pour ne jamais
    exclure une campagne diffusible."""
    return {"status": "active"}


async def fetch_public_job_filter(db, now: Optional[datetime] = None) -> dict:
    """Filtre Mongo « offres publiquement visibles » pour les recherches /
    listes (utilise la même sémantique que `is_job_publicly_visible`).

    On préfiltre les campagnes plausibles (Mongo), on applique
    `is_campaign_diffusible` (Python) pour obtenir l'ensemble EXACT des
    campagnes diffusibles, puis on construit un `$and` combinant :
    - le rattachement : offres liées à une campagne diffusible, OU sans
      campagne du tout (`campaign_id` absent OU `None`, legacy) ;
    - l'expiration (règle unique, fail-closed, alignée sur
      `is_job_publicly_visible`) : `expires_at` absent OU `None` (legacy), OU
      une valeur datetime strictement `> now`. Toute autre valeur est exclue
      par `{"expires_at": {"$gt": now}}` : une datetime passée est barrée, et
      toute valeur non-datetime (chaîne vide/espaces, `null`-like, nombre,
      texte non parseable) est exclue par l'ordre des types BSON. Aucun cas
      « visible en détail mais caché en liste ».

    Le tout est composé via `$and` sans jamais écraser un `$or` existant d'un
    appelant (ex. `search` d'une alerte). `is_active=True` est conservé.
    Les appelants qui ajoutent leurs propres clauses `$and` doivent les
    concaténer au tableau `$and` existant (ne pas l'écraser).
    """
    ts = _now(now)
    camps = await db.campaigns.find(
        _plausible_campaigns_filter(ts),
        {"_id": 1, "status": 1, "start_date": 1, "end_date": 1,
         "billing_mode": 1, "budget_limit": 1, "spent": 1},
    ).to_list(length=100000)
    diffusible_ids = [c["_id"] for c in camps if is_campaign_diffusible(c, ts)]

    campaign_and = {
        "$or": [
            {"campaign_id": {"$in": diffusible_ids}},
            {"campaign_id": {"$exists": False}},
            {"campaign_id": None},
        ]
    }
    expires_and = {
        "$or": [
            {"expires_at": {"$exists": False}},
            {"expires_at": None},
            {"expires_at": {"$gt": ts}},
        ]
    }

    return {
        "is_active": True,
        "$and": [campaign_and, expires_and],
    }


async def get_job_campaign(db, job: dict):
    """Résout la campagne d'une offre si elle y est rattachée (None sinon)."""
    cid = job.get("campaign_id")
    if not cid:
        return None
    return await db.campaigns.find_one({"_id": cid})
