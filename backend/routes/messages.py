"""Messagerie recruteur <-> candidat (quasi temps réel via polling)."""
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from database import get_database
from auth import get_current_active_user
from models import User

router = APIRouter(prefix="/messages", tags=["messages"])


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


async def _can_message(db, me: User, other_id: str) -> bool:
    if not other_id or me.id == other_id:
        return False
    other = await db.users.find_one({"_id": other_id})
    if not other:
        return False
    existing = await db.messages.find_one({"$or": [
        {"sender_id": me.id, "recipient_id": other_id},
        {"sender_id": other_id, "recipient_id": me.id},
    ]})
    if existing:
        return True
    if me.user_type == "candidate":
        my_apps = await db.applications.distinct("job_id", {"candidate_id": me.id})
        if my_apps and await db.jobs.find_one({"_id": {"$in": my_apps}, "employer_id": other_id}):
            return True
    if me.user_type in ("employer", "admin"):
        my_jobs = await db.jobs.distinct("_id", {"employer_id": me.id})
        if my_jobs and await db.applications.find_one({"job_id": {"$in": my_jobs}, "candidate_id": other_id}):
            return True
    return False


class SendMessage(BaseModel):
    recipient_id: str
    text: str
    job_id: Optional[str] = None


@router.post("")
async def send_message(body: SendMessage, current_user: User = Depends(get_current_active_user)):
    db = await get_database()
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message vide")
    if not await _can_message(db, current_user, body.recipient_id):
        raise HTTPException(status_code=403, detail="Vous ne pouvez pas contacter cet utilisateur")
    now = datetime.now(timezone.utc)
    doc = {
        "_id": str(uuid.uuid4()),
        "sender_id": current_user.id,
        "recipient_id": body.recipient_id,
        "text": text[:4000],
        "job_id": body.job_id,
        "read": False,
        "created_at": now,
    }
    await db.messages.insert_one(doc)
    return {
        "id": doc["_id"], "text": doc["text"], "from_me": True,
        "job_id": doc["job_id"], "created_at": now.isoformat(),
    }


@router.get("/unread-count")
async def unread_count(current_user: User = Depends(get_current_active_user)):
    db = await get_database()
    n = await db.messages.count_documents({"recipient_id": current_user.id, "read": False})
    return {"count": n}


@router.get("/can-contact/{other_id}")
async def can_contact(other_id: str, current_user: User = Depends(get_current_active_user)):
    db = await get_database()
    return {"allowed": await _can_message(db, current_user, other_id)}


@router.get("/conversations")
async def conversations(current_user: User = Depends(get_current_active_user)):
    db = await get_database()
    msgs = await db.messages.find({"$or": [
        {"sender_id": current_user.id}, {"recipient_id": current_user.id},
    ]}).sort([("created_at", -1)]).to_list(length=2000)

    convos = {}
    for m in msgs:
        other = m["recipient_id"] if m["sender_id"] == current_user.id else m["sender_id"]
        if other not in convos:
            convos[other] = {
                "other_id": other,
                "last_message": m["text"],
                "last_at": m["created_at"],
                "unread": 0,
                "last_from_me": m["sender_id"] == current_user.id,
            }
        if m["recipient_id"] == current_user.id and not m.get("read"):
            convos[other]["unread"] += 1

    ids = list(convos.keys())
    users = await db.users.find({"_id": {"$in": ids}}).to_list(length=len(ids)) if ids else []
    umap = {u["_id"]: u for u in users}
    out = []
    for oid, c in convos.items():
        u = umap.get(oid, {})
        out.append({
            "other_id": oid,
            "name": f"{u.get('first_name', '')} {u.get('last_name', '')}".strip() or "Utilisateur",
            "user_type": u.get("user_type"),
            "last_message": c["last_message"],
            "last_from_me": c["last_from_me"],
            "unread": c["unread"],
            "last_at": _iso(c["last_at"]),
        })
    out.sort(key=lambda x: x["last_at"] or "", reverse=True)
    return out


@router.get("/thread/{other_id}")
async def thread(other_id: str, current_user: User = Depends(get_current_active_user)):
    db = await get_database()
    other = await db.users.find_one({"_id": other_id})
    if not other:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    await db.messages.update_many(
        {"sender_id": other_id, "recipient_id": current_user.id, "read": False},
        {"$set": {"read": True}},
    )
    msgs = await db.messages.find({"$or": [
        {"sender_id": current_user.id, "recipient_id": other_id},
        {"sender_id": other_id, "recipient_id": current_user.id},
    ]}).sort([("created_at", 1)]).to_list(length=2000)
    return {
        "other": {
            "id": other_id,
            "name": f"{other.get('first_name', '')} {other.get('last_name', '')}".strip() or "Utilisateur",
            "user_type": other.get("user_type"),
        },
        "messages": [{
            "id": m["_id"], "text": m["text"],
            "from_me": m["sender_id"] == current_user.id,
            "created_at": _iso(m["created_at"]),
        } for m in msgs],
    }
