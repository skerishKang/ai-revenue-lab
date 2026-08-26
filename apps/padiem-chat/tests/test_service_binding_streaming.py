from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from padiem_ai_core.b14_execution import (
    B14ChatRequest,
    B14ExecutionConfig,
    B14ExecutionError,
    B14RoutingOptions,
)
from padiem_ai_core.b14_streaming import B14StreamingClient


BASE_URL = "https://b14.internal"
MODEL = "openrouter/free"
WORKER_PATH = Path(__file__).resolve().parents[1] / "worker.py"


class FakeRequest:
    created: list["FakeRequest"] = []

    def __init__(self, url: str, **options: Any):
        self.url = url
        self.options = options
        self.js_object = object()
        self.__class__.created.append(self)


class FakeJSBytes:
    def __init__(self, data: bytes):
        self.data = data

    def to_bytes(self) -> bytes:
        return self.data


class FakeReader:
    def __init__(self, chunks: list[bytes], *, gate_at_read: int | None = None):
        self.chunks = list(chunks)
        self.gate_at_read = gate_at_read
        self.read_count = 0
        self.cancel_count = 0
        self.release_count = 0
        self.read_blocked = asyncio.Event()
        self.allow_read = asyncio.Event()

    async def read(self):
        self.read_count += 1
        if self.gate_at_read == self.read_count:
            self.read_blocked.set()
            await self.allow_read.wait()

        index = self.read_count - 1
        if index >= len(self.chunks):
            return SimpleNamespace(done=True, value=None)
        return SimpleNamespace(done=False, value=FakeJSBytes(self.chunks[index]))

    async def cancel(self):
        self.cancel_count += 1

    def releaseLock(self):
        self.release_count += 1


class FakeBody:
    def __init__(self, reader: FakeReader):
        self.reader = reader
        self.get_reader_count = 0

    def getReader(self):
        self.get_reader_count += 1
        return self.reader


class FakeHeaders:
    def __init__(self, content_type: str | None):
        self.content_type = content_type

    def get(self, name: str):
        if name.lower() == "content-type":
            return self.content_type
        return None


class FakeResponse:
    def __init__(
        self,
        status: int,
        body: FakeBody,
        *,
        content_type: str | None = "text/event-stream",
    ):
        self.status = status
        self.body = body
        self.headers = FakeHeaders(content_type)


class FakeBinding:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.calls: list[Any] = []

    async def fetch(self, request: Any):
        self.calls.append(request)
        return self.response


def _load_worker_streaming_types():
    source = WORKER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "_CloudflareReadableByteStream",
        "CloudflareB14StreamingServiceTransport",
    }
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name in names
    ]
    assert [node.name for node in classes] == [
        "_CloudflareReadableByteStream",
        "CloudflareB14StreamingServiceTransport",
    ]

    module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *classes,
        ],
        type_ignores=[],
    )
    namespace = {
        "Any": Any,
        "Request": FakeRequest,
        "httpx": httpx,
    }
    exec(compile(ast.fix_missing_locations(module), str(WORKER_PATH), "exec"), namespace)
    return (
        namespace["_CloudflareReadableByteStream"],
        namespace["CloudflareB14StreamingServiceTransport"],
    )


def _request() -> B14ChatRequest:
    return B14ChatRequest(
        messages=({"role": "user", "content": "안녕하세요"},),
        model=MODEL,
        routing=B14RoutingOptions(
            allow_external_fallback=False,
            max_attempts=1,
        ),
    )


def _chunk_payload(*, content: str | None = None, finish_reason: str | None = None) -> dict:
    choices = []
    if content is not None or finish_reason is not None:
        choices = [
            {
                "index": 0,
                "delta": {} if content is None else {"content": content},
                "finish_reason": finish_reason,
            }
        ]
    return {
        "id": "stream_binding_1",
        "object": "chat.completion.chunk",
        "model": MODEL,
        "choices": choices,
        "business14": {
            "request_id": "b14stream_binding_1",
            "route_mode": "manual",
            "selected_provider": "OpenRouter",
            "selected_model": MODEL,
            "selected_upstream_model": MODEL,
            "selected_route_id": f"openrouter:{MODEL}",
            "fallback_used": False,
            "attempt_count": 1,
            "route_evidence_status": "live_streaming_preview",
        },
    }


