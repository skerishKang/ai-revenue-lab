"""#7430: the owner-tier plain surface rides the native adapter first.

The compatible endpoint behind the plain wire was the lane that degraded
(503/500/timeout/malformed) while the native streamGenerateContent adapter kept
answering, so the product chat surface waited out three failing candidates for
an outage it could ride through. This suite pins the new order and its limits:

* a tool-less owner-tier turn leaves on the native wire first;
* a pre-byte native failure earns exactly one compatible retry on the SAME
  candidate before the owner-tier chain walks its next candidate;
* a failure after the first byte never rewrites the wire mid-answer;
* a declared-tools turn keeps today's exact behavior (no compatible retry).

Network-free: TestClient -> auto-stream gateway -> streaming router ->
platform adapter -> httpx.MockTransport; no credential is spent and no provider
is reached. Every model identity comes from the effective registry document.
"""
from __future__ import annotations

import json

import httpx
import pytest
from starlette.testclient import TestClient

from app.factory import create_app
from app.pilot import google_provider
from app.pilot.b14_runtime_config import runtime_config as rcfg
from app.pilot.tool_channel import TOOL_CAPABILITY

from _pilot_lane_paths import chat_surface
from _registry_values import (
    model_rows, provider_of, provider_row, requires_owner_document,
)

pytestmark = requires_owner_document

URL = chat_surface() + "/stream-preview"


def _native_family_rows():
    rows = [
        row for row in model_rows()
        if row.get("provider_id") == google_provider.GOOGLE_PROVIDER_ID
        and row.get("enabled", True)
    ]
    assert rows, "the native family must have catalog rows"
    return rows


def _binding(model_id: str) -> str:
    return provider_row(provider_of(model_id))["credential_binding_name"]


def _free_chain() -> tuple[str, list[str]]:
    from app.pilot.model_registry_file import private_registry_snapshot

    snap = private_registry_snapshot()
    tier = snap.registry.tiers["free"]
    return tier["primary"], list(tier["fallback"])


def _native_url(model_id: str, upstream_model: str) -> str:
    origin = provider_row(provider_of(model_id))["base_origin"]
    host = origin.split("/")[2]
    version = origin.rstrip("/").rsplit("/v", 1)[-1].split("/", 1)[0]
    return f"https://{host}/v{version}/models/{upstream_model}:streamGenerateContent?alt=sse"


def _compat_url(model_id: str) -> str:
    origin = provider_row(provider_of(model_id))["base_origin"]
    return origin.rstrip("/") + "/chat/completions"


def _native_frame(parts=None, *, finish=None) -> bytes:
    candidate = {"index": 0, "content": {"role": "model", "parts": parts or []}}
    if finish is not None:
        candidate["finishReason"] = finish
    payload = {
        "responseId": "native_7430",
        "modelVersion": "upstream-7430",
        "candidates": [candidate],
    }
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode()


def _compat_frame(content, *, finish=None) -> str:
    data = {
        "id": "compat_7430",
        "model": "upstream-7430",
        "choices": [{
            "index": 0,
            "delta": {"content": content} if content is not None else {},
            "finish_reason": finish,
        }],
    }
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


class _BreakAfterFirst(httpx.AsyncByteStream):
    """One delivered frame, then the connection itself breaks."""

    def __init__(self, first: bytes):
        self.first = first

    async def __aiter__(self):
        yield self.first
        raise httpx.ReadError("mid-stream break")


@pytest.fixture
def live_native_family(monkeypatch):
    primary, fallbacks = _free_chain()
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    for model_id in {primary, *fallbacks}:
        monkeypatch.setenv(_binding(model_id), "synthetic-local-only-7430-not-a-credential")
    old_mode = rcfg.provider_mode
    rcfg.provider_mode = "live"
    try:
        yield {"primary": primary, "fallbacks": fallbacks}
    finally:
        rcfg.provider_mode = old_mode


def _post(payload, transport) -> TestClient.response:  # type: ignore[valid-type]
    app = create_app()
    app.state.stream_transport = transport
    with TestClient(app) as client:
        return client.post(URL, json=payload)


