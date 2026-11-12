"""One worker process of the #7543 S07 two-process Claw execute check.

Each process builds the real Chat app over the host's SQLite facade on the
SAME database file, signs in as the same synthetic owner and posts one Claw
execute with the same Idempotency-Key. The Engine boundary is a local stand-in
that records every execution in a shared file, so the parent can count how
often the request actually executed. Nothing here opens a network socket.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

BASE = "https://chat.example.test"
OWNER = "usr_" + "7" * 32
SESSION_SECRET = "issue7543-receipt-session-secret-not-a-real-key-0000"
EXECUTE_PATH = "/api/claw/manual-intake/execute"
PAYLOAD = {"content": "두 워커에 동시에 도착한 같은 실행 요청입니다.", "channel": "kakao", "action": "reply"}


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


def make_outcome(answer: str = "worker result"):
    status = MagicMock()
    status.value = "completed"
    projection = MagicMock()
    projection.status = status
    projection.run_id = "run_issue7543"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = answer
    outcome.p01_run_id = "p01_run_issue7543"
    outcome.p01_event_count = 2
    outcome.continuation_ref = None
    outcome.pause_id = None
    outcome.pause_expires_at = None
    outcome.trusted_request = None
    return outcome


async def worker(argv: list[str]) -> None:
    import httpx

    from app.auth import SESSION_COOKIE, create_session_token
    from app.d1_sqlite import SqliteD1, connect
    from app.main import create_app

    database, executions, ready, start = (Path(item) for item in argv[:4])
    key, hold_seconds = argv[4], float(argv[5])

    async def execute(*_args, **_kwargs):
        # O_APPEND makes each line one write, so two processes never interleave.
        with open(executions, "a", encoding="utf-8") as handle:
            handle.write(f"{os.getpid()}\n")
        await asyncio.sleep(hold_seconds)
        return make_outcome(answer=f"executed by {os.getpid()}")

    adapter = MagicMock()
    adapter.execute = execute
    settings = build_settings()
    connection = connect(str(database))
    app = create_app(
        settings, history_store=StubHistory(), d1_binding=SqliteD1(connection, threaded=True)
    )
    app.state.claw_p01_adapter = adapter
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
            response = await client.post(
                EXECUTE_PATH, json=PAYLOAD, headers={"Idempotency-Key": key}
            )
        print(json.dumps({"status": response.status_code, "body": response.text,
                          "pid": os.getpid()}), flush=True)
    finally:
        connection.close()


if __name__ == "__main__":
    asyncio.run(worker(sys.argv[1:]))
