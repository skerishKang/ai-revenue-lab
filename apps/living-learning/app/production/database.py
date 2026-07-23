"""PostgreSQL backend for Living Learning (production parity).

The existing repositories are written against the ``sqlite3.Connection`` surface
(``execute`` with ``?`` placeholders, dict-style rows, ``commit``/``rollback``/
``close``, ``BEGIN IMMEDIATE``). ``PostgresConnection`` presents that same
surface over ``psycopg`` so the repositories run unchanged on PostgreSQL.

Conventions:
  * ``psycopg`` is imported lazily — the SQLite path never needs the driver.
  * SQL is adapted structurally (``?`` -> ``%s``, ``INSERT OR IGNORE`` ->
    ``ON CONFLICT DO NOTHING``), never by naive string replacement.
  * The connection runs in autocommit so explicit ``BEGIN``/``COMMIT`` control
    transactions (matching SQLite's ``in_transaction`` semantics).
  * Errors are translated to neutral, credential-free exceptions.
  * The pool is tuned for Neon scale-to-zero (``min_size=0``, short idle).
"""

from __future__ import annotations

from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Neutral errors (the only error surface repositories depend on).
# ---------------------------------------------------------------------------
class DatabaseError(Exception):
    """Base database error. Messages never include URLs or credentials."""


class IntegrityError(DatabaseError):
    """Constraint violation (unique/FK/check). Translated from the driver."""


class ConfigurationError(DatabaseError):
    """Invalid backend configuration. Messages never include URLs/credentials."""


class SchemaMismatchError(DatabaseError):
    """Schema missing or behind the expected migration state (fail-closed)."""


# ---------------------------------------------------------------------------
# Secret-safe URL handling.
# ---------------------------------------------------------------------------
def redact_url(url: str) -> str:
    """Replace an embedded password with ``***``; never raise on a bad URL."""
    try:
        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(url)
        if parts.password:
            netloc = parts.netloc.replace(f":{parts.password}@", ":***@", 1)
            return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
        return url
    except Exception:
        return "<redacted>"


def is_postgres_url(url: str) -> bool:
    u = (url or "").strip().lower()
    return u.startswith("postgresql://") or u.startswith("postgres://")


