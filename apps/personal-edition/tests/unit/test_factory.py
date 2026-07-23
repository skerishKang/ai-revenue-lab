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


class _FakeState:
    database_url = "postgresql://alice:s3cr3t@db.internal.example.com:5432/prod"


class _FakeApp:
    state = _FakeState()


class _OneShot:
    """Minimal cursor: fetchone returns the first row, fetchall all rows."""

    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class TestPostgresqlStartupSafeErrorBoundary:
    """Startup connect/verify failures normalize to a fixed safe error.

    The Neon contract requires that startup never expose a raw Psycopg
    message, DSN, host, username, password, SQL, or params.  Failures are
    converted to :class:`StartupDatabaseError` (category ``startup``) with
    the original exception preserved only as ``__cause__``.
    """

    def test_startup_uses_read_only_verify_not_migrate(self):
        import inspect
        from app.factory import _startup_postgresql
        src = inspect.getsource(_startup_postgresql)
        assert "verify_pg_schema" in src
        assert "apply_pg_migrations" not in src

    def test_connect_failure_raises_safe_startup_error(self, monkeypatch):
        import psycopg
        from app.factory import _startup_postgresql
        from app.db_runtime import StartupDatabaseError

        secret = _FakeState.database_url

        def boom(url):
            raise psycopg.OperationalError(f"connection to {secret} failed")

        monkeypatch.setattr("app.db_postgres.get_pg_connection", boom)

        with pytest.raises(StartupDatabaseError) as excinfo:
            _startup_postgresql(_FakeApp())

        err = excinfo.value
        assert err.safe_category == "startup"
        text = f"{str(err)} {repr(err)}"
        assert "s3cr3t" not in text
        assert "postgresql://" not in text
        assert "db.internal.example.com" not in text
        assert isinstance(err.__cause__, psycopg.OperationalError)

    def test_verify_failure_raises_safe_startup_error(self, monkeypatch):
        from app.factory import _startup_postgresql
        from app.db_pg_migrations import PgMigrationError
        from app.db_runtime import StartupDatabaseError

        class _NullSchemaConn:
            """dict_row-shaped fake whose current_schema() is NULL.

            This drives the REAL verify_pg_schema down its fail-closed path
            (NULL effective schema -> PgMigrationError) without monkeypatching
            the verifier, so the test is immune to module re-import pollution.
            """

            closed = False

            def execute(self, sql, params=None):
                norm = " ".join(sql.split()).lower()
                if "current_schema() as schema" in norm:
                    return _OneShot([{"schema": None}])
                raise AssertionError(f"unexpected SQL: {sql!r}")

            def close(self):
                self.closed = True

        fake_conn = _NullSchemaConn()
        monkeypatch.setattr(
            "app.db_postgres.get_pg_connection", lambda url: fake_conn
        )

        with pytest.raises(StartupDatabaseError) as excinfo:
            _startup_postgresql(_FakeApp())

        assert excinfo.value.safe_category == "startup"
        assert isinstance(excinfo.value.__cause__, PgMigrationError)
        assert fake_conn.closed, "startup must close the connection on failure"

    def test_startup_error_str_repr_are_fixed_safe_text(self):
        from app.db_runtime import StartupDatabaseError

        err = StartupDatabaseError()
        assert str(err) == "database error (category=startup)"
        assert "category=startup" in repr(err)
