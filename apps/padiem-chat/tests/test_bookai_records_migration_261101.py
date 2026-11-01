"""BookAI v1 SQLite schema and the existing host migration discovery."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app.local_cpython import apply_migrations

MIGRATION = (
    Path(__file__).resolve().parents[1] / "migrations" / "082_bookai_records.sql"
)
INSERT = """
INSERT INTO bookai_records
    (subject, record_id, book_id, locator, kind, payload, updated_at, deleted)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def test_host_discovers_new_bookai_migration_once_without_losing_existing_data(tmp_path):
    # Exercise the real host runner against a pre-existing database, without
    # starting the app or touching its configured data directory.
    (tmp_path / "001_existing.sql").write_text(
        "CREATE TABLE existing(value TEXT); INSERT INTO existing VALUES ('kept');",
        encoding="utf-8",
    )
    with sqlite3.connect(":memory:", isolation_level=None) as connection:
        assert apply_migrations(connection, tmp_path) == 1
        (tmp_path / MIGRATION.name).write_bytes(MIGRATION.read_bytes())
        assert apply_migrations(connection, tmp_path) == 1
        assert apply_migrations(connection, tmp_path) == 0
        assert connection.execute("SELECT value FROM existing").fetchall() == [("kept",)]
        assert connection.execute(
            "SELECT name FROM padiem_local_migration_ledger ORDER BY name"
        ).fetchall() == [("001_existing.sql",), (MIGRATION.name,)]
        columns = connection.execute("PRAGMA table_info(bookai_records)").fetchall()
        assert [column[1] for column in columns] == [
            "subject", "record_id", "book_id", "locator", "kind", "payload",
            "updated_at", "deleted",
        ]


def test_subject_scoped_key_preserves_json_and_deleted_records():
    payload = json.dumps({"text": "사도행전 9장", "nested": {"page": 9}}, ensure_ascii=False)
    with sqlite3.connect(":memory:", isolation_level=None) as connection:
        connection.executescript(MIGRATION.read_text(encoding="utf-8"))
        for subject in ("reader-one", "reader-two"):
            connection.execute(
                INSERT, (subject, "same-id", "bible", "acts:9", "note", payload, 100, 0)
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                INSERT, ("reader-one", "same-id", "bible", "acts:9", "note", payload, 101, 0)
            )
        connection.execute(
            "UPDATE bookai_records SET deleted = 1, updated_at = 200 "
            "WHERE subject = ? AND record_id = ?",
            ("reader-one", "same-id"),
        )
        rows = connection.execute(
            "SELECT subject, payload, deleted FROM bookai_records ORDER BY subject"
        ).fetchall()
        assert rows == [("reader-one", payload, 1), ("reader-two", payload, 0)]
        assert json.loads(rows[0][1]) == {"text": "사도행전 9장", "nested": {"page": 9}}
        # Incremental reads include tombstones and use the subject/time index.
        query = (
            "SELECT record_id, deleted FROM bookai_records "
            "WHERE subject = ? AND updated_at > ? ORDER BY updated_at, record_id"
        )
        assert connection.execute(query, ("reader-one", 100)).fetchall() == [("same-id", 1)]
        plan = connection.execute("EXPLAIN QUERY PLAN " + query, ("reader-one", 100)).fetchall()
        assert any("idx_bookai_records_subject_updated" in row[3] for row in plan)


@pytest.mark.parametrize(
    ("column", "invalid"),
    [
        ("kind", "unknown"),
        ("payload", "not-json"),
        ("payload", "[]"),
        ("updated_at", -1),
        ("updated_at", "not-a-timestamp"),
        ("deleted", 2),
    ],
)
def test_schema_rejects_records_outside_v1_contract(column, invalid):
    row = dict(
        subject="reader", record_id="record", book_id="book", locator="chapter:1",
        kind="note", payload="{}", updated_at=100, deleted=0,
    )
    row[column] = invalid
    with sqlite3.connect(":memory:", isolation_level=None) as connection:
        connection.executescript(MIGRATION.read_text(encoding="utf-8"))
        with pytest.raises((sqlite3.IntegrityError, sqlite3.OperationalError)):
            connection.execute(INSERT, tuple(row.values()))
