"""Shared partner XML feed ingestion. Supports two formats:

1) Joboolo standard (recommended):
   <joboolo><ad><id/><title/><content/><url/><contract/><postcode/><city/><date/></ad></joboolo>
2) Legacy simple:
   <jobs><job><title/><company/><location/><description/><url/><cpc/><job_type/><reference/></job></jobs>

Feed/CPC/billing are provided per campaign (falls back to the partner profile when not given).
"""
import uuid
from datetime import datetime, timedelta

import httpx
from fastapi import HTTPException

VALID_JOB_TYPES = ["CDI", "CDD", "Stage", "Freelance", "Intérim", "Titulaire"]
_CONTRACT_MAP = {
    "cdi": "CDI", "cdd": "CDD", "stage": "Stage", "freelance": "Freelance",
    "interim": "Intérim", "intérim": "Intérim", "titulaire": "Titulaire",
    "intérimaire": "Intérim", "temps plein": "CDI", "temporaire": "Intérim",
}


def _t(node, tag):
    el = node.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return None


def _norm_contract(val):
    if not val:
        return "CDI"
    return _CONTRACT_MAP.get(val.strip().lower(), val.strip() if val.strip() in VALID_JOB_TYPES else "CDI")


def _parse_ads(root):
    """Return a list of normalized job dicts from either supported format."""
    out = []
    # Format 1: <joboolo><ad>
    for node in root.findall(".//ad"):
        title = _t(node, "title")
        if not title:
            continue
        city = _t(node, "city")
        postcode = _t(node, "postcode")
        location = " ".join([p for p in [city, f"({postcode})" if postcode else None] if p]) or "France"
        out.append({
            "title": title,
            "description": _t(node, "content") or "",
            "location": location,
            "url": _t(node, "url"),
            "job_type": _norm_contract(_t(node, "contract")),
            "reference": _t(node, "id") or _t(node, "url") or title,
            "company": _t(node, "company"),
            "cpc_raw": _t(node, "cpc"),
        })
    if out:
        return out
    # Format 2 (legacy): <jobs><job>
    for node in root.findall(".//job"):
        title = _t(node, "title")
        if not title:
            continue
        out.append({
            "title": title,
            "description": _t(node, "description") or "",
            "location": _t(node, "location") or "France",
            "url": _t(node, "url"),
            "job_type": _norm_contract(_t(node, "job_type")),
            "reference": _t(node, "reference") or _t(node, "url") or title,
            "company": _t(node, "company"),
            "cpc_raw": _t(node, "cpc"),
        })
    return out


