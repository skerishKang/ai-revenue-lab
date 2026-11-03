"""The retention purge (stage 2): boundaries, kept tables, bounds, exit status.

These tests run the module against a temporary SQLite database wrapped in the
same ``SqliteD1`` facade the COM2 host uses. The point of each case is the
decision boundary: a row one day inside the period survives, a row one day past
it is shed, and a row whose age cannot be read is never shed.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.retention_purge as retention_purge

from app.d1_sqlite import SqliteD1, connect
from app.claw_task_alert_store import D1ClawTaskAlertStore
from app.retention_purge import (
    DEFAULT_BATCH,
    RETENTION_TARGETS,
    STATUS_PREFIX,
    main,
    purge_expired_by_retention,
    run_once,
)

NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
# 2026-11-03 minus 365 days = 2025-11-03; minus 90 days = 2026-08-05.
WITHIN_WITHDRAWAL_YEAR = "2025-11-04T00:00:00Z"
PAST_WITHDRAWAL_YEAR = "2025-11-02T00:00:00Z"
WITHIN_AUDIT_WINDOW = "2026-08-06T00:00:00Z"
PAST_AUDIT_WINDOW = "2026-08-04T00:00:00Z"
UNREADABLE = "not-a-timestamp"

SCHEMA = """
CREATE TABLE account_deletion_audit (
    id TEXT PRIMARY KEY, user_id_hash TEXT NOT NULL, deleted_at TEXT NOT NULL);
