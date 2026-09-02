import os
import asyncio
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

import stripe
from fastapi import APIRouter, HTTPException, Depends, Request, status, UploadFile, File
from pydantic import BaseModel, Field

from database import get_database
from auth import get_current_active_user
from models import User
from storage import put_object, APP_NAME
from config import get_settings

router = APIRouter(tags=["payments"])

# P0-001 : aucune clé Stripe ni secret codé en dur à l'import. La clé est injectée
# au runtime via la config centralisée. Aucun fallback vers une valeur connue.

def _ensure_stripe():
    """Configure la clé Stripe au runtime à partir de la config centralisée.

    Si aucune clé n'est configurée (cas autorisé en développement/test), une
    erreur explicite est levée, sans exposer de secret, dès qu'un appel réel
    Stripe est nécessaire.
    """
    key = get_settings().STRIPE_SECRET_KEY
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe n'est pas configuré (STRIPE_SECRET_KEY absente).",
        )
    stripe.api_key = key

# Server-side defined packs (EUR). Amounts NEVER trusted from the frontend.
PACKS = {
    "pack_50": 50.0,
    "pack_100": 100.0,
    "pack_200": 200.0,
    "pack_500": 500.0,
}
MIN_AMOUNT = 10.0
MAX_AMOUNT = 5000.0
# Posting pack sizes (number of job postings) for per_posting partners.
POSTING_PACK_SIZES = [5, 10, 20, 50, 100, 200]


def require_partner_or_admin(current_user: User = Depends(get_current_active_user)) -> User:
    if current_user.user_type not in ["partner", "admin"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux partenaires")
    return current_user


class TopupRequest(BaseModel):
    origin_url: str
    pack_id: Optional[str] = None
    amount: Optional[float] = None
    postings: Optional[int] = None  # for per_posting partners: number of postings to buy
    partner_id: Optional[str] = None  # required when an admin recharges a partner


def _resolve_amount(req: TopupRequest) -> float:
    if req.pack_id:
        if req.pack_id not in PACKS:
            raise HTTPException(status_code=400, detail="Pack inconnu")
        return PACKS[req.pack_id]
    if req.amount is not None:
        amt = round(float(req.amount), 2)
        if amt < MIN_AMOUNT or amt > MAX_AMOUNT:
            raise HTTPException(status_code=400, detail=f"Le montant doit être entre {MIN_AMOUNT:.0f} € et {MAX_AMOUNT:.0f} €")
        return amt
    raise HTTPException(status_code=400, detail="Indiquez un pack ou un montant")


@router.get("/payments/packs")
async def list_packs():
    return {
        "packs": [{"id": k, "amount": v} for k, v in PACKS.items()],
        "posting_packs": POSTING_PACK_SIZES,
        "min": MIN_AMOUNT,
        "max": MAX_AMOUNT,
    }


@router.post("/payments/create-topup")
async def create_topup(req: TopupRequest, user: User = Depends(require_partner_or_admin)):
    db = await get_database()

    # Determine which partner is being credited
    if user.user_type == "admin":
        if not req.partner_id:
            raise HTTPException(status_code=400, detail="partner_id requis")
        partner_id = req.partner_id
    else:
        partner_id = user.id

    profile = await db.partner_profiles.find_one({"user_id": partner_id})
    if not profile:
        raise HTTPException(status_code=404, detail="Partenaire introuvable")

    company = profile.get("company_name", "Partenaire")

    # Posting pack purchase (per_posting billing) vs balance top-up (per_click)
    if req.postings is not None:
        postings = int(req.postings)
        if postings not in POSTING_PACK_SIZES:
            raise HTTPException(status_code=400, detail="Pack d'annonces inconnu")
        posting_price = float(profile.get("posting_price", 0.0) or 0.0)
        if posting_price <= 0:
            raise HTTPException(status_code=400, detail="Prix par annonce non configuré")
        amount = round(postings * posting_price, 2)
        kind = "posting_pack"
        product_name = f"{postings} annonces Joboolo — {company}"
    else:
        postings = None
        amount = _resolve_amount(req)
        kind = "partner_topup"
        product_name = f"Recharge solde Joboolo — {company}"

    origin = req.origin_url.rstrip("/")

    _ensure_stripe()
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "eur",
                    "unit_amount": int(round(amount * 100)),
                    "product_data": {"name": product_name},
                },
                "quantity": 1,
            }],
            success_url=f"{origin}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{origin}/payment/cancel",
            metadata={"partner_id": partner_id, "kind": kind},
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Erreur Stripe: {getattr(e, 'user_message', None) or str(e)}")

    now = datetime.now(timezone.utc)
    await db.payment_transactions.insert_one({
        "session_id": session.id,
        "partner_id": partner_id,
        "company_name": company,
        "amount": amount,
        "currency": "eur",
        "kind": kind,
        "postings": postings,
        "status": "initiated",
        "payment_status": "pending",
        "credited": False,
        "initiated_by": user.id,
        "created_at": now,
        "updated_at": now,
    })
    return {"checkout_url": session.url, "session_id": session.id}


