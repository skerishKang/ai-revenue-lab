"""Migration 010 fail-closed row preservation.

Migration 010 is not yet released (never merged to main, never applied to a
durable database), so it is corrected before first release. The table rebuilds
must transfer every valid row, fail closed on any invalid legacy row, and — on
failure — leave the original table and all rows intact (no DROP after loss).
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from app.db import MigrationError, _MIGRATIONS_DIR, _apply_one, apply_migrations


def _apply_through_009(path: str) -> sqlite3.Connection:
    """Apply migrations 001..009 only, returning an open connection."""
    conn = sqlite3.connect(path)
    conn.isolation_level = None
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, "
        "filename TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    for mf in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        if mf.name.startswith("010"):
            break
        _apply_one(conn, mf.name, mf.read_text(encoding="utf-8"))
    return conn


def _seed_learner(conn: sqlite3.Connection, learner_id: str = "L1") -> str:
    conn.execute("INSERT INTO learners (id, topic, status) VALUES (?, 'Python', 'active')", (learner_id,))
    conn.execute(
        "INSERT INTO curricula (id, topic, created_at) VALUES ('curr1', 'Python', datetime('now'))"
    )
    conn.execute(
        "INSERT INTO concepts (id, curriculum_id, name, description, prerequisites, sequence_order, created_at) "
        "VALUES ('c1', 'curr1', 'variables', 'vars', '[]', 0, datetime('now'))"
    )
    return "c1"


def _insert_lesson(conn, lesson_id, learner_id, concept_id, number, publication_state, generation_status="pending_review"):
    conn.execute(
        "INSERT INTO lessons (id, learner_id, concept_id, lesson_number, prior_lesson_id, "
        "generation_status, publication_state, lesson_plan_json, lesson_content_json, adaptation_summary, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, NULL, ?, ?, '{}', '{}', '', datetime('now'), datetime('now'))",
        (lesson_id, learner_id, concept_id, number, generation_status, publication_state),
    )


def _count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def _table_exists(conn, table):
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def test_010_preserves_all_valid_lesson_rows():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = _apply_through_009(path)
        concept_id = _seed_learner(conn)
        for i, pub in enumerate(["pending", "published", "rejected", "pending"], start=1):
            _insert_lesson(conn, f"les{i}", "L1", concept_id, i, pub)
        before = _count(conn, "lessons")
        assert before == 4
        conn.close()

        apply_migrations(path)  # applies 010

        conn = sqlite3.connect(path)
        after = _count(conn, "lessons")
        assert after == before
        pubs = {r[0] for r in conn.execute("SELECT publication_state FROM lessons").fetchall()}
        assert pubs == {"pending", "published", "rejected"}
        conn.close()
    finally:
        _cleanup(path)


def test_010_preserves_all_valid_memberships():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = _apply_through_009(path)
        _seed_learner(conn)
        conn.execute(
            "INSERT INTO external_identities (id, provider, issuer, subject, status) "
            "VALUES ('eid1', 'firebase', 'iss', 'sub', 'active')"
        )
        # Valid memberships: learner WITH learner_id; operator/reviewer WITHOUT.
        conn.execute(
            "INSERT INTO product_memberships (id, external_identity_id, role, learner_id, status) "
            "VALUES ('m1', 'eid1', 'learner', 'L1', 'active')"
        )
        conn.execute(
            "INSERT INTO product_memberships (id, external_identity_id, role, learner_id, status) "
            "VALUES ('m2', 'eid1', 'operator', NULL, 'active')"
        )
        before = _count(conn, "product_memberships")
        assert before == 2
        conn.close()

        apply_migrations(path)

        conn = sqlite3.connect(path)
        assert _count(conn, "product_memberships") == before
        conn.close()
    finally:
        _cleanup(path)


def test_010_row_counts_match_before_and_after():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = _apply_through_009(path)
        concept_id = _seed_learner(conn)
        for i in range(1, 6):
            _insert_lesson(conn, f"les{i}", "L1", concept_id, i, "pending")
        conn.execute(
            "INSERT INTO external_identities (id, provider, issuer, subject, status) "
            "VALUES ('eid1', 'firebase', 'iss', 'sub', 'active')"
        )
        conn.execute(
            "INSERT INTO product_memberships (id, external_identity_id, role, learner_id, status) "
            "VALUES ('m1', 'eid1', 'learner', 'L1', 'active')"
        )
        lessons_before = _count(conn, "lessons")
        memberships_before = _count(conn, "product_memberships")
        conn.close()

        apply_migrations(path)

        conn = sqlite3.connect(path)
        assert _count(conn, "lessons") == lessons_before
        assert _count(conn, "product_memberships") == memberships_before
        conn.close()
    finally:
        _cleanup(path)


def test_010_invalid_lesson_state_rolls_back_without_data_loss():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = _apply_through_009(path)
        concept_id = _seed_learner(conn)
        _insert_lesson(conn, "good1", "L1", concept_id, 1, "pending")
        # publication_state has no CHECK before 010, so this legacy row is insertable.
        _insert_lesson(conn, "bad1", "L1", concept_id, 2, "totally_bogus_state")
        before = _count(conn, "lessons")
        assert before == 2
        conn.close()

        with pytest.raises(MigrationError):
            apply_migrations(path)

        # Original table and ALL rows preserved; rebuild artefact rolled back;
        # 010 not recorded.
        conn = sqlite3.connect(path)
        assert _table_exists(conn, "lessons")
        assert _count(conn, "lessons") == before
        assert not _table_exists(conn, "lessons_new")
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        assert "010_acceptance_repair_contract.sql" not in applied
        # The bogus row is still present (nothing was dropped).
        bogus = conn.execute("SELECT publication_state FROM lessons WHERE id='bad1'").fetchone()
        assert bogus[0] == "totally_bogus_state"
        conn.close()

        # Re-running after fixing the row succeeds (migration is retryable).
        conn = sqlite3.connect(path)
        conn.isolation_level = None
        conn.execute("UPDATE lessons SET publication_state='pending' WHERE id='bad1'")
        conn.close()
        apply_migrations(path)
        conn = sqlite3.connect(path)
        assert _count(conn, "lessons") == before
        conn.close()
    finally:
        _cleanup(path)


def test_010_invalid_membership_rolls_back_without_data_loss():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        conn = _apply_through_009(path)
        _seed_learner(conn)
        conn.execute(
            "INSERT INTO external_identities (id, provider, issuer, subject, status) "
            "VALUES ('eid1', 'firebase', 'iss', 'sub', 'active')"
        )
        conn.execute(
            "INSERT INTO product_memberships (id, external_identity_id, role, learner_id, status) "
            "VALUES ('good_m', 'eid1', 'operator', NULL, 'active')"
        )
        # learner role with NULL learner_id violates the new 010 CHECK but is
        # insertable before 010.
        conn.execute(
            "INSERT INTO product_memberships (id, external_identity_id, role, learner_id, status) "
            "VALUES ('bad_m', 'eid1', 'learner', NULL, 'active')"
        )
        before = _count(conn, "product_memberships")
        assert before == 2
        conn.close()

        with pytest.raises(MigrationError):
            apply_migrations(path)

        conn = sqlite3.connect(path)
        assert _table_exists(conn, "product_memberships")
        assert _count(conn, "product_memberships") == before
        assert not _table_exists(conn, "product_memberships_new")
        applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
        assert "010_acceptance_repair_contract.sql" not in applied
        conn.close()
    finally:
        _cleanup(path)


def _cleanup(path: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)
        except PermissionError:
            pass
