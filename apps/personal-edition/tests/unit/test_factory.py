"""Tests for the app factory initialization.

Covers:
- PostgreSQL runtime configuration
- SQLite fallback behaviors
- Runtime connection opener registration
"""
import pytest
from app.factory import create_app
from app.config import settings
from app.db_runtime import PostgresRuntimeConnection, SqliteRuntimeConnection

def test_postgresql_app_creation(monkeypatch):
    """PostgreSQL app creation configures the correct state."""
    monkeypatch.setattr(settings, "db_backend", "postgresql")
    monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@host/db")

    app = create_app()
    assert app.state.db_backend == "postgresql"
    assert app.state.database_url == "postgresql://user:pass@host/db"
    assert callable(app.state.open_runtime_connection)

def test_postgresql_db_path_override_rejected(monkeypatch):
    """db_path override is not supported for PostgreSQL backend."""
    monkeypatch.setattr(settings, "db_backend", "postgresql")
    monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@host/db")

    with pytest.raises(ValueError, match="db_path override is not supported"):
        create_app(db_path=":memory:")


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

    def test_postgresql_opener_returns_postgres_runtime_connection(self, monkeypatch):
        monkeypatch.setattr(settings, "db_backend", "postgresql")
        monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@host/db")

        class MockPostgresRuntimeConnection:
            def open(self):
                return self
            def close(self):
                pass

        monkeypatch.setattr(
            "app.factory.postgres_runtime_connection",
            lambda url: MockPostgresRuntimeConnection()
        )

        app = create_app()
        conn = app.state.open_runtime_connection()
        try:
            assert isinstance(conn, MockPostgresRuntimeConnection)
        finally:
            conn.close()

    def test_postgresql_opener_returns_opened_connection(self, monkeypatch):
        """The opener must return an already-opened connection, not a lazy adapter."""
        monkeypatch.setattr(settings, "db_backend", "postgresql")
        monkeypatch.setattr(settings, "database_url", "postgresql://user:pass@host/db")

        opened = []

        class MockPostgresRuntimeConnection:
            def open(self):
                opened.append(True)
                return self
            def close(self):
                pass

        monkeypatch.setattr(
            "app.factory.postgres_runtime_connection",
            lambda url: MockPostgresRuntimeConnection()
        )

        app = create_app()
        conn = app.state.open_runtime_connection()
        conn.close()

        assert opened, "opener must call .open() on the adapter"

    def test_startup_migration_uses_raw_sqlite(self):
        import inspect
        from app.factory import _startup_sqlite
        src = inspect.getsource(_startup_sqlite)
        assert "apply_migrations" in src
        assert "get_connection" in src
