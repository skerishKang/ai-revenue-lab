from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from padiem_ai_core.b14_execution import (
    B14ChatRequest,
    B14ExecutionClient,
    B14ExecutionConfig,
    B14ExecutionError,
)
from padiem_ai_core.b14_transport import (
    B14PostJSONTransport,
    B14TransportResponse,
)


def run(coro):
    return asyncio.run(coro)


def request_fixture() -> B14ChatRequest:
    return B14ChatRequest(messages=({"role": "user", "content": "hello"},))


def success_payload() -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": "ok"}}],
        "business14": {"request_id": "req1", "selected_model": "model1"},
    }


class CustomTransport:
    def __init__(self, response=None, exc=None):
        self.response = response or B14TransportResponse(200, json.dumps(success_payload()).encode())
        self.exc = exc
        self.calls = []

    async def post_json(self, url, payload):
        self.calls.append((url, payload))
        if self.exc is not None:
            raise self.exc
        return self.response


def test_custom_transport_flows_through_existing_core_execution_path_once() -> None:
    custom = CustomTransport()
    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.internal"),
        B14PostJSONTransport(custom),
    )
    result = run(client.execute(request_fixture()))
    assert result.answer == "ok"
    assert len(custom.calls) == 1
    url, payload = custom.calls[0]
    assert url == "https://b14.internal/api/pilot/v1/chat/completions"
    assert payload["messages"] == [{"role": "user", "content": "hello"}]


def test_core_rechecks_custom_transport_response_cap() -> None:
    custom = CustomTransport(B14TransportResponse(200, b"x" * 33))
    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.internal", max_response_bytes=32),
        B14PostJSONTransport(custom),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "upstream_response_too_large"
    assert len(custom.calls) == 1


def test_custom_transport_exception_is_safe_and_not_retried() -> None:
    custom = CustomTransport(exc=RuntimeError("private internal transport detail"))
    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.internal"),
        B14PostJSONTransport(custom),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "upstream_unavailable"
    assert "private internal transport detail" not in info.value.safe_message
    assert len(custom.calls) == 1


def test_invalid_custom_transport_response_fails_closed() -> None:
    class BadTransport:
        async def post_json(self, url, payload):
            return (200, b"{}")

    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.internal"),
        B14PostJSONTransport(BadTransport()),
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "upstream_unavailable"


def test_custom_transport_timeout_maps_to_existing_core_timeout() -> None:
    class SlowTransport:
        async def post_json(self, url, payload):
            await asyncio.sleep(0.02)
            return B14TransportResponse(200, b"{}")

    adapter = B14PostJSONTransport(SlowTransport(), timeout_seconds=1)
    adapter._timeout_seconds = 0.001
    client = B14ExecutionClient(
        B14ExecutionConfig(base_url="https://b14.internal"),
        adapter,
    )
    with pytest.raises(B14ExecutionError) as info:
        run(client.execute(request_fixture()))
    assert info.value.code == "upstream_timeout"
