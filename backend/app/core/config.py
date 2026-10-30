"""
Application settings.

All configuration is read from environment variables: the `.env` file during
development and the hosting dashboard in production. Required values are
checked when the app starts, so a missing key fails immediately with a clear
message instead of surfacing later as a confusing runtime error.
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable '{name}' is required but not set.")
    return value


def _optional(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    return value or default


def _list(name: str) -> list[str]:
    """Read a comma-separated value such as 'a.com, b.com' into a clean list."""
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


class Settings:
    # Database
    DATABASE_URL = _required("DATABASE_URL")

    # Authentication
    GOOGLE_CLIENT_ID = _required("GOOGLE_CLIENT_ID")
    JWT_SECRET = _required("JWT_SECRET")
    JWT_EXPIRE_HOURS = int(_optional("JWT_EXPIRE_HOURS", "8"))
    ALLOWED_EMAIL_DOMAINS = [d.lower() for d in _list("ALLOWED_EMAIL_DOMAINS")]
    BOOTSTRAP_ADMIN_EMAILS = [e.lower() for e in _list("BOOTSTRAP_ADMIN_EMAILS")]

    # AI providers: Gemini is primary, Claude double-checks low-confidence results
    GEMINI_API_KEY = _optional("GEMINI_API_KEY")
    GEMINI_MODEL = _optional("GEMINI_MODEL", "gemini-2.5-flash")
    ANTHROPIC_API_KEY = _optional("ANTHROPIC_API_KEY")
    CLAUDE_MODEL = _optional("CLAUDE_MODEL")
    AI_CONFIDENCE_THRESHOLD = float(_optional("AI_CONFIDENCE_THRESHOLD", "0.70"))

    # n8n integration
    N8N_WEBHOOK_URL = _optional("N8N_WEBHOOK_URL")
    N8N_WEBHOOK_SECRET = _optional("N8N_WEBHOOK_SECRET")
    SERVICE_KEY = _optional("SERVICE_KEY")

    # General
    CORS_ORIGINS = _list("CORS_ORIGINS")
    SLA_HOURS = int(_optional("SLA_HOURS", "24"))


settings = Settings()