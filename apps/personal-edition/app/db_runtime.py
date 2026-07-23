"""Backend-neutral runtime connection boundary for Personal Edition.

This module defines the narrow contract that the existing repositories
already rely on (``execute`` / ``commit`` / ``rollback`` / ``close`` /
``in_transaction`` / cursor ``rowcount`` / ``fetchone`` / ``fetchall`` /
``row["column"]``) and provides two concrete implementations:

* :class:`SqliteRuntimeConnection` — a thin boundary over the existing
  :func:`app.db.get_connection`.  SQLite behaviour is preserved exactly:
  ``sqlite3.Row`` rows, existing PRAGMA/migration behaviour, no SQL
  transformation, and raw SQLite errors are left untouched.
* :class:`PostgresRuntimeConnection` — an adapter over a psycopg 3 sync
  connection (``dict_row``) that makes the same repository connection
  shape work against PostgreSQL.

The PostgreSQL adapter is intentionally limited to the runtime boundary:

* **No import-time connection.**  Importing this module never opens a
  network connection.  A connection is only opened when an explicit
  factory/callable is invoked (``open()`` or :func:`open_postgres_runtime`).
* **Explicit write transaction.**  ``begin_write()`` starts a real
  transaction; the legacy ``execute("BEGIN IMMEDIATE")`` is forwarded to
  ``begin_write()`` and is never consumed as a no-op.
* **qmark -> %s placeholder translation** via a small quote/comment aware
  lexer (values always travel through the parameterized API).
* **Backend-neutral errors.**  Driver failures are normalized to
  :class:`DatabaseIntegrityError` / :class:`DatabaseError` with safe
  metadata only; no DSN, credential, SQL, parameter, or raw driver text is
  ever placed in ``str``/``repr``.

This commit does NOT switch any repository, route, pipeline, or the
application factory to PostgreSQL; application startup remains fail-closed.
"""

from __future__ import annotations

import enum
import re
import sqlite3
from typing import Any, Protocol, Sequence

import psycopg
from psycopg import errors as _pg_errors
from psycopg.pq import TransactionStatus as _PgTxStatus

from app import db as _sqlite_db
from app import db_postgres as _pg_db


__all__ = [
    "RuntimeCursor",
    "RuntimeConnection",
    "PlaceholderError",
    "translate_placeholders",
    "DatabaseError",
    "DatabaseIntegrityError",
    "RuntimeTransactionError",
    "classify_pg_error",
    "SqliteRuntimeConnection",
    "sqlite_runtime_connection",
    "PostgresRuntimeConnection",
    "open_postgres_runtime",
]


# ---------------------------------------------------------------------------
# Runtime protocol (structural typing only — not runtime_checkable)
# ---------------------------------------------------------------------------


class RuntimeCursor(Protocol):
    """Minimal cursor shape the repositories consume."""

    @property
    def rowcount(self) -> int: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> list[Any]: ...


class RuntimeConnection(Protocol):
    """Minimal connection shape the repositories consume.

    ``begin_write`` is the explicit write-transaction contract.  ``execute``
    accepts qmark (``?``) placeholders for both backends; the PostgreSQL
    adapter translates them, SQLite passes them through unchanged.
    ``row_lock_suffix`` provides the backend-appropriate row-locking clause
    for SELECT statements inside write transactions.
    """

    @property
    def in_transaction(self) -> bool: ...

    @property
    def row_lock_suffix(self) -> str: ...

    def execute(self, sql: str, params: Sequence[Any] = ()) -> RuntimeCursor: ...

    def begin_write(self) -> None: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Placeholder translation (qmark "?" -> psycopg "%s")
# ---------------------------------------------------------------------------


class PlaceholderError(ValueError):
    """Raised when qmark placeholder translation or binding is invalid.

    The message only ever contains structural counts/positions — never SQL
    values, parameters, or connection details.
    """


# A dollar-quote opener/closer: ``$$`` or ``$tag$`` (tag is an identifier
# that does not start with a digit).
_DOLLAR_TAG_RE = re.compile(r"\$([A-Za-z_]\w*)?\$")


