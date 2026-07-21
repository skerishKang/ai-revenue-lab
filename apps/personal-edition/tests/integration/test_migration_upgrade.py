"""Tests for the 004 pilot_ops_records forward migration.

The migration engine skips any filename already recorded in
``schema_migrations``, so editing migration 003 cannot upgrade a durable
database created earlier. ``004_upgrade_pilot_ops.py`` must therefore upgrade
both legacy layouts (the original 003 shape and the revised canonical shape)
idempotently and without data loss.
"""

import os
import sqlite3
import sys
from pathlib import Path

import pytest

_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _DIR)

from app.db import apply_migrations, get_connection  # noqa: E402

MIGRATIONS = str(Path(_DIR) / "migrations")

_CANONICAL_COLUMNS = {"record_id", "record_type", "participant_id", "created_at", "payload"}

_RECORD_TYPE_VALUES = (
    "benchmark_run",
    "pilot_run",
    "pilot_evidence",
    "payment_evidence",
    "correction",
    "deletion_request",
    "deletion_completion",
)


def _assert_canonical(conn: object) -> None:
    """Assert the migrated table is fully canonical: columns, CHECK constraint,
    both required indexes, and primary-key integrity."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pilot_ops_records)")}
    assert cols == _CANONICAL_COLUMNS

    pks = [
        r["name"]
        for r in conn.execute("PRAGMA table_info(pilot_ops_records)")
        if r["pk"] == 1
    ]
    assert pks == ["record_id"]

    # Indexes verified by indexed columns (names vary across layouts).
    has_participant = False
    has_record_type = False
    for idx in conn.execute("PRAGMA index_list(pilot_ops_records)").fetchall():
        name = idx["name"]
        icols = [
            r["name"]
            for r in conn.execute(f"PRAGMA index_info({name})").fetchall()
        ]
        if icols == ["participant_id"]:
            has_participant = True
        if icols == ["record_type"]:
            has_record_type = True
    assert has_participant, "missing participant_id index"
    assert has_record_type, "missing record_type index"

    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' "
        "AND name='pilot_ops_records'"
    ).fetchone()["sql"]
    lowered = (sql or "").lower()
    assert "record_type in (" in lowered
    for value in _RECORD_TYPE_VALUES:
        assert value in lowered


def _preapply_001_002_003(conn: object) -> None:
    conn.execute(
        "CREATE TABLE schema_migrations ("
        "version TEXT PRIMARY KEY, "
        "applied_at TEXT NOT NULL DEFAULT ("
        "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))"
    )
    for version in (
        "001_initial.sql",
        "002_participant_token_hash_unique.sql",
        "003_benchmark_pilot_ops.sql",
    ):
        conn.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)", (version,)
        )


def test_fresh_db_applies_all_migrations():
    conn = get_connection(":memory:")
    applied = apply_migrations(conn, MIGRATIONS)
    assert "001_initial.sql" in applied
    assert "002_participant_token_hash_unique.sql" in applied
    assert "003_benchmark_pilot_ops.sql" in applied
    assert "004_upgrade_pilot_ops.py" in applied
    _assert_canonical(conn)
    conn.close()


def test_original_003_schema_upgrades_without_data_loss():
    # Original 003 layout: id / record_json shape.
    conn = get_connection(":memory:")
    conn.execute(
        "CREATE TABLE pilot_ops_records ("
        "id TEXT PRIMARY KEY, participant_id TEXT NOT NULL, "
        "record_type TEXT NOT NULL, edition_id TEXT, "
        "record_json TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO pilot_ops_records "
        "(id, participant_id, record_type, edition_id, record_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("rec-1", "p1", "pilot_run", "ed-1", '{"k":1}', "2026-01-01T00:00:00Z"),
    )
    _preapply_001_002_003(conn)

    applied = apply_migrations(conn, MIGRATIONS)
    assert "004_upgrade_pilot_ops.py" in applied

    _assert_canonical(conn)

    row = conn.execute("SELECT * FROM pilot_ops_records").fetchone()
    assert row["record_id"] == "rec-1"
    assert row["participant_id"] == "p1"
    assert row["record_type"] == "pilot_run"
    assert row["payload"] == '{"k":1}'
    assert row["created_at"] == "2026-01-01T00:00:00Z"
    conn.close()


def test_revised_003_schema_upgrades_idempotently():
    # Revised 003 layout (already canonical): idempotent no-op.
    conn = get_connection(":memory:")
    conn.execute(
        "CREATE TABLE pilot_ops_records ("
        "record_id TEXT PRIMARY KEY, record_type TEXT NOT NULL, "
        "participant_id TEXT NOT NULL, created_at TEXT NOT NULL, "
        "payload TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO pilot_ops_records "
        "(record_id, record_type, participant_id, created_at, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("rec-2", "pilot_run", "p2", "t", "{}"),
    )
    _preapply_001_002_003(conn)

    applied = apply_migrations(conn, MIGRATIONS)
    assert "004_upgrade_pilot_ops.py" in applied

    _assert_canonical(conn)

    row = conn.execute("SELECT * FROM pilot_ops_records").fetchone()
    assert row["record_id"] == "rec-2"
    assert row["payload"] == "{}"
    conn.close()


def test_second_migration_run_is_noop():
    conn = get_connection(":memory:")
    first = apply_migrations(conn, MIGRATIONS)
    assert "004_upgrade_pilot_ops.py" in first
    second = apply_migrations(conn, MIGRATIONS)
    assert second == []
    _assert_canonical(conn)
    conn.close()


def test_pilot_record_writable_after_upgrade():
    conn = get_connection(":memory:")
    conn.execute(
        "CREATE TABLE pilot_ops_records ("
        "id TEXT PRIMARY KEY, participant_id TEXT NOT NULL, "
        "record_type TEXT NOT NULL, edition_id TEXT, "
        "record_json TEXT NOT NULL, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO pilot_ops_records "
        "(id, participant_id, record_type, edition_id, record_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("rec-1", "p1", "pilot_run", "ed-1", '{"k":1}', "2026-01-01T00:00:00Z"),
    )
    _preapply_001_002_003(conn)
    apply_migrations(conn, MIGRATIONS)

    conn.execute(
        "INSERT INTO pilot_ops_records "
        "(record_id, record_type, participant_id, created_at, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("rec-3", "correction", "p3", "t", "{}"),
    )
    count = conn.execute("SELECT COUNT(*) AS c FROM pilot_ops_records").fetchone()
    assert count["c"] == 2
    conn.close()


def test_invalid_record_type_rejected_after_upgrade():
    # Revised layout with canonical columns but NO CHECK constraint/indexes.
    conn = get_connection(":memory:")
    conn.execute(
        "CREATE TABLE pilot_ops_records ("
        "record_id TEXT PRIMARY KEY, record_type TEXT NOT NULL, "
        "participant_id TEXT NOT NULL, created_at TEXT NOT NULL, "
        "payload TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO pilot_ops_records "
        "(record_id, record_type, participant_id, created_at, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        ("rec-1", "pilot_run", "p1", "t", "{}"),
    )
    _preapply_001_002_003(conn)

    applied = apply_migrations(conn, MIGRATIONS)
    assert "004_upgrade_pilot_ops.py" in applied
    _assert_canonical(conn)

    # The canonical CHECK constraint now rejects invalid record_type values.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO pilot_ops_records "
            "(record_id, record_type, participant_id, created_at, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            ("rec-2", "evil_type", "p2", "t", "{}"),
        )
    # The previously stored valid row is intact.
    row = conn.execute(
        "SELECT * FROM pilot_ops_records WHERE record_id = 'rec-1'"
    ).fetchone()
    assert row["record_type"] == "pilot_run"
    assert row["payload"] == "{}"
    conn.close()


def test_revised_layout_without_constraints_is_rebuilt_safely():
    # A table with canonical columns but missing CHECK and indexes must be
    # rebuilt so the constraints and indexes exist, preserving every row.
    conn = get_connection(":memory:")
    conn.execute(
        "CREATE TABLE pilot_ops_records ("
        "record_id TEXT PRIMARY KEY, record_type TEXT NOT NULL, "
        "participant_id TEXT NOT NULL, created_at TEXT NOT NULL, "
        "payload TEXT NOT NULL)"
    )
    for i in range(3):
        conn.execute(
            "INSERT INTO pilot_ops_records "
            "(record_id, record_type, participant_id, created_at, payload) "
            "VALUES (?, ?, ?, ?, ?)",
            (f"rec-{i}", "correction", f"p{i}", "t", f'{{"n":{i}}}'),
        )
    _preapply_001_002_003(conn)

    applied = apply_migrations(conn, MIGRATIONS)
    assert "004_upgrade_pilot_ops.py" in applied
    _assert_canonical(conn)

    rows = conn.execute(
        "SELECT record_id, payload FROM pilot_ops_records ORDER BY record_id"
    ).fetchall()
    assert [r["record_id"] for r in rows] == ["rec-0", "rec-1", "rec-2"]
    assert {r["payload"] for r in rows} == {'{"n":0}', '{"n":1}', '{"n":2}'}

    # A second apply must be a no-op.
    second = apply_migrations(conn, MIGRATIONS)
    assert second == []
    conn.close()
