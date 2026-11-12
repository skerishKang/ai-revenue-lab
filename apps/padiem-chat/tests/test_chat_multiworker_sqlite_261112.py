"""Several worker processes on one SQLite file: write batches and the idle checkpoint.

A worker process orders its own writes with a lock in its own memory. Between
processes only the SQLite file lock is left, and an idle process cannot see
that another one is busy. These tests run real OS processes against one
database file and pin three things:

* write batches from two processes all commit, whatever statement they start with;
* a batch that starts by reading waits for the other process instead of failing at once;
* the WAL checkpoint runs in exactly one process, and another takes over when it ends.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.d1_sqlite import SqliteD1, connect

FIXTURE = Path(__file__).parent / "fixtures/chat_multiworker_sqlite_261112.py"
ROUNDS = 300


def _database(tmp_path) -> Path:
    path = tmp_path / "chat.sqlite3"
    connection = connect(str(path))
    connection.execute("CREATE TABLE probe (id TEXT PRIMARY KEY, value INTEGER NOT NULL)")
    connection.execute("CREATE TABLE probe_log (n INTEGER PRIMARY KEY, pid INTEGER NOT NULL)")
    connection.execute("INSERT INTO probe VALUES ('count', 0)")
    connection.close()
    return path


def _spawn(mode, *arguments, stdout=subprocess.PIPE):
    # -u: the checkpoint loop's lines must reach the log file as they happen.
    return subprocess.Popen(
        [sys.executable, "-u", str(FIXTURE), mode, *map(str, arguments)],
        stdout=stdout, stderr=subprocess.PIPE, text=True, encoding="utf-8")


def _wait_until(predicate, seconds=30):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("the synthetic processes did not reach the expected state")


def _stop(processes):
    for process in processes:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)


@pytest.mark.parametrize("shape", ["write_first", "read_first"])
def test_two_processes_repeat_write_batches_without_a_single_failure(tmp_path, shape):
    database = _database(tmp_path)
    start = tmp_path / "start"
    ready = [tmp_path / f"ready-{index}" for index in range(2)]
    processes = [_spawn("batch_writer", database, marker, start, ROUNDS, shape) for marker in ready]
    try:
        _wait_until(lambda: all(marker.exists() for marker in ready))
        start.touch()
        reports = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=120)
            assert process.returncode == 0, stderr
            reports.append(json.loads(stdout))
    finally:
        _stop(processes)
    assert [report["failed"] for report in reports] == [[], []]
    assert [report["done"] for report in reports] == [ROUNDS, ROUNDS]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT value FROM probe WHERE id='count'").fetchone()[0] == 2 * ROUNDS
        per_process = dict(connection.execute("SELECT pid, COUNT(*) FROM probe_log GROUP BY pid"))
    assert per_process == {report["pid"]: ROUNDS for report in reports}


@pytest.mark.asyncio
async def test_batch_that_starts_by_reading_makes_the_other_process_wait(tmp_path):
    database = _database(tmp_path)
    ready, go, done = tmp_path / "ready", tmp_path / "go", tmp_path / "done"
    other_finished_first = []

    def hold_for_other_process():
        # Runs inside the batch, after its first statement started reading:
        # let the other process try to commit, and give it time to do so.
        go.touch()
        until = time.monotonic() + 0.5
        while not done.exists() and time.monotonic() < until:
            time.sleep(0.005)
        other_finished_first.append(done.exists())
        return 1

    connection = connect(str(database))
    connection.create_function("hold_for_other_process", 0, hold_for_other_process)
    db = SqliteD1(connection, threaded=True)
    process = _spawn("contender", database, ready, go, done)
    try:
        _wait_until(ready.exists)
        results = await db.batch([
            db.prepare("SELECT value, hold_for_other_process() AS held FROM probe WHERE id = 'count'"),
            db.prepare("UPDATE probe SET value = value + 1 WHERE id = 'count' RETURNING value"),
        ])
        _, stderr = await asyncio.to_thread(process.communicate, timeout=30)
        assert process.returncode == 0, stderr
        # The batch held the write lock from its first statement, so the other
        # process's commit came after it, not in the middle of it.
        assert other_finished_first == [False]
        assert results[0]["results"] == [{"value": 0, "held": 1}]
        assert results[1]["results"] == [{"value": 1}]
        assert connection.execute("SELECT value FROM probe WHERE id='count'").fetchone()[0] == 101
    finally:
        _stop([process])
        connection.close()


def test_checkpoint_lock_has_one_holder_and_moves_on_release(tmp_path):
    from app.local_bootstrap import checkpoint_owner_lock
    database = _database(tmp_path)
    connections = [connect(str(database)) for _ in range(2)]
    first, second = (checkpoint_owner_lock(connection) for connection in connections)
    try:
        assert first.acquire(wait=False) and first.held
        assert first.acquire(wait=False)
        assert not second.acquire(wait=False) and not second.held
        # The lock file sits in the data folder, next to the database.
        assert (tmp_path / "chat.sqlite3.checkpoint.lock").exists()
        first.release()
        assert not first.held
        assert second.acquire(wait=False) and second.held
    finally:
        first.release()
        second.release()
        for connection in connections:
            connection.close()
    # Nothing shares an in-memory database, so its lock is always granted.
    memory = sqlite3.connect(":memory:")
    try:
        lock = checkpoint_owner_lock(memory)
        assert lock.acquire(wait=False) and lock.held
        lock.release()
    finally:
        memory.close()


@pytest.mark.asyncio
async def test_loop_without_the_lock_asks_again_each_period_and_never_checkpoints(tmp_path):
    from app.local_bootstrap import checkpoint_owner_lock
    from app.local_cpython import run_wal_checkpoint_loop
    database = _database(tmp_path)
    connections = [connect(str(database)) for _ in range(2)]
    holder, waiting = (checkpoint_owner_lock(connection) for connection in connections)
    calls = []

    class Database:
        async def checkpoint_if_idle(self, **options):
            calls.append(options)
            return {"skipped": "recent_activity"}

    assert holder.acquire(wait=False)
    task = asyncio.create_task(run_wal_checkpoint_loop(Database(), waiting, period=0.01))
    try:
        await asyncio.sleep(0.2)
        assert calls == [] and not waiting.held
        holder.release()
        until = time.monotonic() + 10
        while not calls and time.monotonic() < until:
            await asyncio.sleep(0.01)
        # The host passes no options: the facade's own quiet rules apply.
        assert calls and calls[0] == {}
        assert waiting.held
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        holder.release()
        waiting.release()
        for connection in connections:
            connection.close()


def test_one_process_checkpoints_and_another_takes_over_when_it_ends(tmp_path):
    database = _database(tmp_path)
    wal = Path(str(database) + "-wal")
    ready = [tmp_path / f"ready-{index}" for index in range(2)]
    logs = [tmp_path / f"checkpointer-{index}.log" for index in range(2)]
    # This test's own connection is "another connection" to both processes.
    writer = connect(str(database))
    writer.execute("PRAGMA wal_autocheckpoint = 0")
    handles = [log.open("w", encoding="utf-8") for log in logs]
    processes = [_spawn("checkpointer", database, marker, stdout=handle)
                 for marker, handle in zip(ready, handles)]

    def checkpoints(index):
        return [line for line in logs[index].read_text(encoding="utf-8").splitlines()
                if line.startswith("[local] wal_checkpoint busy=")]

    def grow_wal_then_wait_for_truncate():
        # Every commit appends to the WAL and this connection never
        # checkpoints, so an empty WAL after the last insert means one of the
        # two processes truncated it after that insert.
        for _ in range(20):
            writer.execute("INSERT INTO probe_log (pid) VALUES (0)")
        _wait_until(lambda: wal.stat().st_size == 0)

    try:
        _wait_until(lambda: all(marker.exists() for marker in ready))
        grow_wal_then_wait_for_truncate()
        _wait_until(lambda: checkpoints(0) or checkpoints(1))
        owner = 0 if checkpoints(0) else 1
        other = 1 - owner
        for _ in range(3):
            grow_wal_then_wait_for_truncate()
        # Both loops ran the whole time; only the lock holder checkpointed.
        assert processes[other].poll() is None
        assert checkpoints(other) == []

        # The holder ends (killed: no shutdown code runs). Its OS lock goes
        # with it and the other process picks the role up on a later period.
        processes[owner].kill()
        processes[owner].wait(timeout=5)
        before = len(checkpoints(owner))
        grow_wal_then_wait_for_truncate()
        _wait_until(lambda: checkpoints(other))
        assert len(checkpoints(owner)) == before
        for log in logs:
            assert "wal_checkpoint=failed" not in log.read_text(encoding="utf-8")
    finally:
        _stop(processes)
        for handle in handles:
            handle.close()
        writer.close()
