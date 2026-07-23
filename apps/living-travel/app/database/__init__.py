"""Database backend abstraction for Living Travel.

SQLite is the default local/test backend. PostgreSQL (Neon) is the
staging/production backend. The public connection/migration entry points
live in ``app.db`` and dispatch here based on ``LT_DATABASE_BACKEND``.
"""

from app.database.postgres import (
    PostgresConnection,
    translate_placeholders,
    get_pg_connection,
    apply_pg_migrations,
)

__all__ = [
    "PostgresConnection",
    "translate_placeholders",
    "get_pg_connection",
    "apply_pg_migrations",
]
