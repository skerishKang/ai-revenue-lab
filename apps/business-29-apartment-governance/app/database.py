"""Database engine/session wiring.

SQLite for local dev + tests; schema is PostgreSQL-compatible by design.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import settings

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
