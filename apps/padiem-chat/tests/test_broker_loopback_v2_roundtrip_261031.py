"""The Chat COM2 broker loopback and the real broker ingress, in one process.

The sender is the exact class the COM2 gateway composes for port 8799; the
receiver is the broker's own ASGI application (apps/padiem-broker/service.py),
including its proof door and its request-id memory. Only the transport is
in-process, so a change to either side of the contract shows up here.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import time
from pathlib import Path

import httpx
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
for _path in (
    _REPO_ROOT / "apps" / "padiem-broker",
    _REPO_ROOT / "packages" / "padiem-control-plane",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import service as broker_service  # noqa: E402

from app.com2_connector_websocket import LoopbackRpcBinding, _BROKER_METHODS  # noqa: E402

SECRET = "chat-broker-loopback-secret-0123456789"
PEPPER = "broker-pepper-0123456789abcdef0123456789"
AUTHORITY = "control-plane.local-agent-broker.chat-roundtrip.v1"
METHOD = "get_enrollment_binding"
PATH = "/internal/rpc/" + METHOD
PAYLOAD = {"challenge_id": "synthetic.challenge.1"}
BODY = json.dumps(PAYLOAD, separators=(",", ":")).encode()


class _Recording:
    """Forward to the broker's ASGI app and keep exactly what was sent."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self.sent: list[tuple[httpx.Request, int]] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        self.sent.append((request, response.status_code))
        return response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return None

    async def aclose(self) -> None:
        await self._inner.aclose()


def _app(tmp_path: Path, **overrides: str):
    env = {
        "PADIEM_BROKER_RPC_INGRESS_SECRET": SECRET,
        "LOCAL_AGENT_BROKER_PEPPER": PEPPER,
        "LOCAL_AGENT_BROKER_AUTHORITY_REF": AUTHORITY,
        "PADIEM_BROKER_DB_PATH": str(tmp_path / "broker.sqlite3"),
    }
    env.update(overrides)
    return broker_service.build_app(environ=env)


def _v1_headers(at: int | None = None) -> dict[str, str]:
    at = int(time.time()) if at is None else at
    signed = b"\n".join((b"v1", b"POST", PATH.encode(), str(at).encode(), BODY))
    return {
        "content-type": "application/json",
        "x-padiem-service-at": str(at),
        "x-padiem-service-proof": "v1="
        + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest(),
    }


def _v2_proof(request: httpx.Request, service_id: str) -> str:
    signed = b"\n".join(
        (
            b"v2",
            b"POST",
            request.url.path.encode("utf-8"),
            request.headers["x-padiem-service-at"].encode("ascii"),
            service_id.encode("utf-8"),
            request.content,
        )
    )
    return "v2=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_a_loopback_call_is_served_with_a_signed_v2_id(tmp_path):
    recorder = _Recording(httpx.ASGITransport(app=_app(tmp_path)))
    async with httpx.AsyncClient(
        transport=recorder, base_url="http://127.0.0.1:8799"
    ) as client:
        binding = LoopbackRpcBinding(
            port=8799, secret=SECRET, methods=_BROKER_METHODS, client=client
        )
        answer = await binding.get_enrollment_binding(PAYLOAD)

    assert isinstance(answer, dict)
    assert len(recorder.sent) == 1
    request, status = recorder.sent[0]
    assert status == 200
    service_id = request.headers["x-padiem-service-id"]
    assert len(service_id) >= 16
    assert request.headers["x-padiem-service-proof"] == _v2_proof(request, service_id)


@pytest.mark.asyncio
async def test_replaying_the_captured_id_is_refused_and_a_new_call_is_served(tmp_path):
    recorder = _Recording(httpx.ASGITransport(app=_app(tmp_path)))
    async with httpx.AsyncClient(
        transport=recorder, base_url="http://127.0.0.1:8799"
    ) as client:
        binding = LoopbackRpcBinding(
            port=8799, secret=SECRET, methods=_BROKER_METHODS, client=client
        )
        await binding.get_enrollment_binding(PAYLOAD)
        request, status = recorder.sent[0]
        assert status == 200

        # The exact bytes and headers, including the consumed id.
        replay = await client.post(
            request.url.path, content=request.content, headers=dict(request.headers)
        )
        # The same call through the binding names itself again and is served.
        fresh = await binding.get_enrollment_binding(PAYLOAD)

    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "rpc_replay_detected"
    assert isinstance(fresh, dict)
    # served call, refused replay, served call under a new id.
    assert [status for _, status in recorder.sent] == [200, 409, 200]


@pytest.mark.asyncio
async def test_a_v1_request_follows_the_configured_policy(tmp_path):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(tmp_path)), base_url="http://127.0.0.1:8799"
    ) as client:
        optional = await client.post(PATH, content=BODY, headers=_v1_headers())

    required_app = _app(
        tmp_path,
        PADIEM_BROKER_DB_PATH=str(tmp_path / "required.sqlite3"),
        PADIEM_RPC_SERVICE_ID_POLICY="required",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=required_app), base_url="http://127.0.0.1:8799"
    ) as client:
        required = await client.post(PATH, content=BODY, headers=_v1_headers())

    assert optional.status_code == 200
    assert required.status_code == 403
    assert required.json()["error"]["code"] == "rpc_service_id_required"


def test_the_composed_broker_loopback_stays_on_the_signed_id():
    # The round trip above proves the class; this pins the host composition,
    # which is the one line that decides whether the lane signs at all.
    source = (
        _REPO_ROOT / "apps" / "padiem-chat" / "app" / "local_cpython.py"
    ).read_text(encoding="utf-8")
    assert "sign_request_id=False" not in source
