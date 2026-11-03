"""COM2 desktop-secret wire (2026-11-03): the host publishes Chat as a binding.

The Cloudflare entry reads ``PADIEM_CHAT_SERVICE`` as a Service Binding; the
host has only a loopback origin. Without this mapping the desktop / PC-query
tools never registered on COM2, and a plain env string would have registered
them with a ``.fetch`` that does not exist. These tests pin the host stand-in,
its request forwarding, and the registration decision made from env alone.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import types
from contextlib import contextmanager

import pytest

from app import local_runtime as rt

SECRET = "s" * 48
EDGE_SECRET = "e" * 48
BODY = b'{"subject_id":"sub_1","run_id":"run_1","mode":"run_status"}'

#: 2026-11-04 — Chat's edge middleware refuses every forwarded call that does
#: not carry the four ``x-padiem-edge-*`` headers, so the binding now publishes
#: only when this file exists (see ``LocalChatServiceBinding``). The fixture
#: below writes one and hands the path to every env built here.
_EDGE_SECRET_FILE = ""


@pytest.fixture(autouse=True)
def _edge_secret_file(tmp_path, monkeypatch):
    global _EDGE_SECRET_FILE
    f = tmp_path / "com2-edge-secret"
    f.write_text(EDGE_SECRET + "\n", encoding="utf-8")
    f.chmod(0o600)
    _EDGE_SECRET_FILE = str(f)
    monkeypatch.setattr(sys.modules[__name__], "_EDGE_SECRET_FILE", str(f))
    yield str(f)


class _FakeResponse:
    def __init__(self, payload: bytes, status: int = 200) -> None:
        self.content = payload
        self.status_code = status
        self.headers = {"content-type": "application/json"}


class _FakeClient:
    def __init__(self, record: dict, payload: bytes) -> None:
        self._record = record
        self._payload = payload

    async def request(self, method, url, headers=None, content=None):
        self._record.update(
            {"method": method, "url": url, "headers": dict(headers or {}),
             "content": content}
        )
        return _FakeResponse(self._payload)


def _request() -> rt.LocalRequest:
    return rt.LocalRequest(
        "https://padiem-chat.internal/internal/claw/engine-desktop?probe=1",
        method="POST",
        headers={"Content-Type": "application/json",
                 "X-Claw-Engine-Time": "1700000000",
                 "X-Claw-Engine-Proof": "a" * 64},
        body=BODY,
    )


def test_a_loopback_origin_becomes_the_chat_service_binding():
    values = {rt.CHAT_SERVICE_ENV: "http://127.0.0.1:8798",
              rt.CHAT_EDGE_SECRET_FILE_ENV: _EDGE_SECRET_FILE}
    bindings = rt._local_bindings(values)
    assert isinstance(bindings[rt.CHAT_SERVICE_BINDING_NAME], rt.LocalChatServiceBinding)
    # The unchanged Worker code reads this exact name off its env view.
    env = rt._env_view(values)
    assert getattr(env, rt.CHAT_SERVICE_BINDING_NAME) is not None


@pytest.mark.parametrize(
    "origin",
    ["http://chat.example.com:8798", "https://10.0.0.5:8798",
     "http://127.0.0.1", "http://127.0.0.1:8798/path",
     "http://user:pw@127.0.0.1:8798"],
)
def test_a_foreign_or_malformed_origin_leaves_the_binding_absent(origin):
    with pytest.raises(rt.LocalRuntimeError):
        rt.LocalChatServiceBinding(origin)
    assert rt.CHAT_SERVICE_BINDING_NAME not in rt._local_bindings(
        {rt.CHAT_SERVICE_ENV: origin, rt.CHAT_EDGE_SECRET_FILE_ENV: _EDGE_SECRET_FILE}
    )


@pytest.mark.asyncio
async def test_fetch_forwards_the_signed_request_unchanged():
    record: dict = {}
    payload = b'{"ok":true}'
    binding = rt.LocalChatServiceBinding(
        "http://127.0.0.1:8798", client=_FakeClient(record, payload),
        values={rt.CHAT_EDGE_SECRET_FILE_ENV: _EDGE_SECRET_FILE},
    )

    response = await binding.fetch(_request())

    assert record["method"] == "POST"
    assert record["url"] == (
        "http://127.0.0.1:8798/internal/claw/engine-desktop?probe=1"
    )
    assert record["headers"]["x-claw-engine-proof"] == "a" * 64
    # 2026-11-04: the edge middleware on the Chat host refuses unsigned
    # forwards, so the binding adds the four edge headers on top of the
    # Engine-signed headers it forwards.
    for name in ("x-padiem-edge-at", "x-padiem-edge-id",
                 "x-padiem-edge-tls", "x-padiem-edge-proof"):
        assert name in record["headers"], name
    assert record["content"] == BODY
    assert response.status == 200
    assert await response.text() == '{"ok":true}'
    assert (await response.arrayBuffer()).to_py() == payload


@pytest.mark.asyncio
async def test_an_unreachable_chat_raises_one_bounded_reason(monkeypatch):
    class _FailingClient:
        async def request(self, *args, **kwargs):
            raise rt.httpx.ConnectError("down")

    binding = rt.LocalChatServiceBinding(
        "http://127.0.0.1:8798", client=_FailingClient(),
        values={rt.CHAT_EDGE_SECRET_FILE_ENV: _EDGE_SECRET_FILE},
    )
    with pytest.raises(rt.LocalRuntimeError) as caught:
        await binding.fetch(_request())
    assert caught.value.reason == "p01_local_chat_unreachable"


@contextmanager
def _composed_identity():
    saved = {name: sys.modules.get(name) for name in ("workers", "worker", "worker_identity")}
    stub = types.ModuleType("workers")
    stub.Request = rt.LocalRequest
    stub.Response = rt.LocalResponse
    stub.WorkerEntrypoint = rt.WorkerEntrypoint
    sys.modules["workers"] = stub
    for name in ("worker", "worker_identity"):
        sys.modules.pop(name, None)
    try:
        yield importlib.import_module("worker_identity")
    finally:
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _host_env(**overrides) -> dict[str, str]:
    values = {
        rt.B14_ORIGIN_ENV: "http://127.0.0.1:8789",
        rt.B14_PROOF_SECRET_ENV: "b" * 48,
        rt.CHAT_SERVICE_ENV: "http://127.0.0.1:8798",
        rt.CHAT_EDGE_SECRET_FILE_ENV: _EDGE_SECRET_FILE,
        "CLAW_ENGINE_DESKTOP_SECRET": SECRET,
    }
    values.update(overrides)
    return values


def test_env_alone_registers_the_desktop_and_pc_query_tools():
    with _composed_identity() as identity:
        services = asyncio.run(identity._engine_services_for_env(rt._env_view(_host_env())))

    orchestration = services.orchestration
    assert callable(orchestration._desktop_step_driver_factory)
    assert callable(orchestration._pc_query_step_driver_factory)
    resolver = orchestration._tool_binding_resolver
    assert resolver is not None
    claw = resolver("b54-padiem-claw")
    assert claw is not None
    runtime_ids = {entry.runtime_tool_id for entry in claw.registry.entries}
    assert "claw.desktop.capture" in runtime_ids
    assert resolver("padiem-chat") is not None


@pytest.mark.parametrize(
    "missing",
    ["CLAW_ENGINE_DESKTOP_SECRET", rt.CHAT_SERVICE_ENV,
     rt.CHAT_EDGE_SECRET_FILE_ENV],
)
def test_a_missing_half_leaves_the_tools_unregistered(missing):
    values = _host_env()
    del values[missing]
    with _composed_identity() as identity:
        services = asyncio.run(identity._engine_services_for_env(rt._env_view(values)))

    orchestration = services.orchestration
    assert orchestration._desktop_step_driver_factory is None
    assert orchestration._pc_query_step_driver_factory is None


def test_a_short_secret_leaves_the_tools_unregistered():
    with _composed_identity() as identity:
        services = asyncio.run(
            identity._engine_services_for_env(
                rt._env_view(_host_env(**{"CLAW_ENGINE_DESKTOP_SECRET": "s" * 31}))
            )
        )
    assert services.orchestration._desktop_step_driver_factory is None