async def _credit_if_paid(db, session_id: str):
    """Idempotently credit the partner balance once the session is paid."""
    record = await db.payment_transactions.find_one({"session_id": session_id})
    if not record:
        return None
    _ensure_stripe()
    if record.get("payment_status") != "paid":
        try:
            s = stripe.checkout.Session.retrieve(session_id)
            if s.payment_status == "paid" or s.status == "complete":
                await db.payment_transactions.update_one(
                    {"session_id": session_id, "payment_status": {"$ne": "paid"}},
                    {"$set": {"status": "completed", "payment_status": "paid",
                              "stripe_payment_intent_id": s.payment_intent,
                              "updated_at": datetime.now(timezone.utc)}},
                )
                record = await db.payment_transactions.find_one({"session_id": session_id})
        except stripe.error.StripeError:
            pass

    # Credit exactly once
    if record.get("payment_status") == "paid" and not record.get("credited"):
        if record.get("kind") == "recruiter_pack":
            # P0-005 : grant idempotent pour le recruiter_pack uniquement.
            # L'octroi et le marqueur d'idempotence (granted_sessions) sont faits
            # atomiquement sur le document utilisateur : le filtre exclut le
            # session_id déjà accordé, donc un retry/webhook concurrent ne peut
            # jamais incrémenter deux fois. `credited=True` n'est posé qu'après
            # l'octroi confirmé (ou la confirmation qu'il est déjà accordé).
            # Si l'utilisateur est absent ou l'octroi non confirmé, on laisse
            # credited != True pour permettre un retry.
            user_id = record.get("user_id")
            credited_amount = int(record.get("postings") or 0)
            grant_result = await db.users.update_one(
                {
                    "_id": user_id,
                    "granted_sessions": {"$ne": session_id},
                },
                {
                    "$inc": {"premium_credits": credited_amount},
                    "$addToSet": {"granted_sessions": session_id},
                },
            )
            if grant_result.modified_count == 1 or await _recruiter_grant_present(db, user_id, session_id):
                # P0-005 : un seul reçu. Sous appels réellement concurrents, les
                # deux callers peuvent voir l'octroi confirmé (granted_sessions),
                # mais seul celui qui fait passer `credited` de false->true
                # (modified_count == 1) envoie le reçu.
                credited_result = await db.payment_transactions.update_one(
                    {"session_id": session_id, "credited": {"$ne": True}},
                    {"$set": {"credited": True, "credited_at": datetime.now(timezone.utc)}},
                )
                if credited_result.modified_count == 1:
                    await _send_recruiter_receipt(db, record)
        else:
            # posting_pack / partner_topup : effet autoritatif atomique D'ABORD sur partner_profiles.
            partner_id = record["partner_id"]
            session_id = record["session_id"]
            kind = record["kind"]

            if kind == "posting_pack":
                inc_field = "postings_remaining"
                inc_value = int(record["postings"])
                update_doc = {"$inc": {inc_field: inc_value}, "$addToSet": {"credited_sessions": session_id}}
            else:  # partner_topup
                inc_field = "balance"
                inc_value = float(record["amount"])
                update_doc = {"$inc": {inc_field: inc_value}, "$addToSet": {"credited_sessions": session_id}, "$set": {"low_balance_notified": False}}

            # Atomic authoritative effect: filter excludes already-credited session.
            credit_result = await db.partner_profiles.update_one(
                {"user_id": partner_id, "credited_sessions": {"$ne": session_id}},
                update_doc,
            )

            # If modified_count == 0, verify by reading: session already present => effect already applied.
            effect_confirmed = False
            if credit_result.modified_count == 1:
                effect_confirmed = True
            elif await _partner_credit_present(db, partner_id, session_id):
                effect_confirmed = True

            if not effect_confirmed:
                # Partner profile absent or effect not confirmed: leave credited != True, raise retryable error.
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Effet de crédit non confirmé (profil partenaire absent ou écriture échouée). Retry ultérieur requis.",
                )

            # Authoritative effect confirmed: now mark payment_transactions.credited=True (secondary marker).
            credited_result = await db.payment_transactions.update_one(
                {"session_id": session_id, "credited": {"$ne": True}},
                {"$set": {"credited": True, "credited_at": datetime.now(timezone.utc)}},
            )

            # Receipt only on effective transition to credited=True.
            if credited_result.modified_count == 1:
                await _send_receipt(db, record)

        # Re-fetch record for both recruiter_pack and partner_topup/posting_pack
        # to return updated credited status.
        record = await db.payment_transactions.find_one({"session_id": session_id})
    return record