def translate_placeholders(sql: str) -> tuple[str, int]:
    """Translate qmark ``?`` placeholders to psycopg ``%s`` placeholders.

    Only ``?`` characters that appear *outside* of string literals, quoted
    identifiers, comments, and dollar-quoted strings are translated.  The
    lexer recognises:

    * single-quoted string literals with ``''`` escaped quotes,
    * double-quoted identifiers with ``""`` escaped quotes,
    * ``-- ...`` line comments,
    * ``/* ... */`` block comments (nested),
    * PostgreSQL dollar-quoted strings (``$$ ... $$`` / ``$tag$ ... $tag$``).

    Returns ``(translated_sql, placeholder_count)``.

    Raises
    ------
    PlaceholderError
        If a string literal, quoted identifier, comment, or dollar-quoted
        string is unterminated.

    Notes
    -----
    Literal ``%`` characters are not escaped by this boundary.  The current
    runtime repository SQL contains no literal ``%``; a future statement
    that needs one must address psycopg percent-escaping explicitly.
    """
    out: list[str] = []
    count = 0
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]

        # Line comment: -- to end of line.
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            if j == -1:
                out.append(sql[i:])
                i = n
            else:
                out.append(sql[i : j + 1])
                i = j + 1
            continue

        # Block comment: /* ... */ with nesting support.
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            depth = 1
            j = i + 2
            while j + 1 < n and depth > 0:
                if sql[j] == "/" and sql[j + 1] == "*":
                    depth += 1
                    j += 2
                elif sql[j] == "*" and sql[j + 1] == "/":
                    depth -= 1
                    j += 2
                else:
                    j += 1
            if depth > 0:
                raise PlaceholderError("unterminated block comment")
            out.append(sql[i:j])
            i = j
            continue

        # Single-quoted string literal ('' is an escaped quote).
        if ch == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise PlaceholderError("unterminated string literal")
            out.append(sql[i : j + 1])
            i = j + 1
            continue

        # Double-quoted identifier ("" is an escaped quote).
        if ch == '"':
            j = i + 1
            while j < n:
                if sql[j] == '"':
                    if j + 1 < n and sql[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            if j >= n:
                raise PlaceholderError("unterminated quoted identifier")
            out.append(sql[i : j + 1])
            i = j + 1
            continue

        # Dollar-quoted string: $tag$ ... $tag$ (tag may be empty).
        if ch == "$":
            m = _DOLLAR_TAG_RE.match(sql, i)
            if m is not None:
                tag = m.group(0)
                close = sql.find(tag, i + len(tag))
                if close == -1:
                    raise PlaceholderError("unterminated dollar-quoted string")
                end = close + len(tag)
                out.append(sql[i:end])
                i = end
                continue
            out.append(ch)
            i += 1
            continue

        # A genuine placeholder.
        if ch == "?":
            out.append("%s")
            count += 1
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out), count


def _normalize_params(params: Sequence[Any] | None) -> tuple[Any, ...]:
    if params is None:
        return ()
    if isinstance(params, dict):
        raise PlaceholderError(
            "named/dict parameters are not supported by the qmark "
            "runtime boundary"
        )
    if isinstance(params, (str, bytes, bytearray)):
        raise PlaceholderError(
            "params must be a positional sequence (tuple/list), "
            "not a scalar or byte container"
        )
    return tuple(params)


def _is_begin_immediate(sql: str) -> bool:
    normalized = " ".join(sql.strip().rstrip(";").strip().upper().split())
    return normalized == "BEGIN IMMEDIATE"


# ---------------------------------------------------------------------------
# Backend-neutral error contract
# ---------------------------------------------------------------------------


class DatabaseError(RuntimeError):
    """Backend-neutral database error.

    ``str``/``repr`` only ever contain a fixed safe category — never a raw
    driver message, SQL, parameters, DSN, hostname, username, password, or
    connection URL.  The original driver exception may be preserved as
    ``__cause__`` via ``raise ... from exc``.
    """

    safe_category = "database_error"

    def __init__(self, safe_category: str | None = None) -> None:
        if safe_category is not None:
            self.safe_category = safe_category
        super().__init__(f"database error (category={self.safe_category})")


_INTEGRITY_KINDS = frozenset(
    {"unique", "foreign_key", "check", "not_null", "unknown"}
)


class DatabaseIntegrityError(DatabaseError):
    """Backend-neutral integrity violation.

    Safe fields:

    * ``kind`` — one of ``unique`` / ``foreign_key`` / ``check`` /
      ``not_null`` / ``unknown``.
    * ``constraint_name`` — only when the driver safely provides it
      (a schema object name; never a secret).
    * ``safe_category`` — fixed safe category string.
    """

    safe_category = "integrity_violation"

    def __init__(
        self,
        kind: str,
        constraint_name: str | None = None,
    ) -> None:
        if kind not in _INTEGRITY_KINDS:
            kind = "unknown"
        self.kind = kind
        self.constraint_name = constraint_name
        RuntimeError.__init__(
            self, f"database integrity error (kind={self.kind})"
        )


