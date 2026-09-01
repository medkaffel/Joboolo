"""Shared partner XML feed ingestion. Supports two formats:

1) Joboolo standard (recommended):
   <joboolo><ad><id/><title/><content/><url/><contract/><postcode/><city/><date/></ad></joboolo>
2) Legacy simple:
   <jobs><job><title/><company/><location/><description/><url/><cpc/><job_type/><reference/></job></jobs>

Feed/CPC/billing are provided per campaign (falls back to the partner profile when not given).

P0-007 — Identité métier des offres de feed :
- Pour une offre provenant d'une campagne, l'identité est le triplet STRICT
  `(partner_id, campaign_id, external_ref)` (campaign_id = string non vide).
- Pour un import legacy (sans campagne), l'identité est `(partner_id,
  external_ref)` avec `campaign_id: None` (matche `null` ET absent en Mongo).
- Les deux branches ne se croisent JAMAIS : aucun `$or` identité, un import de
  campagne ne réclame jamais un job legacy et réciproquement.
- Un réimport de la même campagne/référence met à jour le MÊME job ; le
  campaign_id n'est jamais « déplacé » d'une campagne vers une autre.
- `expires_at` n'est posé qu'à l'insertion (jamais renouvelé à l'update).
- Déploiement sûr : les créations de jobs de campagne sont fail-closed (503)
  tant que le marqueur `p0007_identity_indexes` n'est pas posé par la migration
  explicite `scripts/migrate_p0007_identity_indexes.py` (aucune fenêtre de
  doublons concurrents sans l'index unique).
- `per_posting` campagne : insertion + débit atomiques dans une transaction
  Mongo (`session.with_transaction`, retries transitoires incluses). Le loser
  concurrent ne débite ni ne rembourse et ne touche jamais `expires_at`.
  Le `per_posting` legacy (hors-scope concurrence P0-007) conserve son
  comportement P0-006 (débit local + écriture différée).
"""
import uuid
from datetime import datetime, timedelta

import httpx
from fastapi import HTTPException
from pymongo.errors import DuplicateKeyError

VALID_JOB_TYPES = ["CDI", "CDD", "Stage", "Freelance", "Intérim", "Titulaire"]
_CONTRACT_MAP = {
    "cdi": "CDI", "cdd": "CDD", "stage": "Stage", "freelance": "Freelance",
    "interim": "Intérim", "intérim": "Intérim", "titulaire": "Titulaire",
    "intérimaire": "Intérim", "temps plein": "CDI", "temporaire": "Intérim",
}

# Marqueur de déploiement posé par la migration explicite P0-007.
P0007_MARKER = "p0007_identity_indexes"


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


def _job_identity(partner_id, campaign_id, reference):
    """Identité métier P0-007 d'une offre de feed.

    Campagne : triplet STRICT `(partner_id, campaign_id, external_ref)` quand
    `campaign_id` est une string non vide. Legacy : `(partner_id, external_ref,
    campaign_id: None)` (matche `null` ET absent en Mongo). Les deux branches
    ne se croisent jamais.
    """
    identity = {"partner_id": partner_id, "external_ref": reference}
    if isinstance(campaign_id, str) and campaign_id:
        identity["campaign_id"] = campaign_id
    else:
        identity["campaign_id"] = None
    return identity


class _NoCredit(Exception):
    """Signal interne : aucun posting per_posting disponible (transaction
    abortée ; aucun débit, aucune insertion)."""


class _UnsupportedTransactions(Exception):
    """Signal interne : la topologie Mongo ne supporte pas les transactions
    (replica set requis). Fail-closed : aucun débit ni insertion."""


def _is_unsupported_transaction(exc: Exception) -> bool:
    """Détecte une erreur Mongo signalant que les transactions (replica set)
    ne sont pas supportées par la topologie runtime, pour fail-closed 503
    (aligné sur P0-005)."""
    text = str(exc)
    lowered = text.lower()
    markers = (
        "replica set",
        "replicaset",
        "transaction numbers",
        "do not support transactions",
        "not supported on standalone",
        "standalone",
        "no such command: 'committransaction'",
        "session support",
        "mongos",
    )
    return any(m in lowered for m in markers)


