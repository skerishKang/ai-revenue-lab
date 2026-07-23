"""SQLite backend connection adapter.

Wraps a ``sqlite3.Connection`` to present the backend-neutral
:class:`~app.database.base.Connection` interface. The wrapper is deliberately
transparent: every operation delegates to the underlying connection so the
existing SQLite behaviour (and the full SQLite test suite) is preserved exactly.
The only translation is at the error boundary — ``sqlite3.IntegrityError`` is
re-raised as the neutral :class:`~app.database.errors.IntegrityError` so
repositories never import ``sqlite3`` for exception handling.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable

from app.database.errors import IntegrityError


class SQLiteConnection:
    """Backend-neutral adapter over a raw ``sqlite3.Connection``."""

    def __init__(self, raw: sqlite3.Connection):
        self._raw = raw

    @property
    def raw(self) -> sqlite3.Connection:
        """The underlying ``sqlite3.Connection`` (used by the SQLite migrator)."""
        return self._raw

    @property
    def in_transaction(self) -> bool:
        return self._raw.in_transaction

    def execute(self, sql: str, parameters: Iterable[Any] = ()) -> Any:
        try:
            return self._raw.execute(sql, parameters)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc

    def executemany(self, sql: str, seq_of_parameters: Iterable[Iterable[Any]]) -> Any:
        try:
            return self._raw.executemany(sql, seq_of_parameters)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc

    def executescript(self, script: str) -> Any:
        return self._raw.executescript(script)

    def cursor(self) -> Any:
        return self._raw.cursor()

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    def begin_immediate(self) -> None:
        self._raw.execute("BEGIN IMMEDIATE")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._raw, name)
