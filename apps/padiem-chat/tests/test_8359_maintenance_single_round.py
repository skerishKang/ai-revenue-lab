"""#8359: a DB lease coexists with the OS lock, without a second maintenance run."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from app.d1_sqlite import SqliteD1
from app.local_bootstrap import pc_maintenance_lock
from app import pc_helper_maintenance_host as host


BASE = datetime(2026, 11, 28, 6, 15, 5, tzinfo=timezone.utc)


def _workers(tmp_path):
    path = tmp_path / "chat.db"
    conn_a = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn_a.row_factory = sqlite3.Row
    migration = Path(__file__).resolve().parents[1] / "migrations" / "142_pc_helper_maintenance_round_lease.sql"
    conn_a.executescript(migration.read_text(encoding="utf-8"))
    conn_b = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn_b.row_factory = sqlite3.Row
    return ((host.HostMaintenanceStore(SqliteD1(conn_a)), pc_maintenance_lock(conn_a), conn_a),
            (host.HostMaintenanceStore(SqliteD1(conn_b)), pc_maintenance_lock(conn_b), conn_b))


def test_two_workers_one_idle_window_even_after_lease_expires(tmp_path, monkeypatch):
    a, b = _workers(tmp_path)
    now = [BASE]
    calls = []
    monkeypatch.setattr(host, "_now", lambda: now[0])

    async def idle(_store):
        return host.IDLE_INTERVAL

    async def round_stub(*args):
        calls.append(now[0])
    monkeypatch.setattr(host, "next_delay", idle)
    monkeypatch.setattr(host, "maintenance_round", round_stub)

    async def check():
        assert await host.maintenance_tick(None, {}, a[0], a[1]) == "completed"
        assert await host.maintenance_tick(None, {}, b[0], b[1]) == "already_run"
        now[0] += timedelta(seconds=host.ROUND_LEASE_SECONDS + 1)
        assert await host.maintenance_tick(None, {}, b[0], b[1]) == "already_run"
        assert len(calls) == 1
        assert a[2].execute("SELECT last_round_at,round_id,lease_expires_at,completed_at "
                            "FROM pc_helper_maintenance_rounds").fetchone()[3] is not None
        now[0] = BASE + timedelta(seconds=900)
        assert await host.maintenance_tick(None, {}, b[0], b[1]) == "completed"
        assert len(calls) == 2
    asyncio.run(check())
    a[2].close()
    b[2].close()


def test_handled_round_failure_is_completed_once_per_window(tmp_path, monkeypatch, caplog):
    """Identity/PC errors do not hammer the same 15-minute window."""
    a, b = _workers(tmp_path)
    now = [BASE]
    calls = []
    monkeypatch.setattr(host, "_now", lambda: now[0])

    async def idle(_store):
        return host.IDLE_INTERVAL

    async def fail_then_succeed(*args):
        calls.append(now[0])
        if len(calls) == 1:
            raise RuntimeError("fixture identity service unavailable")

    monkeypatch.setattr(host, "next_delay", idle)
    monkeypatch.setattr(host, "maintenance_round", fail_then_succeed)

    async def check():
        assert await host.maintenance_tick(None, {}, a[0], a[1]) == "failed"
        row = a[2].execute("SELECT completed_at, outcome FROM "
                           "pc_helper_maintenance_rounds").fetchone()
        assert row["completed_at"] is not None and row["outcome"] == "failed"
        assert "pc_maintenance_round_failed" in caplog.text
        assert await host.maintenance_tick(None, {}, b[0], b[1]) == "already_run"
        now[0] += timedelta(seconds=host.ROUND_LEASE_SECONDS + 1)
        assert await host.maintenance_tick(None, {}, b[0], b[1]) == "already_run"
        assert len(calls) == 1
        now[0] = BASE + timedelta(seconds=900)
        assert await host.maintenance_tick(None, {}, b[0], b[1]) == "completed"
        row = a[2].execute("SELECT outcome FROM pc_helper_maintenance_rounds").fetchone()
        assert row["outcome"] == "completed"
        assert len(calls) == 2
    asyncio.run(check())
    a[2].close()
    b[2].close()


def test_unfinished_worker_lease_expires_and_other_worker_recovers(tmp_path, monkeypatch):
    a, b = _workers(tmp_path)
    now = [BASE]
    calls = []
    monkeypatch.setattr(host, "_now", lambda: now[0])

    async def idle(_store):
        return host.IDLE_INTERVAL

    async def round_stub(*args):
        calls.append("recovered")
    monkeypatch.setattr(host, "next_delay", idle)
    monkeypatch.setattr(host, "maintenance_round", round_stub)

    async def check():
        stale = await a[0].claim_round(900, now[0])
        assert stale
        assert await host.maintenance_tick(None, {}, b[0], b[1]) == "already_run"
        now[0] += timedelta(seconds=host.ROUND_LEASE_SECONDS + 1)
        assert await host.maintenance_tick(None, {}, b[0], b[1]) == "completed"
        assert calls == ["recovered"]
        assert not await a[0].complete_round(900, stale, now[0])
        row = a[2].execute("SELECT completed_at, outcome, round_id "
                           "FROM pc_helper_maintenance_rounds").fetchone()
        assert row["completed_at"] is not None and row["outcome"] == "completed"
        assert row["round_id"] != stale
        assert await host.maintenance_tick(None, {}, a[0], a[1]) == "already_run"
    asyncio.run(check())
    a[2].close()
    b[2].close()


def test_existing_lock_busy_blocks_claim(tmp_path, monkeypatch):
    a, b = _workers(tmp_path)
    assert a[1].acquire(wait=False)
    try:
        async def check():
            assert await host.maintenance_tick(None, {}, b[0], b[1]) == "busy"
        asyncio.run(check())
        assert a[2].execute("SELECT count(*) FROM pc_helper_maintenance_rounds").fetchone()[0] == 0
    finally:
        a[1].release()
        a[2].close()
        b[2].close()


def test_active_reconcile_keeps_60_second_cadence(tmp_path, monkeypatch):
    a, b = _workers(tmp_path)
    now = [BASE]
    calls = []
    monkeypatch.setattr(host, "_now", lambda: now[0])

    async def active(_store):
        return host.INTERVAL

    async def round_stub(*args):
        calls.append(now[0])
    monkeypatch.setattr(host, "next_delay", active)
    monkeypatch.setattr(host, "maintenance_round", round_stub)

    async def check():
        assert await host.maintenance_tick(None, {}, a[0], a[1]) == "completed"
        assert await host.maintenance_tick(None, {}, b[0], b[1]) == "already_run"
        now[0] += timedelta(seconds=60)
        assert await host.maintenance_tick(None, {}, b[0], b[1]) == "completed"
        assert len(calls) == 2
    asyncio.run(check())
    a[2].close()
    b[2].close()

def test_independent_python_processes_share_one_completed_window(tmp_path):
    """Two separate interpreter PIDs, not merely two store objects."""
    import os
    import subprocess
    import sys

    path = tmp_path / "multi-process.db"
    conn = sqlite3.connect(str(path), isolation_level=None)
    migration = Path(__file__).resolve().parents[1] / "migrations" / "142_pc_helper_maintenance_round_lease.sql"
    conn.executescript(migration.read_text(encoding="utf-8"))
    conn.close()
    program = (
        "import asyncio,sqlite3,sys\n"
        "from datetime import datetime\n"
        "from app.d1_sqlite import SqliteD1\n"
        "from app.pc_helper_maintenance_host import HostMaintenanceStore\n"
        "async def main():\n"
        "  db=sqlite3.connect(sys.argv[1],isolation_level=None,check_same_thread=False)\n"
        "  db.row_factory=sqlite3.Row\n"
        "  store=HostMaintenanceStore(SqliteD1(db))\n"
        "  at=datetime.fromisoformat(sys.argv[2])\n"
        "  token=await store.claim_round(900,at)\n"
        "  if token: await store.complete_round(900,token,at)\n"
        "  print('won' if token else 'lost')\n"
        "  db.close()\n"
        "asyncio.run(main())\n"
    )
    repo = Path(__file__).resolve().parents[3]
    paths = [repo / "apps" / "padiem-chat",
             repo / "apps" / "korean-ai-code-agent" / "src",
             repo / "packages" / "padiem-ai-core",
             repo / "packages" / "padiem-control-plane",
             repo / "apps" / "padiem-ai-engine" / "clients" / "python"]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([*(str(p) for p in paths),
                                          env.get("PYTHONPATH", "")])
    outputs = []
    for _ in range(2):
        completed = subprocess.run(
            [sys.executable, "-c", program, str(path), BASE.isoformat()],
            capture_output=True, text=True, timeout=20, check=True, env=env)
        outputs.append(completed.stdout.strip())
    assert outputs == ["won", "lost"]
