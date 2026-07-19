import importlib
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

import app.db as db_module
from app.config import Settings
from app.db import MigrationError, apply_migrations, get_connection


def _write_migration(dirpath: Path, name: str, sql: str) -> Path:
    path = dirpath / name
    path.write_text(sql)
    return path


def _apply_and_ignore_failure(conn, migrations_dir) -> list[str]:
    try:
        return apply_migrations(conn, str(migrations_dir))
    except MigrationError:
        return []


@pytest.fixture
def tmp_migrations():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


class TestGetConnection:
    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "sub", "test.db")
            conn = get_connection(db_path)
            assert os.path.isdir(os.path.dirname(db_path))
            conn.close()

    def test_memory_does_not_create_file(self):
        conn = get_connection(":memory:")
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert len(tables) == 0
        conn.close()

    def test_foreign_keys_enabled(self):
        conn = get_connection(":memory:")
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        assert row["foreign_keys"] == 1
        conn.close()

    def test_row_factory_is_sqlite3_row(self):
        conn = get_connection(":memory:")
        row = conn.execute("SELECT 1 AS v").fetchone()
        assert row["v"] == 1
        conn.close()


class TestApplyMigrations:
    def test_fresh_database_creates_tables(self, tmp_migrations):
        _write_migration(
            tmp_migrations,
            "001_test.sql",
            "CREATE TABLE t1 (id TEXT PRIMARY KEY);",
        )
        conn = get_connection(":memory:")
        versions = apply_migrations(conn, str(tmp_migrations))
        assert versions == ["001_test.sql"]

        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "t1" in tables
        assert "schema_migrations" in tables
        conn.close()

    def test_all_six_tables_exist(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")

        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "schema_migrations",
            "participants",
            "inputs",
            "editions",
            "feedback",
            "generation_runs",
        }
        assert tables == expected
        conn.close()

    def test_idempotent_rerun(self, tmp_migrations):
        _write_migration(
            tmp_migrations,
            "001_test.sql",
            "CREATE TABLE t1 (id TEXT PRIMARY KEY);",
        )
        conn = get_connection(":memory:")
        r1 = apply_migrations(conn, str(tmp_migrations))
        r2 = apply_migrations(conn, str(tmp_migrations))
        assert r1 == ["001_test.sql"]
        assert r2 == []

        count = conn.execute(
            "SELECT COUNT(*) AS c FROM schema_migrations"
        ).fetchone()
        assert count["c"] == 1
        conn.close()

    def test_broken_migration_raises(self, tmp_migrations):
        _write_migration(
            tmp_migrations,
            "001_valid.sql",
            "CREATE TABLE t1 (id TEXT PRIMARY KEY);",
        )
        _write_migration(
            tmp_migrations,
            "002_broken.sql",
            "CREATE TABLE t2 (id TEXT PRIMARY KEY); INVALID SQL HERE;",
        )
        conn = get_connection(":memory:")
        with pytest.raises(MigrationError) as excinfo:
            apply_migrations(conn, str(tmp_migrations))
        assert "002_broken.sql" in str(excinfo.value)
        conn.close()

    def test_first_migration_persists_after_failure(self, tmp_migrations):
        _write_migration(
            tmp_migrations,
            "001_valid.sql",
            "CREATE TABLE t1 (id TEXT PRIMARY KEY);",
        )
        _write_migration(
            tmp_migrations,
            "002_broken.sql",
            "INVALID SQL;",
        )
        conn = get_connection(":memory:")
        with pytest.raises(MigrationError):
            apply_migrations(conn, str(tmp_migrations))

        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "t1" in tables
        assert "t2" not in tables
        conn.close()

    def test_not_recorded_on_failure(self, tmp_migrations):
        _write_migration(
            tmp_migrations,
            "001_valid.sql",
            "CREATE TABLE t1 (id TEXT PRIMARY KEY);",
        )
        _write_migration(
            tmp_migrations,
            "002_broken.sql",
            "INVALID SQL;",
        )
        conn = get_connection(":memory:")
        _apply_and_ignore_failure(conn, tmp_migrations)

        records = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        versions = [r["version"] for r in records]
        assert versions == ["001_valid.sql"]
        conn.close()

    def test_third_migration_not_applied_after_failure(self, tmp_migrations):
        _write_migration(
            tmp_migrations,
            "001_valid.sql",
            "CREATE TABLE t1 (id TEXT PRIMARY KEY);",
        )
        _write_migration(
            tmp_migrations,
            "002_broken.sql",
            "INVALID SQL;",
        )
        _write_migration(
            tmp_migrations,
            "003_good.sql",
            "CREATE TABLE t3 (id TEXT PRIMARY KEY);",
        )
        conn = get_connection(":memory:")
        _apply_and_ignore_failure(conn, tmp_migrations)

        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "t1" in tables
        assert "t3" not in tables

        versions = [
            r["version"]
            for r in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        assert versions == ["001_valid.sql"]
        conn.close()

    def test_repair_and_reapply(self, tmp_migrations):
        _write_migration(
            tmp_migrations,
            "001_valid.sql",
            "CREATE TABLE t1 (id TEXT PRIMARY KEY);",
        )
        _write_migration(
            tmp_migrations,
            "002_broken.sql",
            "INVALID SQL;",
        )
        _write_migration(
            tmp_migrations,
            "003_pending.sql",
            "CREATE TABLE t3 (id TEXT PRIMARY KEY);",
        )
        conn = get_connection(":memory:")
        with pytest.raises(MigrationError):
            apply_migrations(conn, str(tmp_migrations))

        _write_migration(
            tmp_migrations,
            "002_broken.sql",
            "CREATE TABLE t2 (id TEXT PRIMARY KEY);",
        )
        r2 = apply_migrations(conn, str(tmp_migrations))
        assert r2 == ["002_broken.sql", "003_pending.sql"]

        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "t1" in tables
        assert "t2" in tables
        assert "t3" in tables

        versions = [
            r["version"]
            for r in conn.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        assert versions == ["001_valid.sql", "002_broken.sql", "003_pending.sql"]
        conn.close()

    def test_semicolon_in_value(self, tmp_migrations):
        _write_migration(
            tmp_migrations,
            "001_sample.sql",
            (
                "CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL);\n"
                "INSERT INTO sample(value) VALUES ('alpha;beta');\n"
            ),
        )
        conn = get_connection(":memory:")
        apply_migrations(conn, str(tmp_migrations))

        row = conn.execute(
            "SELECT value FROM sample WHERE id = 1"
        ).fetchone()
        assert row["value"] == "alpha;beta"
        conn.close()


class TestSchemaContract:
    def test_access_token_hash_column(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(participants)").fetchall()
        }
        assert "access_token_hash" in cols
        assert "access_token" not in cols
        conn.close()

    def test_normalized_text_column(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(inputs)").fetchall()
        }
        assert "normalized_text" in cols
        conn.close()

    def test_edition_number_column(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(editions)").fetchall()
        }
        assert "edition_number" in cols
        conn.close()

    def test_applied_to_next_edition_column(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(feedback)").fetchall()
        }
        assert "applied_to_next_edition" in cols
        conn.close()

    def test_generation_started_completed_at(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        cols = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(generation_runs)"
            ).fetchall()
        }
        assert "started_at" in cols
        assert "completed_at" in cols
        conn.close()

    def test_human_correction_column(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(editions)").fetchall()
        }
        assert "human_correction_minutes" in cols
        conn.close()

    def test_participant_foreign_key(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        fks = conn.execute(
            "PRAGMA foreign_key_list(inputs)"
        ).fetchall()
        assert any(row["table"] == "participants" for row in fks)
        conn.close()

    def test_foreign_key_violation_fails(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO inputs "
                "(id, participant_id, sequence_number, raw_text, submitted_at, "
                "consent_confirmed) "
                "VALUES ('i1', 'nonexistent', 1, 'text', '2026-01-01', 1)"
            )
        conn.close()

    def test_consent_rejects_invalid_value(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        conn.execute(
            "INSERT INTO participants "
            "(id, display_name, access_token_hash, created_at, updated_at) "
            "VALUES ('p1', 'test', 'hash', '2026-01-01', '2026-01-01')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO inputs "
                "(id, participant_id, sequence_number, raw_text, submitted_at, "
                "consent_confirmed) "
                "VALUES ('i2', 'p1', 1, 'text', '2026-01-01', 2)"
            )
        conn.close()

    def test_negative_retry_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO generation_runs "
                "(id, task_type, provider, advertised_model, started_at, "
                "retry_count) "
                "VALUES ('r1', 'plan', 'mock', 'm', '2026-01-01', -1)"
            )
        conn.close()

    def test_negative_latency_rejected(self):
        conn = get_connection(":memory:")
        apply_migrations(conn, "migrations")
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO generation_runs "
                "(id, task_type, provider, advertised_model, started_at, "
                "retry_count, latency_seconds) "
                "VALUES ('r2', 'plan', 'mock', 'm', '2026-01-01', 0, -0.5)"
            )
        conn.close()


class TestImportDoesNotCreateDatabase:
    def test_settings_import_does_not_create_db(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "should_not_exist.db")
            Settings(database_path=db_path)
            assert not os.path.isfile(db_path)

    def test_db_module_import_does_not_create_db(self):
        importlib.reload(db_module)
        db_files = [
            p for p in Path(".").rglob("*.db")
            if p.name != "should_not_exist.db"
        ]
        assert len(db_files) == 0
