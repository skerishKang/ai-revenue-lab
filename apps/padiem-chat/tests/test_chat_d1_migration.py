"""Stage 3 rehearsal: export → load → ledger → drift refusal, all local (#5573).

The source is a local D1 DOUBLE built from the real migrations (001–077) with a
`d1_migrations` ledger and synthetic rows — Production D1 is never touched. The
target is built from the same migrations, standing in for the COM2 database.
"""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
TOOL_PATH = Path(__file__).resolve().parents[3] / "tools" / "chat_d1_migration.py"

_SPEC = importlib.util.spec_from_file_location("chat_d1_migration", TOOL_PATH)
tool = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(tool)

NOW = "2026-10-29T00:00:00Z"


def _apply_schema(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, isolation_level=None)
    # Rehearsal-only speed: durability is irrelevant for a throwaway double.
    connection.execute("PRAGMA journal_mode = MEMORY")
    connection.execute("PRAGMA synchronous = OFF")
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        connection.executescript(migration.read_text(encoding="utf-8"))
    return connection


def _seed_chat_rows(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO users (id, auth_provider, provider_subject, email, display_name,"
        " picture_url, created_at, updated_at) VALUES (?, 'google', ?, ?, ?, '', ?, ?)",
        ("usr_" + "a" * 32, "subject-a", "a@example.com", "A", NOW, NOW),
    )
    connection.execute(
        "INSERT INTO projects (id, user_id, name, instructions, created_at, updated_at)"
        " VALUES (?, ?, 'project', '', ?, ?)",
        ("prj_" + "b" * 32, "usr_" + "a" * 32, NOW, NOW),
    )
    connection.execute(
        "INSERT INTO conversations (id, user_id, project_id, title, product_scope,"
        " created_at, updated_at) VALUES (?, ?, ?, 'hello', 'b62-chat', ?, ?)",
        ("chat_" + "c" * 32, "usr_" + "a" * 32, "prj_" + "b" * 32, NOW, NOW),
    )
    connection.executemany(
        "INSERT INTO messages (id, conversation_id, sequence_number, role, content, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            (f"msg_{index:032x}", "chat_" + "c" * 32, index,
             "user" if index % 2 == 0 else "assistant", f"본문 {index}", NOW)
            for index in range(300)
        ],
    )


