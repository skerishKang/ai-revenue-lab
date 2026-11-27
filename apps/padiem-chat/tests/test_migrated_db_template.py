"""#889x: prove migrated test DB file copies retain the original SQLite contract."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from _support.migrated_db_template import (
    apply_copied_migrations,
    copy_migrated_database,
    fill_empty_connection,
    migrated_connection,
    migrated_template,
)
from _support.claw_local_task_result import _open_database

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"


def _snapshot(connection: sqlite3.Connection):
    schema = connection.execute(
        "SELECT type,name,tbl_name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_stat%' ORDER BY type,name"
    ).fetchall()
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    rows = {}
    for (name,) in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall():
        # SQLite table row order is not a contract. Compare deterministic
        # serialized row sets including any rows seeded by the migrations.
        contents = connection.execute(f'SELECT * FROM "{name}"').fetchall()
        rows[name] = sorted(tuple(repr(v) for v in row) for row in contents)
    return schema, version, rows


def _raw_fresh(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA synchronous=OFF")
    for sql in sorted(MIGRATIONS.glob("*.sql")):
        connection.executescript(sql.read_text(encoding="utf-8"))
    return connection


def test_raw_fresh_migrations_and_two_file_copies_match_schema_version_and_initial_rows(tmp_path):
    original = _raw_fresh(tmp_path / "original.sqlite3")
    a = migrated_connection(tmp_path / "first.sqlite3")
    b = migrated_connection(tmp_path / "second.sqlite3")
    try:
        expected = _snapshot(original)
        assert _snapshot(a) == expected
        assert _snapshot(b) == expected
        assert a.execute("PRAGMA foreign_keys").fetchone() == original.execute(
            "PRAGMA foreign_keys"
        ).fetchone()
        a.execute("CREATE TABLE isolated_write (id INTEGER PRIMARY KEY)")
        a.execute("PRAGMA user_version=42")
        assert _snapshot(b) == expected
        assert _snapshot(original) == expected
    finally:
        original.close()
        a.close()
        b.close()


def test_in_memory_copy_has_exact_original_schema_version_and_initial_rows(tmp_path):
    original = _raw_fresh(tmp_path / "original.sqlite3")
    clone = migrated_connection(":memory:")
    try:
        assert _snapshot(clone) == _snapshot(original)
        assert clone.execute("PRAGMA foreign_keys").fetchone() == original.execute(
            "PRAGMA foreign_keys"
        ).fetchone()
    finally:
        original.close()
        clone.close()


def test_migration_manifest_add_remove_and_content_change_refresh_templates(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    first = migrations / "001_create.sql"
    first.write_text("CREATE TABLE examples (id INTEGER PRIMARY KEY);", encoding="utf-8")
    initial, _ = migrated_template(migrations)
    assert initial.is_file()
    second = migrations / "002_seed.sql"
    second.write_text("INSERT INTO examples (id) VALUES (1);", encoding="utf-8")
    added, _ = migrated_template(migrations)
    assert added != initial
    with migrated_connection(":memory:", migrations) as connection:
        assert connection.execute("SELECT id FROM examples").fetchall() == [(1,)]
    second.write_text("INSERT INTO examples (id) VALUES (2);", encoding="utf-8")
    edited, _ = migrated_template(migrations)
    assert edited != added
    with migrated_connection(":memory:", migrations) as connection:
        assert connection.execute("SELECT id FROM examples").fetchall() == [(2,)]
    second.unlink()
    removed, _ = migrated_template(migrations)
    assert removed != edited
    with migrated_connection(":memory:", migrations) as connection:
        assert connection.execute("SELECT count(*) FROM examples").fetchone()[0] == 0
    with sqlite3.connect(initial) as connection:
        assert connection.execute("SELECT count(*) FROM examples").fetchone()[0] == 0


def test_local_cpython_ledger_template_preserves_initial_rows_and_isolation(tmp_path):
    from app.local_cpython import apply_migrations

    original = sqlite3.connect(":memory:", isolation_level=None)
    fresh_count = apply_migrations(original, MIGRATIONS)
    a = migrated_connection(":memory:", loader="local_cpython")
    b = migrated_connection(":memory:", loader="local_cpython")
    try:
        assert _snapshot(a)[0:2] == _snapshot(original)[0:2]
        assert _snapshot(b) == _snapshot(a)
        assert fresh_count == len(tuple(MIGRATIONS.glob("*.sql")))
        assert apply_copied_migrations(b, MIGRATIONS) == 0
        assert _snapshot(a) == _snapshot(b)
    finally:
        original.close()
        a.close()
        b.close()


def test_empty_adapter_can_be_filled_without_replacing_its_connection():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    try:
        assert fill_empty_connection(connection) == len(tuple(MIGRATIONS.glob("*.sql")))
        assert connection.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] > 0
        with pytest.raises(ValueError, match="unused"):
            fill_empty_connection(connection)
    finally:
        connection.close()


def test_reopen_existing_file_without_migrations_keeps_test_data(tmp_path):
    database = tmp_path / "reopen.sqlite3"
    first = _open_database(database)
    first._connection.execute("CREATE TABLE reopening_probe (value TEXT)")
    first._connection.execute("INSERT INTO reopening_probe VALUES ('kept')")
    first.close()
    reopened = _open_database(database, migrate=False)
    try:
        assert reopened._connection.execute("SELECT value FROM reopening_probe").fetchone() == ("kept",)
    finally:
        reopened.close()
