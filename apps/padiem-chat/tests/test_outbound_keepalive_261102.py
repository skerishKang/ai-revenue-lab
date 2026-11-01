"""#6615 — the completed Engine lane reuses one client per event loop.

The identity sweep (#6614) found `httpx.AsyncClient` being built per call, so
every request also paid a TCP+TLS handshake. The completed Engine lane had the
same shape: `request()` opened a client, used it once, and closed it.

Streaming keeps its per-call client on purpose — there the connection is the
stream (`stream_request`, and B14's SSE lane), so it is not touched here.
"""
from __future__ import annotations

import asyncio
import inspect

import httpx
import pytest

import app.local_engine_transport as transport_module
from app.local_engine_transport import LocalEngineHttpTransport

ORIGIN = "https://engine.example.test"


class _Recorder:
    def __init__(self) -> None:
        self.built: list[httpx.AsyncClient] = []

    def factory(self):
        real = httpx.AsyncClient

        def build(*args, **kwargs):
            kwargs.pop("transport", None)
            client = real(transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"ok": True})), **kwargs)
            self.built.append(client)
            return client

        return build


def test_repeated_use_in_one_loop_builds_one_client(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", recorder.factory())
    transport = LocalEngineHttpTransport(ORIGIN, timeout=30.0)

    async def use_it():
        first = transport._loop_client()
        assert transport._loop_client() is first      # reused, not rebuilt
        return first

    client = asyncio.run(use_it())
    assert recorder.built == [client]
    assert getattr(client, "follow_redirects", False) is False

    asyncio.run(transport.aclose())
    assert transport._clients == {}


def test_each_event_loop_gets_its_own_client(monkeypatch):
    """A cron tick runs its own loop; a cached client must not be reused there."""
    recorder = _Recorder()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", recorder.factory())
    transport = LocalEngineHttpTransport(ORIGIN, timeout=30.0)

    async def one():
        return transport._loop_client()

    asyncio.run(one())
    asyncio.run(one())                                # a second, distinct loop

    assert len(recorder.built) == 2
    asyncio.run(transport.aclose())


def test_close_then_next_use_reopens(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", recorder.factory())
    transport = LocalEngineHttpTransport(ORIGIN, timeout=30.0)

    asyncio.run(_use(transport))
    asyncio.run(transport.aclose())
    asyncio.run(_use(transport))

    assert len(recorder.built) == 2
    asyncio.run(transport.aclose())


async def _use(transport):
    return transport._loop_client()


def test_an_injected_client_is_used_and_never_closed(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(transport_module.httpx, "AsyncClient", recorder.factory())
    injected = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    transport = LocalEngineHttpTransport(ORIGIN, client=injected)

    async def call():
        # The injected client is the whole transport; no pool is consulted.
        return transport._client is injected

    assert asyncio.run(call()) is True
    asyncio.run(transport.aclose())
    assert recorder.built == []
    assert injected.is_closed is False
    asyncio.run(injected.aclose())


def test_the_stream_lane_still_owns_its_connection():
    """Guard against pooling the stream lane by accident."""
    source = inspect.getsource(LocalEngineHttpTransport.stream_request)
    assert "httpx.AsyncClient(" in source
    assert "_loop_client" not in source
