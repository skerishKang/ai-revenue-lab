"""PostgreSQL backend connection adapter (Psycopg 3).

Presents the same backend-neutral :class:`~app.database.base.Connection`
interface as the SQLite adapter so repository code runs unchanged.

Transaction model
-----------------
The underlying connection runs in ``autocommit`` mode so that plain ``SELECT``
statements do not leave a transaction open (matching SQLite, where reads leave
``in_transaction`` false). Write operations explicitly bracket work with
``BEGIN`` ... ``COMMIT``/``ROLLBACK`` via :meth:`begin_immediate`,
:meth:`commit`, and :meth:`rollback`. Write-conflict safety is provided by the
schema uniqueness constraints, surfaced as the neutral
:class:`~app.database.errors.IntegrityError`.

SQL adaptation
--------------
``?`` placeholders and ``INSERT OR IGNORE`` are adapted structurally (see
:mod:`app.database.sql`), never by naive string replacement. ``BEGIN IMMEDIATE``
maps to a plain ``BEGIN``. ``PRAGMA`` statements (SQLite-only) are ignored.

``psycopg`` is imported lazily so importing this module -- and the whole SQLite
code path -- never requires the PostgreSQL driver to be installed.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.database.errors import ConfigurationError, IntegrityError
from app.database.sql import adapt_sql_for_postgres


def _import_psycopg():
    try:
        import psycopg  # noqa: PLC0415
    except ImportError as exc:
        raise ConfigurationError(
            "PostgreSQL backend requires the 'psycopg' package "
            "(install the [postgres] extra)"
        ) from exc
    return psycopg


def _first_word(sql: str) -> str:
    return sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""


def _safe_message(exc: Exception) -> str:
    """Return an integrity-error message with no connection/credential detail."""
    text = str(exc).strip()
    return text.splitlines()[0] if text else "constraint violation"


class PostgresConnection:
    """Backend-neutral adapter over a Psycopg 3 connection."""

    def __init__(self, raw: Any):
        self._raw = raw

    @property
    def raw(self) -> Any:
        """The underlying Psycopg connection."""
        return self._raw

    @property
    def in_transaction(self) -> bool:
        psycopg = _import_psycopg()
        status = self._raw.info.transaction_status
        return status != psycopg.pq.TransactionStatus.IDLE

    def begin_immediate(self) -> None:
        if not self.in_transaction:
            self._raw.execute("BEGIN")

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> Any:
        word = _first_word(sql)
        if word == "PRAGMA":
            return self._raw.execute("SELECT 1")
        if word == "BEGIN":
            self.begin_immediate()
            return self._raw.execute("SELECT 1")
        if word in ("COMMIT", "END"):
            self.commit()
            return self._raw.execute("SELECT 1")
        if word == "ROLLBACK":
            upper = sql.strip().upper()
            if upper.startswith("ROLLBACK TO"):
                return self._raw.execute(sql)
            self.rollback()
            return self._raw.execute("SELECT 1")
        if word in ("SAVEPOINT", "RELEASE"):
            return self._raw.execute(sql)
        adapted = adapt_sql_for_postgres(sql)
        psycopg = _import_psycopg()
        try:
            return self._raw.execute(adapted, tuple(parameters))
        except psycopg.errors.IntegrityError as exc:
            raise IntegrityError(_safe_message(exc)) from exc

    def executemany(
        self, sql: str, seq_of_parameters: Iterable[Iterable[Any]]
    ) -> Any:
        adapted = adapt_sql_for_postgres(sql)
        psycopg = _import_psycopg()
        try:
            return self._raw.executemany(
                adapted, [tuple(p) for p in seq_of_parameters]
            )
        except psycopg.errors.IntegrityError as exc:
            raise IntegrityError(_safe_message(exc)) from exc

    def cursor(self) -> Any:
        return self._raw.cursor()

    def commit(self) -> None:
        if self.in_transaction:
            self._raw.execute("COMMIT")

    def rollback(self) -> None:
        if self.in_transaction:
            self._raw.execute("ROLLBACK")

    def close(self) -> None:
        self._raw.close()


def connect_postgres(url: str, *, autocommit: bool = True) -> PostgresConnection:
    """Open a single Psycopg connection wrapped in :class:`PostgresConnection`.

    ``autocommit=True`` keeps reads from leaving a transaction open; explicit
    ``BEGIN``/``COMMIT`` bracket writes. ``dict_row`` makes rows support named
    (``row["col"]``) access like ``sqlite3.Row``. The URL is never echoed into
    errors.
    """
    psycopg = _import_psycopg()
    from psycopg.rows import dict_row  # noqa: PLC0415

    try:
        raw = psycopg.connect(url, autocommit=autocommit, row_factory=dict_row)
    except Exception as exc:
        raise ConfigurationError(
            "could not connect to the configured PostgreSQL database"
        ) from exc
    return PostgresConnection(raw)
