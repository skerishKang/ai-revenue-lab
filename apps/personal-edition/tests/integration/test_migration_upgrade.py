"""Tests for the 004 pilot_ops_records forward migration.

The migration engine skips any filename already recorded in
``schema_migrations``, so editing migration 003 cannot upgrade a durable
database created earlier. ``004_upgrade_pilot_ops.py`` must therefore upgrade
both legacy layouts (the original 003 shape and the revised canonical shape)
idempotently and without data loss.
"""

import os
import sys
from pathlib import Path

import pytest

_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, _DIR)

from app.db import apply_migrations, get_connection  # noqa: E402

MIGRATIONS = str(Path(_DIR) / "migrations")

_CANONICAL_COLUMNS = {"record_id", "record_type", "participant_id", "created_at", "payload"}


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
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pilot_ops_records)")}
    assert cols == _CANONICAL_COLUMNS
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

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pilot_ops_records)")}
    assert cols == _CANONICAL_COLUMNS

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

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pilot_ops_records)")}
    assert cols == _CANONICAL_COLUMNS

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
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(pilot_ops_records)")}
    assert cols == _CANONICAL_COLUMNS
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