async def _partner_credit_present(db, partner_id: str, session_id: str) -> bool:
    """Confirme que le session_id est déjà présent dans credited_sessions du partner_profiles
    (cas retry après crash entre l'effet autoritatif et le marquage credited=True)."""
    if not partner_id:
        return False
    profile = await db.partner_profiles.find_one(
        {"user_id": partner_id, "credited_sessions": session_id},
        {"_id": 1},
    )
    return profile is not None


async def _recruiter_grant_present(db, user_id, session_id) -> bool:
    """Confirme que le session_id est déjà présent dans granted_sessions de l'utilisateur
    (cas retry après crash entre l'octroi et le marquage credited=True)."""
    if not user_id:
        return False
    user = await db.users.find_one(
        {"_id": user_id, "granted_sessions": session_id},
        {"_id": 1},
    )
    return user is not None


async def _send_recruiter_receipt(db, record: dict):
    """Reçu best-effort au recruteur après achat d'un pack d'offres Premium."""
    try:
        user = await db.users.find_one({"_id": record["user_id"]})
        if not user or not user.get("email"):
            return
        app_url = os.environ.get("APP_PUBLIC_URL", "https://joboolo.fr")
        postings = int(record.get("postings") or 0)
        html = f"""
        <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
          <table width="100%" style="max-width:600px;margin:0 auto;">
            <tr><td>
              <h1 style="color:#0055FF;font-size:24px;">Joboolo</h1>
              <p style="color:#374151;font-size:15px;">Bonjour {user.get('first_name','')},</p>
              <div style="border-left:4px solid #16a34a;padding:12px 16px;background:#fff;border-radius:6px;margin:16px 0;">
                <p style="color:#111827;font-size:16px;margin:0 0 6px;">Votre paiement a été confirmé ✅</p>
                <p style="color:#6b7280;font-size:14px;margin:0;"><strong>{postings} offre(s) Premium</strong> ont été créditée(s) sur votre compte.</p>
              </div>
              <a href="{app_url}/post-job" style="display:inline-block;margin-top:8px;background:#0055FF;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">Publier mon offre</a>
              <p style="color:#9ca3af;font-size:12px;margin-top:24px;">Reçu envoyé automatiquement par Joboolo.</p>
            </td></tr>
          </table>
        </div>
        """
        from email_service import send_alert_email
        await send_alert_email(user["email"], "Reçu — offres Premium Joboolo", html)
    except Exception:
        pass


async def _send_receipt(db, record: dict):
    """Best-effort receipt email to the partner after a successful recharge."""
    try:
        from email_service import build_topup_receipt_email, send_alert_email
        partner = await db.users.find_one({"_id": record["partner_id"]})
        profile = await db.partner_profiles.find_one({"user_id": record["partner_id"]}) or {}
        if not partner or not partner.get("email"):
            return
        is_posting = record.get("kind") == "posting_pack"
        new_balance = profile.get("postings_remaining", 0) if is_posting else profile.get("balance", 0.0)
        amount = record.get("postings") if is_posting else record.get("amount")
        app_url = os.environ.get("APP_PUBLIC_URL", "https://joboolo.fr")
        subject, html = build_topup_receipt_email(
            record.get("company_name") or profile.get("company_name") or "Partenaire",
            float(amount or 0), record.get("currency", "eur"), float(new_balance or 0),
            record.get("kind", "partner_topup"), app_url,
        )
        await send_alert_email(partner["email"], subject, html)
    except Exception:
        pass


