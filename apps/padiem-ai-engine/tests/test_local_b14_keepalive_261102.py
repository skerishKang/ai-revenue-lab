"""``LocalB14Binding`` reuses one B14 client per event loop (#6614/#6616 follow-on).

The binding opened ``httpx.AsyncClient`` inside ``fetch``, so every P01 model
request paid a fresh connection setup and pool teardown before B14 answered.
The client is now created on first use, reused per loop, and closed by the host
lifespan shutdown — no per-call client, no closed-loop reuse, and a client the
caller injected is never closed here.
"""

from __future__ import annotations

import asyncio
import json

from app import local_runtime as rt

B14_URL = "http://127.0.0.1:8789/api/pilot/v1/chat/completions"
PROOF_SECRET = "synthetic-test-" + "x" * 40


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self.content = payload
        self.status_code = 200
        self.headers = {"content-type": "application/json"}


class _FakeClient:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.requests: list[tuple[str, str]] = []
        self.closed = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def request(self, method, url, headers=None, content=None):
        self.requests.append((method, url))
        return _FakeResponse(self.payload)

    async def aclose(self) -> None:
        self.closed += 1


def _patch(monkeypatch) -> tuple[list[_FakeClient], bytes]:
    created: list[_FakeClient] = []
    payload = json.dumps({"choices": []}).encode()

    def factory(*args, **kwargs):
        client = _FakeClient(payload)
        created.append(client)
        return client

    monkeypatch.setattr(rt.httpx, "AsyncClient", factory)
    return created, payload


def _binding(**kwargs) -> rt.LocalB14Binding:
    return rt.LocalB14Binding(
        "http://127.0.0.1:8789", values={rt.B14_PROOF_SECRET_ENV: PROOF_SECRET}, **kwargs
    )


def _request() -> rt.LocalRequest:
    return rt.LocalRequest(
        B14_URL,
        method="POST",
        headers={"Content-Type": "application/json"},
        body=b'{"model":"host-model"}',
    )


async def test_repeated_calls_share_one_client(monkeypatch) -> None:
    created, _ = _patch(monkeypatch)
    binding = _binding()

    for _ in range(3):
        response = await binding.fetch(_request())
        assert response.status == 200

    assert len(created) == 1
    assert len(created[0].requests) == 3
    assert created[0].closed == 0
    await binding.aclose()
    assert created[0].closed == 1


async def test_each_loop_gets_its_own_client(monkeypatch) -> None:
    created, _ = _patch(monkeypatch)
    binding = _binding()

    await binding.fetch(_request())

    def second_loop() -> None:
        asyncio.run(binding.fetch(_request()))

    await asyncio.to_thread(second_loop)

    assert len(created) == 2
    assert all(client.closed == 0 for client in created)
    await binding.aclose()
    assert [client.closed for client in created] == [1, 1]


async def test_close_then_call_recreates_the_client(monkeypatch) -> None:
    created, _ = _patch(monkeypatch)
    binding = _binding()

    await binding.fetch(_request())
    await binding.aclose()
    await binding.fetch(_request())

    assert len(created) == 2
    assert created[0].closed == 1
    assert created[1].closed == 0
    await binding.aclose()


async def test_injected_client_is_used_and_never_closed(monkeypatch) -> None:
    created, _ = _patch(monkeypatch)
    injected = _FakeClient(json.dumps({"choices": []}).encode())
    binding = _binding(client=injected)

    await binding.fetch(_request())
    await binding.aclose()

    assert created == []  # no client was built behind the caller's back
    assert len(injected.requests) == 1
    assert injected.closed == 0


async def test_lifespan_shutdown_closes_pooled_clients(monkeypatch) -> None:
    created, _ = _patch(monkeypatch)
    bindings = rt._local_bindings({rt.B14_ORIGIN_ENV: "http://127.0.0.1:8789",
                                   rt.B14_PROOF_SECRET_ENV: PROOF_SECRET})
    binding = bindings["B14_SERVICE"]
    await binding.fetch(_request())

    messages = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    sent: list[dict] = []

    async def receive() -> dict:
        return messages.pop(0)

    async def send(message: dict) -> None:
        sent.append(message)

    await rt._lifespan(receive, send)

    assert [message["type"] for message in sent] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]
    assert created[0].closed == 1
    assert binding not in rt._B14_BINDINGS
