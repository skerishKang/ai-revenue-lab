"""Tests for the app factory initialization.

Covers:
- PostgreSQL runtime fail-closed
- SQLite fallback behaviors
"""
import pytest
from app.factory import create_app
from app.config import settings

def test_postgresql_startup_rejected(monkeypatch):
    """PostgreSQL app startup is explicitly rejected."""
    monkeypatch.setattr(settings, "db_backend", "postgresql")
    # Setting an arbitrary URL so pydantic validation would pass if it was re-instantiated
    monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@host/db")
    
    with pytest.raises(NotImplementedError, match="PostgreSQL runtime backend is not yet implemented"):
        create_app()

def test_sqlite_override_allowed_in_postgres_mode(monkeypatch):
    """If a test passes an explicit SQLite db_path, it's allowed even if backend is postgresql."""
    monkeypatch.setattr(settings, "db_backend", "postgresql")
    # Should not raise NotImplementedError because we provide db_path
    app = create_app(db_path=":memory:")
    assert app.state.db_path == ":memory:"
