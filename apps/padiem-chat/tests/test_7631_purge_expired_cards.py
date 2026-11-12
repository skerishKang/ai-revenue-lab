"""#7631 — the daily purge retires expired PC confirmation cards for every
owner, with the one expiry rule the run-history read paths already use.

The read paths (#7603) retire a card only when someone lists the run history;
a card nobody opens stayed ``waiting_approval`` in the database forever. The
daily purge now runs the same conditional UPDATE for all owners, bounded by
the run's batch size, its failures contained to the summary count. The tests
apply the real migrations to SQLite and inject time by stamping rows around
the real clock (expired = an hour ago, young = an hour ahead) — nothing sleeps.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from app.d1_sqlite import SqliteD1, connect
from app.history import D1HistoryStore, expire_stale_confirmation_cards_for_all_owners
from app.local_cpython import apply_migrations

import app.expired_purge as expired_purge
from app.expired_purge import STATUS_PREFIX, run_once

UID_A = "usr_" + "a" * 32
UID_B = "usr_" + "b" * 32
#: Always long expired, whatever the real clock says when the test runs.
ANCIENT = "2020-01-01T00:00:00Z"
#: Fixed stamps for the unit tests that also pass a fixed ``now`` (10:00).
#: The confirm window is 600s, so 09:58 is still young and 00:00 is expired.
OLD = "2026-11-13T00:00:00Z"
YOUNG = "2026-11-13T09:58:00Z"
ACTIONS = ("pc_command", "desktop_type")


def _migrated_binding(tmp_path):
    connection = sqlite3.connect(str(tmp_path / "chat.sqlite3"), isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    return SqliteD1(connection), connection


async def _card(binding, *, user_id, run_id, status, created_at, action="pc_command"):
    await binding.prepare(
        "INSERT INTO claw_run_history (id, user_id, run_id, channel, action, title,"
        " status, created_at, updated_at) VALUES (?, ?, ?, 'pc', ?, ?, ?, ?, ?)"
    ).bind(
        "crh_" + run_id[-16:], user_id, run_id, action, "제목", status,
        created_at, created_at,
    ).run()


async def _status_of(binding, run_id, user_id):
    row = await binding.prepare(
        "SELECT status FROM claw_run_history WHERE run_id=? AND user_id=?"
    ).bind(run_id, user_id).first()
    return (row or {}).get("status")


def test_expired_cards_of_every_owner_retire_after_the_purge(tmp_path):
    binding, _ = _migrated_binding(tmp_path)
    asyncio.run(_card(binding, user_id=UID_A, run_id="run_a_old", status="waiting_approval", created_at=OLD))
    asyncio.run(_card(binding, user_id=UID_B, run_id="run_b_old", status="waiting_approval", created_at=OLD))

    retired = asyncio.run(expire_stale_confirmation_cards_for_all_owners(
        binding, limit=500, now=datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc),
    ))

    assert retired == 2
    assert asyncio.run(_status_of(binding, "run_a_old", UID_A)) == "timed_out"
    assert asyncio.run(_status_of(binding, "run_b_old", UID_B)) == "timed_out"


def test_young_cards_and_other_statuses_are_left_alone(tmp_path):
    binding, _ = _migrated_binding(tmp_path)
    asyncio.run(_card(binding, user_id=UID_A, run_id="run_young", status="waiting_approval", created_at=YOUNG))
    asyncio.run(_card(binding, user_id=UID_A, run_id="run_done", status="completed", created_at=OLD))
    asyncio.run(_card(binding, user_id=UID_A, run_id="run_cancelled", status="cancelled", created_at=OLD))
    asyncio.run(_card(binding, user_id=UID_A, run_id="run_failed", status="failed", created_at=OLD))

    retired = asyncio.run(expire_stale_confirmation_cards_for_all_owners(
        binding, limit=500, now=datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc),
    ))

    assert retired == 0
    assert asyncio.run(_status_of(binding, "run_young", UID_A)) == "waiting_approval"
    assert asyncio.run(_status_of(binding, "run_done", UID_A)) == "completed"
    assert asyncio.run(_status_of(binding, "run_cancelled", UID_A)) == "cancelled"
    assert asyncio.run(_status_of(binding, "run_failed", UID_A)) == "failed"


def test_the_pass_is_bounded_by_its_limit_and_the_rest_waits(tmp_path):
    binding, _ = _migrated_binding(tmp_path)
    for index in range(5):
        asyncio.run(_card(binding, user_id=UID_A if index % 2 == 0 else UID_B,
                          run_id=f"run_old_{index}", status="waiting_approval", created_at=OLD))

    retired = asyncio.run(expire_stale_confirmation_cards_for_all_owners(
        binding, limit=3, now=datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc),
    ))

    assert retired == 3
    left = asyncio.run(binding.prepare(
        "SELECT COUNT(*) AS n FROM claw_run_history WHERE status='waiting_approval'"
        " AND created_at=?"
    ).bind(OLD).first())
    assert (left or {}).get("n") == 2


def test_the_read_paths_narrowing_is_unchanged_one_owner_at_a_time(tmp_path):
    """The list-read moment keeps retiring only the calling owner's cards —
    one owner's expiry must never retire another owner's row."""
    binding, connection = _migrated_binding(tmp_path)
    store = D1HistoryStore(binding)
    expired_stamp = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    asyncio.run(_card(binding, user_id=UID_A, run_id="run_a_old", status="waiting_approval", created_at=expired_stamp))
    asyncio.run(_card(binding, user_id=UID_B, run_id="run_b_old", status="waiting_approval", created_at=expired_stamp))

    retired = asyncio.run(store.expire_stale_confirmation_cards(UID_A))

    assert retired == 1
    assert asyncio.run(_status_of(binding, "run_a_old", UID_A)) == "timed_out"
    assert asyncio.run(_status_of(binding, "run_b_old", UID_B)) == "waiting_approval"


# ── the full daily run: the stage lands in the summary and contains failures ─


def _seed_daily_run_db(tmp_path, *, hours_old: float) -> None:
    """Stamp the cards around the real clock: expired = an hour ago, young = an
    hour ahead. The expiry condition itself is never duplicated here."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(data_dir / "chat.sqlite3"), isolation_level=None)
    connection.row_factory = sqlite3.Row
    apply_migrations(connection)
    now = datetime.now(timezone.utc)
    expired_stamp = (now - timedelta(hours=hours_old)).isoformat()
    young_stamp = (now + timedelta(hours=1)).isoformat()
    stamps = [
        ("usr_" + "c" * 32, "run_daily_old_a", "waiting_approval", expired_stamp),
        ("usr_" + "d" * 32, "run_daily_old_b", "waiting_approval", expired_stamp),
        ("usr_" + "c" * 32, "run_daily_young", "waiting_approval", young_stamp),
    ]
    for user_id, run_id, status, created_at in stamps:
        connection.execute(
            "INSERT INTO claw_run_history (id, user_id, run_id, channel, action, title,"
            " status, created_at, updated_at) VALUES (?, ?, ?, 'pc', 'pc_command', '제목',"
            " ?, ?, ?)",
            ("crh_" + run_id[-16:], user_id, run_id, status, created_at, created_at),
        )
    connection.commit()
    connection.close()


