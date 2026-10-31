"""Synthetic tests for the D1 <-> COM2 parity check (reuses chat_d1_digest).

No Production D1 and no COM2 host is touched: every case builds small SQLite
files in a temp directory.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

parity = importlib.import_module("chat_copy_parity")
gate = importlib.import_module("chat_d1_handback_gate")


def _db(path: Path, tables: dict[str, list[tuple]], extra_ddl: str = "") -> Path:
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE users (id TEXT PRIMARY KEY, name TEXT, note TEXT)")
    connection.execute(
        "CREATE TABLE conversations (id TEXT PRIMARY KEY, user_id TEXT, title TEXT)"
    )
    connection.execute("CREATE TABLE oracle_mesh_dispatch (id TEXT PRIMARY KEY, state TEXT)")
    connection.execute("CREATE TABLE d1_migrations (id INTEGER PRIMARY KEY, name TEXT)")
    if extra_ddl:
        connection.execute(extra_ddl)
    for table, values in tables.items():
        for value in values:
            placeholders = ", ".join("?" for _ in value)
            connection.execute(f'INSERT INTO "{table}" VALUES ({placeholders})', value)
    connection.commit()
    connection.close()
    return path


BASE_TABLES = {
    "users": [("u1", "owner", None), ("u2", "guest", None)],
    "conversations": [("c1", "u1", "first")],
    "oracle_mesh_dispatch": [("d1", "queued")],
    "d1_migrations": [(1, "001")],
}


@pytest.fixture()
def twin(tmp_path: Path):
    d1 = _db(tmp_path / "d1.sqlite3", BASE_TABLES)
    com2 = _db(tmp_path / "com2-copy.sqlite3", BASE_TABLES)
    return d1, com2


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_identical_sides_match(twin, capsys):
    d1, com2 = twin
    report = parity.compare(d1, com2)

    assert report.matches
    assert report.rows == 3
    assert report.mismatch_rows == 0
    assert parity.main(["--d1", str(d1), "--com2", str(com2)]) == parity.EXIT_MATCH

    out = capsys.readouterr().out
    assert "CHAT_COPY_PARITY=MATCH" in out
    assert "CHAT_COPY_PARITY_SUMMARY=2표 3행 불일치 0" in out


def test_a_row_missing_on_com2_fails(tmp_path, capsys):
    d1 = _db(tmp_path / "d1.sqlite3", BASE_TABLES)
    com2 = _db(
        tmp_path / "com2-copy.sqlite3",
        {**BASE_TABLES, "users": [("u1", "owner", None)]},
    )

    report = parity.compare(d1, com2)
    assert not report.matches
    assert report.mismatch_rows == 1
    users = next(table for table in report.tables if table.table == "users")
    assert (users.d1_rows, users.com2_rows, users.missing_on_com2) == (2, 1, 1)

    assert parity.main(["--d1", str(d1), "--com2", str(com2)]) == parity.EXIT_DRIFT
    out = capsys.readouterr().out
    assert "CHAT_COPY_PARITY=DRIFT" in out
    assert "CHAT_COPY_TABLE_DRIFT users" in out
    assert "missing_on_com2=1" in out


def test_a_diffed_value_fails(tmp_path):
    d1 = _db(tmp_path / "d1.sqlite3", BASE_TABLES)
    com2 = _db(
        tmp_path / "com2-copy.sqlite3",
        {
            **BASE_TABLES,
            "conversations": [("c1", "u1", "first (edited on com2)")],
        },
    )

    report = parity.compare(d1, com2)
    assert not report.matches
    assert report.mismatch_rows == 1
    conversations = next(t for t in report.tables if t.table == "conversations")
    assert (conversations.changed, conversations.missing_on_com2) == (1, 0)


def test_a_missing_table_fails(tmp_path, capsys):
    d1 = _db(tmp_path / "d1.sqlite3", BASE_TABLES)
    com2 = _db(
        tmp_path / "com2-copy.sqlite3",
        {**BASE_TABLES, "conversations": []},
    )
    # com2 has no conversations table at all.
    connection = sqlite3.connect(com2)
    connection.execute("DROP TABLE conversations")
    connection.commit()
    connection.close()

    report = parity.compare(d1, com2)
    assert report.d1_only_tables == ["conversations"]
    assert report.mismatch_table_count == 1
    assert parity.main(["--d1", str(d1), "--com2", str(com2)]) == parity.EXIT_DRIFT
    out = capsys.readouterr().out
    assert "only_on_d1" in out


def test_owned_tables_are_excluded_from_the_verdict(tmp_path):
    d1 = _db(tmp_path / "d1.sqlite3", BASE_TABLES)
    com2 = _db(
        tmp_path / "com2-copy.sqlite3",
        {**BASE_TABLES, "oracle_mesh_dispatch": [("d1", "queued"), ("d2", "drained")]},
    )

    report = parity.compare(d1, com2)
    assert report.matches, "queue-owned rows must not decide Chat parity"
    assert "oracle_mesh_dispatch" in report.excluded_tables
    assert "d1_migrations" in report.excluded_tables
    assert not any(table.table == "oracle_mesh_dispatch" for table in report.tables)


def test_a_table_without_a_primary_key_is_reported_not_fatal(tmp_path):
    extra = "CREATE TABLE loose (a TEXT, b TEXT)"
    d1 = _db(tmp_path / "d1.sqlite3", BASE_TABLES, extra_ddl=extra)
    com2 = _db(tmp_path / "com2-copy.sqlite3", BASE_TABLES, extra_ddl=extra)

    report = parity.compare(d1, com2)
    assert report.not_comparable_tables == ["loose"]
    assert report.matches


def test_both_inputs_stay_byte_identical(twin, tmp_path):
    d1, com2 = twin
    before = (_sha(d1), _sha(com2))
    out_json = tmp_path / "parity.json"

    assert parity.main([
        "--d1", str(d1), "--com2", str(com2), "--json", str(out_json),
    ]) == parity.EXIT_MATCH

    assert (_sha(d1), _sha(com2)) == before
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["d1_sha256"] == before[0]
    assert payload["com2_sha256"] == before[1]


def test_parity_and_handback_share_one_digest_implementation():
    """The rollback plan and the parity verdict must measure rows identically."""

    assert parity.digest is gate.digest
    assert parity.digest.row_digest is gate.digest.row_digest


def test_missing_input_file_is_a_usage_error(tmp_path):
    assert parity.main([
        "--d1", str(tmp_path / "absent.sqlite3"),
        "--com2", str(tmp_path / "absent.sqlite3"),
    ]) == parity.EXIT_USAGE