@router.get("/payments/status/{session_id}")
async def payment_status(session_id: str):
    db = await get_database()
    record = await _credit_if_paid(db, session_id)
    if not record:
        raise HTTPException(status_code=404, detail="Transaction introuvable")
    return {
        "session_id": record["session_id"],
        "status": record["status"],
        "payment_status": record["payment_status"],
        "amount": record.get("amount"),
        "currency": record.get("currency"),
        "kind": record.get("kind"),
        "postings": record.get("postings"),
    }


@router.post("/stripe/webhook")
async def stripe_webhook(request: Request):
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    _ensure_stripe()
    # P0-001 : le secret de webhook provient de la config centralisée. En
    # production le démarrage est bloqué s'il manque ; en development/test une
    # protection défensive runtime explicite est conservée (sans exposer de secret).
    webhook_secret = get_settings().STRIPE_WEBHOOK_SECRET
    if not webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook Stripe non configuré (STRIPE_WEBHOOK_SECRET absente).",
        )
    try:
        event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
    except (stripe.error.SignatureVerificationError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid signature")

    obj, t = event["data"]["object"], event["type"]
    db = await get_database()
    if t == "checkout.session.completed":
        await db.payment_transactions.update_one(
            {"session_id": obj["id"], "payment_status": {"$ne": "paid"}},
            {"$set": {"status": "completed", "payment_status": obj.get("payment_status", "paid"),
                      "stripe_payment_intent_id": obj.get("payment_intent"),
                      "updated_at": datetime.now(timezone.utc)}},
        )
        await _credit_if_paid(db, obj["id"])
    elif t == "checkout.session.expired":
        await db.payment_transactions.update_one(
            {"session_id": obj["id"]},
            {"$set": {"status": "expired", "payment_status": "expired", "updated_at": datetime.now(timezone.utc)}},
        )
    return {"status": "ok"}


# ---------- Partner self-service ----------
def require_partner(current_user: User = Depends(get_current_active_user)) -> User:
    if current_user.user_type != "partner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Réservé aux partenaires")
    return current_user


@router.get("/partner/me")
async def partner_me(user: User = Depends(require_partner)):
    db = await get_database()
    profile = await db.partner_profiles.find_one({"user_id": user.id}) or {}
    active_jobs = await db.jobs.count_documents({"partner_id": user.id, "is_active": True})
    return {
        "company_name": profile.get("company_name"),
        "billing_mode": profile.get("billing_mode", "per_click"),
        "default_cpc": profile.get("default_cpc", 0.0),
        "posting_price": profile.get("posting_price", 0.0),
        "postings_remaining": profile.get("postings_remaining", 0),
        "balance": profile.get("balance", 0.0),
        "total_clicks": profile.get("total_clicks", 0),
        "total_spent": profile.get("total_spent", 0.0),
        "xml_feed_url": profile.get("xml_feed_url"),
        "logo_url": profile.get("logo_url"),
        "active_jobs": active_jobs,
    }


class PartnerImportRequest(BaseModel):
    xml_content: Optional[str] = None


class FeedUrlRequest(BaseModel):
    xml_feed_url: Optional[str] = None


@router.post("/partner/import-xml")
async def partner_import_xml(body: PartnerImportRequest, user: User = Depends(require_partner)):
    db = await get_database()
    from partner_feed import import_feed
    return await import_feed(db, user.id, body.xml_content)


