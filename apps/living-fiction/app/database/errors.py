"""Backend-neutral database errors.

These exceptions form the only error surface that repository and service code
may depend on. SQLite-specific ``sqlite3.IntegrityError`` and PostgreSQL-specific
``psycopg`` errors are translated into :class:`IntegrityError` at the connection
adapter boundary so no backend-specific exception type leaks into backend-agnostic
code.
"""

from __future__ import annotations


class DatabaseError(Exception):
    """Base class for all backend-neutral database errors."""


class IntegrityError(DatabaseError):
    """A constraint violation (uniqueness, foreign key, check).

    Raised by both the SQLite and PostgreSQL connection adapters in place of
    their native integrity-error types so repositories can enforce uniqueness
    contracts (one choice per reader/canon, duplicate-branch prevention, invite
    digest uniqueness, single review decision, ...) without importing any
    backend module.
    """


class SchemaMismatchError(DatabaseError):
    """The database schema is missing or behind the version the app requires.

    Production startup fails closed with this error rather than running against
    an unexpected schema. The runtime app never auto-applies migrations.
    """


class ConfigurationError(DatabaseError):
    """The database backend configuration is invalid or incomplete.

    Raised fail-closed at startup for combinations such as production + sqlite,
    or a postgres backend with no connection URL. Messages never include the
    configured URL or any credential.
    """
