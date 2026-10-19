from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "d1_restore_verify.py"

SCHEMA = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);
CREATE TABLE notes (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL
);
CREATE INDEX notes_user_idx ON notes(user_id);
CREATE TRIGGER users_touch AFTER UPDATE ON users
BEGIN
    UPDATE users SET name = NEW.name WHERE id = NEW.id;
END;
CREATE VIEW user_notes AS
    SELECT users.name, notes.body FROM users JOIN notes ON notes.user_id = users.id;
INSERT INTO users (id, name) VALUES (1, 'alpha'), (2, 'beta'), (3, 'gamma');
INSERT INTO notes (id, user_id, body) VALUES (1, 1, 'first'), (2, 2, 'second');
"""


def _load():
    spec = importlib.util.spec_from_file_location("d1_restore_verify_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


restore_ops = _load()


def _write_sql(path: Path, extra: str = "") -> None:
    path.write_text(SCHEMA + extra, encoding="utf-8")


def _build_reference(path: Path, extra: str = "") -> None:
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.executescript(SCHEMA + extra)
    finally:
        connection.close()


def _run(sql: Path, reference: Path, *extra: str) -> int:
    return restore_ops.main(
        ["--sql", str(sql), "--reference", str(reference), *extra]
    )


def test_restore_matches_reference(tmp_path, capsys):
    sql = tmp_path / "chat.sql"
    reference = tmp_path / "chat.sqlite3"
    report = tmp_path / "report.json"
    _write_sql(sql)
    _build_reference(reference)

    code = _run(sql, reference, "--json-out", str(report))

    assert code == 0
    output = capsys.readouterr().out
    assert "D1_RESTORE_OK" in output
    assert "tables=2" in output
    assert "rows=5" in output
    assert "schema=PARITY" in output
    assert "row_counts=PARITY" in output
    assert "integrity=ok" in output
    assert "readonly=PASS" in output

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["row_counts"] == {"notes": 2, "users": 3}
    assert payload["total_rows"] == 5
    assert payload["schema_changed"] == []
    assert payload["foreign_key_violations"] == 0
    assert payload["source_unchanged"] is True


def test_row_count_mismatch_is_reported(tmp_path, capsys):
    sql = tmp_path / "chat.sql"
    reference = tmp_path / "chat.sqlite3"
    report = tmp_path / "report.json"
    _write_sql(sql)
    _build_reference(reference, "INSERT INTO users (id, name) VALUES (4, 'delta');\n")

    code = _run(sql, reference, "--json-out", str(report))

    assert code == 1
    assert "D1_RESTORE_MISMATCH" in capsys.readouterr().out
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["ok"] is False
    assert payload["schema_parity"] is True
    assert payload["row_count_parity"] is False
    assert payload["row_count_mismatches"] == [
        {"table": "users", "reference": 4, "restored": 3}
    ]


def test_schema_mismatch_is_reported(tmp_path, capsys):
    sql = tmp_path / "chat.sql"
    reference = tmp_path / "chat.sqlite3"
    report = tmp_path / "report.json"
    _write_sql(sql)
    _build_reference(reference, "CREATE INDEX notes_body_idx ON notes(body);\n")

    code = _run(sql, reference, "--json-out", str(report))

    assert code == 1
    assert "schema=MISMATCH" in capsys.readouterr().out
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema_parity"] is False
    assert payload["schema_extra_in_restore"] == []
    assert payload["schema_missing_in_restore"] == [["index", "notes_body_idx"]]
    assert payload["row_count_parity"] is True


def test_schema_sql_change_is_reported(tmp_path):
    sql = tmp_path / "chat.sql"
    reference = tmp_path / "chat.sqlite3"
    report = tmp_path / "report.json"
    _write_sql(sql)
    _build_reference(reference)
    connection = sqlite3.connect(reference)
    try:
        connection.execute("DROP VIEW user_notes")
        connection.execute(
            "CREATE VIEW user_notes AS SELECT users.name, notes.body "
            "FROM users JOIN notes ON notes.user_id = users.id WHERE notes.id > 0"
        )
        connection.commit()
    finally:
        connection.close()

    code = _run(sql, reference, "--json-out", str(report))

    assert code == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["schema_changed"] == [["view", "user_notes"]]


def test_missing_sql_file_exits_two(tmp_path, capsys):
    reference = tmp_path / "chat.sqlite3"
    _build_reference(reference)

    code = _run(tmp_path / "missing.sql", reference)

    assert code == 2
    assert "D1_RESTORE_FAILED reason=sql_file_missing" in capsys.readouterr().err


def test_unreadable_reference_exits_two(tmp_path, capsys):
    sql = tmp_path / "chat.sql"
    reference = tmp_path / "chat.sqlite3"
    _write_sql(sql)
    reference.write_text("not a sqlite database", encoding="utf-8")

    code = _run(sql, reference)

    assert code == 2
    assert "D1_RESTORE_FAILED" in capsys.readouterr().err


def test_sources_are_not_modified(tmp_path):
    sql = tmp_path / "chat.sql"
    reference = tmp_path / "chat.sqlite3"
    _write_sql(sql)
    _build_reference(reference)
    before = {
        "sql": hashlib.sha256(sql.read_bytes()).hexdigest(),
        "reference": hashlib.sha256(reference.read_bytes()).hexdigest(),
    }

    assert _run(sql, reference) == 0

    after = {
        "sql": hashlib.sha256(sql.read_bytes()).hexdigest(),
        "reference": hashlib.sha256(reference.read_bytes()).hexdigest(),
    }
    assert before == after


def test_keep_retains_restored_database(tmp_path, capsys):
    sql = tmp_path / "chat.sql"
    reference = tmp_path / "chat.sqlite3"
    work = tmp_path / "work"
    _write_sql(sql)
    _build_reference(reference)

    code = _run(sql, reference, "--work-dir", str(work), "--keep")

    assert code == 0
    restored = list(work.glob("d1-restore-verify-*/restored.sqlite3"))
    assert len(restored) == 1
    connection = sqlite3.connect(restored[0])
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 3
    finally:
        connection.close()
