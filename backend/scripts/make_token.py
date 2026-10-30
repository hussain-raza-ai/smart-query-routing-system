"""
Development helper: prints an access token for an existing user, so the API
can be tried on the /docs page as that user. Demo accounts (@example.com)
cannot sign in with Google, so this is the way to act as them.

It reads JWT_SECRET from .env, so it only works on a machine that already
holds the server's secrets. Never use it in production.

Usage (from the backend folder):
    .\\venv\\Scripts\\python.exe -m scripts.make_token demo.student@example.com
"""
import sys

from app.core.config import settings
from app.core.security import create_access_token
from app.database import SessionLocal
from app.models.models import User


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.make_token <email>")
        return

    email = sys.argv[1].strip().lower()
    with SessionLocal() as db:
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            print(f"No user with email {email}")
            return
        print(f"Token for {user.name} ({user.role}), valid for {settings.JWT_EXPIRE_HOURS} hours:\n")
        print(create_access_token(user))


if __name__ == "__main__":
    main()