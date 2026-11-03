"""The expired-row purge (stage 1): its explicit target list and its bounds.

These tests run the module against a temporary local SQLite database wrapped in
the same ``SqliteD1`` facade the COM2 host uses, so the D1 statement surface —
``prepare().bind().run()/first()`` — is exercised, not re-implemented. No host
is contacted, nothing is installed, and no real database is touched.

The deadline formats are deliberately mixed (``…Z`` and ``…+00:00`` ISO text,
plus one epoch-seconds column): every stored value is fixed-width UTC ISO, so
the lexicographic comparison the purge performs stays order-correct across the
formats the stores actually write.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import app.expired_purge as expired_purge

from app.d1_sqlite import SqliteD1, connect
from app.expired_purge import (
    DEFAULT_BATCH,
    DEFAULT_GRACE_DAYS,
    STATUS_PREFIX,
    main,
    purge_expired_rows,
    run_once,
)

NOW = datetime(2026, 11, 3, 12, 0, 0, tzinfo=timezone.utc)
#: 7-day grace: deadlines before 2026-10-27T12:00:00Z are shed.
EXPIRED_PAST_GRACE = "2026-10-26T00:00:00Z"
EXPIRED_PAST_GRACE_OFFSET = "2026-10-26T06:00:00+00:00"
EXPIRED_WITHIN_GRACE = "2026-10-31T00:00:00Z"
NOT_EXPIRED = "2026-12-01T00:00:00Z"

TEXT_TABLES = (
    "orchestration_continuations",
    "password_reset_tokens",
    "pc_pairing_codes",
)

# The minimal shape the purge reads: deadline column plus a rowid-bearing key.
SCHEMA = """
CREATE TABLE orchestration_continuations (
    continuation_ref TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
CREATE TABLE password_reset_tokens (
    token_id TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
CREATE TABLE pc_pairing_codes (
    code_id TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
CREATE TABLE claw_github_oauth_states (
    state_sha256 TEXT PRIMARY KEY, expires_at INTEGER NOT NULL);
CREATE TABLE padiem_mcp_approvals (
    id TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
CREATE TABLE claw_approval_handoff (
    id TEXT PRIMARY KEY, pause_expires_at TEXT NOT NULL);
CREATE TABLE claw_web_xlsx_selections (
    selection_ref TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
CREATE TABLE claw_web_xlsx_p01_requests (
    request_ref TEXT PRIMARY KEY, pause_expires_at TEXT);
-- Receipts cite their parent with NO ACTION: the purge must leave that pair.
CREATE TABLE claw_web_xlsx_p01_decision_receipts (
    request_ref TEXT PRIMARY KEY,
    FOREIGN KEY (request_ref) REFERENCES claw_web_xlsx_p01_requests(request_ref));
CREATE TABLE claw_web_xlsx_quote_edit_receipts (
    selection_ref TEXT PRIMARY KEY,
    FOREIGN KEY (selection_ref) REFERENCES claw_web_xlsx_selections(selection_ref));
CREATE TABLE claw_web_xlsx_quote_write_pauses (
    selection_ref TEXT PRIMARY KEY, pause_expires_at TEXT);
CREATE TABLE lovetree_login_handoffs (
    ticket_id TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
CREATE TABLE padiem_android_auth_handoffs (
    handoff_id TEXT PRIMARY KEY, expires_at TEXT NOT NULL);
-- Excluded tables: their row counts must never move.
CREATE TABLE password_reset_audit (id INTEGER PRIMARY KEY, event TEXT NOT NULL);
CREATE TABLE pc_device_links (link_id TEXT PRIMARY KEY);
"""


@pytest.fixture()
def binding(tmp_path):
    connection = connect(str(tmp_path / "chat.sqlite3"))
    connection.executescript(SCHEMA)
    yield SqliteD1(connection)
    connection.close()


async def _insert(binding, table: str, deadline: str | int, column: str = "expires_at") -> None:
    if table == "orchestration_continuations":
        key, key_column = deadline, "continuation_ref"
    elif table == "password_reset_tokens":
        key, key_column = deadline, "token_id"
    elif table == "pc_pairing_codes":
        key, key_column = deadline, "code_id"
    elif table == "claw_github_oauth_states":
        key, key_column = deadline, "state_sha256"
    elif table == "padiem_mcp_approvals":
        key, key_column = deadline, "id"
    elif table == "claw_approval_handoff":
        key, key_column = deadline, "id"
        column = "pause_expires_at"
    elif table == "claw_web_xlsx_selections":
        key, key_column = deadline, "selection_ref"
    elif table == "claw_web_xlsx_p01_requests":
        key, key_column = deadline, "request_ref"
        column = "pause_expires_at"
    elif table == "claw_web_xlsx_quote_write_pauses":
        key, key_column = deadline, "selection_ref"
        column = "pause_expires_at"
    elif table == "lovetree_login_handoffs":
        key, key_column = deadline, "ticket_id"
    elif table == "padiem_android_auth_handoffs":
        key, key_column = deadline, "handoff_id"
    elif table == "password_reset_audit":
        key, key_column = deadline, "event"
    elif table == "pc_device_links":
        key, key_column = deadline, "link_id"
    else:  # pragma: no cover - the seed helpers keep this table set closed
        raise AssertionError(f"unknown table {table}")
    if table in ("password_reset_audit", "pc_device_links"):
        await binding.prepare(
            f"INSERT INTO {table} ({key_column}) VALUES (?)"
        ).bind(f"event-{key}" if table == "password_reset_audit" else key).run()
        return
    await binding.prepare(
        f"INSERT INTO {table} ({key_column}, {column}) VALUES (?, ?)"
    ).bind(str(key), deadline).run()


async def _count(binding, table: str) -> int:
    row = await binding.prepare(f"SELECT COUNT(*) AS n FROM {table}").first()
    return int(row["n"])


# ---------------------------------------------------------------------------
# (a) The grace window decides: past it the row is shed, inside it it survives.
# ---------------------------------------------------------------------------


async def test_expired_past_grace_is_deleted_and_the_rest_survive(binding):
    for table in TEXT_TABLES:
        await _insert(binding, table, EXPIRED_PAST_GRACE)
        await _insert(binding, table, EXPIRED_WITHIN_GRACE)
        await _insert(binding, table, NOT_EXPIRED)
    # The same windows in the other stored format, and in the epoch column.
    await _insert(binding, "orchestration_continuations", EXPIRED_PAST_GRACE_OFFSET)
    await _insert(binding, "orchestration_continuations", NOT_EXPIRED.replace("Z", "+00:00"))
    import time as _time

    expired_epoch = int(_time.mktime((2026, 10, 20, 0, 0, 0, 0, 0, 0)))
    live_epoch = int(_time.mktime((2026, 12, 20, 0, 0, 0, 0, 0, 0)))
    await _insert(binding, "claw_github_oauth_states", expired_epoch)
    await _insert(binding, "claw_github_oauth_states", live_epoch)

    counts = await purge_expired_rows(binding, grace_days=DEFAULT_GRACE_DAYS, now=NOW)

    assert counts["orchestration_continuations"] == 2
    assert counts["password_reset_tokens"] == 1
    assert counts["pc_pairing_codes"] == 1
    assert counts["claw_github_oauth_states"] == 1
    # The continuation table seeded five rows (both ISO formats), the other
    # TEXT tables three each: the expired-past-grace row of each is gone.
    assert await _count(binding, "orchestration_continuations") == 3
    for table in TEXT_TABLES[1:]:
        assert await _count(binding, table) == 2
    assert await _count(binding, "claw_github_oauth_states") == 1


# ---------------------------------------------------------------------------
# (b) The excluded tables are outside the module's authority entirely.
# ---------------------------------------------------------------------------


async def test_excluded_tables_keep_every_row(binding):
    for index in range(3):
        await _insert(binding, "password_reset_audit", index)
        await _insert(binding, "pc_device_links", f"link-{index}")

    await purge_expired_rows(binding, grace_days=DEFAULT_GRACE_DAYS, now=NOW)

    assert await _count(binding, "password_reset_audit") == 3
    assert await _count(binding, "pc_device_links") == 3


# ---------------------------------------------------------------------------
# (c) One batch per table per run: a backlog decays, it never locks once.
# ---------------------------------------------------------------------------


async def test_a_large_backlog_sheds_one_batch_per_run(binding):
    for index in range(5):
        await _insert(binding, "pc_pairing_codes", f"expired-{index}")
        # Seed every expired row with a deadline far past the grace window.
        await binding.prepare(
            "UPDATE pc_pairing_codes SET expires_at = ? WHERE code_id = ?"
        ).bind(EXPIRED_PAST_GRACE, f"expired-{index}").run()

    counts = await purge_expired_rows(
        binding, grace_days=DEFAULT_GRACE_DAYS, batch_size=2, now=NOW
    )
    assert counts["pc_pairing_codes"] == 2
    assert await _count(binding, "pc_pairing_codes") == 3

    counts = await purge_expired_rows(
        binding, grace_days=DEFAULT_GRACE_DAYS, batch_size=2, now=NOW
    )
    assert counts["pc_pairing_codes"] == 2
    assert await _count(binding, "pc_pairing_codes") == 1

    # The unbounded default still clears what remains.
    counts = await purge_expired_rows(binding, grace_days=DEFAULT_GRACE_DAYS, now=NOW)
    assert counts["pc_pairing_codes"] == 1
    assert await _count(binding, "pc_pairing_codes") == 0


# ---------------------------------------------------------------------------
# (d) A dry run counts; it never deletes.
# ---------------------------------------------------------------------------


async def test_a_dry_run_counts_without_deleting(binding):
    for table in TEXT_TABLES:
        await _insert(binding, table, EXPIRED_PAST_GRACE)
        await _insert(binding, table, EXPIRED_WITHIN_GRACE)

    counts = await purge_expired_rows(
        binding, grace_days=DEFAULT_GRACE_DAYS, dry_run=True, now=NOW
    )
    assert counts["orchestration_continuations"] == 1
    assert counts["password_reset_tokens"] == 1
    for table in TEXT_TABLES:
        assert await _count(binding, table) == 2


# ---------------------------------------------------------------------------
# (e) The entry gate matches app.local_cron: no host flag, no run.
# ---------------------------------------------------------------------------


def test_without_the_cpython_host_flag_the_purge_does_not_run(capsys):
    status = run_once(environ={})
    assert status == STATUS_PREFIX + "SKIPPED reason=cpython_host_entry_required"
    assert "detail" not in status


def test_with_the_host_flag_set_and_no_database_the_state_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setenv("PADIEM_CHAT_CPYTHON_HOST", "1")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path / "data"))
    status = run_once(environ=dict(**__import__("os").environ))
    # A database that does not exist yet is a bounded state, not a traceback:
    # sqlite creates an empty file, every target table is absent, so the pass
    # completes with zero rows.
    assert status.startswith(STATUS_PREFIX + "ok ")
    detail = json.loads(status.split("detail=", 1)[1])
    assert all(value == 0 for value in detail.values())


# ---------------------------------------------------------------------------
# (f) The output carries table names and counts, never row material.
# ---------------------------------------------------------------------------


async def test_the_result_never_names_a_row(binding, capsys):
    marker = "row-content-IDENTIFIER-do-not-echo"
    await _insert(binding, "orchestration_continuations", EXPIRED_PAST_GRACE)
    await binding.prepare(
        "INSERT INTO password_reset_tokens (token_id, expires_at) VALUES (?, ?)"
    ).bind(marker, EXPIRED_PAST_GRACE).run()

    counts = await purge_expired_rows(binding, grace_days=DEFAULT_GRACE_DAYS, now=NOW)
    status = f"{STATUS_PREFIX}ok detail={json.dumps(counts, sort_keys=True)}"
    print(status)

    captured = capsys.readouterr().out
    assert "orchestration_continuations" in captured
    assert marker not in captured
    assert EXPIRED_PAST_GRACE not in captured


# ---------------------------------------------------------------------------
# The contract guards itself: an invalid bound is a caller error, a missing
# table (an environment behind on migrations) skips instead of failing.
# ---------------------------------------------------------------------------


async def test_invalid_bounds_are_refused(binding):
    with pytest.raises(ValueError):
        await purge_expired_rows(binding, grace_days=-1, now=NOW)
    with pytest.raises(ValueError):
        await purge_expired_rows(binding, batch_size=0, now=NOW)


async def test_a_missing_table_skips_as_zero_rows(binding):
    # The temporary schema has every target table; drop one to represent an
    # environment that has not received its migration yet.
    binding.connection.execute("DROP TABLE claw_web_xlsx_selections")
    counts = await purge_expired_rows(binding, grace_days=DEFAULT_GRACE_DAYS, now=NOW)
    assert counts["claw_web_xlsx_selections"] == 0


def test_the_default_batch_is_bounded():
    assert DEFAULT_BATCH == 1000
    assert DEFAULT_GRACE_DAYS == 7


# This module is storage-only and platform-independent: the SQLite facade it
# reuses behaves identically on Windows and POSIX, so no platform skip marker
# applies. (Windows-only tests elsewhere skip on sys.platform != "win32".)

# ---------------------------------------------------------------------------
# (g) A surviving receipt keeps its parent: NO ACTION foreign keys stay valid.
# ---------------------------------------------------------------------------


async def test_rows_a_surviving_receipt_cites_are_left_alone(binding):
    # 11-03 the real pass stopped here: deleting an expired parent that a
    # receipt still cites raised FOREIGN KEY constraint failed, and every table
    # after it in the run was skipped.
    for ref in ("cited", "free"):
        await binding.prepare(
            "INSERT INTO claw_web_xlsx_selections (selection_ref, expires_at) "
            "VALUES (?, ?)"
        ).bind(ref, EXPIRED_PAST_GRACE).run()
        await binding.prepare(
            "INSERT INTO claw_web_xlsx_p01_requests (request_ref, pause_expires_at) "
            "VALUES (?, ?)"
        ).bind(ref, EXPIRED_PAST_GRACE).run()
    await binding.prepare(
        "INSERT INTO claw_web_xlsx_quote_edit_receipts (selection_ref) VALUES (?)"
    ).bind("cited").run()
    await binding.prepare(
        "INSERT INTO claw_web_xlsx_p01_decision_receipts (request_ref) VALUES (?)"
    ).bind("cited").run()

    counts = await purge_expired_rows(binding, grace_days=DEFAULT_GRACE_DAYS, now=NOW)

    assert counts["claw_web_xlsx_selections"] == 1
    assert counts["claw_web_xlsx_p01_requests"] == 1
    assert await _count(binding, "claw_web_xlsx_selections") == 1
    assert await _count(binding, "claw_web_xlsx_p01_requests") == 1
    assert await _count(binding, "claw_web_xlsx_quote_edit_receipts") == 1

    # The guard is in the counting mode too: nothing cited is promised away.
    counted = await purge_expired_rows(
        binding, grace_days=DEFAULT_GRACE_DAYS, dry_run=True, now=NOW
    )
    assert counted["claw_web_xlsx_selections"] == 0
    assert counted["claw_web_xlsx_p01_requests"] == 0


# ---------------------------------------------------------------------------
# (h) A failed pass tells systemd so instead of exiting 0.
# ---------------------------------------------------------------------------


def test_a_refused_pass_exits_non_zero(tmp_path, monkeypatch):
    monkeypatch.delenv("PADIEM_CHAT_CPYTHON_HOST", raising=False)
    monkeypatch.delenv("PADIEM_LOCAL_DEV", raising=False)
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path / "data"))
    assert main(["--once"]) == 2


def test_the_exit_status_matches_the_reported_state(monkeypatch):
    # A failed pass must not report success to systemd, and a good one must not
    # report failure. The state line is injected: the host's own empty-database
    # path is a separate matter.
    for status_line, expected in (
        (STATUS_PREFIX + "ok detail={}", 0),
        (STATUS_PREFIX + "dry_run detail={}", 0),
        (STATUS_PREFIX + "ERROR reason=purge_failed", 1),
        (STATUS_PREFIX + "STORAGE_ERROR reason=database_unavailable", 1),
    ):
        monkeypatch.setattr(expired_purge, "run_once", lambda **_kw: status_line)
        assert main(["--once"]) == expected, status_line
