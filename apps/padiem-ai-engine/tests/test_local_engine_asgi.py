"""The CPython host entrypoint: same Worker dispatch, host transport only.

Load-bearing claims: the Engine answers its documented health contract without
the Workers runtime, every non-health route still requires the caller identity,
a routable bind is refused, and ``worker.py`` itself is untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import local_runtime
from app.local_runtime import (
    LocalRuntimeError,
    bind_address,
    create_local_app,
    entry_requirements,
)

CALLER_ID = "b62-chat-host"
CALLER_SECRET = "engine-host-caller-secret-0123456789"


def _env(**overrides) -> dict[str, str]:
    base = {
        "PADIEM_ENGINE_CPYTHON_HOST": "1",
        "P01_HOST": "127.0.0.1",
        "P01_PORT": "8811",
        "PADIEM_ENGINE_LOCAL_B14_ORIGIN": "http://127.0.0.1:8789",
    }
    base.update(overrides)
    return base


async def _call(app, method: str, path: str, *, headers=None, body: bytes = b""):
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("latin-1"),
        "query_string": b"",
        "headers": [
            (name.lower().encode("latin-1"), value.encode("latin-1"))
            for name, value in (headers or {}).items()
        ],
        "server": ("127.0.0.1", 8811),
        "client": ("127.0.0.1", 50000),
        "scheme": "http",
    }
    sent: dict[str, object] = {}

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        if message["type"] == "http.response.start":
            sent["status"] = message["status"]
            sent["headers"] = {
                name.decode(): value.decode() for name, value in message["headers"]
            }
        elif message["type"] == "http.response.body":
            sent["body"] = message["body"]

    await app(scope, receive, send)
    return sent


def _payload(sent) -> dict:
    return json.loads(bytes(sent["body"]).decode("utf-8"))


def test_the_entry_needs_an_explicit_host_flag():
    with pytest.raises(LocalRuntimeError) as excinfo:
        entry_requirements({})
    assert "PADIEM_ENGINE_CPYTHON_HOST" in excinfo.value.reason


def test_dev_and_host_flags_cannot_be_combined():
    with pytest.raises(LocalRuntimeError):
        entry_requirements({"PADIEM_LOCAL_DEV": "1", "PADIEM_ENGINE_CPYTHON_HOST": "1"})
    assert entry_requirements({"PADIEM_LOCAL_DEV": "1"}) == "dev"
    assert entry_requirements({"PADIEM_ENGINE_CPYTHON_HOST": "1"}) == "host"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.0.2", "::", "engine.internal"])
def test_a_routable_bind_is_refused(host):
    with pytest.raises(LocalRuntimeError) as excinfo:
        bind_address({"P01_HOST": host, "P01_PORT": "8811"})
    assert excinfo.value.reason == "p01_bind_not_loopback"


def test_the_default_bind_is_loopback_8811():
    assert bind_address({}) == ("127.0.0.1", 8811)
    assert bind_address({"P01_PORT": "18731"}) == ("127.0.0.1", 18731)


def test_a_non_loopback_b14_origin_is_refused():
    with pytest.raises(LocalRuntimeError) as excinfo:
        local_runtime.LocalB14Binding("https://b14.padiem.net")
    assert excinfo.value.reason == "p01_local_b14_origin_invalid"


async def test_health_satisfies_the_packaged_health_contract():
    app = create_local_app(_env())
    sent = await _call(app, "GET", "/internal/v1/health")

    assert sent["status"] == 200
    body = _payload(sent)
    assert body["status"] == "ok"
    assert body["service"] == "padiem-ai-engine"
    assert body["service_identity"] == "required_for_all_non_health_routes"
    assert body["completed_run"] is True
    assert body["streaming_run"] is True


async def test_an_unknown_route_is_not_found():
    app = create_local_app(_env())
    sent = await _call(app, "GET", "/internal/v1/nope")
    assert sent["status"] == 404


async def test_a_deployment_without_a_caller_registry_fails_closed():
    """Same as the Worker: no configured identity is unavailable, not trust."""

    app = create_local_app(_env())
    sent = await _call(
        app,
        "POST",
        "/internal/v1/execute",
        headers={"content-type": "application/json"},
        body=bjson(),
    )
    assert sent["status"] == 503
    assert _payload(sent)["error"]["code"] == "service_identity_unavailable"


async def test_a_configured_caller_without_headers_is_refused():
    app = create_local_app(
        _env(
            PADIEM_ENGINE_CALLER_ID=CALLER_ID,
            PADIEM_ENGINE_CALLER_SECRET=CALLER_SECRET,
            PADIEM_ENGINE_ALLOWED_APPS="padiem-chat",
        )
    )
    sent = await _call(
        app,
        "POST",
        "/internal/v1/execute",
        headers={"content-type": "application/json"},
        body=bjson(),
    )
    assert sent["status"] == 401
    assert _payload(sent)["error"]["code"] == "service_authentication_failed"


async def test_a_configured_caller_passes_the_identity_gate():
    app = create_local_app(
        _env(
            PADIEM_ENGINE_CALLER_ID=CALLER_ID,
            PADIEM_ENGINE_CALLER_SECRET=CALLER_SECRET,
            PADIEM_ENGINE_ALLOWED_APPS="padiem-chat",
        )
    )
    sent = await _call(
        app,
        "POST",
        "/internal/v1/execute",
        headers={
            "content-type": "application/json",
            "x-padiem-engine-caller": CALLER_ID,
            "x-padiem-engine-credential": CALLER_SECRET,
        },
        body=bjson(),
    )
    assert sent["status"] != 401
    assert _payload(sent)["error"]["code"] != "service_authentication_failed"


async def test_a_wrong_credential_is_refused_even_when_the_caller_is_known():
    app = create_local_app(
        _env(
            PADIEM_ENGINE_CALLER_ID=CALLER_ID,
            PADIEM_ENGINE_CALLER_SECRET=CALLER_SECRET,
            PADIEM_ENGINE_ALLOWED_APPS="padiem-chat",
        )
    )
    sent = await _call(
        app,
        "POST",
        "/internal/v1/execute",
        headers={
            "content-type": "application/json",
            "x-padiem-engine-caller": CALLER_ID,
            "x-padiem-engine-credential": "x" * 64,
        },
        body=bjson(),
    )
    assert sent["status"] == 401


async def test_a_streaming_route_is_refused_rather_than_buffered():
    app = create_local_app(
        _env(
            PADIEM_ENGINE_CALLER_ID=CALLER_ID,
            PADIEM_ENGINE_CALLER_SECRET=CALLER_SECRET,
            PADIEM_ENGINE_ALLOWED_APPS="padiem-chat",
        )
    )
    sent = await _call(
        app,
        "POST",
        "/internal/v1/orchestrate/stream",
        headers={
            "content-type": "application/json",
            "x-padiem-engine-caller": CALLER_ID,
            "x-padiem-engine-credential": CALLER_SECRET,
        },
        body=bjson(),
    )
    assert sent["status"] in {400, 401, 422, 503}


async def test_lifespan_startup_is_answered():
    app = create_local_app(_env())
    messages = [
        {"type": "lifespan.startup"},
        {"type": "lifespan.shutdown"},
    ]
    sent: list[dict] = []

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    await app({"type": "lifespan"}, receive, send)
    assert [message["type"] for message in sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]


def test_the_worker_entrypoint_is_untouched():
    """The host door must not move the Cloudflare entrypoint's behaviour."""

    worker_source = (Path(__file__).resolve().parents[1] / "worker.py").read_text(
        encoding="utf-8"
    )
    assert "local_runtime" not in worker_source
    assert "asgi" not in worker_source


def bjson() -> bytes:
    return json.dumps(
        {
            "app_id": "padiem-chat",
            "agent": {"id": "agent:padiem:chat@1"},
            "messages": [{"role": "user", "content": "host entry probe"}],
        }
    ).encode("utf-8")