async def _insert_per_posting_campaign(db, client, partner_id, identity, job_doc,
                                       update_fields, posting_price):
    """Insère un job de campagne `per_posting` en transaction avec son débit.

    Invariants P0-007 :
    - l'insertion du job et `$inc postings_remaining:-1` +
      `$inc total_spent:+posting_price` sont atomiques (même transaction) ;
    - si aucun crédit (`postings_remaining < 1`) -> rollback complet ;
    - le loser concurrent ne débite ni ne rembourse jamais ; `expires_at` n'est
      jamais modifié hors insertion (update_fields ne le contient pas) ;
    - retries transitoires via `session.with_transaction`.

    Retourne : "inserted" (ce job a été créé et PAYÉ par cet appel),
    "updated" (un concurrent a déjà créé la même identité : simple refresh) ou
    "no_credit" (réel manque de crédit, job inexistant). Lève
    `_UnsupportedTransactions` si la topologie ne supporte pas les transactions.
    """
    if client is None:
        raise _UnsupportedTransactions("client Mongo indisponible")

    async def _tx(session):
        existing = await db.jobs.find_one(identity, session=session)
        if existing:
            await db.jobs.update_one({"_id": existing["_id"]}, {"$set": update_fields}, session=session)
            return "updated"
        debit = await db.partner_profiles.update_one(
            {"user_id": partner_id, "postings_remaining": {"$gte": 1}},
            {"$inc": {"postings_remaining": -1, "total_spent": posting_price}},
            session=session,
        )
        if debit.modified_count == 0:
            raise _NoCredit()
        await db.jobs.insert_one(job_doc, session=session)
        return "inserted"

    try:
        async with await client.start_session() as session:
            return await session.with_transaction(_tx)
    except _NoCredit:
        return "no_credit"
    except Exception as exc:
        if _is_unsupported_transaction(exc):
            raise _UnsupportedTransactions() from exc
        # Échec non reclassable (ex. write conflict non résolu après retries).
        # La transaction a été abortée => aucun débit net. L'appelant re-cherche
        # l'identité : si le job existe, c'est un loser => update ; sinon erreur.
        return "error"


