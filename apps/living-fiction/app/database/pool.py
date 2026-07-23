"""Bounded PostgreSQL connection pool tuned for Neon scale-to-zero.

The pool is deliberately small and eager to release idle connections so an idle
deployment holds no open connections and the Neon compute can suspend
(scale-to-zero). Key choices:

* ``min_size=0`` -- the pool never keeps warm connections; it creates them on
  demand and can drain to zero.
* short ``max_idle`` -- a connection unused for this long is closed by the pool,
  freeing the Neon backend to suspend.
* moderate ``max_lifetime`` -- connections are recycled so a pool that outlives
  a Neon suspend/resume cycle does not hand out a dead connection.
* bounded ``max_size`` and ``timeout`` -- a hard cap on concurrent DB
  connections and a short wait for a free connection, so a burst fails fast
  rather than accumulating unbounded load.

Connections handed out by :meth:`PostgresPool.acquire` are returned to the pool
(not physically closed) when the caller calls ``close()``, matching the
per-request ``get_db`` lifecycle.
"""

from __future__ import annotations

from typing import Any

from app.database.errors import ConfigurationError
from app.database.postgres import PostgresConnection, _import_psycopg

DEFAULT_POOL_MIN_SIZE = 0
DEFAULT_POOL_MAX_SIZE = 5
DEFAULT_POOL_TIMEOUT = 5.0
DEFAULT_POOL_MAX_IDLE = 60.0
DEFAULT_POOL_MAX_LIFETIME = 300.0


class _PooledPostgresConnection(PostgresConnection):
    """A pooled connection whose ``close()`` returns it to the pool."""

    def __init__(self, raw: Any, pool: Any):
        super().__init__(raw)
        self._pool = pool

    def close(self) -> None:
        try:
            if self.in_transaction:
                self.rollback()
        finally:
            self._pool.putconn(self._raw)


class PostgresPool:
    """A small, scale-to-zero-friendly Psycopg connection pool."""

    def __init__(
        self,
        url: str,
        *,
        min_size: int = DEFAULT_POOL_MIN_SIZE,
        max_size: int = DEFAULT_POOL_MAX_SIZE,
        timeout: float = DEFAULT_POOL_TIMEOUT,
        max_idle: float = DEFAULT_POOL_MAX_IDLE,
        max_lifetime: float = DEFAULT_POOL_MAX_LIFETIME,
    ):
        if max_size < 1:
            raise ConfigurationError("database pool max_size must be >= 1")
        if min_size < 0 or min_size > max_size:
            raise ConfigurationError(
                "database pool min_size must be between 0 and max_size"
            )
        _import_psycopg()
        from psycopg.rows import dict_row  # noqa: PLC0415
        from psycopg_pool import ConnectionPool  # noqa: PLC0415

        self._pool = ConnectionPool(
            conninfo=url,
            kwargs={"autocommit": True, "row_factory": dict_row},
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            max_idle=max_idle,
            max_lifetime=max_lifetime,
            open=False,
        )

    def open(self) -> None:
        self._pool.open()

    def acquire(self) -> PostgresConnection:
        """Acquire a connection from the pool (bounded wait)."""
        raw = self._pool.getconn()
        return _PooledPostgresConnection(raw, self._pool)

    def close(self) -> None:
        self._pool.close()

    @property
    def raw(self) -> Any:
        return self._pool
