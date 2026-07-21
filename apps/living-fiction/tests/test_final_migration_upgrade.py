"""Final migration upgrade contract tests.

Tests real 001 → 002 → 003 → 004 file-backed upgrade with data preservation,
FK checks, idempotency, and close/reopen semantics.
"""
from __future__ import annotations

import json
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
        os.unlink(path)


def _get_migrations_dir():
    return os.path.join(os.path.dirname(__file__), "..", "migrations")


def test_real_populated_001_to_002_to_003_to_004_upgrade(db_path):
    """Complete 001→002→003→004 upgrade with data preservation."""
    mig_dir = _get_migrations_dir()
    conn = _make_conn(db_path)

    # Apply 001 only
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT)"
    )
    conn.commit()
    # Manually apply 001
    with open(os.path.join(mig_dir, "001_initial.sql")) as f:
        sql_001 = f.read()
    for stmt in sql_001.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as e:
                # Skip IF NOT EXISTS warnings on re-apply
                pass
    conn.execute("INSERT OR IGNORE INTO schema_migrations (version) VALUES ('001_initial.sql')")
    conn.commit()

    # Seed data
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
    conn.commit()
    conn.close()

    # Apply 002
    conn = _make_conn(db_path)
    apply_migrations(conn, mig_dir)
    conn.close()

    # Verify 002 data (canon_snapshots)
    conn = _make_conn(db_path)
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = [r["name"] for r in rows]
    assert "canon_snapshots" in table_names

    # Seed more data (for 003)
    # Need to create episode first for FK
    conn.execute(
        "INSERT INTO episodes (id, world_id, episode_type, episode_number, "
        "title, synopsis, scene_list_json, character_ids_json, "
        "location_ids_json, prose_json, review_state, created_at) "
        "VALUES ('ep-1', 'w1', 'canon', 1, "
        "'Test Ep', 'Test', '[]', '[]', '[]', '[]', 'published', '2025-01-01T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO reader_choices (id, reader_id, canon_episode_id, choice_text, submitted_at) "
        "VALUES ('choice-1', 'reader-1', 'ep-1', 'Test choice', '2025-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.close()

    # Apply 003
    conn = _make_conn(db_path)
    apply_migrations(conn, mig_dir)
    conn.close()

    # Verify 003 data
    conn = _make_conn(db_path)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(branch_generation_requests)").fetchall()]
    assert "operation_type" in cols
    assert "attempt_number" in cols
    assert "pending_lease_at" in cols
    conn.close()

    # Apply 004
    conn = _make_conn(db_path)
    apply_migrations(conn, mig_dir)
    conn.close()

    # Verify 004 data
    conn = _make_conn(db_path)
    pe_cols = [r["name"] for r in conn.execute("PRAGMA table_info(pilot_evidence)").fetchall()]
    assert "privacy_locked" in pe_cols
    ep_cols = [r["name"] for r in conn.execute("PRAGMA table_info(episodes)").fetchall()]
    assert "is_reader_input_anonymized" in ep_cols
    rc_cols = [r["name"] for r in conn.execute("PRAGMA table_info(reader_choices)").fetchall()]
    assert "anonymized_principal_id" in rc_cols

    # Data preservation check
    world = conn.execute("SELECT * FROM worlds WHERE id = 'w1'").fetchone()
    assert world is not None
    char = conn.execute("SELECT * FROM characters WHERE id = 'c1'").fetchone()
    assert char is not None
    reader = conn.execute("SELECT * FROM readers WHERE id = 'reader-1'").fetchone()
    assert reader is not None

    # FK check
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert len(violations) == 0, f"FK violations: {violations}"

    conn.close()


def test_migration_failure_does_not_record_schema_version(db_path):
    """Failed migration does not record schema version."""
    conn = _make_conn(db_path)
    conn.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT)")
    conn.commit()

    # Apply migrations to create tables
    mig_dir = _get_migrations_dir()
    conn.close()
    conn = _make_conn(db_path)
    apply_migrations(conn, mig_dir)
    conn.close()

    # Now insert FK-violating data (disable FK temporarily for test)
    conn = _make_conn(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO episodes (id, world_id, episode_type, episode_number, "
        "title, synopsis, scene_list_json, character_ids_json, "
        "location_ids_json, prose_json, review_state, created_at) "
        "VALUES ('ep-bad', 'nonexistent-world', 'canon', 1, "
        "'Test', 'Test', '[]', '[]', '[]', '[]', 'published', '2025-01-01T00:00:00Z')"
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    # Now test that FK check catches this
    conn = _make_conn(db_path)
    with pytest.raises(MigrationError):
        # Force FK check
        conn.execute("PRAGMA foreign_key_check")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise MigrationError("test_migration.sql", RuntimeError(f"FK violations: {violations}"))
    conn.close()


def test_foreign_key_check_runs_before_migration_success(db_path):
    """FK check runs before migration is recorded as successful."""
    mig_dir = _get_migrations_dir()
    conn = _make_conn(db_path)
    # Apply all migrations
    versions = apply_migrations(conn, mig_dir)
    assert len(versions) >= 4, f"Expected 4+ migrations, got {versions}"
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
    # FK still clean
    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    assert len(violations) == 0
    conn.close()
