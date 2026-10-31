"""Host streaming and durable idempotency: the two pre-cutover limits.

Load-bearing claims: the Worker's own NDJSON builder is streamed chunk by chunk
(never collected), a broken or abandoned stream closes the Core generator, and
the D1 idempotency surface runs on the host's SQLite file through the same
adapter class the Worker uses — while an unconfigured host keeps failing closed.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from app import local_runtime
from app.idempotency_binding import CloudflareD1IdempotencyAdapter
from app.local_runtime import LocalEngineApp, create_local_app
from app.local_sqlite_d1 import (
    LOCAL_ENGINE_LEDGER_TABLE,
    LocalSqliteD1,
    apply_engine_migrations,
    connect_local_database,
)

# The Worker module is importable only after the local runtime stand-ins exist.
local_runtime.install_worker_shims()

CALLER_ID = "b62-chat-host"
CALLER_SECRET = "engine-host-caller-secret-0123456789"


def _env(**overrides) -> dict[str, str]:
    base = {
        "PADIEM_ENGINE_CPYTHON_HOST": "1",
        "P01_HOST": "127.0.0.1",
        "P01_PORT": "8811",
        "PADIEM_ENGINE_CALLER_ID": CALLER_ID,
        "PADIEM_ENGINE_CALLER_SECRET": CALLER_SECRET,
        "PADIEM_ENGINE_ALLOWED_APPS": "padiem-chat",
        # The durable lanes are composed with the bound Engine services, so the
        # host B14 binding must exist for the replay route to be reachable.
        "PADIEM_ENGINE_LOCAL_B14_ORIGIN": "http://127.0.0.1:8789",
    }
    base.update(overrides)
    return base


def _headers() -> dict[str, str]:
    return {
        "content-type": "application/json",
        "x-padiem-engine-caller": CALLER_ID,
        "x-padiem-engine-credential": CALLER_SECRET,
    }


class _Entry:
    def __init__(self, response) -> None:
        self.response = response
        self.requests = []

    async def fetch(self, request):
        self.requests.append(request)
        return self.response


def _streaming_service(lines, *, produced: list[str], closed: list[bool], fail_after=None):
    class Service:
        async def iter_ndjson(self, prepared):
            del prepared
            try:
                for index, line in enumerate(lines):
                    if fail_after is not None and index == fail_after:
                        raise RuntimeError("core stream failed")
                    produced.append(line)
                    yield line
            finally:
                closed.append(True)

    return Service()


def _worker_stream(lines, *, produced, closed, fail_after=None):
    """Build the NDJSON response with the Worker's own builder."""

    import worker as engine_worker

    service = _streaming_service(
        lines, produced=produced, closed=closed, fail_after=fail_after
    )
    return engine_worker._ndjson_response(service, prepared=None)


async def _drive(app, *, path: str = "/internal/v1/orchestrate/stream", body: bytes = b""):
    sent: list[dict] = []
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "headers": [
            (name.encode("latin-1"), value.encode("latin-1"))
            for name, value in _headers().items()
        ],
        "server": ("127.0.0.1", 8811),
        "client": ("127.0.0.1", 50000),
        "scheme": "http",
    }
    await app(scope, receive, send)
    return sent


async def test_ndjson_lines_are_forwarded_as_the_worker_produces_them():
    produced: list[str] = []
    closed: list[bool] = []
    response = _worker_stream(
        ["one\n", "two\n", "three\n"], produced=produced, closed=closed
    )
    app = LocalEngineApp(entry=_Entry(response), values={})
    seen_at_send: list[int] = []

    async def run():
        sends: list[bytes] = []

        async def send(message):
            if message["type"] == "http.response.body" and message["body"]:
                seen_at_send.append(len(produced))
                sends.append(message["body"])

        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "path": "/internal/v1/orchestrate/stream",
            "raw_path": b"/internal/v1/orchestrate/stream",
            "query_string": b"",
            "headers": [],
            "server": ("127.0.0.1", 8811),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }

        async def receive():
            return {"type": "http.request", "body": b"{}", "more_body": False}

        await app(scope, receive, send)
        return sends

    chunks = await run()
    assert chunks == [b"one\n", b"two\n", b"three\n"]
    # Each chunk was sent while the Core had produced only up to that line: the
    # host never collected the whole response first.
    assert seen_at_send == [1, 2, 3]
    assert closed == [True]


