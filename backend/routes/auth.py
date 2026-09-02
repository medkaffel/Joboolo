from fastapi import APIRouter, HTTPException, status, Depends
from models import (
    UserCreate, UserResponse, LoginRequest, LoginResponse, Token, User, UserUpdate
)
from database import get_database
from auth import (
    get_password_hash, authenticate_user, create_access_token,
    get_current_active_user
)
from email_utils import canonical_email
from datetime import datetime, timedelta
from pydantic import BaseModel
import httpx

EMERGENT_SESSION_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"


class GoogleSessionRequest(BaseModel):
    session_id: str


class PartnerRegisterRequest(BaseModel):
    email: str
    password: str
    first_name: str
    last_name: str = ""
    company_name: str
    signup_source: str = None
    signup_referrer: str = None
    signup_landing: str = None
    utm_source: str = None
    utm_medium: str = None
    utm_campaign: str = None


def _build_user_response(doc: dict) -> UserResponse:
    return UserResponse(
        id=doc["_id"],
        email=doc["email"],
        first_name=doc["first_name"],
        last_name=doc["last_name"],
        user_type=doc["user_type"],
        phone=doc.get("phone"),
        location=doc.get("location"),
        bio=doc.get("bio"),
        skills=doc.get("skills", []),
        experience_years=doc.get("experience_years"),
        is_active=doc["is_active"],
        is_verified=doc.get("is_verified", False),
        created_at=doc["created_at"],
        profile_photo_url=doc.get("profile_photo_url"),
        social_link_1=doc.get("social_link_1"),
        social_link_2=doc.get("social_link_2"),
        social_link_3=doc.get("social_link_3"),
    )

router = APIRouter(prefix="/auth", tags=["authentication"])

@router.post("/register", response_model=LoginResponse)
async def register(user_data: UserCreate):
    """Register a new user"""
    db = await get_database()
    
    # P0-009: canonicalize email
    email = canonical_email(user_data.email)
    
    # Check if user already exists (canonical lookup)
    existing_user = await db.users.find_one({"email": email})
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # Hash password
    hashed_password = get_password_hash(user_data.password)
    
    # Create user document with canonical email
    user_doc = {
        "_id": f"user_{email}_{hash(email)}",
        **{k: v for k, v in user_data.dict().items() if k != "email"},
        "email": email,
        "hashed_password": hashed_password,
        "is_active": True,
        "is_verified": False,
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow()
    }
    
    # Insert user
    await db.users.insert_one(user_doc)
    
    # Create access token with canonical sub
    access_token_expires = timedelta(minutes=30 * 24)  # 30 days
    access_token = create_access_token(
        data={"sub": email},
        expires_delta=access_token_expires
    )
    
    # Return user and token - fix the field mapping
    user_response = UserResponse(
        id=user_doc["_id"],
        email=user_doc["email"],
        first_name=user_doc["first_name"],
        last_name=user_doc["last_name"],
        user_type=user_doc["user_type"],
        phone=user_doc.get("phone"),
        location=user_doc.get("location"),
        bio=user_doc.get("bio"),
        skills=user_doc.get("skills", []),
        experience_years=user_doc.get("experience_years"),
        is_active=user_doc["is_active"],
        is_verified=user_doc["is_verified"],
        created_at=user_doc["created_at"]
    )
    token = Token(access_token=access_token)
    
    return LoginResponse(user=user_response, token=token)

@router.post("/register-partner")
async def register_partner(data: PartnerRegisterRequest):
    """Partner self-registration. Account is created in a PENDING state
    (is_active=False) and cannot log in until an admin validates it."""
    import uuid as _uuid
    import os
    db = await get_database()

    # P0-009: canonicalize email
    email = canonical_email(data.email)
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email déjà utilisé")

    now = datetime.utcnow()
    user_id = f"partner_{_uuid.uuid4()}"
    await db.users.insert_one({
        "_id": user_id,
        "email": email,
        "first_name": data.first_name,
        "last_name": data.last_name,
        "user_type": "partner",
        "hashed_password": get_password_hash(data.password),
        "phone": None, "location": None, "bio": None, "skills": [], "experience_years": None,
        "is_active": False,          # en attente de validation admin
        "is_verified": False,
        "pending_validation": True,
        "signup_source": data.signup_source,
        "signup_referrer": data.signup_referrer,
        "signup_landing": data.signup_landing,
        "utm_source": data.utm_source,
        "utm_medium": data.utm_medium,
        "utm_campaign": data.utm_campaign,
        "created_at": now, "updated_at": now,
    })
    await db.partner_profiles.insert_one({
        "_id": str(_uuid.uuid4()),
        "user_id": user_id,
        "company_name": data.company_name,
        "billing_mode": "per_click",
        "default_cpc": 0.0,
        "posting_price": 0.0,
        "xml_feed_url": None,
        "logo_url": None,
        "postings_remaining": 0,
        "balance": 0.0,
        "total_clicks": 0,
        "total_spent": 0.0,
        "is_active": False,
        "pending_validation": True,
        "created_at": now, "updated_at": now,
    })

    # Notify the admin (best-effort)
    try:
        from email_service import build_new_partner_email, send_alert_email
        admin_email = os.environ.get("ADMIN_EMAIL", "admin@joboolo.fr")
        app_url = os.environ.get("APP_PUBLIC_URL", "https://joboolo.fr")
        subject, html = build_new_partner_email(data.company_name, email, app_url)
        await send_alert_email(admin_email, subject, html)
    except Exception:
        pass

    return {
        "pending": True,
        "message": "Votre demande de compte partenaire a bien été reçue. Elle sera validée par notre équipe sous peu ; vous recevrez un email dès l'activation.",
    }


