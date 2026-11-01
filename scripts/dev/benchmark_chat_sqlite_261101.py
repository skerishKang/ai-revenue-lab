#!/usr/bin/env python3
"""Offline SQLite contention sample; synthetic evidence, never production data.

One writer deliberately holds an UPDATE for 120ms while five independent reads
arrive. Output contains durations and counts only. Run from any working directory.
"""
from __future__ import annotations

import asyncio
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps/padiem-chat"))

from app.d1_sqlite import SqliteD1
from app.request_timing import reset_timing, start_timing


async def measure(read_workers=0) -> dict:
    with tempfile.TemporaryDirectory(prefix="padiem-sqlite-measure-") as folder:
        connection = sqlite3.connect(str(Path(folder) / "measure.sqlite3"),
                                     isolation_level=None, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE sample(value INTEGER)")
        connection.execute("INSERT INTO sample VALUES (1)")
        entered = threading.Event()

        def hold(value):
            entered.set()
            time.sleep(0.12)
            return value + 1

        connection.create_function("hold", 1, hold)
        db = SqliteD1(connection, threaded=True, read_workers=read_workers)
        try:
            writer = asyncio.create_task(db.prepare("UPDATE sample SET value=hold(value)").run())
            if not await asyncio.to_thread(entered.wait, 5):
                await writer
                raise RuntimeError("synthetic writer did not enter")

            async def read(index):
                started = time.perf_counter()
                timing, token = start_timing()
                try:
                    await db.prepare("SELECT value FROM sample").first()
                    stages = timing.snapshot()
                    return {"sample": index, "total_ms": round((time.perf_counter() - started) * 1000, 2),
                            "sqlite_wait_ms": stages["sqlite_wait"],
                            "sqlite_execute_ms": stages["sqlite_execute"]}
                finally:
                    reset_timing(token)

            samples = await asyncio.gather(*(read(index) for index in range(1, 6)))
            await writer
            return {"source": "offline_synthetic_writer_contention", "writer_hold_ms": 120,
                    "read_workers": read_workers,
                    "read_count": len(samples), "samples": samples}
        finally:
            await db.close_readers()
            connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-workers", type=int, default=0,
                        help="0 reproduces the serial writer lock; 2 uses the host read-pool default")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(measure(args.read_workers)), sort_keys=True))