CREATE TABLE padiem_mcp_audit (
    id TEXT PRIMARY KEY, tool_name TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE claw_task_alert (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, kind TEXT NOT NULL,
    status TEXT NOT NULL, title TEXT NOT NULL, created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, member_id TEXT NOT NULL DEFAULT '', due_date TEXT,
    source_id TEXT, linked_ref TEXT, severity TEXT, kind_value TEXT,
    visible_to_all INTEGER NOT NULL DEFAULT 1);
CREATE TABLE claw_runs (
    run_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, rule_id TEXT NOT NULL,
    status TEXT NOT NULL, scheduled_time TEXT NOT NULL, started_at TEXT NOT NULL,
    completed_at TEXT, output TEXT, error_message TEXT);
CREATE TABLE claw_run_history (
    id TEXT PRIMARY KEY, run_id TEXT NOT NULL UNIQUE, result_summary TEXT);
CREATE TABLE claw_conversation_artifact_index (
    artifact_id TEXT PRIMARY KEY, source_run_ref TEXT NOT NULL
        REFERENCES claw_run_history(run_id) ON DELETE CASCADE);
-- Tables this module must never touch, whatever their age.
CREATE TABLE users (id TEXT PRIMARY KEY, created_at TEXT);
CREATE TABLE messages (id TEXT PRIMARY KEY, created_at TEXT);
CREATE TABLE bookai_records (id TEXT PRIMARY KEY, created_at TEXT);
CREATE TABLE password_reset_audit (id TEXT PRIMARY KEY, created_at TEXT);
"""


@pytest.fixture()
def binding(tmp_path):
    connection = connect(str(tmp_path / "chat.sqlite3"))
    connection.executescript(SCHEMA)
    yield SqliteD1(connection)
    connection.close()


async def _count(binding, table: str) -> int:
    row = await binding.prepare(f"SELECT COUNT(*) AS n FROM {table}").first()
    return int(row["n"])


async def _insert_deletion(binding, row_id: str, deleted_at: str) -> None:
    await binding.prepare(
        "INSERT INTO account_deletion_audit (id, user_id_hash, deleted_at) VALUES (?, ?, ?)"
    ).bind(row_id, f"hash-{row_id}", deleted_at).run()


async def _insert_audit(binding, row_id: str, created_at: str) -> None:
    await binding.prepare(
        "INSERT INTO padiem_mcp_audit (id, tool_name, created_at) VALUES (?, ?, ?)"
    ).bind(row_id, "pc_read", created_at).run()


async def _insert_claw_alert(
    binding, row_id: str, *, kind: str, status: str, created_at: str
) -> None:
    await binding.prepare(
        "INSERT INTO claw_task_alert "
        "(id, workspace_id, kind, status, title, created_at, updated_at, member_id, "
        "visible_to_all, severity, kind_value) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    ).bind(
        row_id, "ws-1", kind, status, "Synthetic Claw record", created_at,
        created_at, "member-1", 1, "info" if kind == "alert" else None,
        "automation" if kind == "alert" else None,
    ).run()


# ---------------------------------------------------------------------------
# (a) The period decides, not the calendar year: one day either side.
# ---------------------------------------------------------------------------


async def test_a_withdrawal_record_inside_the_year_survives(binding):
    await _insert_deletion(binding, "inside", WITHIN_WITHDRAWAL_YEAR)
    await _insert_deletion(binding, "past", PAST_WITHDRAWAL_YEAR)

    counts = await purge_expired_by_retention(binding, now=NOW)

    assert counts["account_deletion_audit"] == 1
    assert await _count(binding, "account_deletion_audit") == 1
    row = await binding.prepare(
        "SELECT id FROM account_deletion_audit"
    ).first()
    # The survivor is the younger row: the old session still needs its refusal
    # evidence for the full decided year.
    assert row["id"] == "inside"


async def test_an_audit_row_inside_the_90_days_survives(binding):
    await _insert_audit(binding, "inside", WITHIN_AUDIT_WINDOW)
    await _insert_audit(binding, "past", PAST_AUDIT_WINDOW)

    counts = await purge_expired_by_retention(binding, now=NOW)

    assert counts["padiem_mcp_audit"] == 1
    row = await binding.prepare("SELECT id FROM padiem_mcp_audit").first()
    assert row["id"] == "inside"


async def test_claw_alert_retention_uses_strict_90_day_boundary_and_keeps_live_content(binding):
    await _insert_claw_alert(
        binding, "dismissed-before", kind="alert", status="dismissed",
        created_at="2026-08-05T11:59:59Z",
    )
    await _insert_claw_alert(
        binding, "dismissed-at-cutoff", kind="alert", status="dismissed",
        created_at="2026-08-05T12:00:00Z",
    )
    await _insert_claw_alert(
        binding, "dismissed-after", kind="alert", status="dismissed",
        created_at="2026-08-05T12:00:01Z",
    )
    await _insert_claw_alert(
        binding, "active-old", kind="alert", status="active",
        created_at="2026-01-01T00:00:00Z",
    )
    await _insert_claw_alert(
        binding, "task-old", kind="task", status="open",
        created_at="2026-01-01T00:00:00Z",
    )
    for run_id, status in (
        ("queued-run", "pending"),
        ("running-run", "running"),
        ("result-run", "completed"),
    ):
        await binding.prepare(
            "INSERT INTO claw_runs "
            "(run_id, workspace_id, rule_id, status, scheduled_time, started_at, output) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)"
        ).bind(
            run_id, "ws-1", "rule-1", status,
            "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
            "Synthetic user result" if run_id == "result-run" else None,
        ).run()
    await binding.prepare(
        "INSERT INTO claw_run_history (id, run_id, result_summary) VALUES (?, ?, ?)"
    ).bind("history-1", "result-run", "Synthetic user result").run()
    await binding.prepare(
        "INSERT INTO claw_conversation_artifact_index (artifact_id, source_run_ref) "
        "VALUES (?, ?)"
    ).bind("artifact-1", "result-run").run()

    counts = await purge_expired_by_retention(binding, now=NOW)

    assert counts["claw_task_alert"] == 1
    rows = await binding.prepare("SELECT id FROM claw_task_alert ORDER BY id").all()
    assert {row["id"] for row in rows} == {
        "active-old", "dismissed-after", "dismissed-at-cutoff", "task-old"
    }
    # The existing inbox projection still reads surviving task and active-alert
    # records through the production adapter's actual list queries.
    store = D1ClawTaskAlertStore(binding)
    tasks = await store.list_tasks("ws-1", member_id="member-1")
    alerts = await store.list_alerts("ws-1", member_id="member-1")
    assert [item.task_id for item in tasks] == ["task-old"]
    assert {item.alert_id for item in alerts} == {
        "active-old", "dismissed-after", "dismissed-at-cutoff"
    }
    runs = await binding.prepare(
        "SELECT status FROM claw_runs ORDER BY run_id"
    ).all()
    assert {row["status"] for row in runs} == {
        "pending", "running", "completed"
    }
    result = await binding.prepare(
        "SELECT output FROM claw_runs WHERE run_id=?"
    ).bind("result-run").first()
    assert result["output"] == "Synthetic user result"
    assert await _count(binding, "claw_runs") == 3
    assert await _count(binding, "claw_run_history") == 1
    assert await _count(binding, "claw_conversation_artifact_index") == 1
    # This mixed target has no FK of its own; result history's existing FK child
    # remains queryable because neither result table is a purge target.
    foreign_keys = await binding.prepare(
        "PRAGMA foreign_key_list(claw_task_alert)"
    ).all()
    assert foreign_keys == []


def test_098_migration_installs_the_global_retention_index(binding):
    migration = (
        Path(__file__).parents[1]
        / "migrations"
        / "098_claw_task_alert_retention_index.sql"
    )
    binding.connection.executescript(migration.read_text(encoding="utf-8"))
    columns = binding.connection.execute(
        "PRAGMA index_info(idx_claw_task_alert_retention)"
    ).fetchall()
    assert [row[2] for row in columns] == ["kind", "status", "created_at"]


async def test_claw_alert_backlog_is_limited_to_one_batch_per_pass(binding):
    for index in range(5):
        await _insert_claw_alert(
            binding, f"old-dismissed-{index}", kind="alert", status="dismissed",
            created_at="2026-01-01T00:00:00Z",
        )

    counts = await purge_expired_by_retention(binding, batch_size=2, now=NOW)
    assert counts["claw_task_alert"] == 2
    assert await _count(binding, "claw_task_alert") == 3

    counts = await purge_expired_by_retention(binding, batch_size=2, now=NOW)
    assert counts["claw_task_alert"] == 2
    assert await _count(binding, "claw_task_alert") == 1


async def test_an_unreadable_timestamp_is_kept(binding):
    await _insert_audit(binding, "unknown", UNREADABLE)
    await _insert_deletion(binding, "unknown", UNREADABLE)

    counts = await purge_expired_by_retention(binding, now=NOW)

    assert counts["padiem_mcp_audit"] == 0
    assert counts["account_deletion_audit"] == 0
    assert await _count(binding, "padiem_mcp_audit") == 1
    assert await _count(binding, "account_deletion_audit") == 1


# ---------------------------------------------------------------------------
# (b) User content and identity tables are outside this module's authority.
# ---------------------------------------------------------------------------


async def test_user_content_and_identity_tables_keep_every_row(binding):
    for table in ("users", "messages", "bookai_records", "password_reset_audit"):
        for index in range(2):
            await binding.prepare(
                f"INSERT INTO {table} (id, created_at) VALUES (?, ?)"
            ).bind(f"{table}-{index}", PAST_WITHDRAWAL_YEAR).run()

    await purge_expired_by_retention(binding, now=NOW)

    for table in ("users", "messages", "bookai_records", "password_reset_audit"):
        assert await _count(binding, table) == 2, table


# ---------------------------------------------------------------------------
# (c) One batch per table per run; a dry run counts and deletes nothing.
# ---------------------------------------------------------------------------


async def test_a_backlog_decays_one_batch_per_run(binding):
    for index in range(5):
        await _insert_audit(binding, f"old-{index}", PAST_AUDIT_WINDOW)

    counts = await purge_expired_by_retention(binding, batch_size=2, now=NOW)
    assert counts["padiem_mcp_audit"] == 2
    assert await _count(binding, "padiem_mcp_audit") == 3

    counts = await purge_expired_by_retention(binding, batch_size=2, now=NOW)
    assert counts["padiem_mcp_audit"] == 2
    assert await _count(binding, "padiem_mcp_audit") == 1

    counts = await purge_expired_by_retention(binding, now=NOW)
    assert counts["padiem_mcp_audit"] == 1
    assert await _count(binding, "padiem_mcp_audit") == 0


async def test_a_dry_run_counts_without_deleting(binding):
    await _insert_audit(binding, "old", PAST_AUDIT_WINDOW)
    await _insert_audit(binding, "young", WITHIN_AUDIT_WINDOW)

    counts = await purge_expired_by_retention(binding, dry_run=True, now=NOW)

    assert counts["padiem_mcp_audit"] == 1
    assert await _count(binding, "padiem_mcp_audit") == 2


async def test_invalid_batch_is_refused(binding):
    with pytest.raises(ValueError):
        await purge_expired_by_retention(binding, batch_size=0, now=NOW)


async def test_a_table_behind_on_migrations_is_skipped_as_zero(binding):
    binding.connection.execute("DROP TABLE account_deletion_audit")
    binding.connection.execute("DROP TABLE claw_task_alert")

    counts = await purge_expired_by_retention(binding, now=NOW)

    assert counts["account_deletion_audit"] == 0
    assert counts["claw_task_alert"] == 0
    assert "padiem_mcp_audit" in counts


# ---------------------------------------------------------------------------
# (d) The decided periods are the code's periods, not a caller's argument.
# ---------------------------------------------------------------------------


def test_the_decided_periods_are_declared_once():
    periods = {target.table: target.retention_days for target in RETENTION_TARGETS}
    assert periods == {
        "account_deletion_audit": 365,
        "padiem_mcp_audit": 90,
        "claw_task_alert": 90,
    }
    claw_target = next(target for target in RETENTION_TARGETS if target.table == "claw_task_alert")
    assert claw_target.predicate == "kind = 'alert' AND status = 'dismissed'"
    assert DEFAULT_BATCH == 1000


# ---------------------------------------------------------------------------
# (e) Host entry gate, output shape and exit status.
# ---------------------------------------------------------------------------


def test_without_the_host_flag_no_run_is_claimed():
    status = run_once(environ={})
    assert status == STATUS_PREFIX + "SKIPPED reason=cpython_host_entry_required"
    assert "detail" not in status


def test_an_operator_can_stop_the_pass_without_uninstalling_the_timer():
    status = run_once(environ={"PADIEM_CHAT_CPYTHON_HOST": "1",
                               "PADIEM_CHAT_RETENTION_PURGE_DISABLED": "1"})
    assert status == STATUS_PREFIX + "SKIPPED reason=disabled_by_env"


def test_the_status_line_names_tables_and_counts_only(tmp_path):
    padiem = tmp_path / "data"
    padiem.mkdir()
    status = run_once(
        environ={"PADIEM_CHAT_CPYTHON_HOST": "1",
                 "PADIEM_CHAT_LOCAL_DATA_DIR": str(padiem)}
    )
    assert status.startswith(STATUS_PREFIX + "ok ")
    detail = json.loads(status.split("detail=", 1)[1])
    assert set(detail) == {
        "account_deletion_audit", "padiem_mcp_audit", "claw_task_alert"
    }
    assert all(value == 0 for value in detail.values())
    assert "hash-" not in status


def test_the_exit_status_matches_the_reported_state(monkeypatch):
    for status_line, expected in (
        (STATUS_PREFIX + "ok detail={}", 0),
        (STATUS_PREFIX + "dry_run detail={}", 0),
        (STATUS_PREFIX + "ERROR reason=retention_purge_failed", 1),
        (STATUS_PREFIX + "STORAGE_ERROR reason=database_unavailable", 1),
        (STATUS_PREFIX + "SKIPPED reason=cpython_host_entry_required", 2),
    ):
        monkeypatch.setattr(retention_purge, "run_once", lambda **_kw: status_line)
        assert main(["--once"]) == expected, status_line


def test_a_refused_pass_exits_non_zero(monkeypatch):
    monkeypatch.delenv("PADIEM_CHAT_CPYTHON_HOST", raising=False)
    monkeypatch.delenv("PADIEM_LOCAL_DEV", raising=False)
    assert main(["--once"]) == 2


def test_an_unknown_argument_is_refused():
    assert main(["--everything"]) == 2
