"""Backend-neutral connection engine.

The application factory builds one engine at startup and stores it on
``app.state``; the per-request ``get_db`` dependency acquires a connection from
the engine and releases it at request end. Two engines exist:

* :class:`SQLiteEngine` -- opens a fresh file-backed connection per request
  (the existing local behaviour).
* :class:`PostgresEngine` -- borrows a connection from a small bounded pool and
  returns it at request end. The pool is sized so an idle deployment holds no
  warm connections and Neon can scale to zero.

``build_engine`` routes on the explicit ``LF_DATABASE_BACKEND`` setting; it never
infers the backend from a URL.
"""

from __future__ import annotations

from typing import Any

from app.database.base import Connection
from app.database.errors import ConfigurationError
from app.database.pool import PostgresPool


class SQLiteEngine:
    """Per-request SQLite connections (local/default backend)."""

    backend = "sqlite"

    def __init__(self, db_path: str):
        self.db_path = db_path

    def acquire(self) -> Connection:
        from app.db import get_connection  # noqa: PLC0415

        return get_connection(self.db_path)

    def release(self, conn: Connection) -> None:
        conn.close()

    def close(self) -> None:
        return None


class PostgresEngine:
    """Pooled PostgreSQL connections (production backend)."""

    backend = "postgres"

    def __init__(self, pool: PostgresPool):
        self.pool = pool

    def acquire(self) -> Connection:
        return self.pool.acquire()

    def release(self, conn: Connection) -> None:
        # For pooled connections close() returns the connection to the pool
        # rather than closing the physical connection.
        conn.close()

    def close(self) -> None:
        self.pool.close()


def build_engine(settings: Any, db_path: str) -> SQLiteEngine | PostgresEngine:
    """Build the connection engine for the configured backend.

    *db_path* is the database path already resolved by the factory (honouring
    any ``create_app(db_path=...)`` override) so the SQLite engine always targets
    the same file the startup migrations ran against.

    Fails closed on an unknown backend or a postgres backend without a runtime
    URL. The URL is never included in the error.
    """
    backend = (getattr(settings, "database_backend", "sqlite") or "").strip().lower()
    if backend == "sqlite":
        return SQLiteEngine(db_path)
    if backend == "postgres":
        url = (getattr(settings, "database_url", "") or "").strip()
        if not url:
            raise ConfigurationError(
                "postgres backend requires LF_DATABASE_URL to be set"
            )
        pool = PostgresPool(
            url,
            max_size=getattr(settings, "database_pool_max_size", 5),
        )
        pool.open()
        return PostgresEngine(pool)
    raise ConfigurationError(
        "LF_DATABASE_BACKEND must be 'sqlite' or 'postgres'"
    )