class RuntimeTransactionError(DatabaseError):
    """Backend-neutral: a write transaction cannot be started right now.

    ``state`` is a safe fixed string (``in_transaction`` / ``failed`` /
    ``unknown``) — never a raw driver transaction-status value.
    """

    safe_category = "transaction_state"

    def __init__(self, state: str) -> None:
        self.state = state
        RuntimeError.__init__(
            self, f"cannot begin write transaction (state={self.state})"
        )


class StartupDatabaseError(DatabaseError):
    """Backend-neutral: PostgreSQL startup verification failed.

    Raised by the application factory when the startup connection or the
    read-only schema/version/checksum verification fails.  ``str``/``repr``
    only ever contain the fixed safe category ``startup`` — never a raw
    Psycopg message, DSN, host, username, password, SQL, or parameter.  The
    original exception is preserved only as ``__cause__`` for internal
    debugging.
    """

    safe_category = "startup"

    def __init__(self) -> None:
        RuntimeError.__init__(
            self, f"database error (category={self.safe_category})"
        )


def _safe_constraint_name(exc: BaseException) -> str | None:
    diag = getattr(exc, "diag", None)
    name = getattr(diag, "constraint_name", None) if diag is not None else None
    if isinstance(name, str) and name:
        return name
    return None


def classify_pg_error(exc: psycopg.Error) -> DatabaseError:
    """Map a psycopg exception to a backend-neutral error.

    Classification uses the official psycopg exception classes and the
    SQLSTATE class (23 = integrity constraint violation).  The original
    exception is intended to be attached by the caller via
    ``raise ... from exc``; it is never interpolated into the message.

    Neon contract: connection wake-up, transient connection failure, and
    closed connection situations are classified as safe DatabaseError with
    category="connection".
    """
    # Connection errors (Neon wake-up, transient failure, closed connection)
    if isinstance(exc, (
        _pg_errors.ConnectionException,
        _pg_errors.ConnectionFailure,
        _pg_errors.ConnectionTimeout,
        _pg_errors.ConnectionDoesNotExist,
        _pg_errors.CannotConnectNow,
        _pg_errors.SqlclientUnableToEstablishSqlconnection,
        _pg_errors.SqlserverRejectedEstablishmentOfSqlconnection,
        _pg_errors.AdminShutdown,
        _pg_errors.CrashShutdown,
        _pg_errors.OperatorIntervention,
    )):
        return DatabaseError(safe_category="connection")

    # OperationalError is a broad category that includes connection issues
    if isinstance(exc, psycopg.OperationalError):
        return DatabaseError(safe_category="connection")

    constraint = _safe_constraint_name(exc)
    if isinstance(exc, _pg_errors.UniqueViolation):
        return DatabaseIntegrityError("unique", constraint)
    if isinstance(exc, _pg_errors.ForeignKeyViolation):
        return DatabaseIntegrityError("foreign_key", constraint)
    if isinstance(exc, _pg_errors.CheckViolation):
        return DatabaseIntegrityError("check", constraint)
    if isinstance(exc, _pg_errors.NotNullViolation):
        return DatabaseIntegrityError("not_null", constraint)
    sqlstate = getattr(exc, "sqlstate", None) or ""
    if sqlstate.startswith("23"):
        return DatabaseIntegrityError("unknown", constraint)
    return DatabaseError(safe_category="unknown")


# ---------------------------------------------------------------------------
# Internal transaction-state normalization (PostgreSQL)
# ---------------------------------------------------------------------------


class _TxState(enum.Enum):
    IDLE = "idle"
    IN_TRANSACTION = "in_transaction"
    FAILED = "failed"
    UNKNOWN = "unknown"


class _NullCursor:
    """Cursor returned for intercepted transaction-control statements."""

    rowcount = -1

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []


# ---------------------------------------------------------------------------
# SQLite runtime boundary
# ---------------------------------------------------------------------------


