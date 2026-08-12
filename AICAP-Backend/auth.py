"""
Auth Middleware — AICAP-Backend
===============================
JWT issuance/verification, Google OAuth client registration, and
Role-Based Access Control (RBAC) dependencies for Module 1.
"""

import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from jose import jwt, JWTError

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from authlib.integrations.starlette_client import OAuth
from starlette.config import Config

from database import get_db
from models import User, RoleEnum

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-jwt-key-for-development")

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

security = HTTPBearer()

config = Config(".env")

oauth = OAuth(config)

oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID", ""),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET", ""),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# ==========================================
# Token issuance / verification
# ==========================================

def create_access_token(user: User) -> str:
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    role_value = user.role.value if hasattr(user.role, "value") else str(user.role)

    payload = {
        "id": user.id,
        "sub": user.email,
        "role": role_value,
        "exp": expire,
    }

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """Decode and validate the JWT. Returns the raw payload (id/sub/role/exp)."""
    token = credentials.credentials

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload

    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or Expired Token",
        )


def get_current_user(
    payload: dict = Depends(verify_token),
    db: Session = Depends(get_db),
) -> User:
    """
    DB-backed dependency: use this whenever a route needs the live user row
    rather than just the JWT claims.
    """
    user_id = payload.get("id")
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
        )

    return user


# ==========================================
# RBAC
# ==========================================

def require_role(*allowed_roles: str):
    """
    Dependency factory for RBAC. Accepts one or more roles:
        Depends(require_role("ADMIN"))
        Depends(require_role("ADMIN", "WELLNESS_COACH"))
    Raises 403 if the caller's JWT role isn't in the allowed set.
    """
    normalized_allowed = {
        r.value if isinstance(r, RoleEnum) else str(r) for r in allowed_roles
    }

    def checker(user_payload: dict = Depends(verify_token)) -> dict:
        if user_payload.get("role") not in normalized_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access Denied",
            )
        return user_payload

    return checker