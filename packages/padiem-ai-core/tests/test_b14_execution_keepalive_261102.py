"""#6615 — one pooled client for the completed B14 lane (#6614's counterpart).

`B14ExecutionClient.execute()` used to build its own `httpx.AsyncClient` per
call, so every completion also paid a TCP+TLS handshake. The body is fully read
inside the call, so the connection can be reused; the SSE lane
(`b14_streaming`) keeps a per-call client because there the connection *is* the
stream.
"""
from __future__ import annotations

import asyncio
import inspect

import httpx
import pytest

import padiem_ai_core.b14_execution as execution_module
from padiem_ai_core.b14_execution import B14ExecutionClient, B14ExecutionConfig

BASE = "https://b14.example.test"


def config(**overrides) -> B14ExecutionConfig:
    values = dict(base_url=BASE, timeout_seconds=30.0)
    values.update(overrides)
    return B14ExecutionConfig(**values)


def _client(**kwargs) -> B14ExecutionClient:
    return B14ExecutionClient(config(), **kwargs)


def test_the_client_is_built_once_and_reused(monkeypatch):
    built: list = []
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)          # the mock replaces it
        client = real(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True})), **kwargs)
        built.append(client)
        return client

    monkeypatch.setattr(execution_module.httpx, "AsyncClient", factory)
    client = _client()

    first = client._shared_client()
    assert client._shared_client() is first
    assert built == [first]
    assert first.timeout == client._timeout()      # same budget as before
    assert first.follow_redirects is False

    asyncio.run(client.aclose())
    assert client._client is None
    assert client._shared_client() is not first
    assert len(built) == 2
    asyncio.run(client.aclose())


def test_transport_and_timeout_are_unchanged():
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    client = B14ExecutionClient(config(timeout_seconds=12.5), transport=transport)
    shared = client._shared_client()

    assert shared._transport is transport
    assert shared.timeout == httpx.Timeout(
        connect=12.5, read=12.5, write=12.5, pool=10.0)
    asyncio.run(client.aclose())


def test_the_streaming_lane_is_deliberately_left_alone():
    """A pooled client must not be handed to the SSE lane."""
    # A submodule import, not a package-root import: the root surface is the
    # declared ``__all__`` only (test_package_root_consumer_inventory).
    import padiem_ai_core.b14_streaming as b14_streaming

    source = inspect.getsource(b14_streaming)
    assert "async with httpx.AsyncClient(" in source
    assert "_shared_client" not in source
