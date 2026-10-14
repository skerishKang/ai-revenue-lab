"""Focused negative tests: OpenCode Go SSE/completed error boundaries (#4416).

MockTransport only, synthetic safe content, five exact OFF models untouched
(registry OFF gate bypassed by monkeypatched test seam, exactly like the
existing wire tests). No live provider call, no activation, no B54/P01
touch. Every malformed shape must surface as a bounded pilot error — never
an unbounded AttributeError, never a false success.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.pilot import opencode_go_wire as go
from app.pilot.errors import (
    MalformedUpstreamResponse,
    UpstreamResponseTooLarge,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.upstream_answer_contract import UpstreamEmptyAnswer

SESSION = "chat_0123456789abcdef0123456789abcdef"
TURNS = [{"role": "user", "content": "Write a Python function."}]


@pytest.fixture()
def live_wire(monkeypatch):
    """Bypass OFF registry + secrets exactly like existing wire tests."""

    monkeypatch.setattr(go, "_authorization_gate", lambda *_: None)

    async def synthetic_auth(h, wire):
        if wire == "messages":
            return {**h, "x-api-key": "synthetic-test-credential"}
        return {**h, "Authorization": "Bearer synthetic-test-credential"}

    monkeypatch.setattr(go, "_authenticated_headers", synthetic_auth)


def _sse_transport(content: bytes):
    return httpx.MockTransport(
        lambda req: httpx.Response(
            200, content=content, headers={"Content-Type": "text/event-stream"}
        )
    )


def _frame(event: str, data) -> bytes:
    if isinstance(data, str):
        raw = data
    else:
        raw = json.dumps(data)
    return f"event: {event}\ndata: {raw}\n\n".encode()


def _chat_delta(content: str) -> bytes:
    return (
        b'data: {"choices":[{"delta":{"content":"'
        + content.encode()
        + b'"},"finish_reason":null}]}\n\n'
    )


async def _collect(agen):
    return [e async for e in agen]


def _stream_kwargs(name, **over):
    kw = dict(
        model_id="opencode-go/" + name,
        upstream_model=name,
        messages=TURNS,
        session_id=SESSION,
        max_tokens=32,
    )
    kw.update(over)
    return kw


# --------------------------------------------------------------------------
# Real defects: non-dict shapes must raise bounded errors, not AttributeError.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_stream_non_dict_choice_is_bounded(live_wire) -> None:
    body = b'data: {"choices":["not-a-dict"]}\n\ndata: [DONE]\n\n'
    with pytest.raises(MalformedUpstreamResponse):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("longcat-2.5-preview-free"),
                transport=_sse_transport(body),
            )
        )


@pytest.mark.asyncio
async def test_chat_stream_non_dict_delta_is_bounded(live_wire) -> None:
    body = b'data: {"choices":[{"delta":"not-a-dict"}]}\n\ndata: [DONE]\n\n'
    with pytest.raises(MalformedUpstreamResponse):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("step-5-preview-free"),
                transport=_sse_transport(body),
            )
        )


@pytest.mark.asyncio
async def test_messages_stream_non_dict_delta_is_bounded(live_wire) -> None:
    body = _frame("message_delta", {"type": "message_delta", "delta": "nope"})
    with pytest.raises(MalformedUpstreamResponse):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("claude-haiku-5-5", max_tokens=16),
                transport=_sse_transport(body),
            )
        )


# --------------------------------------------------------------------------
# Wrong model id, malformed frames, truncation: fail closed, no false DONE.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_wrong_response_model_is_failure_not_fallback(live_wire) -> None:
    body = b'data: {"model":"some-other-model","choices":[{"delta":{"content":"Hi"}}]}\n\ndata: [DONE]\n\n'
    with pytest.raises(MalformedUpstreamResponse):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("longcat-2.5-preview-free"),
                transport=_sse_transport(body),
            )
        )


@pytest.mark.asyncio
async def test_stream_malformed_json_frame_is_bounded(live_wire) -> None:
    body = b"data: {not-json\n\n"
    with pytest.raises(MalformedUpstreamResponse):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("step-5-preview-free"),
                transport=_sse_transport(body),
            )
        )


@pytest.mark.asyncio
async def test_stream_truncated_without_terminal_is_bounded(live_wire) -> None:
    body = _chat_delta("Hi")  # text but no DONE / terminal event
    with pytest.raises(MalformedUpstreamResponse):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("longcat-2.5-preview-free"),
                transport=_sse_transport(body),
            )
        )


@pytest.mark.asyncio
async def test_stream_done_without_text_is_empty_not_success(live_wire) -> None:
    body = b"data: [DONE]\n\n"
    with pytest.raises(UpstreamEmptyAnswer):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("step-5-preview-free"),
                transport=_sse_transport(body),
            )
        )


@pytest.mark.asyncio
async def test_stream_whitespace_only_then_done_is_empty(live_wire) -> None:
    body = _chat_delta("   ") + b"data: [DONE]\n\n"
    with pytest.raises(UpstreamEmptyAnswer):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("longcat-2.5-preview-free"),
                transport=_sse_transport(body),
            )
        )


@pytest.mark.asyncio
async def test_stream_upstream_error_frame_is_bounded(live_wire) -> None:
    body = _frame(
        "message_delta",
        {"type": "error", "error": {"code": "overloaded_error"}},
    )
    with pytest.raises(MalformedUpstreamResponse):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("claude-haiku-5-5", max_tokens=16),
                transport=_sse_transport(body),
            )
        )


@pytest.mark.asyncio
async def test_stream_responses_failed_is_bounded(live_wire) -> None:
    body = _frame("response.failed", {"type": "response.failed"})
    with pytest.raises(MalformedUpstreamResponse):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("muse-spark-1.3-contributor"),
                transport=_sse_transport(body),
            )
        )


# --------------------------------------------------------------------------
# Transport boundaries: timeout vs server error vs client cancellation.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_provider_timeout_is_timeout_not_server_error(
    live_wire,
) -> None:
    def handle(req):
        raise httpx.ConnectTimeout("synthetic connect timeout")

    with pytest.raises(UpstreamTimeout):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("longcat-2.5-preview-free"),
                transport=httpx.MockTransport(handle),
            )
        )


@pytest.mark.asyncio
async def test_stream_transport_error_is_server_error(live_wire) -> None:
    def handle(req):
        raise httpx.ConnectError("synthetic connect error")

    with pytest.raises(UpstreamServerError):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("step-5-preview-free"),
                transport=httpx.MockTransport(handle),
            )
        )


@pytest.mark.asyncio
async def test_stream_client_cancellation_is_not_converted_to_done(
    live_wire,
) -> None:
    body = _chat_delta("Hi")  # stream stays open; client cancels mid-flight
    gen = go.stream_go_model(
        **_stream_kwargs("longcat-2.5-preview-free"),
        transport=_sse_transport(body),
    )
    first = await gen.__anext__()
    assert (first.delta_content or "") == "Hi"
    with pytest.raises(asyncio.CancelledError):
        await gen.athrow(asyncio.CancelledError())
    await gen.aclose()


@pytest.mark.asyncio
async def test_stream_single_frame_resource_cap_is_enforced(live_wire) -> None:
    from app.pilot import platform as plat

    # Resource guard is per unfinished/individual event, not total model text.
    body = b"data: " + b"x" * (plat.MAX_RESPONSE_BYTES + 1) + b"\n\n"
    with pytest.raises(UpstreamResponseTooLarge):
        await _collect(
            go.stream_go_model(
                **_stream_kwargs("step-5-preview-free"),
                transport=_sse_transport(body),
            )
        )



@pytest.mark.asyncio
async def test_coalesced_healthy_chat_events_over_1mib_are_not_rejected(live_wire) -> None:
    """One HTTP block can contain >1MiB of *valid* small events."""
    from app.pilot import platform as plat

    frame = _chat_delta("G" * 900)
    count = plat.MAX_RESPONSE_BYTES // len(frame) + 5
    body = frame * count + b"data: [DONE]\n\n"
    assert len(body) > plat.MAX_RESPONSE_BYTES
    seen = []
    def handle(request):
        seen.append(request)
        return httpx.Response(200, content=body, headers={"Content-Type": "text/event-stream"})
    events = await _collect(go.stream_go_model(
        **_stream_kwargs("longcat-2.5-preview-free"),
        transport=httpx.MockTransport(handle),
    ))
    assert len(seen) == 1
    assert len([event for event in events if event.delta_content]) == count
    assert events[-1].done is True


@pytest.mark.asyncio
async def test_responses_healthy_coalesced_events_over_1mib_are_not_rejected(live_wire) -> None:
    from app.pilot import platform as plat

    frame = _frame("response.output_text.delta",
                   {"type": "response.output_text.delta", "delta": "R" * 900})
    count = plat.MAX_RESPONSE_BYTES // len(frame) + 4
    done = _frame("response.completed",
                  {"type": "response.completed",
                   "response": {"status": "completed", "model": "muse-spark-1.2-contributor"}})
    body = frame * count + done
    assert len(body) > plat.MAX_RESPONSE_BYTES
    events = await _collect(go.stream_go_model(
        **_stream_kwargs("muse-spark-1.2-contributor"),
        transport=_sse_transport(body),
    ))
    assert len([event for event in events if event.delta_content]) == count
    assert events[-1].done is True


@pytest.mark.asyncio
async def test_long_single_valid_sse_frame_under_resource_cap_crosses_chunks(live_wire) -> None:
    body = _chat_delta("Z" * (70 * 1024)) + b"data: [DONE]\n\n"
    events = await _collect(go.stream_go_model(
        **_stream_kwargs("step-5-preview-free"),
        transport=_sse_transport(body),
    ))
    assert events[0].delta_content == "Z" * (70 * 1024)
    assert events[-1].done is True


# --------------------------------------------------------------------------
# Completed-path negatives on the same wire (no retry: exactly one POST).
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completed_wrong_model_posts_once_then_fails(live_wire) -> None:
    seen: list = []

    def handle(req):
        seen.append(req)
        return httpx.Response(
            200,
            json={
                "model": "some-other-model",
                "choices": [{"message": {"content": "Hi"}}],
            },
        )

    with pytest.raises(MalformedUpstreamResponse):
        await go.call_go_model(
            **_stream_kwargs("longcat-2.5-preview-free"),
            transport=httpx.MockTransport(handle),
        )
    assert len(seen) == 1
