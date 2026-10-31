"""#5015: the real fetch entrypoint retains the refusal code it answers with.

The exporter unit test proves the code survives `make_events`. This one closes
the gap between that function and Production: it calls the real
``worker_identity.Default.fetch`` entrypoint with the Cloudflare ``workers``
runtime surface stubbed - the same canonical pattern as
``test_idempotency_replay_worker_route.py`` - and lets the route build its own
error response through ``worker._json_response``.

It asserts the one thing an operator needs after a failed run: the exported
``http_request`` event for that request id carries the exact code the Engine
answered with, not just ``client_error``.

**Evidence boundary:** this is a local CPython harness proof. The ``workers``
runtime is stubbed and no isolate, Service Binding or Grafana ingestion is
involved, so it is not Production Workers verification. A production claim still
requires a deployed request whose event is read back from the approved log path.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

CALLER_ID = "r2a-test-caller"
CALLER_SECRET = "r2a-test-secret-0123456789abcdef-0123456789abcdef"
ALLOWED_APP = "b62"
REQUEST_ID = "req_5015worker001"


class _FakeResponse:
    def __init__(self, body: Any = None, status: int = 200, headers: Any = None) -> None:
        self.body = body
        self.status = status
        self.headers = headers or {}


class _FakeWorkerEntrypoint:
    def __init__(self, ctx: Any = None, env: Any = None) -> None:
        self.ctx = ctx
        self.env = env


def _workers_stub() -> types.ModuleType:
    module = types.ModuleType("workers")
    module.Request = lambda *args, **kwargs: None  # type: ignore[attr-defined]
    module.Response = _FakeResponse  # type: ignore[attr-defined]
    module.WorkerEntrypoint = _FakeWorkerEntrypoint  # type: ignore[attr-defined]
    return module


@pytest.fixture(scope="module")
def identity_modules():
    saved = {name: sys.modules.get(name) for name in ("workers", "worker", "worker_identity")}
    sys.modules["workers"] = _workers_stub()
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    try:
        identity = importlib.import_module("worker_identity")
        yield importlib.import_module("worker"), identity
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


class _Env:
    def __init__(self, **attrs: Any) -> None:
        self.__dict__.update(attrs)


class _Request:
    def __init__(self, path: str, *, method: str = "POST", body: bytes = b"{}") -> None:
        self.url = f"https://engine.internal{path}"
        self.method = method
        self.headers = {
            "content-type": "application/json",
            "x-request-id": REQUEST_ID,
            "x-padiem-engine-caller": CALLER_ID,
            "x-padiem-engine-credential": CALLER_SECRET,
        }
        self._text = body.decode("utf-8")

    async def text(self) -> str:
        return self._text


def _identity_env(**extra: Any) -> _Env:
    return _Env(
        PADIEM_ENGINE_CALLER_ID=CALLER_ID,
        PADIEM_ENGINE_CALLER_SECRET=CALLER_SECRET,
        PADIEM_ENGINE_ALLOWED_APPS=ALLOWED_APP,
        **extra,
    )


def test_the_real_fetch_entrypoint_reports_the_code_it_answered_with(
    identity_modules, monkeypatch
) -> None:
    _legacy, identity = identity_modules
    import app.stack_telemetry as telemetry
    from app.orchestration_wire import ORCHESTRATE_PATH

    # Spy on the canonical event builder instead of replacing it: the real
    # start/finish trace and the real response path run unmodified, and ctx is
    # None so nothing is exported to the network.
    captured: list[list[dict]] = []
    real_make_events = telemetry.make_events

    def _capture(state, status):
        events = real_make_events(state, status)
        captured.append(events)
        return events

    monkeypatch.setattr(telemetry, "make_events", _capture)

    request = _Request(ORCHESTRATE_PATH, body=json.dumps({"app_id": ALLOWED_APP}).encode("utf-8"))
    response = asyncio.run(identity.Default(ctx=None, env=_identity_env(B14_SERVICE=object())).fetch(request))

    body = json.loads(str(response.body))
    refusal_code = body["error"]["code"]

    # The route refused this request before any B14/model/tool call, and the
    # refusal is a bounded identifier the caller can act on.
    assert response.status == 400, body
    assert refusal_code == "invalid_request"

    assert len(captured) == 1, captured
    events = captured[0]
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "http_request"
    assert event["status"] == 400
    assert event["outcome"] == "client_error"
    # The exact code the Engine answered with, on the same request id.
    assert event["error_code"] == refusal_code
    assert event["request_id"] == REQUEST_ID
    # Content-blind: no message, caller identity or credential in the event.
    assert "message" not in event
    rendered = json.dumps(event, ensure_ascii=False)
    assert CALLER_ID not in rendered
    assert CALLER_SECRET not in rendered
