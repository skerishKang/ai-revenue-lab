"""Backend-neutral database layer for Living Fiction.

Public surface used by the application factory, web layer, repositories, and
operator commands:

* :class:`~app.database.base.Connection` / :data:`~app.database.base.Row` --
  the backend-neutral interface repositories are written against.
* :func:`~app.database.base.begin_immediate` -- backend-appropriate write
  transaction start.
* :class:`~app.database.errors.IntegrityError` and friends -- neutral errors
  raised by both adapters.
* :class:`~app.database.sqlite.SQLiteConnection` /
  :class:`~app.database.postgres.PostgresConnection` -- the two adapters.
* :func:`~app.database.engine.build_engine` -- startup engine construction.

``psycopg`` is imported lazily inside the postgres modules so importing this
package -- and running the entire SQLite path -- never requires the PostgreSQL
driver.
"""

from __future__ import annotations

from app.database.base import Connection, Cursor, Row, begin_immediate
from app.database.engine import PostgresEngine, SQLiteEngine, build_engine
from app.database.errors import (
    ConfigurationError,
    DatabaseError,
    IntegrityError,
    SchemaMismatchError,
)
from app.database.sqlite import SQLiteConnection

__all__ = [
    "Connection",
    "Cursor",
    "Row",
    "begin_immediate",
    "build_engine",
    "SQLiteEngine",
    "PostgresEngine",
    "SQLiteConnection",
    "DatabaseError",
    "IntegrityError",
    "SchemaMismatchError",
    "ConfigurationError",
]
