"""#4379: the Engine must not refuse a model request or a tool result by size.

The Engine used to refuse any B14 request body larger than 256 KB and used the
completed-response byte budget as the streaming budget too, so a large context
never reached the model even though the product side accepted it. The Engine
tool projection additionally cut every result string at 2,048 characters and
replaced a result larger than 32 KB with ``None``.

Network-free: no provider call, no production mutation, no secret.
"""
from __future__ import annotations

import json

import httpx
import pytest

from padiem_ai_core import B14ExecutionConfig

from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
    build_b14_execution_configs,
)
from app.tool_projection import REDACTED_TOOL_VALUE, project_redacted_tool_output


class _FakeHeaders:
    def __init__(self, content_type="application/json"):
        self.content_type = content_type

    def get(self, name):
        if name.lower() == "content-type":
            return self.content_type
        return None


class _FakeChunk:
    def __init__(self, value, done=False):
        self.value = value
        self.done = done


class _FakeReader:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    async def read(self):
        if self._chunks:
            return _FakeChunk(self._chunks.pop(0))
        return _FakeChunk(b"", done=True)

    def releaseLock(self):
        return None


class _FakeBody:
    def __init__(self, chunks):
        self._reader = _FakeReader(chunks)

    def getReader(self):
        return self._reader


class _FakeResponse:
    def __init__(self, *, status=200, chunks=(), content_type="application/json"):
        self.status = status
        self.headers = _FakeHeaders(content_type)
        self.body = _FakeBody(chunks)


class _FakeBinding:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    async def fetch(self, request):
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


class _FakeWorkerRequest:
    def __init__(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        self.js_object = self


class _RequestFactory:
    def __init__(self):
        self.calls = []

    def __call__(self, url, **kwargs):
        request = _FakeWorkerRequest(url, **kwargs)
        self.calls.append(request)
        return request


def _transport(response=None, error=None):
    binding = _FakeBinding(response=response, error=error)
    factory = _RequestFactory()
    transport = CloudflareB14ServiceBindingTransport(
        binding=binding, request_factory=factory,
    )
    return transport, binding, factory


@pytest.mark.asyncio
async def test_engine_b14_request_larger_than_the_old_256kb_ceiling_is_delivered():
    """#4379: a large model context reaches B14 instead of being refused."""
    body = {"messages": [{"role": "user", "content": "가" * 300_000}]}
    encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
    assert len(encoded) > 256 * 1024
    transport, binding, factory = _transport(response=_FakeResponse(chunks=[b"{}"]))

    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.post(
            B14_INTERNAL_ORIGIN + "/api/pilot/v1/chat/completions",
            content=encoded,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 200
    assert len(binding.calls) == 1
    delivered = factory.calls[0].kwargs["body"]
    assert len(delivered.encode("utf-8")) == len(encoded)
    assert json.loads(delivered)["messages"][0]["content"] == body["messages"][0]["content"]


def test_engine_completed_and_stream_budgets_are_not_the_same_number():
    """#4379: the completed body budget and the stream frame bound differ.

    Sharing the smaller frame bound with the completed client made the Engine
    refuse healthy model answers that Chat/Claw accept.
    """
    completed, streaming = build_b14_execution_configs(timeout_seconds=600.0)
    assert isinstance(completed, B14ExecutionConfig)
    assert isinstance(streaming, B14ExecutionConfig)
    assert completed.max_response_bytes > streaming.max_response_bytes
    assert completed.timeout_seconds == 600.0
    assert streaming.timeout_seconds == 600.0


def test_engine_tool_result_is_not_shortened_or_dropped():
    """#4379: the tool result reaches the caller exactly as it was produced."""
    long_text = "답" * 40_000
    output = {
        "body": long_text,
        "rows": list(range(5_000)),
        "api_key": "sk-live-abcdef",
    }
    projected, truncated = project_redacted_tool_output(output)
    assert truncated is False
    assert projected["body"] == long_text
    assert len(projected["rows"]) == 5_000
    assert projected["rows"][-1] == 4_999
    # The secret redaction is unchanged and still authoritative.
    assert projected["api_key"] == REDACTED_TOOL_VALUE
    assert "sk-live-abcdef" not in repr(projected)
