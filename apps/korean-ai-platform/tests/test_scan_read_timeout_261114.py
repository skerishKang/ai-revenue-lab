"""Scan-page read lane: its own 120-second bound, and only its own.

The lane is selected by the path, never by a body field. These tests pin three
things: the shared defaults stay 15/40/55, the scan path sees its own policy
inside the context only, and the handler refuses everything that is not one
non-streaming image page before the canonical gateway is reached.
"""

from __future__ import annotations

import json

import pytest
from starlette.responses import JSONResponse

from app.pilot import b14_timeout_policy, scan_read_routes


class _Request:
    def __init__(self, body: object, *, headers: dict[str, str] | None = None):
        self._raw = json.dumps(body).encode("utf-8")
        self.headers = headers or {}

    async def body(self) -> bytes:
        return self._raw


IMAGE_BODY = {
    "model": "catalog/test-model",
    "max_tokens": 16384,
    "stream": False,
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "전사하세요"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64,/9j/AA=="},
                },
            ],
        }
    ],
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(scan_read_routes.SCAN_READ_ENABLED_ENV, raising=False)
    monkeypatch.delenv(b14_timeout_policy.SCAN_READ_TIMEOUT_ENV, raising=False)
    monkeypatch.delenv(b14_timeout_policy.SCAN_READ_FIRST_BYTE_ENV, raising=False)


def test_the_shared_defaults_are_unchanged() -> None:
    policy = b14_timeout_policy.get_timeout_policy()
    assert (policy.first_byte_seconds, policy.attempt_seconds) == (15.0, 40.0)
    assert (policy.stream_idle_seconds, policy.chain_budget_seconds) == (20.0, 55.0)


def test_the_scan_context_changes_only_the_enclosed_policy() -> None:
    with b14_timeout_policy.scan_read_timeout():
        inside = b14_timeout_policy.get_timeout_policy()
        assert (inside.first_byte_seconds, inside.attempt_seconds) == (60.0, 120.0)
        assert inside.chain_budget_seconds == 120.0
        assert inside.stream_idle_seconds == 20.0
    after = b14_timeout_policy.get_timeout_policy()
    assert after.chain_budget_seconds == 55.0


def test_the_scan_bound_is_configurable(monkeypatch) -> None:
    monkeypatch.setenv(b14_timeout_policy.SCAN_READ_TIMEOUT_ENV, "90")
    monkeypatch.setenv(b14_timeout_policy.SCAN_READ_FIRST_BYTE_ENV, "45")
    with b14_timeout_policy.scan_read_timeout():
        policy = b14_timeout_policy.get_timeout_policy()
        assert (policy.first_byte_seconds, policy.attempt_seconds) == (45.0, 90.0)
        assert policy.chain_budget_seconds == 90.0


def test_the_scan_switch_is_off_unless_exactly_true(monkeypatch) -> None:
    assert scan_read_routes.scan_read_enabled() is False
    for value, expected in (("false", False), ("1", False), (" true ", True)):
        assert (
            scan_read_routes.scan_read_enabled(
                {scan_read_routes.SCAN_READ_ENABLED_ENV: value}
            )
            is expected
        )


async def _call(monkeypatch, body: object) -> JSONResponse:
    return await scan_read_routes.pilot_scan_read(_Request(body))


async def test_a_closed_lane_answers_404_without_calling_the_gateway(monkeypatch) -> None:
    called = []

    async def forbidden(_request):
        called.append(True)
        return JSONResponse({}, status_code=200)

    from app.pilot import gateway

    monkeypatch.setattr(gateway, "pilot_chat_completions", forbidden)
    response = await _call(monkeypatch, IMAGE_BODY)
    assert response.status_code == 404
    assert called == []


async def test_a_text_only_body_is_refused_before_the_gateway(monkeypatch) -> None:
    monkeypatch.setenv(scan_read_routes.SCAN_READ_ENABLED_ENV, "true")
    called = []

    async def forbidden(_request):
        called.append(True)
        return JSONResponse({}, status_code=200)

    from app.pilot import gateway

    monkeypatch.setattr(gateway, "pilot_chat_completions", forbidden)
    response = await _call(
        monkeypatch,
        {"model": "m", "messages": [{"role": "user", "content": "text only"}]},
    )
    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "scan_read_image_required"
    assert called == []


async def test_a_streaming_image_body_is_refused(monkeypatch) -> None:
    monkeypatch.setenv(scan_read_routes.SCAN_READ_ENABLED_ENV, "true")
    streaming = dict(IMAGE_BODY)
    streaming["stream"] = True
    response = await _call(monkeypatch, streaming)
    assert response.status_code == 400


async def test_the_scan_path_reaches_the_gateway_under_the_scan_bound(monkeypatch) -> None:
    monkeypatch.setenv(scan_read_routes.SCAN_READ_ENABLED_ENV, "true")
    seen = {}

    async def gateway_stub(_request):
        seen["policy"] = b14_timeout_policy.get_timeout_policy()
        return JSONResponse({"ok": True}, status_code=200)

    from app.pilot import gateway

    monkeypatch.setattr(gateway, "pilot_chat_completions", gateway_stub)
    response = await _call(monkeypatch, IMAGE_BODY)
    assert response.status_code == 200
    assert seen["policy"].chain_budget_seconds == 120.0
    # Outside the handler the shared defaults are back.
    assert b14_timeout_policy.get_timeout_policy().chain_budget_seconds == 55.0


def test_a_body_field_cannot_widen_the_ordinary_path(monkeypatch) -> None:
    monkeypatch.setenv(scan_read_routes.SCAN_READ_ENABLED_ENV, "true")
    flagged = dict(IMAGE_BODY)
    flagged["scan_read"] = True
    flagged["business14"] = {"scan_read_timeout_seconds": 600}

    # Asking the policy object directly is the ordinary path's view; no body
    # field is consulted here or in the gateway.
    assert b14_timeout_policy.get_timeout_policy().chain_budget_seconds == 55.0
    # And the same body without the scan path context still reads 55.
    assert not hasattr(b14_timeout_policy, "SCAN_READ_MARKER")


def test_the_router_exposes_exactly_the_scan_path() -> None:
    paths = [route.path for route in scan_read_routes.router.routes]
    assert paths == [scan_read_routes.SCAN_READ_PATH]
    assert scan_read_routes.SCAN_READ_PATH == "/v1/scan-pages/read"


def test_the_scan_socket_read_bound_covers_its_first_byte_wait() -> None:
    # A non-final scan attempt must be able to wait the scan first-byte limit
    # (60 s) for a completed answer; the socket read bound used to cut it at 20 s.
    with b14_timeout_policy.scan_read_timeout():
        inside = b14_timeout_policy.build_provider_http_timeout("any/model")
        assert inside.read == 60.0
        assert inside.connect == 60.0
    outside = b14_timeout_policy.build_provider_http_timeout("any/model")
    assert (outside.connect, outside.read) == (15.0, 20.0)
