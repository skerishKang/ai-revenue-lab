from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from padiem_ai_core import (
    B14ChatRequest,
    B14ExecutionClient,
    B14ExecutionConfig,
    B14ExecutionError,
)

from app.cloudflare_transport import (
    B14_INTERNAL_ORIGIN,
    CloudflareB14ServiceBindingTransport,
)


class FakeReader:
    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.read_calls = 0
        self.cancel_calls = 0
        self.release_calls = 0

    async def read(self):
        self.read_calls += 1
        if self._chunks:
            return SimpleNamespace(done=False, value=self._chunks.pop(0))
        return SimpleNamespace(done=True, value=None)

    async def cancel(self):
        self.cancel_calls += 1

    def releaseLock(self):
        self.release_calls += 1


class FakeBody:
    def __init__(self, chunks):
        self.reader = FakeReader(chunks)
        self.get_reader_calls = 0

    def getReader(self):
        self.get_reader_calls += 1
        return self.reader


class FakeHeaders:
    def __init__(self, content_type="application/json"):
        self.content_type = content_type

    def get(self, name):
        if name.lower() == "content-type":
            return self.content_type
        return None


class FakeResponse:
    def __init__(self, *, status=200, chunks=(), content_type="application/json"):
        self.status = status
        self.headers = FakeHeaders(content_type)
        self.body = FakeBody(chunks)


class FakeBinding:
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


class FakeWorkerRequest:
    def __init__(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        self.js_object = self


class RequestFactory:
    def __init__(self):
        self.calls = []

    def __call__(self, url, **kwargs):
        request = FakeWorkerRequest(url, **kwargs)
        self.calls.append(request)
        return request


def transport_for(response=None, error=None):
    binding = FakeBinding(response=response, error=error)
    factory = RequestFactory()
    transport = CloudflareB14ServiceBindingTransport(
        binding=binding,
        request_factory=factory,
    )
    return transport, binding, factory


@pytest.mark.asyncio
async def test_fixed_target_uses_binding_once_and_delivers_progressive_bytes() -> None:
    response = FakeResponse(chunks=[b'{"part":', b'"one"}'])
    transport, binding, factory = transport_for(response=response)

    async with httpx.AsyncClient(transport=transport) as client:
        async with client.stream(
            "POST",
            B14_INTERNAL_ORIGIN + "/api/pilot/v1/chat/completions",
            json={"hello": "world"},
        ) as result:
            chunks = [chunk async for chunk in result.aiter_bytes()]

    assert result.status_code == 200
    assert b"".join(chunks) == b'{"part":"one"}'
    assert len(factory.calls) == 1
    assert len(binding.calls) == 1
    request = factory.calls[0]
    assert request.url == B14_INTERNAL_ORIGIN + "/api/pilot/v1/chat/completions"
    assert request.kwargs["method"] == "POST"
    assert request.kwargs["headers"] == {"Content-Type": "application/json"}
    assert json.loads(request.kwargs["body"])["hello"] == "world"
    assert response.body.get_reader_calls == 1
    assert response.body.reader.read_calls == 3
    assert response.body.reader.cancel_calls == 0
    assert response.body.reader.release_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/api/pilot/v1/chat/completions",
        "http://b14.internal/api/pilot/v1/chat/completions",
        "https://b14.internal/api/pilot/v1/other",
        "https://b14.internal/api/pilot/v1/chat/completions?target=x",
    ],
)
async def test_target_override_rejected_before_service_binding(url) -> None:
    transport, binding, factory = transport_for(response=FakeResponse(chunks=[b"{}"] ))
    request = httpx.Request("POST", url, json={"x": 1})

    with pytest.raises(httpx.RequestError):
        await transport.handle_async_request(request)

    assert binding.calls == []
    assert factory.calls == []


@pytest.mark.asyncio
async def test_early_response_close_cancels_and_releases_reader_once() -> None:
    response = FakeResponse(chunks=[b"first", b"second"])
    transport, _, _ = transport_for(response=response)
    request = httpx.Request(
        "POST",
        B14_INTERNAL_ORIGIN + "/api/pilot/v1/chat/completions",
        json={"x": 1},
    )

    result = await transport.handle_async_request(request)
    iterator = result.aiter_bytes()
    assert await anext(iterator) == b"first"
    await result.aclose()

    assert response.body.reader.cancel_calls == 1
    assert response.body.reader.release_calls == 1


@pytest.mark.asyncio
async def test_binding_exception_is_bounded_connect_error() -> None:
    transport, binding, _ = transport_for(error=RuntimeError("PRIVATE_BINDING_DETAIL"))
    request = httpx.Request(
        "POST",
        B14_INTERNAL_ORIGIN + "/api/pilot/v1/chat/completions",
        json={"x": 1},
    )

    with pytest.raises(httpx.ConnectError) as captured:
        await transport.handle_async_request(request)

    assert len(binding.calls) == 1
    assert "PRIVATE_BINDING_DETAIL" not in str(captured.value)


def valid_b14_json(answer="hello") -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"content": answer}}],
            "business14": {
                "selected_provider": "openrouter",
                "selected_model": "openrouter/free",
            },
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        }
    ).encode()


@pytest.mark.asyncio
async def test_core_response_ceiling_remains_authoritative_over_binding_stream() -> None:
    response = FakeResponse(chunks=[valid_b14_json("x" * 300)])
    transport, binding, _ = transport_for(response=response)
    client = B14ExecutionClient(
        B14ExecutionConfig(
            base_url=B14_INTERNAL_ORIGIN,
            max_response_bytes=64,
        ),
        transport=transport,
    )

    with pytest.raises(B14ExecutionError) as captured:
        await client.execute(B14ChatRequest(messages=({"role": "user", "content": "hi"},)))

    assert captured.value.code == "upstream_response_too_large"
    assert len(binding.calls) == 1
    assert response.body.reader.release_calls == 1


@pytest.mark.asyncio
async def test_core_normalizes_binding_429_without_public_fallback() -> None:
    response = FakeResponse(status=429, chunks=[b'{}'])
    transport, binding, _ = transport_for(response=response)
    client = B14ExecutionClient(
        B14ExecutionConfig(base_url=B14_INTERNAL_ORIGIN),
        transport=transport,
    )

    with pytest.raises(B14ExecutionError) as captured:
        await client.execute(B14ChatRequest(messages=({"role": "user", "content": "hi"},)))

    assert captured.value.code == "upstream_rate_limited"
    assert captured.value.retryable is True
    assert len(binding.calls) == 1


@pytest.mark.asyncio
async def test_core_success_uses_observed_binding_response() -> None:
    response = FakeResponse(chunks=[valid_b14_json("hello from b14")])
    transport, binding, _ = transport_for(response=response)
    client = B14ExecutionClient(
        B14ExecutionConfig(base_url=B14_INTERNAL_ORIGIN),
        transport=transport,
    )

    result = await client.execute(
        B14ChatRequest(messages=({"role": "user", "content": "hi"},))
    )

    assert result.answer == "hello from b14"
    assert result.route.selected_provider == "openrouter"
    assert result.route.selected_model == "openrouter/free"
    assert result.usage.total_tokens == 3
    assert len(binding.calls) == 1