def _daily_environ(tmp_path, monkeypatch, *, batch=None):
    monkeypatch.setenv("PADIEM_CHAT_CPYTHON_HOST", "1")
    monkeypatch.setenv("PADIEM_CHAT_LOCAL_DATA_DIR", str(tmp_path / "data"))
    if batch is not None:
        monkeypatch.setenv("PADIEM_CHAT_EXPIRED_PURGE_BATCH", str(batch))
    environ = dict(__import__("os").environ)
    if batch is not None:
        environ["PADIEM_CHAT_EXPIRED_PURGE_BATCH"] = str(batch)
    return environ


def test_the_daily_run_retires_expired_cards_and_reports_the_count(tmp_path, monkeypatch):
    _seed_daily_run_db(tmp_path, hours_old=1)
    environ = _daily_environ(tmp_path, monkeypatch)

    status = run_once(environ=environ)

    assert status.startswith(STATUS_PREFIX + "ok ")
    detail = json.loads(status.split("detail=", 1)[1])
    assert detail["pc_cards_timed_out"] == 2
    connection = sqlite3.connect(str(tmp_path / "data" / "chat.sqlite3"))
    connection.row_factory = sqlite3.Row
    rows = {
        row["run_id"]: row["status"]
        for row in connection.execute("SELECT run_id, status FROM claw_run_history").fetchall()
    }
    connection.close()
    assert rows["run_daily_old_a"] == "timed_out"
    assert rows["run_daily_old_b"] == "timed_out"
    assert rows["run_daily_young"] == "waiting_approval"


