"""The stage-3 copy tool is prepared, tested offline, and never run by CI."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

# Loaded by path: the tool sits next to the app package, not inside it, and
# this test must not depend on the runner's sys.path.
_SPEC = importlib.util.spec_from_file_location(
    "chat_copy_state", Path(__file__).resolve().parents[1] / "copy_state.py"
)
copy_state_module = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(copy_state_module)

SNAPSHOT_TABLE = copy_state_module.SNAPSHOT_TABLE
copy_state = copy_state_module.copy_state
source_tables = copy_state_module.source_tables


def _schema(db: sqlite3.Connection) -> None:
    db.executescript(
        "CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL);"
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT);"
        "CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, content TEXT);"
    )


def _export(path: str) -> None:
    db = sqlite3.connect(path)
    _schema(db)
    db.execute("INSERT INTO users VALUES ('usr_1', 'a@example.com')")
    db.execute("INSERT INTO conversations VALUES ('chat_1', 'usr_1', 'hello')")
    db.execute("INSERT INTO messages VALUES ('msg_1', 'chat_1', '본문')")
    db.commit()
    db.close()


def _target(path: str) -> None:
    db = sqlite3.connect(path)
    _schema(db)
    db.execute("CREATE TABLE padiem_local_migration_ledger (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
    db.execute("INSERT INTO users VALUES ('usr_old', 'old@example.com')")
    db.commit()
    db.close()


def test_copy_replaces_each_table_and_records_the_snapshot(tmp_path):
    source, target = str(tmp_path / "export.sqlite3"), str(tmp_path / "chat.sqlite3")
    _export(source)
    _target(target)

    report = copy_state(source, target)

    assert set(report) == {"users", "conversations", "messages"}
    db = sqlite3.connect(target)
    try:
        assert db.execute("SELECT id FROM users").fetchall() == [("usr_1",)]
        assert db.execute("SELECT content FROM messages").fetchall() == [("본문",)]
        snapshots = db.execute(
            f"SELECT table_name, COUNT(*) FROM {SNAPSHOT_TABLE} GROUP BY table_name ORDER BY table_name"
        ).fetchall()
        assert snapshots == [("conversations", 1), ("messages", 1), ("users", 1)]
        # The local migration ledger is neither copied nor cleared.
        assert db.execute("SELECT COUNT(*) FROM padiem_local_migration_ledger").fetchone()[0] == 0
    finally:
        db.close()
    assert source_tables(sqlite3.connect(source)) == ["conversations", "messages", "users"]


def test_copy_refuses_a_missing_target_table_before_touching_anything(tmp_path):
    source, target = str(tmp_path / "export.sqlite3"), str(tmp_path / "chat.sqlite3")
    _export(source)
    db = sqlite3.connect(target)
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL)")
    db.execute("INSERT INTO users VALUES ('usr_keep', 'keep@example.com')")
    db.commit()
    db.close()

    with pytest.raises(SystemExit) as caught:
        copy_state(source, target)
    assert "target_table_missing" in str(caught.value)

    db = sqlite3.connect(target)
    try:
        assert db.execute("SELECT id FROM users").fetchall() == [("usr_keep",)]
    finally:
        db.close()


def test_copy_refuses_a_column_mismatch(tmp_path):
    source, target = str(tmp_path / "export.sqlite3"), str(tmp_path / "chat.sqlite3")
    _export(source)
    db = sqlite3.connect(target)
    db.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT NOT NULL, extra TEXT)")
    db.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT)")
    db.execute("CREATE TABLE messages (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, content TEXT)")
    db.commit()
    db.close()

    with pytest.raises(SystemExit) as caught:
        copy_state(source, target)
    assert "column_mismatch" in str(caught.value)
