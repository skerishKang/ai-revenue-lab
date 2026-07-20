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

B. revised 003 layout (already canonical columns)::

       record_id, record_type, participant_id, created_at, payload

Canonical target::

    record_id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL
        CHECK(record_type IN (... seven types ...)),
    participant_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL

Canonicality is defined as the *conjunction* of:

- exactly the five required columns in any order (checked via PRAGMA
  table_info);
- a ``record_type`` CHECK constraint enumerating the seven accepted types
  (checked via the stored CREATE TABLE SQL);
- a ``participant_id`` index and a ``record_type`` index (checked via
  PRAGMA index_list);
- primary-key integrity (exactly one PRIMARY KEY column, ``record_id``).

A table that has the five columns but is missing the CHECK constraint, an
index, or the primary key is NOT canonical: the migration rebuilds it,
preserving every row, and recreates the required constraints and indexes.
This is idempotent and data-preserving.
"""

import sqlite3

_TABLE = "pilot_ops_records"

_CANONICAL_COLUMNS = frozenset(
    {"record_id", "record_type", "participant_id", "created_at", "payload"}
)

_RECORD_TYPE_VALUES = (
    "benchmark_run",
    "pilot_run",
    "pilot_evidence",
    "payment_evidence",
    "correction",
    "deletion_request",
    "deletion_completion",
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

# Indexes are created with the FINAL table name so that after the temporary
# table is renamed they remain attached under the expected names.
_INDEX_PARTICIPANT = (
    f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_participant_id "
    f"ON {{table}}(participant_id)"
)
_INDEX_TYPE = (
    f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_record_type "
    f"ON {{table}}(record_type)"
)

_TEMP_TABLE = _TABLE + "_canonical_tmp"


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (_TABLE,),
    ).fetchone()
    return row is not None


def _table_columns(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({_TABLE})").fetchall()
    return [r["name"] for r in rows]


def _table_sql(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
        (_TABLE,),
    ).fetchone()
    return (row["sql"] or "") if row else ""


def _index_names(conn: sqlite3.Connection) -> set[str]:
    return {
        r["name"] for r in conn.execute(f"PRAGMA index_list({_TABLE})").fetchall()
    }


def _has_required_indexes(conn: sqlite3.Connection) -> bool:
    """True when an index covers participant_id and another covers record_type.

    Index *names* vary across the legacy 003 layout and the runtime
    ``_create_pilot_table`` helper, so we verify the indexed columns rather
    than exact names.
    """
    has_participant = False
    has_record_type = False
    for idx in conn.execute(f"PRAGMA index_list({_TABLE})").fetchall():
        name = idx["name"]
        cols = [
            r["name"]
            for r in conn.execute(f"PRAGMA index_info({name})").fetchall()
        ]
        if cols == ["participant_id"]:
            has_participant = True
        if cols == ["record_type"]:
            has_record_type = True
    return has_participant and has_record_type


def _has_canonical_check(sql: str) -> bool:
    lowered = sql.lower()
    if "record_type in (" not in lowered:
        return False
    for value in _RECORD_TYPE_VALUES:
        if value not in lowered:
            return False
    return True


def _is_canonical(conn: sqlite3.Connection) -> bool:
    """True only when columns, CHECK, indexes, and PK are all canonical."""
    if set(_table_columns(conn)) != _CANONICAL_COLUMNS:
        return False

    rows = conn.execute(f"PRAGMA table_info({_TABLE})").fetchall()
    pks = [r["name"] for r in rows if r["pk"] == 1]
    if pks != ["record_id"]:
        return False

    if not _has_canonical_check(_table_sql(conn)):
        return False

    if not _has_required_indexes(conn):
        return False

    return True


def _create_canonical_table(conn: sqlite3.Connection, table: str) -> None:
    conn.execute(
        f"""
        CREATE TABLE {table} (
            record_id TEXT PRIMARY KEY,
            record_type TEXT NOT NULL CHECK({_RECORD_TYPE_CHECK}),
            participant_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """
    )
    conn.execute(_INDEX_PARTICIPANT.format(table=table))
    conn.execute(_INDEX_TYPE.format(table=table))


def _copy_canonical(conn: sqlite3.Connection, source: str) -> None:
    """Copy the five canonical columns from source into the temp table."""
    conn.execute(
        f"""
        INSERT INTO {_TEMP_TABLE}
            (record_id, record_type, participant_id, created_at, payload)
        SELECT record_id, record_type, participant_id, created_at, payload
        FROM {source}
        """
    )


def _materialize_canonical_from_original(conn: sqlite3.Connection) -> None:
    """Rebuild from the original 003 layout (id / record_json shape)."""
    _create_canonical_table(conn, _TEMP_TABLE)
    conn.execute(
        f"""
        INSERT INTO {_TEMP_TABLE}
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
    conn.execute(f"ALTER TABLE {_TEMP_TABLE} RENAME TO {_TABLE}")


def _rebuild_canonical_preserving(conn: sqlite3.Connection) -> None:
    """Rebuild a same-shape table to (re)attach CHECK constraint + indexes."""
    _create_canonical_table(conn, _TEMP_TABLE)
    _copy_canonical(conn, _TABLE)
    conn.execute(f"DROP TABLE {_TABLE}")
    conn.execute(f"ALTER TABLE {_TEMP_TABLE} RENAME TO {_TABLE}")


def migrate(conn: sqlite3.Connection) -> None:
    """Idempotently normalize the pilot_ops_records table to canonical form."""
    if not _table_exists(conn):
        _create_canonical_table(conn, _TABLE)
        return

    if _is_canonical(conn):
        # Already canonical: columns, CHECK, indexes, and PK all present.
        return

    columns = set(_table_columns(conn))

    if "record_json" in columns:
        # Original 003 layout: id / record_json shape.
        _materialize_canonical_from_original(conn)
        return

    # Revised layout with canonical column names but missing the CHECK
    # constraint, an index, or the primary key: rebuild safely, preserving
    # every row.
    _rebuild_canonical_preserving(conn)