def _seed_ledger(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS d1_migrations (id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " name TEXT UNIQUE, applied_at TEXT)"
    )
    connection.executemany(
        "INSERT OR IGNORE INTO d1_migrations (name, applied_at) VALUES (?, ?)",
        [(path.name, NOW) for path in sorted(MIGRATIONS_DIR.glob("*.sql"))],
    )


def _seed_owned(connection: sqlite3.Connection, *, device: str, generation: int) -> None:
    connection.execute(
        "INSERT INTO mesh_device_presence (device_id, connected, received_at, credential_generation)"
        " VALUES (?, 1, ?, ?)",
        (device, NOW, generation),
    )


@pytest.fixture(scope="module")
def d1_double(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("d1") / "d1-export.sqlite3"
    connection = _apply_schema(path)
    try:
        _seed_chat_rows(connection)
        _seed_ledger(connection)
        _seed_owned(connection, device="device.from.d1", generation=1)
    finally:
        connection.close()
    return path


@pytest.fixture(scope="module")
def target_template(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("target") / "target-template.sqlite3"
    connection = _apply_schema(path)
    try:
        # The COM2 queue is already authoritative here: its row must survive.
        _seed_owned(connection, device="device.com2.queue", generation=2)
    finally:
        connection.close()
    return path


@pytest.fixture()
def target_db(tmp_path, target_template) -> Path:
    path = tmp_path / "chat.sqlite3"
    shutil.copyfile(target_template, path)
    return path


def _copy(path: Path, tmp_path: Path, name: str) -> Path:
    copy = tmp_path / name
    shutil.copyfile(path, copy)
    return copy


def test_plan_marks_owned_tables_and_counts_rows(d1_double, target_db):
    report = tool.plan_state(str(d1_double), str(target_db))
    assert report["tables"]["mesh_device_presence"]["status"] == "EXCLUDED_OWNED"
    assert report["tables"]["messages"]["status"] == "OK"
    assert report["tables"]["messages"]["rows"] == 300
    assert "d1_migrations" not in report["tables"]  # ledger, never data
    assert report["ledger"][-1] == sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))[-1]


def test_load_is_atomic_keeps_queue_rows_and_verifies(d1_double, target_db):
    result = tool.load_state(str(d1_double), str(target_db))
    assert result["tables"] > 0 and result["rows"] >= 300

    connection = sqlite3.connect(target_db)
    try:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 300
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
        # The queue-owned table kept the COM2 row and did not take the D1 row.
        rows = connection.execute("SELECT device_id FROM mesh_device_presence").fetchall()
        assert rows == [("device.com2.queue",)]
        summary = connection.execute(
            "SELECT COUNT(*) FROM chat_migration_summary WHERE run_id = ?", (result["run_id"],)
        ).fetchone()[0]
        assert summary > 0
        snapshot = connection.execute(
            "SELECT COUNT(*) FROM chat_migration_snapshot WHERE run_id = ?", (result["run_id"],)
        ).fetchone()[0]
        assert snapshot >= 300
    finally:
        connection.close()

    assert tool.verify_state(str(target_db))["tables"]["messages"] == "OK"
    assert tool.verify_state(str(target_db), source_path=str(d1_double))["tables"]["messages"] == "OK"


def test_a_row_edited_after_the_load_is_refused(d1_double, target_db, tmp_path):
    tool.load_state(str(d1_double), str(target_db))
    tampered = _copy(d1_double, tmp_path, "tampered-export.sqlite3")
    connection = sqlite3.connect(tampered)
    try:
        connection.execute(
            "UPDATE messages SET content = '바뀐 본문' WHERE sequence_number = 7"
        )
        connection.commit()
    finally:
        connection.close()

    result = tool.verify_state(str(target_db), source_path=str(tampered))
    assert result["tables"]["messages"] == "SOURCE_DRIFT"
    assert tool.main(["verify", "--target", str(target_db), "--source", str(tampered)]) == 3


def test_schema_mismatch_or_missing_pk_refuses_the_whole_load(d1_double, target_db, tmp_path):
    broken_target = _copy(target_db, tmp_path, "broken-target.sqlite3")
    connection = sqlite3.connect(broken_target)
    try:
        connection.execute("ALTER TABLE users ADD COLUMN extra_column TEXT")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(tool.MigrationRefused):
        tool.load_state(str(d1_double), str(broken_target))
    connection = sqlite3.connect(broken_target)
    try:
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
        # A refused load writes nothing at all — not even bookkeeping tables.
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'chat_migration_summary'"
        ).fetchone()[0] == 0
    finally:
        connection.close()

    source_no_pk = _copy(d1_double, tmp_path, "no-pk-export.sqlite3")
    target_no_pk = _copy(target_db, tmp_path, "no-pk-target.sqlite3")
    for path in (source_no_pk, target_no_pk):
        connection = sqlite3.connect(path)
        try:
            connection.execute("CREATE TABLE IF NOT EXISTS no_primary_key (value TEXT)")
            connection.execute("INSERT INTO no_primary_key (value) VALUES ('row')")
            connection.commit()
        finally:
            connection.close()
    with pytest.raises(tool.MigrationRefused):
        tool.load_state(str(source_no_pk), str(target_no_pk))


def test_reverse_export_is_a_read_only_copy_for_hand_back(d1_double, target_db, tmp_path):
    tool.load_state(str(d1_double), str(target_db))
    out = tmp_path / "reverse-export.sqlite3"
    result = tool.export_readonly_copy(str(target_db), str(out))
    assert result["tables"] > 0
    connection = sqlite3.connect(out)
    try:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 300
        # Owned tables are not part of the hand-back set.
        owned = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'mesh_device_presence'"
        ).fetchone()[0]
        assert owned == 0
        summary = dict(connection.execute(
            "SELECT table_name, row_count FROM chat_export_summary"
        ).fetchall())
        assert summary["messages"] == 300
    finally:
        connection.close()


def test_cli_reports_counts_and_never_row_content(d1_double, target_db, capsys):
    assert tool.main(["plan", "--source", str(d1_double), "--target", str(target_db)]) == 0
    assert tool.main(["load", "--source", str(d1_double), "--target", str(target_db)]) == 0
    captured = capsys.readouterr().out
    assert "CHAT_MIGRATION_LOAD=PASS" in captured
    assert "CHAT_MIGRATION_TABLE=messages OK ROWS=300" in captured
    assert "본문 7" not in captured
