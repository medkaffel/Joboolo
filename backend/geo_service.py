"""Résolution de la hiérarchie géographique française via geo.api.gouv.fr.

Permet de transformer un nom de département ou de région en une liste de codes
de département, afin de faire remonter les offres des villes situées dans ce
périmètre (les offres partenaires stockent la localisation « Ville (codepostal) »).
"""
import logging
import re

import httpx

logger = logging.getLogger(__name__)

GEO_BASE = "https://geo.api.gouv.fr"
_cache: dict = {}


async def resolve_location_codes(query: str) -> list:
    """Renvoie la liste des codes de département correspondant à une recherche.

    - « Loire »  -> ["42"]
    - « Auvergne-Rhône-Alpes » (région) -> tous les codes de ses départements
    - Une ville / code postal quelconque -> [] (la recherche texte suffit)
    """
    q = (query or "").strip()
    if len(q) < 2:
        return []
    key = q.lower()
    if key in _cache:
        return _cache[key]

    codes: list = []
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            # 1) Département par nom (correspondance EXACTE du nom)
            r = await client.get(
                f"{GEO_BASE}/departements",
                params={"nom": q, "fields": "nom,code", "limit": 10},
            )
            deps = r.json() if r.status_code == 200 else []
            for d in deps:
                if (d.get("nom") or "").lower() == key:
                    codes.append(d["code"])

            # 2) Sinon, région par nom (exacte) -> ses départements
            if not codes:
                rr = await client.get(
                    f"{GEO_BASE}/regions",
                    params={"nom": q, "fields": "nom,code", "limit": 10},
                )
                regs = rr.json() if rr.status_code == 200 else []
                region = None
                for rg in regs:
                    if (rg.get("nom") or "").lower() == key:
                        region = rg
                        break
                if region:
                    rd = await client.get(
                        f"{GEO_BASE}/regions/{region['code']}/departements",
                        params={"fields": "code"},
                    )
                    for d in (rd.json() if rd.status_code == 200 else []):
                        codes.append(d["code"])
    except Exception as e:  # réseau indisponible -> on retombe sur la recherche texte
        logger.info(f"[geo] resolve failed for '{q}': {e}")
        codes = []

    codes = list(dict.fromkeys(codes))
    _cache[key] = codes
    return codes


def postcode_regex(code: str) -> str:
    """Regex d'un code postal appartenant à un département donné, tel que stocké
    dans la localisation d'une offre : « Ville (42680) »."""
    if len(code) == 2:
        return r"\(" + code + r"\d{3}\)"
    # Départements d'outre-mer (971, 972, ...) : code postal à 5 chiffres
    return r"\(" + code + r"\d{2}\)"


_geo_cache: dict = {}


async def geocode_place(query: str):
    """Renvoie [lng, lat] du centre d'une commune (par code postal si présent,
    sinon par nom). None si introuvable. France uniquement (geo.api.gouv.fr)."""
    q = (query or "").strip()
    if len(q) < 2:
        return None
    key = q.lower()
    if key in _geo_cache:
        return _geo_cache[key]

    center = None
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            m = re.search(r"\d{5}", q)
            if m:
                r = await client.get(
                    f"{GEO_BASE}/communes",
                    params={"codePostal": m.group(0), "fields": "centre", "limit": 1},
                )
            else:
                city = re.split(r"[,(]", q)[0].strip()
                r = await client.get(
                    f"{GEO_BASE}/communes",
                    params={"nom": city, "fields": "centre", "boost": "population", "limit": 1},
                )
            arr = r.json() if r.status_code == 200 else []
            if arr and arr[0].get("centre", {}).get("coordinates"):
                center = arr[0]["centre"]["coordinates"]  # [lng, lat]
    except Exception as e:
        logger.info(f"[geo] geocode failed for '{q}': {e}")
        center = None

    _geo_cache[key] = center
    return center