# ---------------------------------------------------------------------------
# Structural SQL adaptation (sqlite -> postgres).
# ---------------------------------------------------------------------------
def translate_placeholders(sql: str) -> str:
    """Translate sqlite ``?`` placeholders to psycopg ``%s`` structurally.

    Tracks single-quoted string literals (with ``''`` escapes) and
    double-quoted identifiers so ``?``/``%`` inside them are left untouched.
    Literal ``%`` outside strings is escaped to ``%%`` for psycopg.
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    in_single = False
    in_double = False
    while i < n:
        ch = sql[i]
        if in_single:
            out.append(ch)
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            out.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue
        if ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue
        if ch == "?":
            out.append("%s")
            i += 1
            continue
        if ch == "%":
            out.append("%%")
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def translate_insert_or_ignore(sql: str) -> str:
    """Rewrite ``INSERT OR IGNORE`` -> ``INSERT ... ON CONFLICT DO NOTHING``."""
    stripped = sql.lstrip()
    upper = stripped.upper()
    if upper.startswith("INSERT OR IGNORE"):
        # Replace the leading "INSERT OR IGNORE" with "INSERT".
        idx = sql.upper().find("INSERT OR IGNORE")
        rewritten = sql[:idx] + "INSERT" + sql[idx + len("INSERT OR IGNORE"):]
        return rewritten.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


def adapt_sql_for_postgres(sql: str) -> str:
    return translate_placeholders(translate_insert_or_ignore(sql))


# ---------------------------------------------------------------------------
# Cursor / row adapters.
# ---------------------------------------------------------------------------
class PostgresCursor:
    def __init__(self, raw) -> None:
        self._raw = raw

    @property
    def rowcount(self) -> int:
        return self._raw.rowcount if self._raw.rowcount is not None else 0

    def fetchone(self):
        return self._raw.fetchone()

    def fetchall(self):
        return self._raw.fetchall()


class PostgresConnection:
    """A ``sqlite3.Connection``-compatible wrapper over a psycopg connection.

    Rows are dict rows (``row["col"]``). ``execute`` adapts SQL and translates
    integrity errors. ``PRAGMA`` statements are no-ops; ``BEGIN IMMEDIATE`` maps
    to a plain ``BEGIN`` (uniqueness constraints provide the serialization).
    """

    def __init__(self, raw) -> None:
        self._raw = raw
        self._in_transaction = False

    @property
    def raw(self):
        return self._raw

    @property
    def in_transaction(self) -> bool:
        return self._in_transaction

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> PostgresCursor:
        stripped = sql.strip()
        upper = stripped.upper()
        # PRAGMA is SQLite-specific; ignore for Postgres.
        if upper.startswith("PRAGMA"):
            return PostgresCursor(_NullCursor())
        # Transaction control.
        if upper.startswith("BEGIN"):
            if not self._in_transaction:
                self._raw.execute("BEGIN")
                self._in_transaction = True
            return PostgresCursor(_NullCursor())
        if upper.startswith("COMMIT") or upper.startswith("END"):
            if self._in_transaction:
                self._raw.execute("COMMIT")
                self._in_transaction = False
            return PostgresCursor(_NullCursor())
        if upper.startswith("ROLLBACK"):
            if self._in_transaction:
                self._raw.execute("ROLLBACK")
                self._in_transaction = False
            return PostgresCursor(_NullCursor())

        adapted = adapt_sql_for_postgres(stripped)
        params = tuple(parameters) if parameters else ()
        try:
            cur = self._raw.execute(adapted, params)
            return PostgresCursor(cur)
        except Exception as exc:  # noqa: BLE001 - translate to neutral error
            if _is_integrity_error(exc):
                raise IntegrityError("constraint violation") from exc
            raise DatabaseError("database error") from exc

    def commit(self) -> None:
        if self._in_transaction:
            self._raw.execute("COMMIT")
            self._in_transaction = False

    def rollback(self) -> None:
        if self._in_transaction:
            self._raw.execute("ROLLBACK")
            self._in_transaction = False

    def close(self) -> None:
        try:
            if self._in_transaction:
                self.rollback()
        finally:
            self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


class _NullCursor:
    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []


def _is_integrity_error(exc: Exception) -> bool:
    try:
        from psycopg import errors as pg_errors

        return isinstance(
            exc,
            (pg_errors.IntegrityError, pg_errors.UniqueViolation, pg_errors.ForeignKeyViolation, pg_errors.CheckViolation),
        )
    except Exception:
        return "integrity" in type(exc).__name__.lower() or "violation" in str(exc).lower()


# ---------------------------------------------------------------------------
# Connection / pool factories.
# ---------------------------------------------------------------------------
def connect_postgres(url: str, *, autocommit: bool = True) -> PostgresConnection:
    """Open a single direct PostgreSQL connection (migration-owner style)."""
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - driver optional
        raise ConfigurationError("psycopg driver not installed") from exc
    try:
        raw = psycopg.connect(url, autocommit=autocommit, row_factory=dict_row, prepare_threshold=None)
    except Exception as exc:  # noqa: BLE001 - never echo the URL
        raise ConfigurationError("could not connect to postgres") from exc
    return PostgresConnection(raw)


class PostgresPool:
    """A bounded psycopg pool tuned for Neon scale-to-zero.

    ``min_size=0`` + short ``max_idle`` let the pool drain to zero so Neon can
    suspend; ``prepare_threshold=None`` is pgbouncer/Neon safe.
    """

    def __init__(self, url: str, *, min_size: int = 0, max_size: int = 5, timeout: float = 5.0, max_idle: float = 60.0, max_lifetime: float = 300.0) -> None:
        try:
            from psycopg_pool import ConnectionPool
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - driver optional
            raise ConfigurationError("psycopg-pool not installed") from exc
        self._url = url
        try:
            self._pool = ConnectionPool(
                conninfo=url,
                kwargs={"autocommit": True, "row_factory": dict_row, "prepare_threshold": None},
                min_size=min_size,
                max_size=max_size,
                timeout=timeout,
                max_idle=max_idle,
                max_lifetime=max_lifetime,
                open=False,
            )
        except Exception as exc:  # noqa: BLE001
            raise ConfigurationError("could not create postgres pool") from exc

    def open(self) -> None:
        self._pool.open()

    def close(self) -> None:
        self._pool.close()

    def acquire(self) -> PostgresConnection:
        raw = self._pool.getconn()
        return _PooledPostgresConnection(raw, self._pool)


class _PooledPostgresConnection(PostgresConnection):
    def __init__(self, raw, pool) -> None:
        super().__init__(raw)
        self._pool = pool

    def close(self) -> None:
        try:
            if self._in_transaction:
                self.rollback()
        finally:
            self._pool.putconn(self._raw)
