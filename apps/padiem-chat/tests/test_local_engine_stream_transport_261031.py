"""Host streaming transport: a real loopback ASGI engine, chunk by chunk.

The engine's own ASGI app (#6385/#6387) is not in this baseline yet, so the
streams below are served by a small ASGI app on a real uvicorn socket. That still
exercises the claim under test: the host transport forwards NDJSON as it
arrives, propagates Engine errors as statuses, and tears the connection down when
the consumer stops reading.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
import uvicorn
from padiem_ai_engine_client import (
    ENGINE_HEALTH_PATH,
    ENGINE_INTERNAL_ORIGIN,
    ENGINE_ORCHESTRATE_PATH,
    ENGINE_ORCHESTRATE_STREAM_PATH,
    EngineStreamTransportResponse,
)

from app.local_engine_transport import (
    DEFAULT_STREAM_TIMEOUT_SECONDS,
    LocalEngineHttpTransport,
    LocalEngineTransportError,
)


class _EngineStub:
    """One ASGI app that streams the given frames and watches for disconnect."""

    def __init__(
        self,
        chunks: tuple[bytes, ...],
        *,
        status: int = 200,
        content_type: str = "application/x-ndjson",
        gap: float = 0.15,
    ) -> None:
        self.chunks = chunks
        self.status = status
        self.content_type = content_type
        self.gap = gap
        self.sent_at: list[float] = []
        self.disconnected = False
        self.completed = False
        self.requests: list[dict[str, str]] = []

    async def _watch(self, receive, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                message = await asyncio.wait_for(receive(), timeout=deadline - time.monotonic())
            except asyncio.TimeoutError:
                return False
            if message.get("type") == "http.disconnect":
                return True
        return False

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            return
        self.requests.append(
            {
                "path": scope["path"],
                "method": scope["method"],
                "caller": dict(scope["headers"]).get(b"x-padiem-engine-caller", b"").decode(),
            }
        )
        await send(
            {
                "type": "http.response.start",
                "status": self.status,
                "headers": [(b"content-type", self.content_type.encode())],
            }
        )
        for chunk in self.chunks:
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
            self.sent_at.append(time.monotonic())
            if await self._watch(receive, self.gap):
                self.disconnected = True
                return
        await send({"type": "http.response.body", "body": b"", "more_body": False})
        self.completed = True


class _RunningEngine:
    def __init__(self, app) -> None:
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=0,
                log_level="error",
                access_log=False,
                lifespan="off",
            )
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> str:
        self.thread.start()
        deadline = time.monotonic() + 10
        while not self.server.started:
            if time.monotonic() > deadline:
                raise RuntimeError("stub engine did not start")
            time.sleep(0.01)
        sockets = self.server.servers[0].sockets
        port = sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{port}"

    def __exit__(self, *exc_info) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def _stream_call(transport: LocalEngineHttpTransport):
    return transport.stream_request(
        method="POST",
        url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_STREAM_PATH}",
        headers={
            "X-Padiem-Engine-Caller": "b62-chat-host",
            "X-Padiem-Engine-Credential": "x" * 40,
            "Content-Type": "application/json",
        },
        body=b'{"goal":"turn"}',
    )


async def test_frames_are_handed_on_as_they_arrive():
    frames = (b'{"ok":true,"text_delta":{"delta":"a"}}\n', b'{"ok":true}\n')
    stub = _EngineStub(frames, gap=0.25)
    with _RunningEngine(stub) as origin:
        transport = LocalEngineHttpTransport(origin)
        started = time.monotonic()
        response = await _stream_call(transport)
        assert isinstance(response, EngineStreamTransportResponse)
        assert response.status == 200
        assert response.headers["content-type"].startswith("application/x-ndjson")
        received: list[tuple[float, bytes]] = []
        async for chunk in response.chunks:
            received.append((time.monotonic() - started, chunk))
        await response.chunks.aclose()

    assert [chunk for _, chunk in received] == list(frames)
    # The first frame reached the client long before the stub finished sending
    # the second: the transport never collected the body.
    assert received[0][0] < (received[-1][0] - 0.15)
    assert stub.completed is True
    assert stub.requests[0]["path"] == ENGINE_ORCHESTRATE_STREAM_PATH
    assert stub.requests[0]["caller"] == "b62-chat-host"


async def test_stopping_early_closes_the_engine_connection():
    frames = tuple(b'{"ok":true,"seq":%d}\n' % index for index in range(6))
    stub = _EngineStub(frames, gap=0.4)
    with _RunningEngine(stub) as origin:
        transport = LocalEngineHttpTransport(origin)
        response = await _stream_call(transport)
        first = await response.chunks.__anext__()
        assert first == frames[0]
        await response.chunks.aclose()
        deadline = time.monotonic() + 5
        while not stub.disconnected and time.monotonic() < deadline:
            await asyncio.sleep(0.05)

    assert stub.disconnected is True
    assert stub.completed is False


async def test_an_engine_error_is_a_status_not_a_stream():
    stub = _EngineStub(
        (b'{"ok":false,"error":{"code":"engine_busy"}}',),
        status=503,
        content_type="application/json",
    )
    with _RunningEngine(stub) as origin:
        response = await _stream_call(LocalEngineHttpTransport(origin))
        body = b"".join([chunk async for chunk in response.chunks])
        await response.chunks.aclose()

    assert response.status == 503
    assert response.headers["content-type"].startswith("application/json")
    assert b"engine_busy" in body


@pytest.mark.parametrize(
    "method,url",
    [
        ("GET", f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_STREAM_PATH}"),
        ("POST", f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_PATH}"),
        ("POST", f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_HEALTH_PATH}"),
        ("POST", f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_STREAM_PATH}?x=1"),
        ("POST", "https://elsewhere.internal/internal/v1/orchestrate/stream"),
    ],
)
async def test_only_the_one_stream_target_is_accepted(method, url):
    transport = LocalEngineHttpTransport("http://127.0.0.1:8811")
    with pytest.raises(LocalEngineTransportError):
        await transport.stream_request(method=method, url=url, headers={}, body=b"{}")


async def test_an_oversized_stream_request_is_refused_before_connecting():
    from app.local_engine_transport import MAX_ENGINE_MODEL_REQUEST_BYTES

    transport = LocalEngineHttpTransport("http://127.0.0.1:8811")
    with pytest.raises(LocalEngineTransportError):
        await transport.stream_request(
            method="POST",
            url=f"{ENGINE_INTERNAL_ORIGIN}{ENGINE_ORCHESTRATE_STREAM_PATH}",
            headers={},
            body=b"x" * (MAX_ENGINE_MODEL_REQUEST_BYTES + 1),
        )


def test_the_stream_budget_is_the_engine_model_idle_budget():
    assert DEFAULT_STREAM_TIMEOUT_SECONDS == 600.0
