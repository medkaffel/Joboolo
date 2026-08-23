"""Détection géographique simplifiée par IP (pré-remplissage « Où » + cookie pays)."""
from fastapi import APIRouter, Request
import httpx

router = APIRouter(prefix="/geo", tags=["geo"])

_PRIVATE_PREFIXES = ("10.", "192.168.", "127.", "172.16.", "172.17.", "172.18.",
                     "172.19.", "172.2", "172.30.", "172.31.", "::1")


def _client_ip(request: Request):
    xff = request.headers.get("x-forwarded-for", "")
    for part in xff.split(","):
        p = part.strip()
        if p and not p.startswith(_PRIVATE_PREFIXES):
            return p
    return None


@router.get("/detect")
async def detect(request: Request):
    ip = _client_ip(request)
    url = f"http://ip-api.com/json/{ip or ''}"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url, params={"fields": "status,country,countryCode,regionName,city"})
            d = r.json()
            if d.get("status") == "success":
                return {
                    "country": d.get("country"),
                    "country_code": d.get("countryCode"),
                    "region": d.get("regionName"),
                    "city": d.get("city"),
                }
    except Exception:
        pass
    return {"country": None, "country_code": None, "region": None, "city": None}


GEO_BASE = "https://geo.api.gouv.fr"


@router.get("/autocomplete")
async def autocomplete(q: str = ""):
    """Autocomplétion de localisation basée sur les villes, départements et régions
    de France (geo.api.gouv.fr) — indépendamment du contenu de la base."""
    q = (q or "").strip()
    if len(q) < 2:
        return {"suggestions": []}
    out = []
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            # Régions
            rr = await client.get(f"{GEO_BASE}/regions", params={"nom": q, "fields": "nom", "limit": 3})
            for r in (rr.json() if rr.status_code == 200 else []):
                out.append({"value": r["nom"], "label": f"{r['nom']} · Région", "type": "region"})
            # Départements
            rd = await client.get(f"{GEO_BASE}/departements", params={"nom": q, "fields": "nom,code", "limit": 5})
            for d in (rd.json() if rd.status_code == 200 else []):
                out.append({"value": d["nom"], "label": f"{d['nom']} ({d['code']}) · Département", "type": "departement"})
            # Villes (communes) triées par population
            rc = await client.get(f"{GEO_BASE}/communes", params={"nom": q, "fields": "nom,codesPostaux", "boost": "population", "limit": 7})
            for c in (rc.json() if rc.status_code == 200 else []):
                cp = (c.get("codesPostaux") or [None])[0]
                label = f"{c['nom']}" + (f" ({cp})" if cp else "")
                out.append({"value": c["nom"], "label": label, "type": "commune"})
    except Exception:
        out = []
    return {"suggestions": out}
