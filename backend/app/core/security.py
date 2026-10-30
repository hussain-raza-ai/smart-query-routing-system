"""
Authentication helpers: issuing and checking JWT session tokens, and the
FastAPI dependencies that protect routes by role.

Flow: the frontend obtains a Google ID token, the /auth/google endpoint
verifies it and returns our own signed JWT. Every protected request then
sends that JWT in the `Authorization: Bearer <token>` header.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.models.models import User

JWT_ALGORITHM = "HS256"

# Reads the "Authorization: Bearer <token>" header and adds the
# "Authorize" button to the /docs page.
bearer_scheme = HTTPBearer(auto_error=False, description="Access token returned by /auth/google")


def create_access_token(user: User) -> str:
    """Issue a signed session token for the given user."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.user_id),
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(hours=settings.JWT_EXPIRE_HOURS),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Resolve the logged-in user from the Bearer token.

    The role is always read from the database, not from the token, so a role
    change or deactivation by the Admin takes effect on the very next request.
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing or malformed token")
    try:
        payload = jwt.decode(credentials.credentials, settings.JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Account not found or deactivated")
    return user


def require_roles(*allowed_roles: str):
    """Dependency factory: only users with one of `allowed_roles` may continue."""

    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="Your role is not allowed to perform this action")
        return user

    return checker


def require_service_key(x_service_key: Optional[str] = Header(default=None)) -> None:
    """Protect machine-to-machine endpoints that only n8n should call."""
    expected = settings.SERVICE_KEY
    if not expected or not secrets.compare_digest(x_service_key or "", expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid service key")