"""Test-only PostgreSQL role/schema provisioning for the integration suite.

These helpers are imported by the opt-in integration test modules; the file is
NOT collected by pytest (it is not ``test_*.py``). Everything here runs against
the DISPOSABLE database named by ``LF_TEST_POSTGRES_URL`` using the owner /
migration role, and provisions a deliberately under-privileged ``runtime`` role
that mirrors the production application role:

* CONNECT on the database and USAGE on the target schema;
* SELECT / INSERT / UPDATE / DELETE on tables and USAGE on sequences;
* NO CREATE on the schema and NO ownership of any table, so CREATE / ALTER /
  DROP all fail for it.

No real credentials live here: the runtime role password is a fixed, obviously
test-only value used solely inside the throwaway database.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

RUNTIME_ROLE = "lf_it_runtime"
RUNTIME_PASSWORD = "lf_it_runtime_test_only_pw"


def admin_connect(owner_url: str):
    """Open a raw autocommit Psycopg connection as the owner role (dict rows)."""
    import psycopg  # noqa: PLC0415
    from psycopg.rows import dict_row  # noqa: PLC0415

    return psycopg.connect(owner_url, autocommit=True, row_factory=dict_row)


def ensure_runtime_role(owner_url: str) -> None:
    """Create (or reset) the restricted runtime login role."""
    raw = admin_connect(owner_url)
    try:
        cur = raw.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s", (RUNTIME_ROLE,)
        )
        if cur.fetchone() is None:
            raw.execute(
                f"CREATE ROLE {RUNTIME_ROLE} LOGIN PASSWORD '{RUNTIME_PASSWORD}'"
            )
        else:
            raw.execute(
                f"ALTER ROLE {RUNTIME_ROLE} LOGIN PASSWORD '{RUNTIME_PASSWORD}'"
            )
        db = raw.execute("SELECT current_database() AS db").fetchone()["db"]
        raw.execute(f'GRANT CONNECT ON DATABASE "{db}" TO {RUNTIME_ROLE}')
    finally:
        raw.close()


def grant_runtime_dml(owner_url: str, schema: str) -> None:
    """Grant the runtime role DML (but never DDL) on a migrated schema."""
    raw = admin_connect(owner_url)
    try:
        raw.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {RUNTIME_ROLE}')
        raw.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE "
            f'ON ALL TABLES IN SCHEMA "{schema}" TO {RUNTIME_ROLE}'
        )
        raw.execute(
            f"GRANT USAGE ON ALL SEQUENCES "
            f'IN SCHEMA "{schema}" TO {RUNTIME_ROLE}'
        )
        # Deliberately NOT granted: CREATE ON SCHEMA, or ownership of any table.
    finally:
        raw.close()


def revoke_runtime_create(owner_url: str, schema: str) -> None:
    """Ensure the runtime role has no CREATE on the schema (defensive)."""
    raw = admin_connect(owner_url)
    try:
        raw.execute(
            f'REVOKE CREATE ON SCHEMA "{schema}" FROM {RUNTIME_ROLE}'
        )
    finally:
        raw.close()


def runtime_url(owner_url: str, schema: str) -> str:
    """Build the runtime-role connection URL for a schema (search_path pinned)."""
    parts = urlsplit(owner_url)
    host = parts.hostname
    netloc = f"{RUNTIME_ROLE}:{RUNTIME_PASSWORD}@{host}"
    if parts.port:
        netloc += f":{parts.port}"
    base = urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    return f"{base}?options=-csearch_path%3D{schema}"
