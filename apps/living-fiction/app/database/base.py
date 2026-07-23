"""Backend-neutral connection interface.

Repository and service code is written against the :class:`Connection` protocol
rather than ``sqlite3.Connection``. Both :class:`~app.database.sqlite.SQLiteConnection`
and :class:`~app.database.postgres.PostgresConnection` satisfy this interface, so
the same repository code runs unchanged on either backend.

The protocol intentionally mirrors the small slice of the DB-API the app uses:
``execute`` returning a cursor, explicit ``commit``/``rollback``, an
``in_transaction`` flag, and dict-style row access. SQLite-specific transaction
control (``BEGIN IMMEDIATE``) is exposed only through :func:`begin_immediate`,
which each adapter implements with backend-appropriate semantics.
"""

from __future__ import annotations

from typing import Any, Iterable, Protocol, runtime_checkable


@runtime_checkable
class Row(Protocol):
    """A result row supporting named (``row["col"]``) access."""

    def __getitem__(self, key: str) -> Any: ...

    def keys(self) -> list[str]: ...


@runtime_checkable
class Cursor(Protocol):
    """A cursor supporting the fetch/rowcount slice the repositories use."""

    @property
    def rowcount(self) -> int: ...

    def fetchone(self) -> Row | None: ...

    def fetchall(self) -> list[Row]: ...


@runtime_checkable
class Connection(Protocol):
    """Backend-neutral database connection used by repositories and services."""

    @property
    def in_transaction(self) -> bool: ...

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> Cursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...

    def begin_immediate(self) -> None: ...


def begin_immediate(conn: Connection) -> None:
    """Start a write transaction with backend-appropriate semantics.

    On SQLite this issues ``BEGIN IMMEDIATE`` (an immediate reserved write lock).
    On PostgreSQL this begins a normal transaction; write-conflict safety is
    provided by uniqueness constraints surfaced as :class:`~app.database.errors.IntegrityError`.
    Accepts any object exposing ``begin_immediate()``; falls back to a raw
    ``BEGIN IMMEDIATE`` for a plain ``sqlite3.Connection``.
    """
    begin = getattr(conn, "begin_immediate", None)
    if callable(begin):
        begin()
        return
    conn.execute("BEGIN IMMEDIATE")
