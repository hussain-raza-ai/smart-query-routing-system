"""
Authentication endpoints (FR-01).

The browser signs the user in with Google and sends us the resulting ID
token. We verify it against Google's public keys, find or register the
user, and return our own short-lived JWT for all further requests.
No password is ever seen or stored by this system.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from google.auth.exceptions import TransportError
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import Role
from app.core.security import create_access_token, get_current_user
from app.database import get_db
from app.models.models import User
from app.services.audit import record_action

router = APIRouter(prefix="/auth", tags=["Authentication"])


class GoogleLoginRequest(BaseModel):
    credential: str = Field(..., min_length=20, description="Google ID token from the sign-in button")


def user_profile(user: User) -> dict:
    """Public view of a user, safe to send to the browser."""
    department = user.department
    return {
        "user_id": user.user_id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "department_id": user.department_id,
        "department_name": department.name if department else None,
        "department_type": department.type if department else None,
        "on_leave": user.is_on_leave(),
        "leave_from": user.leave_from,
        "leave_until": user.leave_until,
        "auto_reply_message": user.auto_reply_message,
    }


def _verify_google_token(credential: str) -> dict:
    """Check the token's signature, expiry and audience with Google."""
    try:
        return id_token.verify_oauth2_token(
            credential,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
            clock_skew_in_seconds=10,  # tolerate small differences in PC clocks
        )
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Google sign-in could not be verified. Please try again.")
    except TransportError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Could not reach Google to verify the sign-in.")


def _register_new_user(db: Session, email: str, name: str) -> User:
    """
    Create an account on first sign-in, or refuse it.

    - Emails listed in BOOTSTRAP_ADMIN_EMAILS become Admin.
    - Emails from an allowed domain become Student.
    - Everyone else must be added by the Admin first (SRS UC-01).
    """
    domain = email.rsplit("@", 1)[-1]
    if email in settings.BOOTSTRAP_ADMIN_EMAILS:
        role = Role.ADMIN
    elif domain in settings.ALLOWED_EMAIL_DOMAINS:
        role = Role.STUDENT
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="This account is not registered. Please sign in with your "
                                   "university email or contact the administrator.")

    user = User(name=name[:100], email=email, role=role)
    db.add(user)
    db.flush()  # assigns user_id so the audit entry can reference it
    record_action(db, "USER_REGISTERED", user_id=user.user_id, details=f"Self-registered as {role}")
    return user


@router.post("/google")
def login_with_google(body: GoogleLoginRequest, db: Session = Depends(get_db)):
    claims = _verify_google_token(body.credential)
    if not claims.get("email_verified"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Your Google email address is not verified.")

    email = claims["email"].strip().lower()
    name = claims.get("name") or email.split("@")[0]

    user = db.query(User).filter(func.lower(User.email) == email).first()
    if user is None:
        user = _register_new_user(db, email, name)
    elif not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Your account has been deactivated. Please contact the administrator.")

    record_action(db, "LOGIN", user_id=user.user_id, details=f"Signed in with Google as {user.role}")
    db.commit()

    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "user": user_profile(user),
    }


@router.get("/me")
def read_my_profile(user: User = Depends(get_current_user)):
    return user_profile(user)


@router.post("/logout")
def logout(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Tokens are stateless, so the browser simply discards its copy.
    This endpoint exists to record the logout in the audit trail.
    """
    record_action(db, "LOGOUT", user_id=user.user_id)
    db.commit()
    return {"message": "Signed out"}
    

@router.get("/config")
def sign_in_config():
    """What the sign-in page needs to show the Google button. A client ID is public by design."""
    return {"google_client_id": settings.GOOGLE_CLIENT_ID}