async def import_feed(db, partner_id, xml_content=None, *, feed_url=None, cpc=None,
                      billing_mode=None, campaign_id=None, validity_days=None):
    import xml.etree.ElementTree as ET

    profile = await db.partner_profiles.find_one({"user_id": partner_id})
    if not profile:
        raise HTTPException(status_code=404, detail="Partenaire introuvable")

    billing_mode = billing_mode or profile.get("billing_mode", "per_click")
    default_cpc = cpc if cpc is not None else profile.get("default_cpc", 0.0)

    if not xml_content:
        src = feed_url or profile.get("xml_feed_url")
        if not src:
            raise HTTPException(status_code=400, detail="Aucun contenu XML ni URL de flux configurée")
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                resp = await client.get(src)
                resp.raise_for_status()
                xml_content = resp.text
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Impossible de récupérer le flux: {e}")

    try:
        root = ET.fromstring(xml_content.strip())
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"XML invalide: {e}")

    ads = _parse_ads(root)
    from geo_service import geocode_place
    postings_remaining = int(profile.get("postings_remaining", 0))
    imported, updated, skipped_budget = 0, 0, 0
    now = datetime.utcnow()

    for ad in ads:
        company_name = ad.get("company") or profile.get("company_name", "Partenaire")
        cpc_val = float(ad["cpc_raw"]) if ad.get("cpc_raw") else float(default_cpc or 0.0)
        reference = ad["reference"]

        company = await db.companies.find_one({"name": company_name, "owner_id": partner_id})
        if not company:
            company_id = f"pcomp_{uuid.uuid4()}"
            await db.companies.insert_one({
                "_id": company_id, "name": company_name, "owner_id": partner_id,
                "location": ad["location"], "industry": None, "size": None, "description": None,
                "created_at": now, "updated_at": now,
            })
        else:
            company_id = company["_id"]

        existing = await db.jobs.find_one({"partner_id": partner_id, "external_ref": reference})
        job_fields = {
            "title": ad["title"], "description": ad["description"], "location": ad["location"],
            "job_type": ad["job_type"], "company_id": company_id, "employer_id": partner_id,
            "partner_id": partner_id, "campaign_id": campaign_id, "is_partner": True,
            "external_url": ad["url"], "external_ref": reference, "cpc": cpc_val,
            "is_remote": False, "is_urgent": False, "requirements": [], "benefits": [], "tags": [],
            "salary_min": None, "salary_max": None, "salary_currency": "EUR", "updated_at": now,
        }
        center = await geocode_place(ad["location"])
        if center:
            job_fields["loc"] = {"type": "Point", "coordinates": center}

        if existing:
            await db.jobs.update_one({"_id": existing["_id"]}, {"$set": job_fields})
            updated += 1
        else:
            if billing_mode == "per_posting":
                if postings_remaining <= 0:
                    skipped_budget += 1
                    continue
                postings_remaining -= 1
            job_fields.update({
                "_id": f"pjob_{uuid.uuid4()}", "is_active": True,
                "views_count": 0, "applications_count": 0, "created_at": now,
            })
            # P0-006 : un job per_posting nouvelle insertion expire
            # validity_days après sa création. Une mise à jour du même
            # external_ref ne renouvelle jamais expires_at (job_fields ne le
            # contient pas). Legacy sans expires_at reste compatible.
            if billing_mode == "per_posting" and validity_days:
                job_fields["expires_at"] = now + timedelta(days=int(validity_days))
            await db.jobs.insert_one(job_fields)
            imported += 1

    inc_spent = 0.0
    if billing_mode == "per_posting":
        consumed = int(profile.get("postings_remaining", 0)) - postings_remaining
        if consumed:
            inc_spent = consumed * float(profile.get("posting_price", 0.0))
            await db.partner_profiles.update_one(
                {"user_id": partner_id},
                {"$set": {"postings_remaining": postings_remaining}, "$inc": {"total_spent": inc_spent}},
            )

    return {
        "imported": imported, "updated": updated,
        "skipped_no_credit": skipped_budget,
        "postings_remaining": postings_remaining if billing_mode == "per_posting" else None,
        "charged": round(inc_spent, 2) if inc_spent else 0,
    }


async def import_campaign_feed(db, campaign, xml_content=None, trigger="manual"):
    """Run a campaign import and record an import_logs entry (start/end/new ads).

    P0-006 fail-closed : une campagne paused/future/expirée/budget épuisé n'est
    PAS diffusible => import refusé (409) sans aucune écriture. C'est le cas
    d'un import manuel ; l'import auto saute en amont dans le scheduler."""
    from campaign_lifecycle import is_campaign_diffusible
    if not is_campaign_diffusible(campaign, datetime.utcnow()):
        raise HTTPException(
            status_code=409,
            detail="La campagne n'est pas effectivement diffusible (paused, future, expirée ou budget épuisé). Import refusé.",
        )
    started = datetime.utcnow()
    log = {
        "_id": f"implog_{uuid.uuid4()}", "campaign_id": campaign["_id"],
        "campaign_name": campaign.get("name"), "partner_id": campaign["partner_id"],
        "started_at": started, "trigger": trigger,
    }
    try:
        result = await import_feed(
            db, campaign["partner_id"], xml_content,
            feed_url=campaign.get("xml_feed_url"), cpc=campaign.get("cpc"),
            billing_mode=campaign.get("billing_mode"), campaign_id=campaign["_id"],
            validity_days=campaign.get("validity_days"),
        )
    except HTTPException as e:
        log.update({"finished_at": datetime.utcnow(), "imported": 0, "updated": 0, "status": "error", "error": str(e.detail)})
        await db.import_logs.insert_one(log)
        raise
    jobs_count = await db.jobs.count_documents({"campaign_id": campaign["_id"], "is_active": True})
    finished = datetime.utcnow()
    await db.campaigns.update_one({"_id": campaign["_id"]}, {"$set": {"jobs_count": jobs_count, "last_import_at": finished}})
    log.update({"finished_at": finished, "imported": result["imported"], "updated": result["updated"], "status": "success"})
    await db.import_logs.insert_one(log)
    return result
