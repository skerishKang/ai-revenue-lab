"""Loopback-only subprocess fixture using the host's actual SQLite facade."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path


def migration_worker(argv):
    from app.local_cpython import apply_migrations

    database, migrations, ready, start = map(Path, argv)
    connection = sqlite3.connect(database, isolation_level=None)
    connection.create_function("test_pause", 0, lambda: time.sleep(0.15))
    ready.touch()
    while not start.exists():
        time.sleep(0.01)
    try:
        count = apply_migrations(connection, migrations)
        print(json.dumps({"applied": count}), flush=True)
    finally:
        connection.close()


def create_app():
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Route
    from app.d1_sqlite import SqliteD1, connect
    from app.local_cpython import apply_migrations

    connection = connect(os.environ["PADIEM_TEST_WORKER_DB"])
    apply_migrations(connection, Path(os.environ["PADIEM_TEST_WORKER_MIGRATIONS"]))
    database = SqliteD1(connection, threaded=True)

    async def count(request):
        if request.method == "POST":
            row = await database.prepare(
                "UPDATE worker_probe SET value=value+1 WHERE id='count' RETURNING value"
            ).first()
        else:
            row = await database.prepare("SELECT value FROM worker_probe WHERE id='count'").first()
        return JSONResponse({"count": row["value"], "pid": os.getpid()})

    async def stream(request):
        async def events():
            yield b"data: started\n\n"
            while True:
                row = await database.prepare("SELECT value FROM worker_probe WHERE id='release'").first()
                if row["value"]:
                    break
                await asyncio.sleep(0.02)
            yield b"data: finished\n\n"
        return StreamingResponse(events(), media_type="text/event-stream")

    async def release(request):
        await database.prepare("UPDATE worker_probe SET value=1 WHERE id='release'").run()
        return JSONResponse({"ok": True})

    return Starlette(routes=[
        Route("/count", count, methods=["GET", "POST"]),
        Route("/stream", stream), Route("/release", release, methods=["POST"]),
    ])


if __name__ == "__main__":
    migration_worker(sys.argv[1:])
