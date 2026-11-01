"""#6617 — the queue lane (8797) reuses one client per event loop.

Same shape as #6614's identity fix: `QueueStoreClient.call()` built an
`httpx.AsyncClient` per call, so each queue call also paid a TCP+TLS handshake.
Only the client source changed — the call's stage tracing, logging, exception
classification, retry-free contract, timeout and secret header are untouched.
"""
from __future__ import annotations

import asyncio

import httpx

import app.queue_store_proxy as proxy_module
from app.queue_store_proxy import QueueStoreClient

SECRET = "queue-service-secret-0123456789abcdef"
ORIGIN = "http://127.0.0.1:8830"


def _client(factory=None) -> QueueStoreClient:
    return QueueStoreClient(origin=ORIGIN, service_secret=SECRET,
                            allow_loopback_http=True, client_factory=factory)


class _Recorder:
    def __init__(self) -> None:
        self.built: list = []
        self.requests: list[httpx.Request] = []

    def factory(self):
        real = httpx.AsyncClient

        def build(*args, **kwargs):
            kwargs.pop("transport", None)
            client = real(transport=httpx.MockTransport(self._respond), **kwargs)
            self.built.append(client)
            return client

        return build

    def _respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200, json={"ok": True, "result": {"value": 1}},
            headers={"content-type": "application/json"})


def test_three_calls_build_one_client(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", recorder.factory())
    client = _client()

    async def three():
        return [await client.call("load", node_id="n1") for _ in range(3)]

    assert asyncio.run(three()) == [{"value": 1}] * 3
    assert len(recorder.requests) == 3
    assert len(recorder.built) == 1, len(recorder.built)
    # The queue service secret header is still on every call.
    assert all(r.headers["X-Padiem-Queue-Secret"] == SECRET for r in recorder.requests)
    asyncio.run(client.aclose())
    assert client._clients == {}


def test_a_second_loop_gets_its_own_client(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", recorder.factory())
    client = _client()

    asyncio.run(client.call("load", node_id="n1"))
    asyncio.run(client.call("load", node_id="n2"))

    assert len(recorder.built) == 2
    assert len(recorder.requests) == 2
    asyncio.run(client.aclose())


def test_close_then_next_call_reopens(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", recorder.factory())
    client = _client()

    asyncio.run(client.call("load", node_id="n1"))
    asyncio.run(client.aclose())
    asyncio.run(client.call("load", node_id="n1"))

    assert len(recorder.built) == 2
    asyncio.run(client.aclose())


def test_an_injected_factory_keeps_its_per_call_shape():
    """Tests and the Workers compat path inject a factory; nothing is pooled."""
    built: list = []

    def factory(**kwargs):
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"ok": True, "result": {}},
                headers={"content-type": "application/json"})))
        built.append(client)
        return client

    client = _client(factory)
    asyncio.run(client.call("load", node_id="n1"))
    asyncio.run(client.call("load", node_id="n1"))

    assert len(built) == 2          # a factory is asked once per call, as before
    assert client._clients == {}    # and nothing is retained
    asyncio.run(client.aclose())


def test_a_refused_call_still_raises_the_same_bounded_error(monkeypatch):
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(transport=httpx.MockTransport(
            lambda request: httpx.Response(503, json={"ok": False})), **kwargs)

    monkeypatch.setattr(proxy_module.httpx, "AsyncClient", factory)
    client = _client()
    from app.queue_store_proxy import QueueUnavailable

    try:
        asyncio.run(client.call("load", node_id="n1"))
    except QueueUnavailable as exc:
        assert "queue refused the call" in str(exc)
    else:                                        # pragma: no cover - asserted above
        raise AssertionError("a 503 must stay QueueUnavailable")
    asyncio.run(client.aclose())