class SqliteRuntimeConnection:
    """Thin runtime boundary over the existing SQLite connection.

    Reuses :func:`app.db.get_connection` unchanged (``sqlite3.Row`` rows,
    ``PRAGMA foreign_keys = ON``, existing migration behaviour).  Adds the
    explicit ``begin_write()`` contract, which maps to the existing
    ``BEGIN IMMEDIATE`` write transaction.  No SQL transformation is
    performed and SQLite errors propagate exactly as before.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @property
    def in_transaction(self) -> bool:
        return self._conn.in_transaction

    @property
    def row_lock_suffix(self) -> str:
        return ""

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        if params:
            return self._conn.execute(sql, params)
        return self._conn.execute(sql)

    def begin_write(self) -> None:
        self._conn.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SqliteRuntimeConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.close()
        return False


def sqlite_runtime_connection(db_path: str) -> SqliteRuntimeConnection:
    """Open the existing SQLite connection wrapped in the runtime boundary."""
    return SqliteRuntimeConnection(_sqlite_db.get_connection(db_path))


# ---------------------------------------------------------------------------
# PostgreSQL runtime adapter
# ---------------------------------------------------------------------------


class PostgresRuntimeConnection:
    """Adapter exposing the repository connection shape over psycopg 3.

    The supplied ``connection_factory`` is a zero-argument callable that
    opens a psycopg connection (e.g. ``lambda: get_pg_connection(url)``).
    It is NOT called on construction — only when :meth:`open` (or the
    context-manager ``__enter__``) is invoked explicitly.
    """

    def __init__(self, connection_factory: Any) -> None:
        self._factory = connection_factory
        self._conn: Any | None = None

    def open(self) -> "PostgresRuntimeConnection":
        if self._conn is None:
            try:
                self._conn = self._factory()
            except psycopg.Error as exc:
                raise DatabaseError(safe_category="connection") from exc
        return self

    def _require_open(self) -> Any:
        if self._conn is None:
            raise RuntimeError(
                "PostgreSQL runtime connection is not open"
            )
        return self._conn

    @property
    def in_transaction(self) -> bool:
        self._require_open()
        return self._tx_state() is not _TxState.IDLE

    @property
    def row_lock_suffix(self) -> str:
        return " FOR UPDATE"

    def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        conn = self._require_open()
        if _is_begin_immediate(sql):
            self.begin_write()
            return _NullCursor()
        translated, count = translate_placeholders(sql)
        normalized = _normalize_params(params)
        if len(normalized) != count:
            raise PlaceholderError(
                f"placeholder count mismatch: SQL has {count} "
                f"placeholder(s) but {len(normalized)} parameter(s) "
                f"were supplied"
            )
        return self._guard(conn.execute, translated, normalized)

    def begin_write(self) -> None:
        conn = self._require_open()
        state = self._tx_state()
        if state is _TxState.IDLE:
            self._guard(conn.execute, "BEGIN")
            return
        raise RuntimeTransactionError(state.value)

    def commit(self) -> None:
        conn = self._require_open()
        self._guard(conn.commit)

    def rollback(self) -> None:
        conn = self._require_open()
        self._guard(conn.rollback)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _tx_state(self) -> _TxState:
        try:
            raw = self._conn.info.transaction_status
        except Exception:
            return _TxState.UNKNOWN
        if raw == _PgTxStatus.IDLE:
            return _TxState.IDLE
        if raw in (_PgTxStatus.INTRANS, _PgTxStatus.ACTIVE):
            return _TxState.IN_TRANSACTION
        if raw == _PgTxStatus.INERROR:
            return _TxState.FAILED
        return _TxState.UNKNOWN

    def _guard(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except DatabaseError:
            raise
        except psycopg.Error as exc:
            raise classify_pg_error(exc) from exc

    def __enter__(self) -> "PostgresRuntimeConnection":
        return self.open()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.close()
        return False

    def __repr__(self) -> str:
        state = "open" if self._conn is not None else "closed"
        return f"<PostgresRuntimeConnection backend=postgresql state={state}>"


def open_postgres_runtime(url: str) -> PostgresRuntimeConnection:
    """Explicitly open a PostgreSQL runtime connection for ``url``.

    Reuses :func:`app.db_postgres.get_pg_runtime_connection` (autocommit=True,
    dict_row).  This is the only place a real connection is opened; it is not
    invoked by the application factory in this commit (startup remains
    fail-closed).
    """
    adapter = PostgresRuntimeConnection(
        lambda: _pg_db.get_pg_runtime_connection(url)
    )
    return adapter.open()


def postgres_runtime_connection(url: str) -> PostgresRuntimeConnection:
    """Return a PostgreSQL runtime connection factory for ``url``.

    The connection is opened lazily on first use (via ``open()`` or context
    manager).  This mirrors :func:`sqlite_runtime_connection` for symmetric
    factory usage.
    """
    return PostgresRuntimeConnection(
        lambda: _pg_db.get_pg_runtime_connection(url)
    )