@router.put("/partner/feed-url")
async def partner_set_feed_url(body: FeedUrlRequest, user: User = Depends(require_partner)):
    db = await get_database()
    await db.partner_profiles.update_one(
        {"user_id": user.id},
        {"$set": {"xml_feed_url": body.xml_feed_url or None, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"xml_feed_url": body.xml_feed_url or None}


@router.get("/partner/transactions")
async def partner_transactions(user: User = Depends(require_partner)):
    db = await get_database()
    docs = await db.payment_transactions.find({"partner_id": user.id}).sort([("created_at", -1)]).limit(100).to_list(length=100)
    return [{
        "amount": d.get("amount"),
        "currency": d.get("currency"),
        "status": d.get("status"),
        "payment_status": d.get("payment_status"),
        "created_at": d.get("created_at"),
    } for d in docs]


@router.get("/partner/performance")
async def partner_performance(days: int = 14, user: User = Depends(require_partner)):
    db = await get_database()
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)
    since_naive = datetime.utcnow() - timedelta(days=days)

    events = await db.click_events.find({"partner_id": user.id, "ts": {"$gte": since_naive}}).to_list(length=100000)

    # daily buckets
    daily = {}
    for i in range(days):
        d = (datetime.utcnow() - timedelta(days=days - 1 - i)).strftime("%Y-%m-%d")
        daily[d] = {"date": d, "clicks": 0, "cost": 0.0}
    total_clicks, total_cost = 0, 0.0
    per_job = {}
    for e in events:
        ts = e.get("ts")
        key = ts.strftime("%Y-%m-%d") if ts else None
        if key in daily:
            daily[key]["clicks"] += 1
            daily[key]["cost"] += float(e.get("cost", 0.0))
        total_clicks += 1
        total_cost += float(e.get("cost", 0.0))
        t = e.get("job_title") or "Offre"
        pj = per_job.setdefault(t, {"title": t, "clicks": 0, "cost": 0.0})
        pj["clicks"] += 1
        pj["cost"] += float(e.get("cost", 0.0))

    # impressions réelles (offres partenaires affichées dans les résultats) sur la période
    impressions = await db.impression_events.count_documents({"partner_id": user.id, "ts": {"$gte": since_naive}})

    top_jobs = sorted(per_job.values(), key=lambda x: x["clicks"], reverse=True)[:5]
    for tj in top_jobs:
        tj["cost"] = round(tj["cost"], 2)

    return {
        "days": days,
        "daily": [{"date": v["date"], "clicks": v["clicks"], "cost": round(v["cost"], 2)} for v in daily.values()],
        "totals": {
            "clicks": total_clicks,
            "cost": round(total_cost, 2),
            "impressions": impressions,
            "ctr": round((total_clicks / impressions * 100), 2) if impressions else 0.0,
            "avg_cpc": round((total_cost / total_clicks), 2) if total_clicks else 0.0,
        },
        "top_jobs": top_jobs,
    }


# ---------- Partner display campaigns ----------
class CampaignCreate(BaseModel):
    name: str
    billing_mode: str = "per_click"  # per_click | per_posting
    cpc: Optional[float] = None
    cpc_max: Optional[float] = None
    pack_price: Optional[float] = None
    xml_feed_url: Optional[str] = None
    logo_url: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget_limit: Optional[float] = None  # only for per_click


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    cpc: Optional[float] = None
    cpc_max: Optional[float] = None
    pack_price: Optional[float] = None
    xml_feed_url: Optional[str] = None
    logo_url: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    budget_limit: Optional[float] = None
    status: Optional[str] = None  # active | paused


class CampaignImport(BaseModel):
    xml_content: Optional[str] = None


def _validate_campaign_dates(start_date, end_date):
    """P0-006 : valide les bornes de date d'une campagne (create ET update).

    - format strict 'YYYY-MM-DD' + vraie date calendrier (sinon 400) ;
    - état final fusionné : start_date <= end_date (sinon 400).
    - une valeur None ou '' ('' = suppression de la borne) n'impose aucune
      contrainte. Une date non vide mais invalide => 400.

    Retourne les valeurs normalisées (None, '' ou chaîne YYYY-MM-DD exacte)
    pour que l'appelant stocke toujours une valeur propre, sans espaces
    extérieurs, quelle que soit la saisie d'origine.
    """
    def _check(value, label):
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            return None
        s = value.strip()
        try:
            d = datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"{label} invalide : format attendu YYYY-MM-DD avec une date calendrier réelle.",
            )
        if d.strftime("%Y-%m-%d") != s:
            raise HTTPException(
                status_code=400,
                detail=f"{label} invalide : format attendu YYYY-MM-DD.",
            )
        return s  # valeur normalisée (trimée, strict YYYY-MM-DD)

    start = _check(start_date, "start_date")
    end = _check(end_date, "end_date")
    # Comparaison sur les chaînes normalisées (format YYYY-MM-DD ordonné lexicalement).
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=400,
            detail="start_date doit être inférieure ou égale à end_date.",
        )
    return start, end


def _validate_campaign_status(status):
    if status is None:
        return
    if status not in ("active", "paused"):
        raise HTTPException(
            status_code=400,
            detail="status doit être 'active' ou 'paused'.",
        )


