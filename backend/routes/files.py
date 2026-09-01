import uuid
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Header, Query
from fastapi.responses import Response
from pydantic import BaseModel

from database import get_database
from auth import get_current_active_user, get_user_by_email, get_secret_key
from jose import jwt, JWTError
from auth import ALGORITHM
from models import User
from storage import put_object, get_object, APP_NAME

router = APIRouter(prefix="/files", tags=["files"])

ALLOWED = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
IMAGE_ALLOWED = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "gif": "image/gif",
}
MAX_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_PHOTO_SIZE = 3 * 1024 * 1024  # 3 MB


@router.post("/upload-profile-photo")
async def upload_profile_photo(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
):
    """Upload a profile photo (jpg/png/webp/gif) and set it on the user doc."""
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "").lower()
    if ext not in IMAGE_ALLOWED:
        raise HTTPException(status_code=400, detail="Format non supporté. Utilisez JPG, PNG, WEBP ou GIF.")

    data = await file.read()
    if len(data) > MAX_PHOTO_SIZE:
        raise HTTPException(status_code=400, detail="Image trop volumineuse (max 3 Mo).")

    content_type = IMAGE_ALLOWED[ext]
    path = f"{APP_NAME}/profile-photos/{current_user.id}/{uuid.uuid4()}.{ext}"

    try:
        result = await asyncio.to_thread(put_object, path, data, content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Échec de l'upload: {e}")

    db = await get_database()
    await db.files.insert_one({
        "_id": str(uuid.uuid4()),
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "owner_id": current_user.id,
        "is_public": True,  # profile photos are public
        "kind": "profile_photo",
        "is_deleted": False,
        "created_at": datetime.utcnow(),
    })
    # Serve via /files/public/<path>
    from fastapi import Request  # only for building URL; we use a relative path
    public_url = f"/api/files/public/{result['path']}"
    await db.users.update_one({"_id": current_user.id}, {"$set": {"profile_photo_url": public_url, "updated_at": datetime.utcnow()}})

    return {
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "profile_photo_url": public_url,
    }


# ---------- Candidate documents (CV + cover letters, max 3 each) ----------
CANDIDATE_CATEGORIES = {"cv", "cover_letter"}
MAX_DOCS_PER_CATEGORY = 3


@router.get("/candidate-documents")
async def list_candidate_documents(current_user: User = Depends(get_current_active_user)):
    db = await get_database()
    docs = await db.candidate_documents.find(
        {"owner_id": current_user.id, "is_deleted": False}
    ).sort([("created_at", -1)]).to_list(length=100)
    return [
        {
            "id": d["_id"],
            "category": d.get("category"),
            "title": d.get("title"),
            "description": d.get("description"),
            "original_filename": d.get("original_filename"),
            "content_type": d.get("content_type"),
            "storage_path": d.get("storage_path"),
            "size": d.get("size"),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
        }
        for d in docs
    ]


@router.post("/candidate-documents")
async def upload_candidate_document(
    category: str,
    title: str = "",
    description: str = "",
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
):
    """Upload a CV or cover letter (max 3 per category)."""
    if current_user.user_type not in ("candidate",) and str(current_user.user_type).lower() not in ("usertype.candidate", "candidate"):
        raise HTTPException(status_code=403, detail="Réservé aux candidats")
    if category not in CANDIDATE_CATEGORIES:
        raise HTTPException(status_code=400, detail="Catégorie invalide (cv ou cover_letter attendu).")

    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "").lower()
    if ext not in ALLOWED:
        raise HTTPException(status_code=400, detail="Format non supporté. Utilisez PDF, DOC ou DOCX.")

    db = await get_database()
    current = await db.candidate_documents.count_documents(
        {"owner_id": current_user.id, "category": category, "is_deleted": False}
    )
    if current >= MAX_DOCS_PER_CATEGORY:
        raise HTTPException(status_code=400, detail=f"Vous ne pouvez enregistrer que {MAX_DOCS_PER_CATEGORY} documents par catégorie.")

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 10 Mo).")

    content_type = ALLOWED[ext]
    path = f"{APP_NAME}/candidates/{current_user.id}/{category}/{uuid.uuid4()}.{ext}"
    try:
        result = await asyncio.to_thread(put_object, path, data, content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Échec de l'upload: {e}")

    doc_id = str(uuid.uuid4())
    now = datetime.utcnow()
    doc = {
        "_id": doc_id,
        "owner_id": current_user.id,
        "category": category,
        "title": (title or file.filename)[:120],
        "description": (description or "")[:400],
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
    }
    await db.candidate_documents.insert_one(doc)
    return {**doc, "id": doc_id}


class CandidateDocumentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None


@router.put("/candidate-documents/{doc_id}")
async def update_candidate_document(
    doc_id: str,
    body: CandidateDocumentUpdate,
    current_user: User = Depends(get_current_active_user),
):
    db = await get_database()
    doc = await db.candidate_documents.find_one({"_id": doc_id, "owner_id": current_user.id, "is_deleted": False})
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    payload = {k: v for k, v in body.dict(exclude_none=True).items()}
    if "title" in payload:
        payload["title"] = payload["title"][:120]
    if "description" in payload:
        payload["description"] = payload["description"][:400]
    if payload:
        payload["updated_at"] = datetime.utcnow()
        await db.candidate_documents.update_one({"_id": doc_id}, {"$set": payload})
    updated = await db.candidate_documents.find_one({"_id": doc_id})
    return {"id": doc_id, **{k: updated.get(k) for k in ("category","title","description","original_filename","storage_path","content_type","size","created_at","updated_at")}}


@router.delete("/candidate-documents/{doc_id}")
async def delete_candidate_document(
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
):
    db = await get_database()
    res = await db.candidate_documents.update_one(
        {"_id": doc_id, "owner_id": current_user.id, "is_deleted": False},
        {"$set": {"is_deleted": True, "updated_at": datetime.utcnow()}},
    )
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return {"message": "Document supprimé"}


@router.post("/upload-cv")
async def upload_cv(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_active_user),
):
    """Upload a CV (PDF/DOC/DOCX) to object storage and register it in DB."""
    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "").lower()
    if ext not in ALLOWED:
        raise HTTPException(status_code=400, detail="Format non supporté. Utilisez PDF, DOC ou DOCX.")

    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Fichier trop volumineux (max 10 Mo).")

    content_type = ALLOWED[ext]
    path = f"{APP_NAME}/uploads/{current_user.id}/{uuid.uuid4()}.{ext}"

    try:
        result = await asyncio.to_thread(put_object, path, data, content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Échec de l'upload: {e}")

    db = await get_database()
    await db.files.insert_one({
        "_id": str(uuid.uuid4()),
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "owner_id": current_user.id,
        "is_deleted": False,
        "created_at": datetime.utcnow(),
    })

    return {
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
    }


async def _resolve_user(authorization: str, auth: str):
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
    elif auth:
        token = auth
    if not token:
        return None
    try:
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        email = payload.get("sub")
    except JWTError:
        return None
    if not email:
        return None
    return await get_user_by_email(email)


@router.get("/public/{path:path}")
async def public_file(path: str):
    """Serve a public asset (e.g. partner/campaign logos) without authentication."""
    db = await get_database()
    record = await db.files.find_one({"storage_path": path, "is_public": True, "is_deleted": False})
    if not record:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    try:
        content, content_type = await asyncio.to_thread(get_object, path)
    except Exception:
        raise HTTPException(status_code=404, detail="Fichier introuvable dans le stockage")
    return Response(
        content=content,
        media_type=record.get("content_type", content_type),
        headers={"Cache-Control": "public, max-age=86400"},
    )



@router.get("/{path:path}")
async def download_file(
    path: str,
    authorization: str = Header(None),
    auth: str = Query(None),
):
    """Download a stored file. Any authenticated user may download (candidate/employer)."""
    user = await _resolve_user(authorization, auth)
    if not user:
        raise HTTPException(status_code=401, detail="Authentification requise")

    db = await get_database()
    record = await db.files.find_one({"storage_path": path, "is_deleted": False})
    if not record:
        raise HTTPException(status_code=404, detail="Fichier introuvable")

    try:
        content, content_type = await asyncio.to_thread(get_object, path)
    except Exception:
        raise HTTPException(status_code=404, detail="Fichier introuvable dans le stockage")

    filename = record.get("original_filename", "cv")
    return Response(
        content=content,
        media_type=record.get("content_type", content_type),
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