async def test_a_broken_core_stream_closes_the_generator_and_aborts():
    produced: list[str] = []
    closed: list[bool] = []
    response = _worker_stream(
        ["one\n", "two\n"], produced=produced, closed=closed, fail_after=1
    )
    app = LocalEngineApp(entry=_Entry(response), values={})
    sends: list[bytes] = []

    async def send(message):
        if message["type"] == "http.response.body" and message["body"]:
            sends.append(message["body"])

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "path": "/internal/v1/orchestrate/stream",
        "raw_path": b"/internal/v1/orchestrate/stream",
        "query_string": b"",
        "headers": [],
        "server": ("127.0.0.1", 8811),
        "client": ("127.0.0.1", 50000),
        "scheme": "http",
    }

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    with pytest.raises(local_runtime.LocalRuntimeError):
        await app(scope, receive, send)

    assert sends == [b"one\n"]
    assert closed == [True]


async def test_a_failed_send_closes_the_core_generator():
    """A client that goes away stops the Core stream instead of buffering on."""

    produced: list[str] = []
    closed: list[bool] = []
    response = _worker_stream(["first\n", "second\n"], produced=produced, closed=closed)
    app = LocalEngineApp(entry=_Entry(response), values={})

    class FailingSend:
        async def __call__(self, message):
            if message["type"] == "http.response.body" and message["body"]:
                raise ConnectionResetError("client went away")

    async def receive():
        return {"type": "http.request", "body": b"{}", "more_body": False}

    with pytest.raises(ConnectionResetError):
        await app(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "POST",
                "path": "/internal/v1/orchestrate/stream",
                "raw_path": b"/internal/v1/orchestrate/stream",
                "query_string": b"",
                "headers": [],
                "server": ("127.0.0.1", 8811),
                "client": ("127.0.0.1", 50000),
                "scheme": "http",
            },
            receive,
            FailingSend(),
        )
    assert closed == [True]
    assert produced == ["first\n"]


async def test_the_durable_lane_fails_closed_without_a_database(tmp_path):
    """No database means no binding, and the unbound composition answers as before."""

    unbound = create_local_app(_env(PADIEM_ENGINE_LOCAL_B14_ORIGIN=""))
    sent = await _drive(
        unbound,
        path="/internal/v1/idempotency/completed/replay",
        body=json.dumps({"app_id": "padiem-chat"}).encode("utf-8"),
    )
    payload = json.loads(bytes(sent[-1]["body"]).decode("utf-8"))
    assert sent[0]["status"] == 503
    assert payload["error"]["code"] == "idempotency_unavailable"

    assert getattr(unbound.entry.env, "ENGINE_IDEMPOTENCY", None) is None
    with_db = create_local_app(
        _env(PADIEM_ENGINE_LOCAL_DB=str(tmp_path / "engine.sqlite3"))
    )
    assert isinstance(with_db.entry.env.ENGINE_IDEMPOTENCY, LocalSqliteD1)


def test_engine_migrations_apply_once_and_provide_the_idempotency_table(tmp_path):
    path = tmp_path / "engine.sqlite3"
    connection = connect_local_database(path)
    try:
        applied = apply_engine_migrations(connection)
        assert applied >= 13
        assert apply_engine_migrations(connection) == 0
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert "padiem_engine_idempotency" in tables
        assert LOCAL_ENGINE_LEDGER_TABLE in tables
    finally:
        connection.close()


async def test_the_same_idempotency_key_replays_the_completed_result(tmp_path):
    """Worker parity: the same adapter class over the same table shape."""

    connection = connect_local_database(tmp_path / "engine.sqlite3")
    apply_engine_migrations(connection)
    adapter = CloudflareD1IdempotencyAdapter(LocalSqliteD1(connection))

    fingerprint = "a" * 64
    assert (
        await adapter.begin(
            app_id="padiem-chat", idempotency_key="key-1", request_fingerprint=fingerprint
        )
        is None
    )
    await adapter.complete(
        app_id="padiem-chat",
        idempotency_key="key-1",
        request_fingerprint=fingerprint,
        result={"answer": "same answer", "route": {}, "metadata": {}},
    )
    replayed = await adapter.begin(
        app_id="padiem-chat", idempotency_key="key-1", request_fingerprint=fingerprint
    )
    assert replayed is not None
    assert replayed.answer == "same answer"
    # A different request cannot read that result back.
    assert (
        await adapter.read_completed(
            app_id="padiem-chat",
            idempotency_key="key-1",
            request_fingerprint="b" * 64,
        )
        is None
    )
    connection.close()


async def test_a_configured_database_binds_the_idempotency_lane(tmp_path):
    values = _env(PADIEM_ENGINE_LOCAL_DB=str(tmp_path / "engine.sqlite3"))
    app = create_local_app(values)
    sent = await _drive(
        app,
        path="/internal/v1/idempotency/completed/replay",
        body=json.dumps({"app_id": "padiem-chat"}).encode("utf-8"),
    )
    payload = json.loads(bytes(sent[-1]["body"]).decode("utf-8"))
    assert payload["error"]["code"] != "idempotency_unavailable"