def _campaign_out(d: dict) -> dict:
    return {
        "id": d["_id"], "name": d.get("name"), "billing_mode": d.get("billing_mode"),
        "cpc": d.get("cpc"), "cpc_max": d.get("cpc_max"), "pack_price": d.get("pack_price"),
        "xml_feed_url": d.get("xml_feed_url"), "logo_url": d.get("logo_url"),
        "start_date": d.get("start_date"), "end_date": d.get("end_date"),
        "budget_limit": d.get("budget_limit"), "spent": d.get("spent", 0.0),
        "clicks": d.get("clicks", 0), "jobs_count": d.get("jobs_count", 0),
        "validity_days": d.get("validity_days"),
        "status": d.get("status", "active"), "created_at": d.get("created_at"),
    }


@router.get("/partner/campaigns")
async def list_campaigns(user: User = Depends(require_partner)):
    db = await get_database()
    docs = await db.campaigns.find({"partner_id": user.id}).sort([("created_at", -1)]).to_list(length=200)
    return [_campaign_out(d) for d in docs]


@router.post("/partner/campaigns")
async def create_campaign(data: CampaignCreate, user: User = Depends(require_partner)):
    db = await get_database()
    import uuid as _uuid
    from routes.admin import get_settings
    if not (data.xml_feed_url or "").strip():
        raise HTTPException(status_code=400, detail="L'URL du flux XML est obligatoire")
    start_date, end_date = _validate_campaign_dates(data.start_date, data.end_date)
    settings = await get_settings(db)
    now = datetime.now(timezone.utc)
    validity = settings["pack_validity_days"] if data.billing_mode == "per_posting" else None
    doc = {
        "_id": f"camp_{_uuid.uuid4()}",
        "partner_id": user.id,
        "name": data.name,
        "billing_mode": data.billing_mode,
        "cpc": data.cpc if data.billing_mode == "per_click" else None,
        "cpc_max": data.cpc_max if data.billing_mode == "per_click" else None,
        "pack_price": data.pack_price if data.billing_mode == "per_posting" else None,
        "xml_feed_url": data.xml_feed_url,
        "logo_url": data.logo_url,
        "start_date": start_date,
        "end_date": end_date,
        "budget_limit": data.budget_limit if data.billing_mode == "per_click" else None,
        "validity_days": validity,
        "spent": 0.0, "clicks": 0, "jobs_count": 0, "status": "active",
        "created_at": now, "updated_at": now,
    }
    await db.campaigns.insert_one(doc)
    return _campaign_out(doc)


