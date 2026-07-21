"""Integration tests for Living Travel database and migrations."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.db import apply_migrations, get_connection, MigrationError, _iter_sql_statements


@pytest.fixture
def temp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    apply_migrations(db_path)
    return db_path


class TestMigrations:
    def test_creates_all_tables(self, temp_db):
        conn = sqlite3.connect(temp_db)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        expected = {
            "schema_migrations",
            "travelers",
            "sources",
            "travel_inputs",
            "editions",
            "feedback",
            "generation_runs",
            "pilot_evidence",
        }
        assert expected.issubset(tables)

    def test_idempotent(self, temp_db):
        apply_migrations(temp_db)
        apply_migrations(temp_db)
        conn = sqlite3.connect(temp_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM schema_migrations"
        ).fetchone()[0]
        conn.close()
        assert count == 3  # 001_initial.sql + 002_audit_constraints.sql + 003_auth.sql

    def test_schema_migrations_records_version(self, temp_db):
        conn = sqlite3.connect(temp_db)
        row = conn.execute(
            "SELECT version, filename FROM schema_migrations"
        ).fetchone()
        conn.close()
        assert row[0] == "001_initial.sql"
        assert row[1] == "001_initial.sql"


class TestConnection:
    def test_connection_has_row_factory(self, temp_db):
        conn = get_connection(temp_db)
        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_foreign_keys_enabled(self, temp_db):
        conn = get_connection(temp_db)
        row = conn.execute("PRAGMA foreign_keys").fetchone()
        conn.close()
        assert row[0] == 1


class TestIterSqlStatements:
    def test_simple_statements(self):
        sql = "CREATE TABLE a (id INTEGER); CREATE TABLE b (id INTEGER);"
        stmts = list(_iter_sql_statements(sql))
        assert len(stmts) == 2

    def test_comments_ignored(self):
        sql = "-- comment\nCREATE TABLE a (id INTEGER);"
        stmts = list(_iter_sql_statements(sql))
        assert len(stmts) == 1
        assert "CREATE TABLE" in stmts[0]

    def test_block_comments(self):
        sql = "/* block */ CREATE TABLE a (id INTEGER);"
        stmts = list(_iter_sql_statements(sql))
        assert len(stmts) == 1