async def import_feed(db, partner_id, xml_content=None, *, feed_url=None, cpc=None,
                      billing_mode=None, campaign_id=None, validity_days=None):
    import xml.etree.ElementTree as ET

    profile = await db.partner_profiles.find_one({"user_id": partner_id})
    if not profile:
        raise HTTPException(status_code=404, detail="Partenaire introuvable")

    campaign_import = isinstance(campaign_id, str) and bool(campaign_id)

    if campaign_import:
        # P0-007 : valider l'identité avant toute écriture et fail-closed tant
        # que la garantie d'index (marqueur posé par la migration explicite)
        # n'est pas en place. Aucune fenêtre de doublons concurrents sans index.
        if not (isinstance(partner_id, str) and partner_id.strip()):
            raise HTTPException(status_code=400, detail="P0-007 : partner_id invalide pour un import de campagne.")
        marker = await db.migration_flags.find_one({"_id": P0007_MARKER})
        if not marker:
            raise HTTPException(
                status_code=503,
                detail="P0-007 : l'index d'identité des offres de campagne n'est pas encore déployé. "
                       "Exécutez scripts/migrate_p0007_identity_indexes.py avant tout import de campagne.",
            )

    billing_mode = billing_mode or profile.get("billing_mode", "per_click")
    default_cpc = cpc if cpc is not None else profile.get("default_cpc", 0.0)
    posting_price = float(profile.get("posting_price", 0.0) or 0.0)

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
    imported, updated, skipped_no_credit, charged_count = 0, 0, 0, 0
    # Legacy per_posting : comportement P0-006 conservé (débit local + écriture
    # différée). Le per_posting campagne débite dans la transaction d'insertion.
    legacy_postings_remaining = int(profile.get("postings_remaining", 0)) if (
        billing_mode == "per_posting" and not campaign_import) else None
    now = datetime.utcnow()

    for ad in ads:
        reference = ad.get("reference") if isinstance(ad.get("reference"), str) else None
        if not reference or not reference.strip():
            continue
        identity = _job_identity(partner_id, campaign_id, reference)
        company_name = ad.get("company") or profile.get("company_name", "Partenaire")
        cpc_val = float(ad["cpc_raw"]) if ad.get("cpc_raw") else float(default_cpc or 0.0)

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

        existing = await db.jobs.find_one(identity)
        update_fields = {
            "title": ad["title"], "description": ad["description"], "location": ad["location"],
            "job_type": ad["job_type"], "company_id": company_id, "employer_id": partner_id,
            "partner_id": partner_id, "campaign_id": campaign_id, "is_partner": True,
            "external_url": ad["url"], "external_ref": reference, "cpc": cpc_val,
            "is_remote": False, "is_urgent": False, "requirements": [], "benefits": [], "tags": [],
            "salary_min": None, "salary_max": None, "salary_currency": "EUR", "updated_at": now,
        }
        center = await geocode_place(ad["location"])
        if center:
            update_fields["loc"] = {"type": "Point", "coordinates": center}

        if existing:
            # Identité stricte => jamais un job d'une autre campagne ni un legacy.
            await db.jobs.update_one({"_id": existing["_id"]}, {"$set": update_fields})
            updated += 1
            continue

        # Nouvelle insertion.
        job_doc = {
            "_id": f"pjob_{uuid.uuid4()}", **update_fields,
            "is_active": True, "views_count": 0, "applications_count": 0, "created_at": now,
        }
        if billing_mode == "per_posting" and validity_days:
            # P0-006 : un job per_posting en nouvelle insertion expire après
            # validity_days. Jamais renouvelé à l'update (update_fields ne le
            # contient pas).
            job_doc["expires_at"] = now + timedelta(days=int(validity_days))

        if billing_mode == "per_posting" and campaign_import:
            from database import get_client
            try:
                outcome = await _insert_per_posting_campaign(
                    db, get_client(), partner_id, identity, job_doc, update_fields, posting_price)
            except _UnsupportedTransactions:
                raise HTTPException(
                    status_code=503,
                    detail="P0-007 : les transactions MongoDB ne sont pas disponibles pour l'import "
                           "per_posting de campagne. Aucune insertion ni aucun débit. "
                           "Utilisez une topologie replica-set.",
                )
            if outcome == "inserted":
                imported += 1
                charged_count += 1
            elif outcome == "updated":
                updated += 1
            else:
                # "no_credit" ou erreur non classifiee : re-cherche stricte de
                # l'identité => si un concurrent a gagné, c'est un update.
                existing = await db.jobs.find_one(identity)
                if existing:
                    await db.jobs.update_one({"_id": existing["_id"]}, {"$set": update_fields})
                    updated += 1
                elif outcome == "no_credit":
                    skipped_no_credit += 1
                else:
                    # Échec de transaction sans job concurrent : la transaction a
                    # été abortée (aucun débit net) => erreur serveur explicite.
                    raise HTTPException(
                        status_code=500,
                        detail="P0-007 : la transaction per_posting a échoué sans insertion concurrente. "
                               "Aucun débit n'a été appliqué.",
                    )
        elif billing_mode == "per_posting":
            # Legacy sans campagne (identité {partner, ref, campaign_id: None}) :
            # comportement P0-006 conservé. La concurrence legacy n'est PAS dans
            # le scope P0-007 (pas d'index unique dédié).
            if legacy_postings_remaining <= 0:
                skipped_no_credit += 1
                continue
            legacy_postings_remaining -= 1
            await db.jobs.insert_one(job_doc)
            imported += 1
        else:
            try:
                await db.jobs.insert_one(job_doc)
                imported += 1
            except DuplicateKeyError:
                # Un concurrent a inséré la même identité entre notre find et
                # notre insert (l'index unique p0007 l'a refusé) => update.
                existing = await db.jobs.find_one(identity)
                if existing:
                    await db.jobs.update_one({"_id": existing["_id"]}, {"$set": update_fields})
                    updated += 1
                else:
                    raise

    if billing_mode == "per_posting":
        if campaign_import:
            # Relecture autoritaire du solde final ; charged = insertions
            # RÉELLEMENT facturées par CETTE invocation (jamais un delta global).
            final_postings = int((await db.partner_profiles.find_one(
                {"user_id": partner_id}) or {}).get("postings_remaining", 0) or 0)
            charged = round(charged_count * posting_price, 2)
        else:
            final_postings = max(0, legacy_postings_remaining)
            consumed = max(0, int(profile.get("postings_remaining", 0)) - final_postings)
            if consumed:
                await db.partner_profiles.update_one(
                    {"user_id": partner_id},
                    {"$set": {"postings_remaining": final_postings},
                     "$inc": {"total_spent": consumed * posting_price}},
                )
            charged = round(consumed * posting_price, 2)
        return {
            "imported": imported, "updated": updated,
            "skipped_no_credit": skipped_no_credit,
            "postings_remaining": final_postings,
            "charged": charged,
        }

    return {
        "imported": imported, "updated": updated,
        "skipped_no_credit": skipped_no_credit,
        "postings_remaining": None,
        "charged": 0,
    }


async def import_campaign_feed(db, campaign, xml_content=None, trigger="manual"):
    """Run a campaign import and record an import_logs entry (start/end/new ads).

    P0-006 fail-closed : une campagne paused/future/expirée/budget épuisé n'est
    PAS diffusible => import refusé (409) sans aucune écriture. C'est le cas
    d'un import manuel ; l'import auto saute en amont dans le scheduler.
    """
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
