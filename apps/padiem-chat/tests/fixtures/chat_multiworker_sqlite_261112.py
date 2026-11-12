"""Subprocess fixture: separate OS processes on one SQLite file, through the host's facade."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path


def _wait_for(marker: Path) -> None:
    while not marker.exists():
        time.sleep(0.005)


def _statements(db, shape: str):
    add = db.prepare("UPDATE probe SET value = value + 1 WHERE id = 'count'")
    log = db.prepare("INSERT INTO probe_log (pid) VALUES (?)").bind(os.getpid())
    if shape == "write_first":
        return [add, log]
    if shape == "read_first":
        return [db.prepare("SELECT value FROM probe WHERE id = 'count'"), add, log]
    raise SystemExit(f"unknown batch shape: {shape}")


async def batch_writer(database, ready, start, rounds, shape):
    """Repeat one write batch; report how many committed and every failure."""
    from app.d1_sqlite import SqliteD1, connect

    connection = connect(database)
    db = SqliteD1(connection, threaded=True)
    Path(ready).touch()
    _wait_for(Path(start))
    done, failed = 0, []
    for _ in range(int(rounds)):
        try:
            await db.batch(_statements(db, shape))
            done += 1
        except Exception as exc:
            failed.append(f"{type(exc).__name__}: {exc}")
    connection.close()
    print(json.dumps({"pid": os.getpid(), "done": done, "failed": failed}), flush=True)


async def contender(database, ready, go, done):
    """Commit one plain write as soon as the test says go."""
    from app.d1_sqlite import connect

    connection = connect(database)
    Path(ready).touch()
    _wait_for(Path(go))
    connection.execute("UPDATE probe SET value = value + 100 WHERE id = 'count'")
    Path(done).touch()
    connection.close()


async def checkpointer(database, ready):
    """Run the host's checkpoint loop, sped up, until the test stops this process."""
    from app.d1_sqlite import SqliteD1, connect
    from app.local_bootstrap import checkpoint_owner_lock
    from app.local_cpython import run_wal_checkpoint_loop

    connection = connect(database)
    db = SqliteD1(connection, threaded=True)
    Path(ready).touch()
    await run_wal_checkpoint_loop(
        db, checkpoint_owner_lock(connection), period=0.05, quiet_seconds=0.0, min_interval=0.0)


if __name__ == "__main__":
    asyncio.run({
        "batch_writer": batch_writer,
        "contender": contender,
        "checkpointer": checkpointer,
    }[sys.argv[1]](*sys.argv[2:]))
