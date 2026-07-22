"""PostgreSQL connection and migration boundary for Personal Edition.

This module provides a minimal, explicit connection boundary around
psycopg 3 (sync mode).  It is intentionally separate from the SQLite
``app.db`` module so that the two backends never share code paths.

Design principles:

* **No import-time connection** — importing this module never opens a
  network connection.  A connection is only opened when
  :func:`get_pg_connection` is called explicitly.
* **Explicit transaction control** — every write path uses
  ``conn.commit()`` / ``conn.rollback()`` with clear ``try/finally``.
* **Context manager** — :func:`pg_connection` is a context manager that
  guarantees ``close()`` on exit.
* **Parameterized API** — all SQL uses ``%s`` placeholders via
  ``conn.execute(sql, params)``.
* **Credential redaction** — :func:`redact_database_url` (re-exported
  from :mod:`app.config`) is used in all error messages.
* **Testability** — ``get_pg_connection`` accepts an explicit ``url``
  argument so tests can monkeypatch it without touching production URLs.
"""

from __future__ import annotations

import contextlib
from typing import Any

from app.config import redact_database_url

# psycopg 3 sync connection.  Importing psycopg does NOT open a connection.
from psycopg import Connection, connect
from psycopg.rows import DictRow, dict_row


__all__ = [
    "get_pg_connection",
    "pg_connection",
    "redact_database_url",
    "PG_MIGRATIONS_DIR",
]


# PostgreSQL migrations live alongside the SQLite migrations.
# The ``pg_`` prefix ensures deterministic ordering before any
# SQLite ``NNN_`` files (pg_ < 0 in ASCII), and keeps the two
# migration sets physically separate.
import os as _os

_BASE_DIR = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
PG_MIGRATIONS_DIR = _os.path.join(_BASE_DIR, "migrations")


def get_pg_connection(url: str) -> Connection[DictRow]:
    """Open a synchronous PostgreSQL connection.

    Parameters
    ----------
    url:
        A ``postgresql://`` or ``postgres://`` connection URL.

    Returns
    -------
    psycopg.Connection
        A connection configured with ``dict_row`` row factory so rows
        can be accessed by column name (mirroring ``sqlite3.Row``).

    Raises
    ------
    psycopg.OperationalError
        If the connection cannot be established.  The error message
        is safe to log — callers should redact the URL separately
        via :func:`redact_database_url`.
    """
    conn = connect(url, row_factory=dict_row, autocommit=False)
    return conn


@contextlib.contextmanager
def pg_connection(url: str):
    """Context manager that yields a PostgreSQL connection and closes it.

    Usage::

        with pg_connection(url) as conn:
            conn.execute("SELECT 1")
            conn.commit()

    The connection is opened with ``autocommit=False`` so that
    transactions are explicit.  On exception the transaction is
    rolled back; on success the caller is responsible for committing.
    """
    conn = get_pg_connection(url)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _redact_url(url: str) -> str:
    """Internal helper — never log the raw URL."""
    return redact_database_url(url)


# Re-export for convenience so callers can do:
#   from app.db_postgres import redact_database_url
