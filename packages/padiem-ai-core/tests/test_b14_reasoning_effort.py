"""#3906 — provider-native reasoning level on the B14 wire (core contract).

The selected level must reach the ACTUAL request body of both the completed and
the streaming B14 call, unchanged, and the field must be absent when no level was
selected so the served provider keeps its own default. These tests read the JSON
the client really POSTs through a mock transport, not a renderer self-report.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from padiem_ai_core.b14_execution import (
    REASONING_EFFORT_VALUES,
    B14ChatRequest,
    B14ExecutionClient,
    B14ExecutionConfig,
)
from padiem_ai_core.b14_streaming import B14StreamingClient

BASE_URL = "https://b14.internal"
MODEL = "google/gemini-3.1-flash-lite"
MESSAGES = ({"role": "user", "content": "synthetic quotation"},)


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk

    async def aclose(self) -> None:
        return None


def request(*, reasoning_effort: str | None = None) -> B14ChatRequest:
    return B14ChatRequest(messages=MESSAGES, model=MODEL, reasoning_effort=reasoning_effort)


def _completion_body() -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"role": "assistant", "content": "{}"}}],
            "business14": {"route_mode": "manual", "selected_model": MODEL},
        }
    ).encode()


# --------------------------------------------------------------------------
# 1. Payload contract: omitted stays omitted, explicit is transmitted as-is.
# --------------------------------------------------------------------------

def test_payload_omits_the_field_when_no_level_is_selected():
    assert "reasoning_effort" not in request().to_payload()


@pytest.mark.parametrize("level", sorted(REASONING_EFFORT_VALUES))
def test_payload_carries_the_explicit_level_unchanged(level):
    assert request(reasoning_effort=level).to_payload()["reasoning_effort"] == level


def test_invented_level_is_rejected_before_a_request_can_be_built():
    """Fail closed on a level the provider never documented."""
    with pytest.raises(ValueError):
        request(reasoning_effort="xhigh")


# --------------------------------------------------------------------------
# 2. Completed (non-streaming) request body.
# --------------------------------------------------------------------------

def test_non_streaming_request_body_carries_the_selected_level():
    seen: dict = {}

    async def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        return httpx.Response(200, content=_completion_body())

    async def run() -> None:
        client = B14ExecutionClient(B14ExecutionConfig(BASE_URL), httpx.MockTransport(handler))
        await client.execute(request(reasoning_effort="low"))

    asyncio.run(run())
    assert seen["model"] == MODEL
    assert seen["reasoning_effort"] == "low"


def test_non_streaming_request_body_keeps_the_field_absent_when_unset():
    seen: dict = {}

    async def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        return httpx.Response(200, content=_completion_body())

    async def run() -> None:
        client = B14ExecutionClient(B14ExecutionConfig(BASE_URL), httpx.MockTransport(handler))
        await client.execute(request())

    asyncio.run(run())
    assert "reasoning_effort" not in seen


# --------------------------------------------------------------------------
# 3. Streaming request body: same field, same value (general/stream parity).
# --------------------------------------------------------------------------

def _stream_handler(seen: dict):
    async def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content))
        chunk = {
            "id": "stream_1",
            "object": "chat.completion.chunk",
            "model": MODEL,
            "choices": [
                {"index": 0, "delta": {"content": "A"}, "finish_reason": "stop"}
            ],
            "business14": {
                "request_id": "b14stream_1",
                "route_mode": "manual",
                "selected_provider": "Google",
                "selected_model": MODEL,
                "selected_upstream_model": MODEL,
                "selected_route_id": f"google:{MODEL}",
                "fallback_used": False,
                "attempt_count": 1,
                "route_evidence_status": "live_streaming_preview",
            },
        }
        raw = b"data: " + json.dumps(chunk).encode() + b"\n\ndata: [DONE]\n\n"
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, stream=ChunkStream([raw])
        )

    return handler


def test_streaming_request_body_carries_the_selected_level():
    seen: dict = {}

    async def run() -> None:
        client = B14StreamingClient(B14ExecutionConfig(BASE_URL), httpx.MockTransport(_stream_handler(seen)))
        async for _event in client.stream(request(reasoning_effort="high")):
            pass

    asyncio.run(run())
    assert seen["stream"] is True
    assert seen["model"] == MODEL
    assert seen["reasoning_effort"] == "high"


def test_streaming_request_body_keeps_the_field_absent_when_unset():
    seen: dict = {}

    async def run() -> None:
        client = B14StreamingClient(B14ExecutionConfig(BASE_URL), httpx.MockTransport(_stream_handler(seen)))
        async for _event in client.stream(request()):
            pass

    asyncio.run(run())
    assert "reasoning_effort" not in seen
