"""Integration tests for database setup and migrations."""

from __future__ import annotations

import os
import tempfile

import pytest
import sqlite3

from app.db import apply_migrations, get_connection, MigrationError


def test_apply_migrations_creates_tables(temp_db_path: str) -> None:
    apply_migrations(temp_db_path)

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()

    table_names = [t["name"] for t in tables]

    assert "learners" in table_names
    assert "lessons" in table_names
    assert "feedback" in table_names
    assert "generation_runs" in table_names
    assert "pilot_evidence" in table_names
    assert "schema_migrations" in table_names

    conn.close()


def test_migrations_are_idempotent(temp_db_path: str) -> None:
    apply_migrations(temp_db_path)
    apply_migrations(temp_db_path)

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row

    migrations = conn.execute(
        "SELECT COUNT(*) as cnt FROM schema_migrations"
    ).fetchone()

    assert migrations["cnt"] == 6

    conn.close()


def test_foreign_keys_enabled_after_migration(temp_db_path: str) -> None:
    apply_migrations(temp_db_path)

    conn = get_connection(temp_db_path)
    result = conn.execute("PRAGMA foreign_keys").fetchone()
    conn.close()
    assert result[0] == 1


def test_get_connection_returns_row_factory(temp_db_path: str) -> None:
    apply_migrations(temp_db_path)

    conn = get_connection(temp_db_path)
    conn.execute(
        "INSERT INTO learners (id, display_name, topic) VALUES (?, ?, ?)",
        ("test_learner", "Test", "Python"),
    )
    conn.commit()
    conn.close()

    conn2 = get_connection(temp_db_path)
    row = conn2.execute("SELECT * FROM learners WHERE id = ?", ("test_learner",)).fetchone()
    assert row is not None
    assert row["display_name"] == "Test"
    conn2.close()