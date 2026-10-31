"""Local cold-start analog for the Chat Worker (#6346-class measurement).

One fresh subprocess per run: stub the Workers runtime, time the entry import
(the isolate-load analog), build the app the test way, then time the FIRST
ASGI request of each light path. Not a production number — the relative
before/after comparison is the point.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
import time
import types

sys.path.insert(0, str(Path(__file__).resolve().parent / "apps" / "padiem-chat"))


def _build():
    from app.config import Settings

    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.local",
        google_client_id="unit-test-client.apps.googleusercontent.com",
        google_client_secret="unit-test-secret",
        session_secret="cold-import-measure-secret-000000000000",
        session_max_age_seconds=3600,
    )
    from app.main import create_app

    return create_app(settings=settings)


async def _first_call(app, path):
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "https", "path": path, "raw_path": path.encode(),
        "query_string": b"", "headers": [(b"host", b"chat.local")],
        "client": ("127.0.0.1", 1), "server": ("chat.local", 443),
    }
    status = {"v": None}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            status["v"] = message["status"]

    started = time.perf_counter()
    await app(scope, receive, send)
    return time.perf_counter() - started, status["v"]


def main() -> None:
    stub = types.ModuleType("workers")
    stub.Request = object

    class _Response:
        def __init__(self, body="", *, status=200, headers=None):
            self.body, self.status = body, status
            self.headers = dict(headers or {})

    class _WorkerEntrypoint:
        def __init__(self, env=None, ctx=None):
            self.env, self.ctx = env, ctx

    stub.Response = _Response
    stub.WorkerEntrypoint = _WorkerEntrypoint
    sys.modules["workers"] = stub

    started = time.perf_counter()
    import worker  # noqa: F401  (the isolate-load analog)

    import_done = time.perf_counter()
    app = _build()
    build_done = time.perf_counter()

    async def run():
        out = {}
        for path in ("/health", "/api/auth/status", "/api/files/capabilities"):
            elapsed, status = await _first_call(app, path)
            out[path] = {"ms": round(elapsed * 1000, 1), "status": status}
        return out

    first = asyncio.run(run())
    print(json.dumps({
        "import_worker_ms": round((import_done - started) * 1000, 1),
        "build_app_ms": round((build_done - import_done) * 1000, 1),
        "first_requests": first,
    }))


if __name__ == "__main__":
    main()
