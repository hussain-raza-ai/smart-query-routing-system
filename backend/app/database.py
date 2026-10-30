"""
Database engine and session handling.

Routes receive a session through the `get_db` dependency. The session is
always closed after the request finishes, even when an error is raised.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,   # Supabase closes idle connections; test before reuse
    pool_recycle=1800,    # refresh connections every 30 minutes
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()