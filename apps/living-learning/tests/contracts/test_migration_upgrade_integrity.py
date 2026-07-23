"""Blocker H: migration integrity.

Verifies fresh apply, staged upgrade, idempotent re-run, foreign-key integrity
(PRAGMA foreign_key_check), zero orphans, and that the new contract tables and
constraints exist. Additive migrations only — 001..008 are never modified.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile

from app.db import MigrationError, apply_migrations, get_connection


def test_fresh_apply_creates_contract_tables():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        apply_migrations(path)
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        for expected in (
            "idempotency_requests",
            "adaptation_decisions",
            "external_identities",
            "product_memberships",
            "generation_runs",
        ):
            assert expected in tables, f"missing table {expected}"
        conn.close()
    finally:
        _cleanup(path)


def test_idempotent_rerun_keeps_nine_migrations():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        apply_migrations(path)
        apply_migrations(path)  # re-run must be a no-op
        conn = sqlite3.connect(path)
        count = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
        assert count == 9
        conn.close()
    finally:
        _cleanup(path)


def test_staged_upgrade_from_pre_009_database():
    """Simulate a database that stopped at 008, then upgrade to 009."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        # Apply only 001..008 by temporarily hiding 009 via a partial apply.
        _apply_up_to(path, stop_before="009")
        conn = sqlite3.connect(path)
        pre_count = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
        assert pre_count == 8
        conn.close()

        # Now run the full migration set — 009 upgrades the schema.
        apply_migrations(path)
        conn = sqlite3.connect(path)
        post_count = conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]
        assert post_count == 9
        # idempotency_requests now supports the widened status domain.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(idempotency_requests)").fetchall()}
        assert "status" in cols
        # adaptation_decisions rebuilt with the new columns.
        adapt_cols = {r[1] for r in conn.execute("PRAGMA table_info(adaptation_decisions)").fetchall()}
        assert {"learner_id", "prior_lesson_id", "next_lesson_id", "dimension"} <= adapt_cols
        conn.close()
    finally:
        _cleanup(path)


def test_foreign_key_check_clean_after_apply():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        apply_migrations(path)
        conn = sqlite3.connect(path)
        conn.execute("PRAGMA foreign_keys=ON")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert violations == []
        conn.close()
    finally:
        _cleanup(path)


def test_idempotency_status_check_constraint_enforced():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        apply_migrations(path)
        conn = sqlite3.connect(path)
        # Valid lifecycle statuses are accepted.
        for status in ("pending", "completed", "failed_retryable", "failed_terminal"):
            conn.execute(
                "INSERT INTO idempotency_requests (id, key_value, operation_type, status) "
                "VALUES (?, ?, 'task', ?)",
                (f"id_{status}", f"key_{status}", status),
            )
        conn.commit()
        # An invalid status is rejected by the CHECK constraint.
        try:
            conn.execute(
                "INSERT INTO idempotency_requests (id, key_value, operation_type, status) "
                "VALUES ('bad', 'badkey', 'task', 'bogus')"
            )
            conn.commit()
            assert False, "expected CHECK constraint failure"
        except sqlite3.IntegrityError:
            pass
        conn.close()
    finally:
        _cleanup(path)


def test_membership_role_check_constraint_enforced():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        apply_migrations(path)
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO external_identities (id, provider, issuer, subject, status) "
            "VALUES ('eid1', 'firebase', 'iss', 'sub', 'active')"
        )
        for role in ("learner", "operator", "reviewer"):
            conn.execute(
                "INSERT INTO product_memberships (id, external_identity_id, role, status) "
                "VALUES (?, 'eid1', ?, 'active')",
                (f"mem_{role}", role),
            )
        conn.commit()
        try:
            conn.execute(
                "INSERT INTO product_memberships (id, external_identity_id, role, status) "
                "VALUES ('mem_bad', 'eid1', 'superuser', 'active')"
            )
            conn.commit()
            assert False, "expected role CHECK failure"
        except sqlite3.IntegrityError:
            pass
        conn.close()
    finally:
        _cleanup(path)


def _apply_up_to(path: str, stop_before: str) -> None:
    from app.db import _MIGRATIONS_DIR, _iter_sql_statements

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, filename TEXT NOT NULL, applied_at TEXT)"
    )
    conn.commit()
    for mf in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        if mf.name.startswith(stop_before):
            break
        for stmt in _iter_sql_statements(mf.read_text(encoding="utf-8")):
            conn.execute(stmt)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (version, filename) VALUES (?, ?)",
            (mf.name, mf.name),
        )
        conn.commit()
    conn.close()


def _cleanup(path: str) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            if os.path.exists(path + suffix):
                os.unlink(path + suffix)
        except PermissionError:
            pass