def test_plain_owner_tier_turn_leaves_on_the_native_wire_first(live_native_family) -> None:
    primary = live_native_family["primary"]
    upstream = next(r["upstream_model"] for r in _native_family_rows()
                    if r["id"] == primary)
    urls = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_native_frame([{"text": "네 정상입니다"}], finish="STOP"),
        )

    response = _post(
        {"model": primary, "messages": [{"role": "user", "content": "한 문장으로 답해"}],
         "stream": True},
        httpx.MockTransport(respond),
    )

    assert response.status_code == 200, response.text
    assert "네 정상입니다" in response.text
    assert len(urls) == 1, urls
    assert ":streamGenerateContent" in urls[0]
    assert "/chat/completions" not in urls[0]
    assert upstream in urls[0]


def test_native_prebyte_failure_earns_exactly_one_compatible_retry(live_native_family) -> None:
    primary = live_native_family["primary"]
    upstream = next(r["upstream_model"] for r in _native_family_rows()
                    if r["id"] == primary)
    urls = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        if ":streamGenerateContent" in str(request.url):
            return httpx.Response(503, json={"error": {"code": "unavailable"}})
        wire = _compat_frame("호환 응답") + _compat_frame(None, finish="stop") + "data: [DONE]\n\n"
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=wire.encode(),
        )

    response = _post(
        {"model": primary, "messages": [{"role": "user", "content": "한 문장으로 답해"}],
         "stream": True},
        httpx.MockTransport(respond),
    )

    assert response.status_code == 200, response.text
    assert "호환 응답" in response.text
    assert urls == [_native_url(primary, upstream), _compat_url(primary)], urls


def test_prebyte_failures_walk_the_owner_tier_chain_then_surface_the_error(
    live_native_family,
) -> None:
    primary, fallbacks = _free_chain()
    urls = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(503, json={"error": {"code": "unavailable"}})

    response = _post(
        {"model": primary, "messages": [{"role": "user", "content": "한 문장으로 답해"}],
         "stream": True},
        httpx.MockTransport(respond),
    )

    assert response.status_code != 200
    # The chain walks primary -> fallbacks, and every attempt pairs the native
    # first byte with exactly one compatible retry: never two native or two
    # compatible calls in a row for the same candidate.
    for native, compat in zip(urls[::2], urls[1::2]):
        assert ":streamGenerateContent" in native
        assert "/chat/completions" in compat
    tried_models = {u.split("/models/")[-1].split(":")[0] for u in urls
                    if "/models/" in u}
    if urls[0].count("/models/"):
        tried_models |= {u.split("/chat/completions")[0].rsplit("/", 1)[-1]
                         for u in urls if "/chat/completions" in u}
    assert len(urls) >= 2 * (1 + len(fallbacks)), urls
    assert tried_models, "the chain must have left request evidence"


def test_post_first_byte_failure_keeps_the_no_fallback_contract(live_native_family) -> None:
    primary = live_native_family["primary"]
    urls = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_BreakAfterFirst(_native_frame([{"text": "첫 바이트"}])),
        )

    response = _post(
        {"model": primary, "messages": [{"role": "user", "content": "한 문장으로 답해"}],
         "stream": True},
        httpx.MockTransport(respond),
    )

    assert len(urls) == 1, "a mid-stream break must not earn a second wire"
    assert response.status_code == 200
    assert "event: error" in response.text
    assert "호환" not in response.text


def test_a_tools_turn_keeps_the_existing_native_behavior(live_native_family) -> None:
    tool_rows = [r for r in _native_family_rows()
                 if TOOL_CAPABILITY in r.get("capabilities", [])]
    assert tool_rows, "the native family must keep a tools-capable row"
    model_id = tool_rows[0]["id"]
    declaration = {"type": "function", "function": {
        "name": "pc_files", "description": "Inspect the requested PC scope.",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                       "required": ["path"]},
    }}
    urls = []

    def respond(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(503, json={"error": {"code": "unavailable"}})

    response = _post(
        {"model": model_id, "messages": [{"role": "user", "content": "파일을 찾아"}],
         "tools": [declaration], "stream": True},
        httpx.MockTransport(respond),
    )

    # Existing contract: the declared-tools turn never earns the compatible
    # same-candidate retry — the owner-tier chain walks on the native wire only.
    assert urls, urls
    assert all("/chat/completions" not in u for u in urls), urls
    assert all(":streamGenerateContent" in u for u in urls), urls
    assert response.status_code != 200
