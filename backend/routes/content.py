"""Contenu public géré depuis l'admin (liens pays du footer)."""
from fastapi import APIRouter

from database import get_database

router = APIRouter(tags=["content"])


@router.get("/footer-countries")
async def public_footer_countries():
    """Liste publique des versions internationales affichées dans le footer."""
    db = await get_database()
    docs = await db.footer_countries.find({"is_active": True}).sort([("order", 1)]).to_list(length=500)
    return [{
        "id": d["_id"],
        "code": d.get("code"),
        "label": d.get("label"),
        "url": d.get("url") or "#",
    } for d in docs]
