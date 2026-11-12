"""One worker process of the #7543 S09 two-process PDF→Markdown run check.

Each process builds the real Chat app over the host's SQLite facade on the
SAME database file and the same object directory, signs in as the same
synthetic owner and posts the run request for the same item. The daily
allowance and the converter are local stand-ins that write one line per call
to shared files, so the parent can count how often each actually happened.
The grade lookup is held for a moment so both processes have read the item
before either writes it — the window the real lookups open in production.
Nothing here opens a network socket.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

BASE = "https://chat.example.test"
OWNER = "usr_" + "a" * 32
SESSION_SECRET = "issue7543-run-claim-session-secret-not-a-real-key-00"


class StubHistory:
    """The signed-in session resolver only asks whether a user row exists."""

    async def get_user(self, user_id):
        return SimpleNamespace(id=user_id) if user_id == OWNER else None


def build_settings():
    from app.config import Settings

    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=BASE,
        google_client_id="issue7543.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
        web_provider="off",
    )


def _append(path: Path) -> None:
    # O_APPEND makes each line one write, so two processes never interleave.
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{os.getpid()}\n")


class RecordingAllowance:
    """Stands in for the daily conversion allowance and records every take."""

    def __init__(self, log: Path):
        self._log = log

    async def authorize_conversion(self, *, user_id, grade):
        from app.usage_gate import CONVERSION_BUCKET_TYPE, UsageDecision

        _append(self._log)
        return UsageDecision(
            allowed=True, subject_type="user", bucket_type=CONVERSION_BUCKET_TYPE,
            count=1, limit=10,
        )


async def worker(argv: list[str]) -> None:
    import httpx

    from app import document_convert_routes
    from app import sqlite_settings as sqlite_policy
    from app.auth import SESSION_COOKIE, create_session_token
    from app.d1_sqlite import SqliteD1
    from app.local_r2 import ThreadedLocalDiskR2
    from app.main import create_app

    database, objects, conversions, allowances, ready, start = (
        Path(item) for item in argv[:6]
    )
    item_id, hold_seconds = argv[6], float(argv[7])

    real_convert = document_convert_routes.convert_pdf_to_markdown

    def convert(*args, **kwargs):
        _append(conversions)
        return real_convert(*args, **kwargs)

    async def slow_grade(_request, _user_id):
        # The grade lookup sits between the route's read of the item and its
        # write. Holding it keeps both processes inside that window together.
        await asyncio.sleep(hold_seconds)
        return "free"

    document_convert_routes.convert_pdf_to_markdown = convert
    document_convert_routes._conversion_grade = slow_grade
    document_convert_routes.PDFMD_NEW_WORK_DISABLED = False

    settings = build_settings()
    # Opened the way the host opens it (app.local_cpython): no foreign_keys pragma.
    connection = sqlite3.connect(str(database), isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    sqlite_policy.configure_writer(connection)
    app = create_app(
        settings, history_store=StubHistory(), d1_binding=SqliteD1(connection, threaded=True)
    )
    app.state.workspace_document_store = SimpleNamespace(
        r2_bucket=ThreadedLocalDiskR2(objects)
    )
    app.state.usage_gate = RecordingAllowance(allowances)
    app.state.usage_gate_enforced = True
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE, headers={"Origin": BASE}
        ) as client:
            client.cookies.set(
                SESSION_COOKIE,
                create_session_token(settings, OWNER),
                domain="chat.example.test",
                path="/",
            )
            ready.touch()
            while not start.exists():
                await asyncio.sleep(0.005)
            run = await client.post(f"/api/document-conversions/items/{item_id}/run")
            # Stay alive until the item settles: the winner's conversion is a
            # background task of this process.
            final = None
            for _ in range(400):
                detail = await client.get(f"/api/document-conversions/items/{item_id}")
                final = detail.json()["item"]["status"]
                if final in ("reviewed", "done", "failed"):
                    break
                await asyncio.sleep(0.05)
        print(json.dumps({"status": run.status_code, "final": final, "pid": os.getpid()}),
              flush=True)
    finally:
        connection.close()


if __name__ == "__main__":
    asyncio.run(worker(sys.argv[1:]))
