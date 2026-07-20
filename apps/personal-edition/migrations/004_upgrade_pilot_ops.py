"""Forward migration: normalize pilot_ops_records to the canonical schema.

This migration is required because the migration engine skips any filename
already recorded in ``schema_migrations``. Phase 5A databases created with the
*original* ``003_benchmark_pilot_ops.sql`` therefore never receive later
changes made by editing migration 003. Editing 003 is also unsafe for an
already-applied, durable database.

A plain SQL migration cannot safely branch on the existing SQLite column
layout (SQLite has limited ``ALTER TABLE`` support), so this is a versioned
Python migration hook executed by :func:`app.db.apply_migrations`.

It handles two legacy layouts that may already be present:

A. original 003 layout::

       id, participant_id, record_type, edition_id, record_json, created_at

B. revised 003 layout (already canonical)::

       record_id, record_type, participant_id, created_at, payload

Canonical target (matches ``app.pipeline`` expectations and pilot_ops.py)::

    record_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL
        CHECK(record_type IN (...)),
    participant_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL

The migration is idempotent and data-preserving: existing rows keep their
``participant_id``, ``record_type``, ``created_at`` and payload data; the
legacy ``id`` becomes ``record_id`` and the legacy ``record_json`` becomes
``payload``. The legacy ``edition_id`` column (not part of the canonical
contract) is dropped. Indexes are recreated.
"""

import sqlite3

_TABLE = "pilot_ops_records"

_CANONICAL_COLUMNS = frozenset(
    {"record_id", "record_type", "participant_id", "created_at", "payload"}
)

_RECORD_TYPE_CHECK = (
    "record_type IN ("
    "'benchmark_run',"
    "'pilot_run',"
    "'pilot_evidence',"
    "'payment_evidence',"
    "'correction',"
    "'deletion_request',"
    "'deletion_completion'"
    ")"
)

_CREATE_CANONICAL = f"""
CREATE TABLE {_TABLE}_new (
    record_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL CHECK({_RECORD_TYPE_CHECK}),
    participant_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
)
"""

_INDEX_PARTICIPANT = (
    f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_participant_id "
    f"ON {_TABLE}(participant_id)"
)
_INDEX_TYPE = (
    f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_record_type "
    f"ON {_TABLE}(record_type)"
)


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (_TABLE,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({_TABLE})").fetchall()
    return [r["name"] for r in rows]


def _create_canonical(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TABLE} (
            record_id TEXT PRIMARY KEY,
            record_type TEXT NOT NULL CHECK({_RECORD_TYPE_CHECK}),
            participant_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    conn.execute(_INDEX_PARTICIPANT)
    conn.execute(_INDEX_TYPE)


def _upgrade_original_to_canonical(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_CANONICAL)
    conn.execute(
        f"""
        INSERT INTO {_TABLE}_new
            (record_id, record_type, participant_id, created_at, payload)
        SELECT
            id,
            record_type,
            participant_id,
            created_at,
            record_json
        FROM {_TABLE}
        """
    )
    conn.execute(f"DROP TABLE {_TABLE}")
    conn.execute(f"ALTER TABLE {_TABLE}_new RENAME TO {_TABLE}")
    conn.execute(_INDEX_PARTICIPANT)
    conn.execute(_INDEX_TYPE)


def migrate(conn: sqlite3.Connection) -> None:
    """Idempotently normalize the pilot_ops_records table."""
    if not _table_exists(conn):
        _create_canonical(conn)
        return

    columns = set(_table_columns(conn))
    if columns == _CANONICAL_COLUMNS:
        # Already canonical (revised 003): idempotent no-op.
        return

    if "record_json" in columns:
        # Original 003 layout: id / record_json shape.
        _upgrade_original_to_canonical(conn)
        return

    # Unknown legacy layout: rebuild to canonical, preserving by column name
    # where possible and falling back to NULL for missing canonical columns.
    conn.execute(_CREATE_CANONICAL)
    cols = ", ".join(
        c
        for c in (
            "record_id",
            "record_type",
            "participant_id",
            "created_at",
            "payload",
        )
        if c in columns
    )
    if cols:
        conn.execute(
            f"INSERT INTO {_TABLE}_new ({cols}) SELECT {cols} FROM {_TABLE}"
        )
    conn.execute(f"DROP TABLE {_TABLE}")
    conn.execute(f"ALTER TABLE {_TABLE}_new RENAME TO {_TABLE}")
    conn.execute(_INDEX_PARTICIPANT)
    conn.execute(_INDEX_TYPE)