def test_the_daily_run_is_bounded_by_the_batch_size(tmp_path, monkeypatch):
    _seed_daily_run_db(tmp_path, hours_old=1)
    data_dir = tmp_path / "data"
    connection = sqlite3.connect(str(data_dir / "chat.sqlite3"))
    connection.execute("DELETE FROM claw_run_history")
    for index in range(5):
        connection.execute(
            "INSERT INTO claw_run_history (id, user_id, run_id, channel, action, title,"
            " status, created_at, updated_at) VALUES (?, ?, ?, 'pc', 'pc_command', '제목',"
            " 'waiting_approval', ?, ?)",
            ("crh_" + f"{index:016x}", "usr_" + f"{index:032x}", f"run_cap_{index}",
             ANCIENT, ANCIENT),
        )
    connection.commit()
    connection.close()
    environ = _daily_environ(tmp_path, monkeypatch, batch=3)

    status = run_once(environ=environ)

    detail = json.loads(status.split("detail=", 1)[1])
    assert detail["pc_cards_timed_out"] == 3
    connection = sqlite3.connect(str(data_dir / "chat.sqlite3"))
    connection.row_factory = sqlite3.Row
    left = connection.execute(
        "SELECT COUNT(*) AS n FROM claw_run_history WHERE status='waiting_approval'"
        " AND created_at=?", (ANCIENT,),
    ).fetchone()
    connection.close()
    assert left["n"] == 2


def test_a_stage_failure_keeps_the_other_passes_in_the_summary(tmp_path, monkeypatch):
    _seed_daily_run_db(tmp_path, hours_old=1)
    environ = _daily_environ(tmp_path, monkeypatch)

    def raiser(binding, *, limit, now=None):
        raise RuntimeError("card stage down")

    monkeypatch.setattr(
        "app.history.expire_stale_confirmation_cards_for_all_owners", raiser,
    )

    status = run_once(environ=environ)

    assert status.startswith(STATUS_PREFIX + "ok ")
    detail = json.loads(status.split("detail=", 1)[1])
    assert detail["pc_cards_timed_out"] == 0
    # The other passes still answered through the same summary.
    assert "account_cleanup_done" in detail
    assert "deleted_conversations" in detail
    connection = sqlite3.connect(str(tmp_path / "data" / "chat.sqlite3"))
    connection.row_factory = sqlite3.Row
    rows = {
        row["run_id"]: row["status"]
        for row in connection.execute("SELECT run_id, status FROM claw_run_history").fetchall()
    }
    connection.close()
    assert rows["run_daily_old_a"] == "waiting_approval"


def test_a_dry_run_does_not_touch_the_cards(tmp_path, monkeypatch):
    _seed_daily_run_db(tmp_path, hours_old=1)
    environ = _daily_environ(tmp_path, monkeypatch)

    status = run_once(environ=environ, dry_run=True)

    detail = json.loads(status.split("detail=", 1)[1])
    assert detail["pc_cards_timed_out"] == 0
    connection = sqlite3.connect(str(tmp_path / "data" / "chat.sqlite3"))
    connection.row_factory = sqlite3.Row
    rows = {
        row["run_id"]: row["status"]
        for row in connection.execute("SELECT run_id, status FROM claw_run_history").fetchall()
    }
    connection.close()
    assert rows["run_daily_old_a"] == "waiting_approval"
    assert rows["run_daily_old_b"] == "waiting_approval"
