"""The B14 ledger retention purge: the 90-day boundary and what must survive.

Each case builds a throwaway SQLite file with the ledger's two tables, so the
module's plain-``sqlite3`` path is exercised without a D1 binding or a host.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from app.pilot.call_ledger_retention import (
    ATTEMPT_TABLE,
    CALL_TABLE,
    STATUS_PREFIX,
    main,
    purge,
)

NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
#: A synthetic identity: the status line must name tables and counts only.
RETENTION_MODEL = "fixture/retention-model"
# 90 days before NOW is 2026-08-05T12:00:00Z.
INSIDE = "2026-08-06T00:00:00Z"
PAST = "2026-08-04T00:00:00Z"
UNREADABLE = "2026-13-99T99:99:99Z"

SCHEMA = f"""
CREATE TABLE {CALL_TABLE} (
    log_id TEXT PRIMARY KEY,
    started_at TEXT,
    selected_model_id TEXT NOT NULL,
    subject_ref TEXT);
CREATE TABLE {ATTEMPT_TABLE} (
    log_id TEXT NOT NULL,
    attempt_index INTEGER NOT NULL,
    started_at TEXT,
    PRIMARY KEY (log_id, attempt_index));
"""


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "b14-call-ledger.db"
    connection = sqlite3.connect(str(path))
    connection.executescript(SCHEMA)
    connection.commit()
    connection.close()
    return path


def _add(db, log_id: str, started_at, attempts: int = 1) -> None:
    connection = sqlite3.connect(str(db))
    connection.execute(
        f"INSERT INTO {CALL_TABLE} (log_id, started_at, selected_model_id, subject_ref)"
        " VALUES (?, ?, ?, ?)",
        (log_id, started_at, RETENTION_MODEL, f"subject-{log_id}"),
    )
    for index in range(attempts):
        connection.execute(
            f"INSERT INTO {ATTEMPT_TABLE} (log_id, attempt_index, started_at) VALUES (?, ?, ?)",
            (log_id, index, None),
        )
    connection.commit()
    connection.close()


def _count(db, table: str) -> int:
    connection = sqlite3.connect(str(db))
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


def test_a_call_inside_the_period_survives(db):
    _add(db, "inside", INSIDE)
    _add(db, "past", PAST)

    counts = purge(db, now=NOW)

    assert counts == {CALL_TABLE: 1, ATTEMPT_TABLE: 1}
    assert _count(db, CALL_TABLE) == 1
    connection = sqlite3.connect(str(db))
    try:
        assert connection.execute(f"SELECT log_id FROM {CALL_TABLE}").fetchone()[0] == "inside"
    finally:
        connection.close()


def test_an_attempt_goes_with_its_call_and_only_with_it(db):
    _add(db, "past", PAST, attempts=2)
    _add(db, "inside", INSIDE, attempts=2)

    counts = purge(db, now=NOW)

    assert counts == {CALL_TABLE: 1, ATTEMPT_TABLE: 2}
    assert _count(db, ATTEMPT_TABLE) == 2


def test_a_call_without_a_timestamp_is_kept(db):
    _add(db, "unknown", None)
    _add(db, "garbled", UNREADABLE)

    counts = purge(db, now=NOW)

    assert counts == {CALL_TABLE: 0, ATTEMPT_TABLE: 0}
    assert _count(db, CALL_TABLE) == 2


def test_a_dry_run_counts_and_deletes_nothing(db):
    _add(db, "past", PAST, attempts=2)

    counts = purge(db, now=NOW, dry_run=True)

    assert counts == {CALL_TABLE: 1, ATTEMPT_TABLE: 2}
    assert _count(db, CALL_TABLE) == 1
    assert _count(db, ATTEMPT_TABLE) == 2


def test_a_backlog_decays_one_batch_per_run_and_the_second_run_is_zero(db):
    for index in range(5):
        _add(db, f"past-{index}", PAST, attempts=1)

    first = purge(db, now=NOW, batch_size=2)
    assert first == {CALL_TABLE: 2, ATTEMPT_TABLE: 2}
    assert _count(db, CALL_TABLE) == 3

    purge(db, now=NOW, batch_size=2)
    final = purge(db, now=NOW, batch_size=2)
    assert final[CALL_TABLE] == 1
    assert purge(db, now=NOW) == {CALL_TABLE: 0, ATTEMPT_TABLE: 0}
    assert _count(db, CALL_TABLE) == 0
    assert _count(db, ATTEMPT_TABLE) == 0


def test_bounds_are_refused(db):
    with pytest.raises(ValueError):
        purge(db, retention_days=0, now=NOW)
    with pytest.raises(ValueError):
        purge(db, batch_size=0, now=NOW)


def test_a_missing_database_is_a_skipped_run(tmp_path, capsys):
    assert main(["--db", str(tmp_path / "absent.db"), "--once"]) == 2
    assert capsys.readouterr().out.strip() == STATUS_PREFIX + "SKIPPED reason=database_missing"


def test_a_schema_without_the_ledger_reports_zero(db, capsys):
    connection = sqlite3.connect(str(db))
    connection.execute(f"DROP TABLE {CALL_TABLE}")
    connection.commit()
    connection.close()

    assert main(["--db", str(db), "--once"]) == 0
    assert f"{CALL_TABLE}=0" in capsys.readouterr().out


def test_the_status_line_names_tables_and_counts_only(db, capsys):
    _add(db, "past", PAST, attempts=1)

    assert main(["--db", str(db), "--once"]) == 0

    out = capsys.readouterr().out.strip()
    # Sorted table names: b14_model_call sorts before b14_model_call_attempt,
    # because the shorter name is a prefix of the longer one.
    assert out == f"{STATUS_PREFIX}ok {CALL_TABLE}=1 {ATTEMPT_TABLE}=1"
    assert "subject-past" not in out
    assert RETENTION_MODEL not in out
