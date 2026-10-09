"""#3554: every canonical B14 model has exact, single, network-free wire dispatch.

This does NOT prove live provider availability, valid credentials, owner entitlement,
or Claw/Engine customer E2E. No real network or secret value is used.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.pilot.model_registry_file import read_registry
from app.pilot.platform import (
    call_platform_chat_completions,
    stream_platform_chat_completions,
)
from app.pilot import platform as adapter
from app.pilot.platform_secrets import get_platform_provider


CANONICAL = read_registry()["models"]
assert CANONICAL


@pytest.fixture
def no_egress_credentials(monkeypatch):
    # Emulate the live provider *request construction* path with no real
    # credentials and a MockTransport replacing every network call.
    monkeypatch.setenv("B14_PROVIDER_MODE", "live")
    monkeypatch.setattr(
        adapter,
        "_request_headers",
        lambda spec, model_id="": {"Content-Type": "application/json"},
    )
    monkeypatch.setattr(
        adapter,
        "resolve_secret",
        lambda spec: (_ for _ in ()).throw(
            AssertionError("real credential lookup forbidden in wire parity test")
        ),
    )


def _assert_wire(request: httpx.Request, model: dict, stream: bool) -> dict:
    spec = get_platform_provider(model["provider_id"])
    assert spec is not None
    assert request.method == "POST"
    assert str(request.url) == spec.base_origin.rstrip("/") + "/chat/completions"
    assert "authorization" not in request.headers
    outgoing = json.loads(request.content)
    assert outgoing["model"] == model["upstream_model"]
    assert outgoing["messages"] == [{"role": "user", "content": "synthetic contract only"}]
    assert "temperature" not in outgoing
    assert "max_tokens" not in outgoing
    assert "reasoning_effort" not in outgoing
    assert ("stream" in outgoing) == stream
    if stream:
        assert outgoing["stream"] is True
    return outgoing


@pytest.mark.asyncio
@pytest.mark.parametrize("model", CANONICAL, ids=lambda m: m["id"])
async def test_canonical_completed_chat_preserves_exact_selected_upstream_once(
    model, no_egress_credentials
):
    calls: list[dict] = []

    async def respond(request):
        calls.append(_assert_wire(request, model, stream=False))
        return httpx.Response(200, json={
            "id": "synthetic-3554",
            "model": model["upstream_model"],
            "choices": [{
                "message": {"role": "assistant", "content": "fixture completed"},
                "finish_reason": "stop",
            }],
        })

    result = await call_platform_chat_completions(
        model_id=model["id"],
        upstream_model=model["upstream_model"],
        platform_provider_id=model["provider_id"],
        provider=model["provider_name"],
        messages=[{"role": "user", "content": "synthetic contract only"}],
        transport=httpx.MockTransport(respond),
    )
    assert len(calls) == 1  # no retries, fallbacks or second model
    assert result["_live"] is True
    assert result["_requested_upstream_model"] == model["upstream_model"]
    assert result["_actual_response_model"] == model["upstream_model"]
    assert result["choices"][0]["message"]["content"] == "fixture completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("model", CANONICAL, ids=lambda m: m["id"])
async def test_canonical_stream_preserves_exact_selected_upstream_and_done_once(
    model, no_egress_credentials
):
    calls: list[dict] = []
    upstream = model["upstream_model"]

    async def respond(request):
        calls.append(_assert_wire(request, model, stream=True))
        msg = json.dumps({
            "id": "synthetic-3554",
            "model": upstream,
            "choices": [{"delta": {"content": "fixture stream"}, "finish_reason": "stop"}],
        })
        sse = f"data: {msg}\n\ndata: [DONE]\n\n"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse.encode("utf-8"),
        )

    events = []
    async for event in stream_platform_chat_completions(
        model_id=model["id"],
        upstream_model=upstream,
        platform_provider_id=model["provider_id"],
        provider=model["provider_name"],
        messages=[{"role": "user", "content": "synthetic contract only"}],
        transport=httpx.MockTransport(respond),
    ):
        events.append(event)

    assert len(calls) == 1
    assert sum(getattr(event, "done", False) for event in events) == 1
    assert any(getattr(event, "delta_content", None) == "fixture stream" for event in events)