@router.post("/login", response_model=LoginResponse)
async def login(login_data: LoginRequest):
    """Login user"""
    user = await authenticate_user(login_data.email, login_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Votre compte est en attente de validation par notre équipe.",
        )

    # Strict role separation: if the client explicitly asks for a role,
    # the account's real type MUST match. Prevents an admin/recruteur from
    # signing in through a candidate flow (and vice versa).
    if login_data.expected_user_type:
        expected = login_data.expected_user_type.lower().strip()
        # user.user_type is a UserType enum → normalise to plain string
        actual_raw = user.user_type
        if hasattr(actual_raw, "value"):
            actual = str(actual_raw.value).lower().strip()
        else:
            actual = str(actual_raw).split(".")[-1].lower().strip()
        role_labels = {
            "candidate": "Candidat",
            "employer": "Recruteur",
            "partner": "Partenaire",
            "admin": "Administrateur",
        }
        if expected != actual:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Ce compte est de type « {role_labels.get(actual, actual or 'inconnu')} » "
                    f"et ne peut pas se connecter en tant que « {role_labels.get(expected, expected)} »."
                ),
            )
    
    # Create access token with canonical sub
    access_token_expires = timedelta(minutes=30 * 24)  # 30 days
    access_token = create_access_token(
        data={"sub": canonical_email(user.email)},
        expires_delta=access_token_expires
    )
    
    # Return user and token
    user_response = UserResponse(
        id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        user_type=user.user_type,
        phone=user.phone,
        location=user.location,
        bio=user.bio,
        skills=user.skills,
        experience_years=user.experience_years,
        is_active=user.is_active,
        is_verified=user.is_verified,
        created_at=user.created_at
    )
    token = Token(access_token=access_token)
    
    return LoginResponse(user=user_response, token=token)

@router.post("/google/session", response_model=LoginResponse)
async def google_session(payload: GoogleSessionRequest):
    """Exchange an Emergent Google session_id for the app's own JWT.
    The session-data call is made server-side, never from the frontend."""
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.get(
                EMERGENT_SESSION_URL,
                headers={"X-Session-ID": payload.session_id},
            )
        except httpx.HTTPError:
            raise HTTPException(status_code=502, detail="Auth provider unreachable")

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Session Google invalide")

    data = resp.json()
    email_raw = data.get("email")
    name = data.get("name") or ""
    if not email_raw:
        raise HTTPException(status_code=401, detail="Email Google introuvable")

    # P0-009: canonicalize email
    email = canonical_email(email_raw)

    db = await get_database()
    user_doc = await db.users.find_one({"email": email})

    if not user_doc:
        parts = name.split(" ", 1)
        first_name = parts[0] if parts and parts[0] else email.split("@")[0]
        last_name = parts[1] if len(parts) > 1 else ""
        user_doc = {
            "_id": f"user_{email}_{hash(email)}",
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "user_type": "candidate",
            "phone": None,
            "location": None,
            "bio": None,
            "skills": [],
            "experience_years": None,
            "hashed_password": "",
            "is_active": True,
            "is_verified": True,
            "oauth_provider": "google",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        await db.users.insert_one(user_doc)

    access_token = create_access_token(
        data={"sub": canonical_email(email)},
        expires_delta=timedelta(minutes=30 * 24 * 60),
    )
    return LoginResponse(user=_build_user_response(user_doc), token=Token(access_token=access_token))


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_active_user)):
    """Get current user information"""
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        user_type=current_user.user_type,
        phone=current_user.phone,
        location=current_user.location,
        bio=current_user.bio,
        skills=current_user.skills,
        experience_years=current_user.experience_years,
        is_active=current_user.is_active,
        is_verified=current_user.is_verified,
        created_at=current_user.created_at,
        profile_photo_url=getattr(current_user, "profile_photo_url", None),
        social_link_1=getattr(current_user, "social_link_1", None),
        social_link_2=getattr(current_user, "social_link_2", None),
        social_link_3=getattr(current_user, "social_link_3", None),
    )

@router.put("/me", response_model=UserResponse)
async def update_current_user(
    update_data: UserUpdate,
    current_user: User = Depends(get_current_active_user)
):
    """Update current user's profile"""
    db = await get_database()

    fields = {k: v for k, v in update_data.dict().items() if v is not None}
    fields["updated_at"] = datetime.utcnow()

    await db.users.update_one({"_id": current_user.id}, {"$set": fields})

    updated = await db.users.find_one({"_id": current_user.id})
    return UserResponse(
        id=updated["_id"],
        email=updated["email"],
        first_name=updated["first_name"],
        last_name=updated["last_name"],
        user_type=updated["user_type"],
        phone=updated.get("phone"),
        location=updated.get("location"),
        bio=updated.get("bio"),
        skills=updated.get("skills", []),
        experience_years=updated.get("experience_years"),
        is_active=updated.get("is_active", True),
        is_verified=updated.get("is_verified", False),
        created_at=updated["created_at"],
        profile_photo_url=updated.get("profile_photo_url"),
        social_link_1=updated.get("social_link_1"),
        social_link_2=updated.get("social_link_2"),
        social_link_3=updated.get("social_link_3"),
    )