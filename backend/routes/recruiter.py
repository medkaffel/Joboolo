"""Espace Recruteur premium : packs d'offres à l'unité (paiement Stripe) et demande de devis."""
import os
import uuid as _uuid
from datetime import datetime, timezone
from typing import Optional

import stripe
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr

from database import get_database
from auth import get_current_active_user, require_employer
from models import User
from email_service import send_alert_email
from config import get_settings

router = APIRouter(tags=["recruiter"])

# Packs d'offres Premium à l'unité (EUR). Prix unitaire paramétrable via l'admin ; remises par volume.
DEFAULT_PREMIUM_UNIT_PRICE = 299.0

_PACK_DEFS = {
    "premium_1": {"postings": 1, "multiplier": 1.0, "label": "1 offre Premium"},
    "premium_3": {"postings": 3, "multiplier": 3 * 0.89, "label": "Pack 3 offres Premium"},
    "premium_5": {"postings": 5, "multiplier": 5 * 0.80, "label": "Pack 5 offres Premium"},
}


async def _get_unit_price(db) -> float:
    doc = await db.settings.find_one({"_id": "global"}) or {}
    try:
        val = float(doc.get("recruiter_premium_price"))
        return val if val > 0 else DEFAULT_PREMIUM_UNIT_PRICE
    except (TypeError, ValueError):
        return DEFAULT_PREMIUM_UNIT_PRICE


def _build_packs(unit: float) -> dict:
    return {
        pid: {"postings": d["postings"], "price": float(round(unit * d["multiplier"])), "label": d["label"]}
        for pid, d in _PACK_DEFS.items()
    }


def _ensure_stripe():
    # P0-001 : aucune clé secret codée en dur ; config centralisée, erreur explicite si absente.
    key = get_settings().STRIPE_SECRET_KEY
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe n'est pas configuré (STRIPE_SECRET_KEY absente).",
        )
    stripe.api_key = key


@router.get("/recruiter/packs")
async def recruiter_packs():
    db = await get_database()
    unit = await _get_unit_price(db)
    packs = _build_packs(unit)
    return {
        "unit_price": unit,
        "packs": [{"id": k, **v} for k, v in packs.items()],
    }


class RecruiterCheckout(BaseModel):
    origin_url: str
    pack_id: str


@router.post("/recruiter/checkout")
async def recruiter_checkout(req: RecruiterCheckout, user: User = Depends(require_employer)):
    db = await get_database()
    unit = await _get_unit_price(db)
    packs = _build_packs(unit)
    pack = packs.get(req.pack_id)
    if not pack:
        raise HTTPException(status_code=400, detail="Pack inconnu")

    amount = float(pack["price"])
    product_name = f"{pack['label']} — Joboolo Recruteur"
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
            metadata={"user_id": user.id, "kind": "recruiter_pack", "pack_id": req.pack_id},
        )
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Erreur Stripe: {getattr(e, 'user_message', None) or str(e)}")

    now = datetime.now(timezone.utc)
    await db.payment_transactions.insert_one({
        "session_id": session.id,
        "user_id": user.id,
        "company_name": f"{user.first_name} {user.last_name}".strip(),
        "amount": amount,
        "currency": "eur",
        "kind": "recruiter_pack",
        "pack_id": req.pack_id,
        "postings": int(pack["postings"]),
        "status": "initiated",
        "payment_status": "pending",
        "credited": False,
        "initiated_by": user.id,
        "created_at": now,
        "updated_at": now,
    })
    return {"checkout_url": session.url, "session_id": session.id}


class QuoteRequest(BaseModel):
    first_name: str
    last_name: str
    company: str
    email: EmailStr
    phone: Optional[str] = None
    message: Optional[str] = None
    need: Optional[str] = None  # e.g. "cpc" | "targeted" | "premium"


@router.post("/recruiter/quote")
async def recruiter_quote(body: QuoteRequest):
    """Demande de devis publique (formulaire de la page Recruteur)."""
    db = await get_database()
    now = datetime.now(timezone.utc)
    lead = {
        "_id": str(_uuid.uuid4()),
        "first_name": body.first_name.strip(),
        "last_name": body.last_name.strip(),
        "company": body.company.strip(),
        "email": str(body.email),
        "phone": (body.phone or "").strip() or None,
        "message": (body.message or "").strip() or None,
        "need": body.need or None,
        "status": "new",
        "created_at": now,
    }
    await db.recruiter_leads.insert_one(lead)

    # Notification best-effort à l'équipe (Resend)
    admin_email = os.environ.get("ADMIN_EMAIL")
    if admin_email:
        app_url = os.environ.get("APP_PUBLIC_URL", "https://joboolo.fr")
        html = f"""
        <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
          <table width="100%" style="max-width:600px;margin:0 auto;">
            <tr><td>
              <h1 style="color:#0055FF;font-size:24px;">Joboolo — Nouvelle demande de devis</h1>
              <div style="border-left:4px solid #0055FF;padding:12px 16px;background:#fff;border-radius:6px;margin:16px 0;">
                <p style="color:#111827;font-size:16px;margin:0 0 6px;"><strong>{lead['first_name']} {lead['last_name']}</strong> — {lead['company']}</p>
                <p style="color:#4b5563;font-size:14px;margin:0 0 4px;">Email : {lead['email']}</p>
                {f"<p style='color:#4b5563;font-size:14px;margin:0 0 4px;'>Tél : {lead['phone']}</p>" if lead['phone'] else ''}
                {f"<p style='color:#4b5563;font-size:14px;margin:0 0 4px;'>Besoin : {lead['need']}</p>" if lead['need'] else ''}
                {f"<p style='color:#4b5563;font-size:14px;margin:8px 0 0;'>{lead['message']}</p>" if lead['message'] else ''}
              </div>
              <a href="{app_url}/adminos" style="display:inline-block;margin-top:8px;background:#0055FF;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">Ouvrir le back-office</a>
            </td></tr>
          </table>
        </div>
        """
        await send_alert_email(admin_email, f"Nouvelle demande de devis — {lead['company']}", html)

    return {"success": True, "message": "Votre demande a bien été envoyée. Notre équipe vous recontactera sous 24h ouvrées."}


@router.get("/recruiter/quotes")
async def list_quotes(user: User = Depends(get_current_active_user)):
    """Liste des demandes de devis (admin uniquement)."""
    if user.user_type != "admin":
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    db = await get_database()
    docs = await db.recruiter_leads.find().sort([("created_at", -1)]).limit(500).to_list(length=500)
    return [{
        "id": d["_id"],
        "first_name": d.get("first_name"),
        "last_name": d.get("last_name"),
        "company": d.get("company"),
        "email": d.get("email"),
        "phone": d.get("phone"),
        "message": d.get("message"),
        "need": d.get("need"),
        "status": d.get("status"),
        "created_at": d.get("created_at"),
    } for d in docs]
