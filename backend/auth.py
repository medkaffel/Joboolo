from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import ValidationError
from passlib.context import CryptContext
from jose import JWTError, jwt
from models import User, TokenData
from database import get_database
from email_utils import canonical_email

# Configuration (P0-001 : source unique, aucun secret codé en dur).
# SECRET_KEY est peuplé dynamiquement par la config centralisée et validé au
# démarrage ; il n'existe aucun fallback codé en dur.
def get_secret_key() -> str:
    """Retourne la clé de signature JWT, obligatoire dans tous les environnements."""
    from config import get_settings
    key = get_settings().SECRET_KEY
    if not key:
        # Ne jamais retomber sur un secret connu ; la validation de présence est
        # aussi effectuée au démarrage (validate_startup_config).
        raise RuntimeError("SECRET_KEY non configurée (obligatoire dans tous les environnements).")
    return key

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 * 24  # 30 days

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Bearer token
security = HTTPBearer()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash"""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash a password"""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Create access token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, get_secret_key(), algorithm=ALGORITHM)
    return encoded_jwt

async def get_user_by_email(email: str) -> Optional[User]:
    """Get user by email (P0-009: canonical lookup).

    Returns a strict ``User`` for legitimate full accounts.  Raises
    ``LookupAggregationError`` or ``LookupCollisionError`` on ambiguous
    states — callers MUST propagate or fail-closed.
    """
    from email_utils import lookup_user_by_email
    return await lookup_user_by_email(email)


def _user_from_raw_doc(doc: dict) -> Optional[User]:
    """Build a strict ``User`` from a raw Mongo document, returning ``None``
    if the document is incomplete (lightweight/OAuth/XML account).

    This is used by paths that need a full ``User`` model but where the
    document may be incomplete.  Returning ``None`` is fail-closed:
    the caller treats the account as non-selectable rather than crashing.
    """
    if doc is None:
        return None
    from models import User
    try:
        return User(**doc)
    except ValidationError:
        # Document is incomplete — account is lightweight, cannot be
        # represented as a strict User.  Fail closed.
        return None


async def authenticate_user(email: str, password: str) -> Optional[User]:
    """Authenticate user with email and password (P0-009: canonical lookup).

    Uses the raw-doc lookup so lightweight accounts (OAuth-only, XML
    login-less) with ``hashed_password=None`` do not raise a
    ``ValidationError`` during login.

    Raises ``LookupAggregationError`` or ``LookupCollisionError`` on
    ambiguous lookup states — callers MUST propagate or fail-closed.
    """
    from email_utils import lookup_user_doc_by_email
    doc = await lookup_user_doc_by_email(email)
    if doc is None:
        return None
    if not doc.get("hashed_password"):
        # OAuth-only account (e.g. Google) has no password
        return None
    if not verify_password(password, doc["hashed_password"]):
        return None
    return _user_from_raw_doc(doc)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> User:
    """Get current authenticated user"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(token, get_secret_key(), algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        # P0-009: normalize JWT sub to canonical form before lookup
        email = canonical_email(email)
        token_data = TokenData(email=email)
    except (JWTError, ValueError):
        raise credentials_exception
    
    # P0-009: use the tolerant raw-doc lookup so lightweight accounts
    # (e.g. XML partners / OAuth) do not raise a ValidationError here.
    # LookupAggregationError / LookupCollisionError must map to a
    # controlled 503 (consistent with /auth/login), never a raw 500.
    from email_utils import lookup_user_doc_by_email, LookupAggregationError, LookupCollisionError
    try:
        doc = await lookup_user_doc_by_email(email=token_data.email)
    except (LookupAggregationError, LookupCollisionError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email lookup temporarily unavailable, please retry"
        )
    if doc is None:
        # Email unknown — the JWT cannot be resolved.
        raise credentials_exception

    user = _user_from_raw_doc(doc)
    if user is None:
        # Lightweight/incomplete account — cannot be represented / used as
        # an authenticated session; fail closed.
        raise credentials_exception
    return user

async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    """Get current active user"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

def require_employer(current_user: User = Depends(get_current_active_user)) -> User:
    """Require employer role"""
    if current_user.user_type not in ["employer", "admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions"
        )
    return current_user

def require_admin(current_user: User = Depends(get_current_active_user)) -> User:
    """Require admin role"""
    if current_user.user_type != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Réservé à l'administrateur"
        )
    return current_user