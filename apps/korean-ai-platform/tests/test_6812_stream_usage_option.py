"""#6812 stage 2: the streaming usage option and its safety paths.

A streamed attempt consumed input tokens the ledger could not see. These tests
pin that the OpenAI-compatible streaming request asks for the usage frame, that
the frame becomes a ledger prompt_tokens, and that a route which rejects the
field still gets its answer.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.pilot import platform as plat
from app.pilot.call_ledger import (
    TOKEN_MEASURED,
    LedgerDraft,
    new_log_id,
    utc_now_iso,
)
from app.pilot.stream_gateway import _ledger_usage
from app.pilot.stream_types import _parse_sse_frame
from app.pilot.stream_usage_option import (
    STREAM_USAGE_OPT_OUT_ENV,
    rejects_stream_usage_option,
    stream_options_payload,
    stream_usage_option_enabled,
)

MODEL_ID = "test-model"
UPSTREAM_MODEL = "test-upstream"
PROVIDER_ID = "test-route"

SSE_OK = (
    b'data: {"id":"r1","model":"m",'
    b'"choices":[{"index":0,"delta":{"content":"ok"},"finish_reason":null}]}\n\n'
    b'data: {"id":"r1","model":"m","choices":[],'
    b'"usage":{"prompt_tokens":11,"completion_tokens":2,"total_tokens":13}}\n\n'
    b"data: [DONE]\n\n"
)


def run(coro):
    return asyncio.run(coro)


class _Spec:
    base_origin = "https://upstream.invalid"
    credential_binding_name = "TEST_CREDENTIAL_BINDING"


async def _no_secret(name: str | None = None) -> None:
    return None


async def _collect(agen):
    collected = []
    async for event in agen:
        collected.append(event)
    return collected


def _wire(monkeypatch, handler):
    """Isolate the streaming lane's own logic from the provider registry."""
    monkeypatch.setattr(plat, "_require_spec", lambda provider_id: _Spec())
    monkeypatch.setattr(plat, "_provider_mode", lambda: "live")
    monkeypatch.setattr(plat, "_require_owner_allowed_live_model", lambda *a, **k: None)
    monkeypatch.setattr(
        plat, "_request_headers",
        lambda spec, model_id=None: {
            "Content-Type": "application/json",
            "Authorization": "Bearer test",
        },
    )
    monkeypatch.setattr("app.pilot.worker_env.load_request_secret", _no_secret)
    return httpx.MockTransport(handler)


def _stream(transport):
    return plat.stream_platform_chat_completions(
        model_id=MODEL_ID,
        upstream_model=UPSTREAM_MODEL,
        provider="test-provider",
        platform_provider_id=PROVIDER_ID,
        messages=[{"role": "user", "content": "안녕"}],
        transport=transport,
    )


# ---------------------------------------------------------------------------
# The option itself
# ---------------------------------------------------------------------------


def test_option_payload_is_the_usage_request() -> None:
    assert stream_options_payload() == {"include_usage": True}


def test_option_is_on_by_default_and_a_route_can_be_excluded(monkeypatch) -> None:
    assert stream_usage_option_enabled(PROVIDER_ID) is True
    assert stream_usage_option_enabled(None) is False
    assert stream_usage_option_enabled("  ") is False

    monkeypatch.setenv(STREAM_USAGE_OPT_OUT_ENV, f"other, {PROVIDER_ID.upper()}")

    assert stream_usage_option_enabled(PROVIDER_ID) is False
    assert stream_usage_option_enabled("other") is False
    assert stream_usage_option_enabled("untouched") is True


def test_only_a_rejection_naming_the_field_is_a_retry_signal() -> None:
    assert rejects_stream_usage_option(b'{"error":"Unsupported parameter: stream_options"}')
    assert rejects_stream_usage_option('{"error":"include_usage is not supported"}')
    assert rejects_stream_usage_option(b'{"error":"rate limited"}') is False
    assert rejects_stream_usage_option(b"") is False
    assert rejects_stream_usage_option(None) is False


# ---------------------------------------------------------------------------
# Request and ledger
# ---------------------------------------------------------------------------


def test_stream_request_asks_for_usage(monkeypatch) -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, content=SSE_OK, headers={"content-type": "text/event-stream"},
        )

    events = run(_collect(_stream(_wire(monkeypatch, handler))))

    assert bodies and bodies[0]["stream"] is True
    assert bodies[0]["stream_options"] == {"include_usage": True}
    assert events


def test_usage_frame_reaches_the_ledger(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=SSE_OK, headers={"content-type": "text/event-stream"},
        )

    events = run(_collect(_stream(_wire(monkeypatch, handler))))

    reported = [event.usage for event in events if event.usage is not None]
    assert reported, "the usage frame must arrive as a usage event"
    assert reported[-1].prompt_tokens == 11

    # The gateway lane records the reported usage, and an observed count keeps
    # its measured source instead of becoming a zero.
    ledger = LedgerDraft(
        log_id=new_log_id(),
        request_id="req-6812",
        endpoint="/api/pilot/v1/chat/completions/stream-preview",
        protocol="chat/completions",
        streaming=True,
        requested_model_id=MODEL_ID,
        started_at=utc_now_iso(),
    )
    attempt = ledger.record_attempt(
        provider="test-provider",
        model_id=MODEL_ID,
        usage=_ledger_usage(reported[-1]),
    )

    assert attempt.prompt_tokens == 11
    assert attempt.completion_tokens == 2
    assert attempt.token_source == TOKEN_MEASURED


def test_usage_only_frame_parses_as_usage() -> None:
    frame = (
        b'data: {"id":"r1","model":"m","choices":[],'
        b'"usage":{"prompt_tokens":7,"completion_tokens":1,"total_tokens":8}}'
    )

    event = _parse_sse_frame(frame, provider="test", model_id=MODEL_ID)

    assert event is not None
    assert event.usage is not None
    assert event.usage.prompt_tokens == 7
    assert event.done is False


# ---------------------------------------------------------------------------
# Safety paths
# ---------------------------------------------------------------------------


def test_excluded_route_sends_no_usage_option(monkeypatch) -> None:
    monkeypatch.setenv(STREAM_USAGE_OPT_OUT_ENV, PROVIDER_ID)
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200, content=SSE_OK, headers={"content-type": "text/event-stream"},
        )

    run(_collect(_stream(_wire(monkeypatch, handler))))

    assert bodies and "stream_options" not in bodies[0]


def test_route_that_rejects_the_option_still_answers(monkeypatch) -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        if len(bodies) == 1:
            return httpx.Response(
                400,
                content=b'{"error":{"message":"Unsupported parameter: stream_options"}}',
                headers={"content-type": "application/json"},
            )
        return httpx.Response(
            200, content=SSE_OK, headers={"content-type": "text/event-stream"},
        )

    events = run(_collect(_stream(_wire(monkeypatch, handler))))

    assert len(bodies) == 2
    assert bodies[0]["stream_options"] == {"include_usage": True}
    assert "stream_options" not in bodies[1]
    assert any(event.delta_content == "ok" for event in events)


def test_unrelated_request_error_is_not_retried(monkeypatch) -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(
            400,
            content=b'{"error":{"message":"context length exceeded"}}',
            headers={"content-type": "application/json"},
        )

    with pytest.raises(Exception):
        run(_collect(_stream(_wire(monkeypatch, handler))))

    assert len(bodies) == 1