def _sse(payload: dict) -> bytes:
    return b"data: " + json.dumps(payload).encode("utf-8") + b"\n\n"


def _client(binding: FakeBinding, *, max_response_bytes: int = 1_048_576):
    _, transport_type = _load_worker_streaming_types()
    transport = transport_type(binding)
    return B14StreamingClient(
        B14ExecutionConfig(BASE_URL, max_response_bytes=max_response_bytes),
        transport=transport,
    )


async def _collect(client: B14StreamingClient):
    return [event async for event in client.stream(_request())]


def test_service_binding_stream_delivers_first_event_before_final_chunk():
    async def scenario():
        FakeRequest.created.clear()
        reader = FakeReader(
            [_sse(_chunk_payload(content="첫 토큰")), b"data: [DONE]\n\n"],
            gate_at_read=2,
        )
        body = FakeBody(reader)
        binding = FakeBinding(FakeResponse(200, body))
        stream = _client(binding).stream(_request())

        first = await anext(stream)
        assert first.delta_content == "첫 토큰"
        assert first.done is False

        done_task = asyncio.create_task(anext(stream))
        await asyncio.wait_for(reader.read_blocked.wait(), timeout=1)
        assert done_task.done() is False

        reader.allow_read.set()
        done = await asyncio.wait_for(done_task, timeout=1)
        assert done.done is True

        with pytest.raises(StopAsyncIteration):
            await anext(stream)

        assert len(binding.calls) == 1
        assert len(FakeRequest.created) == 1
        request = FakeRequest.created[0]
        assert binding.calls[0] is request.js_object
        assert request.url == BASE_URL + "/api/pilot/v1/chat/completions/stream-preview"
        assert request.options["method"] == "POST"
        assert request.options["headers"] == {"Content-Type": "application/json"}
        payload = json.loads(request.options["body"])
        assert payload["stream"] is True
        assert payload["model"] == MODEL
        assert payload["business14"]["allow_external_fallback"] is False
        assert payload["business14"]["max_attempts"] == 1
        assert "authorization" not in {key.lower() for key in request.options["headers"]}
        assert body.get_reader_count == 1
        assert reader.cancel_count == 1
        assert reader.release_count == 1

    asyncio.run(scenario())


def test_service_binding_stream_preserves_arbitrary_sse_fragmentation():
    raw = _sse(_chunk_payload(content="분할")) + b"data: [DONE]\n\n"
    chunks = [raw[:3], raw[3:17], raw[17:61], raw[61:]]
    reader = FakeReader(chunks)
    binding = FakeBinding(FakeResponse(200, FakeBody(reader)))

    events = asyncio.run(_collect(_client(binding)))

    assert [event.delta_content for event in events if event.delta_content] == ["분할"]
    assert events[-1].done is True
    assert len(binding.calls) == 1
    assert reader.cancel_count == 1
    assert reader.release_count == 1


@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        (401, "upstream_auth_error"),
        (403, "upstream_auth_error"),
        (429, "upstream_rate_limited"),
        (400, "upstream_request_error"),
        (500, "upstream_server_error"),
    ],
)
def test_service_binding_stream_preserves_http_status_without_reading_body(
    status: int,
    expected_code: str,
):
    reader = FakeReader([b"must-not-be-read"])
    body = FakeBody(reader)
    binding = FakeBinding(FakeResponse(status, body))

    with pytest.raises(B14ExecutionError) as info:
        asyncio.run(_collect(_client(binding)))

    assert info.value.code == expected_code
    assert len(binding.calls) == 1
    assert body.get_reader_count == 0
    assert reader.read_count == 0


