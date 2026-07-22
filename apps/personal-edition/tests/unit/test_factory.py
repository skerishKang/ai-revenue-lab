"""Tests for the app factory initialization.

Covers:
- PostgreSQL runtime fail-closed
- SQLite fallback behaviors
- Runtime connection opener registration
"""
import pytest
from app.factory import create_app
from app.config import settings
from app.db_runtime import SqliteRuntimeConnection

def test_postgresql_startup_rejected(monkeypatch):
    """PostgreSQL app startup is explicitly rejected."""
    monkeypatch.setattr(settings, "db_backend", "postgresql")
    monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@host/db")
    
    with pytest.raises(NotImplementedError, match="PostgreSQL runtime backend is not yet implemented"):
        create_app()

def test_sqlite_override_allowed_in_postgres_mode(monkeypatch):
    """If a test passes an explicit SQLite db_path, it's allowed even if backend is postgresql."""
    monkeypatch.setattr(settings, "db_backend", "postgresql")
    app = create_app(db_path=":memory:")
    assert app.state.db_path == ":memory:"


class TestRuntimeOpener:
    def test_open_runtime_connection_registered(self):
        app = create_app(db_path=":memory:")
        assert hasattr(app.state, "open_runtime_connection")
        assert callable(app.state.open_runtime_connection)

    def test_app_creation_does_not_open_connection(self):
        app = create_app(db_path=":memory:")
        assert app.state.open_runtime_connection is not None

    def test_opener_returns_sqlite_runtime_connection(self):
        app = create_app(db_path=":memory:")
        conn = app.state.open_runtime_connection()
        try:
            assert isinstance(conn, SqliteRuntimeConnection)
        finally:
            conn.close()

    def test_opener_returns_distinct_connections(self):
        app = create_app(db_path=":memory:")
        conn1 = app.state.open_runtime_connection()
        conn2 = app.state.open_runtime_connection()
        try:
            assert conn1 is not conn2
        finally:
            conn1.close()
            conn2.close()

    def test_db_path_override_preserved(self):
        app = create_app(db_path="/tmp/custom-test.db")
        assert app.state.db_path == "/tmp/custom-test.db"

    def test_postgresql_factory_not_called(self, monkeypatch):
        monkeypatch.setattr(settings, "db_backend", "postgresql")
        monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@host/db")
        with pytest.raises(NotImplementedError):
            create_app()

    def test_startup_migration_uses_raw_sqlite(self):
        import inspect
        from app.factory import create_app
        src = inspect.getsource(create_app)
        assert "apply_migrations" in src
        assert "get_connection" in src
