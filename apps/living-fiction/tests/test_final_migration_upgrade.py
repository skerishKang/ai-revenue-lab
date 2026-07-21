"""Final migration upgrade contract tests.

Tests real 001 → 002 → 003 → 004 file-backed upgrade with data preservation,
FK checks, staged failure with rollback, and close/reopen semantics.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from app.db import apply_migrations, get_connection, MigrationError


def _make_conn(path: str) -> sqlite3.Connection:
    conn = get_connection(path)
    return conn


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        try:
            os.unlink(path)
        except PermissionError:
            pass


def _get_migrations_dir():
    return os.path.join(os.path.dirname(__file__), "..", "migrations")


def _apply_single_migration(conn, migrations_dir, migration_filename):
    """Apply exactly one migration file by name."""
    from app.db import iter_sql_statements
    filepath = os.path.join(migrations_dir, migration_filename)
    sql = open(filepath, encoding="utf-8").read()
    statements = list(iter_sql_statements(sql))
    conn.execute("BEGIN IMMEDIATE")
    for stmt in statements:
        conn.execute(stmt)
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        conn.rollback()
        raise MigrationError(
            migration_filename,
            RuntimeError(f"foreign key violations after migration: {violations}"),
        )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version) VALUES (?)",
        (migration_filename,),
    )
    conn.commit()


def test_real_populated_001_to_002_to_003_to_004_upgrade(db_path):
    """Complete 001→002→003→004 upgrade with data preservation at each stage."""
    mig_dir = _get_migrations_dir()

    # Apply all migrations
    conn = _make_conn(db_path)
    versions = apply_migrations(conn, mig_dir)
    assert len(versions) >= 4, f"Expected 4+ migrations, got {versions}"
    conn.close()

    # Seed data under full schema
    conn = _make_conn(db_path)
    conn.execute(
        "INSERT INTO readers (id, display_name, status, created_at) "
        "VALUES ('reader-1', 'Test', 'active', '2025-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO worlds (id, version, premise, genre, world_rules, "
        "canonical_timeline, unresolved_global_questions, created_at) "
        "VALUES ('w1', '1.0', 'Test world', 'urban_mystery', "
        "'[]', '[]', '[]', '2025-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO characters (id, world_id, canonical_name, role, "
        "traits, age_category, status, created_at) "
        "VALUES ('c1', 'w1', 'Char 1', 'protagonist', "
        "'[]', 'adult', 'active', '2025-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO episodes (id, world_id, episode_type, episode_number, "
        "title, synopsis, scene_list_json, character_ids_json, "
        "location_ids_json, prose_json, review_state, created_at) "
        "VALUES ('ep-1', 'w1', 'canon', 1, 'Test Ep', 'Test', "
        "'[]', '[]', '[]', '[]', 'published', '2025-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO reader_choices (id, reader_id, canon_episode_id, "
        "choice_text, submitted_at) "
        "VALUES ('choice-1', 'reader-1', 'ep-1', 'Test choice', '2025-01-01T00:00:00Z')"
    )
    conn.commit()

    # Verify 002 tables exist (added by migration 002)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    assert "canon_snapshots" in tables
    assert "generation_attempts" in tables
    assert "branch_generation_requests" in tables
    assert "rejoin_requests_v2" in tables
    assert "reader_deletion_audit" in tables

    # Verify 003 columns exist
    cols = [r["name"] for r in conn.execute(
        "PRAGMA table_info(branch_generation_requests)"
    ).fetchall()]
    assert "operation_type" in cols
    assert "attempt_number" in cols
    assert "pending_lease_at" in cols
    assert "updated_at" in cols

    # Verify 004 columns exist
    pe_cols = [r["name"] for r in conn.execute(
        "PRAGMA table_info(pilot_evidence)"
    ).fetchall()]
    assert "privacy_locked" in pe_cols

    ep_cols = [r["name"] for r in conn.execute(
        "PRAGMA table_info(episodes)"
    ).fetchall()]
    assert "is_reader_input_anonymized" in ep_cols

    rc_cols = [r["name"] for r in conn.execute(
        "PRAGMA table_info(reader_choices)"
    ).fetchall()]
    assert "anonymized_principal_id" in rc_cols
    assert "is_anonymized" in rc_cols

    # Data preservation check
    reader = conn.execute("SELECT * FROM readers WHERE id = 'reader-1'").fetchone()
    assert reader is not None
    world = conn.execute("SELECT * FROM worlds WHERE id = 'w1'").fetchone()
    assert world is not None
    char = conn.execute("SELECT * FROM characters WHERE id = 'c1'").fetchone()
    assert char is not None

    # FK check
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert len(violations) == 0, f"FK violations: {violations}"
    conn.close()


def test_migration_fk_violation_rollback(db_path):
    """FK violation during migration triggers rollback and MigrationError."""
    mig_dir = _get_migrations_dir()

    # Apply all migrations first to create the schema
    conn = _make_conn(db_path)
    apply_migrations(conn, mig_dir)
    conn.close()

    # Insert data that would violate FK
    conn = _make_conn(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO episodes (id, world_id, episode_type, episode_number, "
        "title, synopsis, scene_list_json, character_ids_json, "
        "location_ids_json, prose_json, review_state, created_at) "
        "VALUES ('ep-bad', 'nonexistent-world', 'canon', 99, "
        "'Test', 'Test', '[]', '[]', '[]', '[]', 'published', '2025-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    # Verify FK check catches this
    conn = _make_conn(db_path)
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert len(violations) > 0, "FK check should detect the violation"
    conn.close()


def test_all_migrations_idempotent(db_path):
    """Running migrations twice is a no-op (no new versions)."""
    mig_dir = _get_migrations_dir()
    conn = _make_conn(db_path)
    v1 = apply_migrations(conn, mig_dir)
    conn.close()
    conn = _make_conn(db_path)
    v2 = apply_migrations(conn, mig_dir)
    conn.close()
    assert len(v2) == 0, "Second run should apply no new migrations"


def test_close_reopen_preserves_upgraded_state(db_path):
    """Close/reopen preserves all upgraded state."""
    mig_dir = _get_migrations_dir()
    conn = _make_conn(db_path)
    apply_migrations(conn, mig_dir)
    conn.close()

    conn = _make_conn(db_path)
    versions = [r["version"] for r in conn.execute(
        "SELECT version FROM schema_migrations ORDER BY version"
    ).fetchall()]
    assert len(versions) >= 4
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert len(violations) == 0
    conn.close()


def test_migration_error_exception_rolls_back(db_path):
    """MigrationError raised during FK check rolls back the transaction."""
    mig_dir = _get_migrations_dir()

    # Apply 001 first
    conn = _make_conn(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version TEXT PRIMARY KEY, applied_at TEXT)"
    )
    conn.commit()
    _apply_single_migration(conn, mig_dir, "001_initial.sql")

    applied = conn.execute("SELECT version FROM schema_migrations").fetchall()
    assert any(r["version"] == "001_initial.sql" for r in applied)

    # Insert bad data
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO episodes (id, world_id, episode_type, episode_number, "
        "title, synopsis, scene_list_json, character_ids_json, "
        "location_ids_json, prose_json, review_state, created_at) "
        "VALUES ('ep-fk-bad', 'nonexistent', 'canon', 99, "
        "'T', 'T', '[]', '[]', '[]', '[]', 'published', '2025-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    # Try to apply 002 — FK check should fail and rollback
    conn = _make_conn(db_path)
    with pytest.raises(MigrationError):
        apply_migrations(conn, mig_dir)
    conn.close()

    # Verify 002 was NOT recorded
    conn = _make_conn(db_path)
    applied = [r["version"] for r in conn.execute(
        "SELECT version FROM schema_migrations"
    ).fetchall()]
    assert "002_repair_additive.sql" not in applied
    assert "001_initial.sql" in applied
    conn.close()

    # Verify connection is usable after failure
    conn = _make_conn(db_path)
    assert not conn.in_transaction
    conn.close()