@router.put("/partner/campaigns/{campaign_id}")
async def update_campaign(campaign_id: str, data: CampaignUpdate, user: User = Depends(require_partner)):
    db = await get_database()
    camp = await db.campaigns.find_one({"_id": campaign_id, "partner_id": user.id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campagne introuvable")
    fields = {k: v for k, v in data.dict().items() if v is not None}
    _validate_campaign_status(fields.get("status"))
    # P0-006 : valide chaque borne envoyée ET l'état final fusionné avec l'autre
    # borne déjà stockée (update partielle). Les valeurs renvoyées sont
    # normalisées (espaces extérieurs retirés AVANT écriture) et persistées.
    new_start = fields.get("start_date") if "start_date" in fields else camp.get("start_date")
    new_end = fields.get("end_date") if "end_date" in fields else camp.get("end_date")
    new_start, new_end = _validate_campaign_dates(new_start, new_end)
    if "start_date" in fields:
        fields["start_date"] = new_start
    if "end_date" in fields:
        fields["end_date"] = new_end
    fields["updated_at"] = datetime.now(timezone.utc)
    await db.campaigns.update_one({"_id": campaign_id}, {"$set": fields})
    return _campaign_out(await db.campaigns.find_one({"_id": campaign_id}))


@router.delete("/partner/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str, user: User = Depends(require_partner)):
    db = await get_database()
    res = await db.campaigns.delete_one({"_id": campaign_id, "partner_id": user.id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Campagne introuvable")
    # Supprime aussi les offres importées par cette campagne (pas d'offres orphelines)
    await db.jobs.delete_many({"campaign_id": campaign_id})
    return {"message": "Campagne supprimée"}


@router.post("/partner/campaigns/{campaign_id}/import")
async def import_campaign(campaign_id: str, body: CampaignImport, user: User = Depends(require_partner)):
    """Import the campaign's XML feed. Uses the campaign's own CPC + billing mode,
    and tags every imported job with campaign_id."""
    db = await get_database()
    camp = await db.campaigns.find_one({"_id": campaign_id, "partner_id": user.id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campagne introuvable")
    from partner_feed import import_campaign_feed
    return await import_campaign_feed(db, camp, body.xml_content, trigger="manual")


@router.get("/partner/imports")
async def partner_imports(user: User = Depends(require_partner)):
    """Import history for the partner's campaigns over the last 30 days."""
    from datetime import timedelta
    db = await get_database()
    since = datetime.utcnow() - timedelta(days=30)
    docs = await db.import_logs.find({"partner_id": user.id, "started_at": {"$gte": since}}).sort([("started_at", -1)]).limit(500).to_list(length=500)
    return [{
        "campaign_name": d.get("campaign_name"),
        "started_at": d.get("started_at"),
        "finished_at": d.get("finished_at"),
        "new_ads": d.get("imported", 0),
        "updated": d.get("updated", 0),
        "trigger": d.get("trigger", "manual"),
        "status": d.get("status", "success"),
    } for d in docs]


@router.get("/partner/campaigns/{campaign_id}/jobs")
async def campaign_jobs(campaign_id: str, user: User = Depends(require_partner)):
    """Offres importées par une campagne donnée (loupe)."""
    db = await get_database()
    camp = await db.campaigns.find_one({"_id": campaign_id, "partner_id": user.id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campagne introuvable")
    docs = await db.jobs.find({"campaign_id": campaign_id}).sort([("created_at", -1)]).limit(1000).to_list(length=1000)
    return [{
        "id": d["_id"],
        "title": d.get("title"),
        "location": d.get("location"),
        "job_type": d.get("job_type"),
        "is_active": d.get("is_active", True),
        "external_url": d.get("external_url"),
        "views_count": d.get("views_count", 0),
        "created_at": d.get("created_at"),
    } for d in docs]


# ---------- Logo upload (partner profile + per campaign) ----------
_IMG_ALLOWED = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "svg": "image/svg+xml",
}
_MAX_LOGO = 3 * 1024 * 1024  # 3 Mo


async def _store_logo(db, owner_id: str, file: UploadFile) -> str:
    ext = (file.filename.rsplit(".", 1)[-1] if "." in (file.filename or "") else "").lower()
    if ext not in _IMG_ALLOWED:
        raise HTTPException(status_code=400, detail="Format d'image non supporté (PNG, JPG, WEBP, SVG, GIF).")
    data = await file.read()
    if len(data) > _MAX_LOGO:
        raise HTTPException(status_code=400, detail="Image trop volumineuse (max 3 Mo).")
    content_type = _IMG_ALLOWED[ext]
    path = f"{APP_NAME}/logos/{owner_id}/{_uuid.uuid4()}.{ext}"
    try:
        result = await asyncio.to_thread(put_object, path, data, content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Échec de l'upload: {e}")
    await db.files.insert_one({
        "_id": str(_uuid.uuid4()),
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "owner_id": owner_id,
        "is_public": True,
        "is_deleted": False,
        "created_at": datetime.utcnow(),
    })
    return f"/api/files/public/{result['path']}"


@router.post("/partner/logo")
async def upload_partner_logo(file: UploadFile = File(...), user: User = Depends(require_partner)):
    db = await get_database()
    logo_url = await _store_logo(db, user.id, file)
    await db.partner_profiles.update_one(
        {"user_id": user.id},
        {"$set": {"logo_url": logo_url, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"logo_url": logo_url}


@router.post("/partner/campaigns/{campaign_id}/logo")
async def upload_campaign_logo(campaign_id: str, file: UploadFile = File(...), user: User = Depends(require_partner)):
    db = await get_database()
    camp = await db.campaigns.find_one({"_id": campaign_id, "partner_id": user.id})
    if not camp:
        raise HTTPException(status_code=404, detail="Campagne introuvable")
    logo_url = await _store_logo(db, user.id, file)
    await db.campaigns.update_one(
        {"_id": campaign_id},
        {"$set": {"logo_url": logo_url, "updated_at": datetime.now(timezone.utc)}},
    )
    return {"logo_url": logo_url}