def test_service_binding_stream_preserves_content_type_gate_without_body_buffering():
    reader = FakeReader([b'{"not":"sse"}'])
    body = FakeBody(reader)
    binding = FakeBinding(FakeResponse(200, body, content_type="application/json"))

    with pytest.raises(B14ExecutionError) as info:
        asyncio.run(_collect(_client(binding)))

    assert info.value.code == "malformed_upstream"
    assert body.get_reader_count == 0
    assert reader.read_count == 0


def test_service_binding_stream_missing_done_fails_closed_and_releases_reader():
    async def scenario():
        reader = FakeReader([_sse(_chunk_payload(content="미완료"))])
        binding = FakeBinding(FakeResponse(200, FakeBody(reader)))
        stream = _client(binding).stream(_request())

        first = await anext(stream)
        assert first.delta_content == "미완료"
        with pytest.raises(B14ExecutionError) as info:
            await anext(stream)

        assert info.value.code == "malformed_upstream"
        assert reader.cancel_count == 0
        assert reader.release_count == 1

    asyncio.run(scenario())


def test_service_binding_stream_post_start_error_is_bounded_and_closes_reader():
    async def scenario():
        error_frame = (
            b"event: error\n"
            b'data: {"error":{"code":"provider_stream_error","message":"safe failure"}}\n\n'
        )
        reader = FakeReader([_sse(_chunk_payload(content="부분")), error_frame])
        binding = FakeBinding(FakeResponse(200, FakeBody(reader)))
        stream = _client(binding).stream(_request())

        first = await anext(stream)
        assert first.delta_content == "부분"
        with pytest.raises(B14ExecutionError) as info:
            await anext(stream)

        assert info.value.code == "provider_stream_error"
        assert str(info.value) == "safe failure"
        assert reader.cancel_count == 1
        assert reader.release_count == 1

    asyncio.run(scenario())


def test_service_binding_stream_consumer_close_cancels_upstream_once():
    async def scenario():
        reader = FakeReader(
            [_sse(_chunk_payload(content="첫 토큰")), b"data: [DONE]\n\n"]
        )
        binding = FakeBinding(FakeResponse(200, FakeBody(reader)))
        stream = _client(binding).stream(_request())

        first = await anext(stream)
        assert first.delta_content == "첫 토큰"
        await stream.aclose()
        await stream.aclose()

        assert reader.cancel_count == 1
        assert reader.release_count == 1

    asyncio.run(scenario())


def test_service_binding_stream_core_byte_cap_still_closes_upstream():
    async def scenario():
        frame = _sse(_chunk_payload(content="크기 제한"))
        reader = FakeReader([frame])
        binding = FakeBinding(FakeResponse(200, FakeBody(reader)))

        with pytest.raises(B14ExecutionError) as info:
            await _collect(_client(binding, max_response_bytes=len(frame) - 1))

        assert info.value.code == "upstream_response_too_large"
        assert reader.cancel_count == 1
        assert reader.release_count == 1

    asyncio.run(scenario())


def test_completed_json_bridge_is_preserved_and_streaming_bridge_never_buffers_response():
    tree = ast.parse(WORKER_PATH.read_text(encoding="utf-8"))
    classes = {
        node.name: ast.unparse(node)
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }

    completed = classes["CloudflareB14ServiceTransport"]
    streaming = classes["CloudflareB14StreamingServiceTransport"]
    byte_stream = classes["_CloudflareReadableByteStream"]

    assert "await response.text()" in completed
    assert "CloudflareB14ServiceTransport(b14_binding)" in WORKER_PATH.read_text(
        encoding="utf-8"
    )
    for forbidden in (".text()", ".json()", ".arrayBuffer()"):
        assert forbidden not in streaming
        assert forbidden not in byte_stream
    assert "binding.fetch(service_request.js_object)" in streaming
    assert "getReader()" in byte_stream
    assert "reader.cancel()" not in byte_stream  # cancellation stays dynamically guarded
    assert "getattr(reader, 'cancel', None)" in byte_stream
    assert "getattr(reader, 'releaseLock', None)" in byte_stream
