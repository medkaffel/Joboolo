from datetime import datetime, timedelta
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
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

    Raises ``LookupAggregationError`` or ``LookupCollisionError`` on
    ambiguous states — callers MUST propagate or fail-closed.
    """
    from email_utils import lookup_user_by_email
    return await lookup_user_by_email(email)

async def authenticate_user(email: str, password: str) -> Optional[User]:
    """Authenticate user with email and password (P0-009: canonical lookup).

    Raises ``LookupAggregationError`` or ``LookupCollisionError`` on
    ambiguous lookup states — callers MUST propagate or fail-closed.
    """
    user = await get_user_by_email(email)
    if not user:
        return None
    if not user.hashed_password:
        # OAuth-only account (e.g. Google) has no password
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user

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
    
    user = await get_user_by_email(email=token_data.email)
    if user is None:
        # P0-009: LookupAggregationError / LookupCollisionError propagate
        # up as unhandled exceptions (HTTP 500) — the JWT cannot be
        # resolved safely, so we MUST NOT select or create an account.
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