"""CPython-host Engine transport for the P01 lane (#6356 follow-up, 2026-10-31).

On Cloudflare the P01 client travels a Service Binding
(``CloudflareEngineServiceTransport`` in ``worker_orchestration``). A native
CPython host has no bindings at all, so the tick's Engine gate could only report
``NOT_CONFIGURED reason=p01_engine_transport_unbound``.

This module is that missing transport and nothing more: one bounded
JSON-over-loopback-HTTP call to a co-located Engine, over the same closed path
allowlist and the same byte limits the Worker transport enforces. The client
still builds every URL from ``ENGINE_INTERNAL_ORIGIN``; only the origin the
socket connects to is the configured loopback origin, so no caller can widen
the target.

Deliberately absent: NDJSON streaming, retries, redirect following and any
non-loopback target. A host transport that guesses at those would be a second
Engine protocol, not a host stand-in for the existing one.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from urllib.parse import urlparse
from time import perf_counter
from .request_timing import timed_async, record_duration

import httpx

from padiem_ai_core.b14_multimodal import MAX_B14_IMAGE_BYTES
from padiem_ai_engine_client import (
    ENGINE_DOCUMENT_ADMISSION_PATH,
    ENGINE_HEALTH_PATH,
    ENGINE_INTERNAL_ORIGIN,
    ENGINE_MULTIMODAL_ATTACHMENTS_PATH,
    ENGINE_ORCHESTRATE_CANCEL_PATH,
    ENGINE_ORCHESTRATE_PATH,
    ENGINE_ORCHESTRATE_RESUME_PATH,
    ENGINE_ORCHESTRATE_STREAM_PATH,
    ENGINE_RESEARCH_PATH,
    EngineStreamTransportResponse,
    EngineTransportResponse,
)
from padiem_ai_engine_client.orchestration_stream import MAX_NDJSON_TERMINAL_LINE_BYTES

# Same envelope as ``worker_orchestration``: a Host/Worker parity test pins these
# values, so a later widening of one side cannot silently skip the other.
MAX_ENGINE_REQUEST_BYTES = 256 * 1024
MAX_ENGINE_MODEL_REQUEST_BYTES = 6_000_000
MAX_ENGINE_RESPONSE_BYTES = 10 * 1024 * 1024
MODEL_REQUEST_PATHS = frozenset(
    {
        ENGINE_ORCHESTRATE_PATH,
        ENGINE_ORCHESTRATE_RESUME_PATH,
        ENGINE_ORCHESTRATE_STREAM_PATH,
    }
)
_MAX_ATTACHMENT_BASE64_CHARS = ((MAX_B14_IMAGE_BYTES + 2) // 3) * 4 + 4
MAX_ATTACHMENT_REQUEST_BYTES = _MAX_ATTACHMENT_BASE64_CHARS + (8 * 1024)
ALLOWED_PATHS = frozenset(
    {
        ENGINE_HEALTH_PATH,
        ENGINE_RESEARCH_PATH,
        ENGINE_ORCHESTRATE_PATH,
        ENGINE_ORCHESTRATE_RESUME_PATH,
        ENGINE_ORCHESTRATE_CANCEL_PATH,
        ENGINE_MULTIMODAL_ATTACHMENTS_PATH,
        ENGINE_DOCUMENT_ADMISSION_PATH,
    }
)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_TIMEOUT_SECONDS = 30.0
# The Worker path has no client-side read cap; its bound is the deployment's
# model idle budget. The host uses the same number the Engine itself applies.
DEFAULT_STREAM_TIMEOUT_SECONDS = 600.0
# A non-200 Engine answer is one bounded JSON error, never a stream.
MAX_STREAM_ERROR_BODY_BYTES = 64 * 1024
STREAM_CHUNK_BYTES = 65_536
STREAM_PATHS = frozenset({ENGINE_ORCHESTRATE_STREAM_PATH})


class LocalEngineTransportError(ValueError):
    """A host Engine target or response that the transport refuses to carry."""


def local_engine_origin(value: object) -> str:
    """Return the normalized loopback origin, or refuse it.

    Only a bare ``http://<loopback>:<port>`` is accepted: the Engine is
    co-located with the Chat host, so a routable origin would mean a different
    trust boundary and no TLS/credential decision has been made for it.
    """

    raw = value.strip() if isinstance(value, str) else ""
    parsed = urlparse(raw)
    try:
        port = parsed.port
    except ValueError:
        raise LocalEngineTransportError("local engine origin had an invalid port") from None
    if (
        not raw
        or parsed.scheme != "http"
        or parsed.hostname not in LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or not port
    ):
        raise LocalEngineTransportError(
            "local engine origin must be a bare loopback http origin"
        )
    return f"http://{parsed.netloc}"


class LocalEngineHttpTransport:
    """``EngineTransport`` over one loopback HTTP origin.

    ``client`` is injectable so a test can supply a MockTransport; otherwise one
    short-lived client per request is used, because a cron tick runs inside its
    own event loop and a cached client would be bound to a dead one.
    """

    def __init__(
        self,
        origin: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = MAX_ENGINE_RESPONSE_BYTES,
        stream_timeout: float = DEFAULT_STREAM_TIMEOUT_SECONDS,
    ) -> None:
        self._origin = local_engine_origin(origin)
        self._client = client
        # #6615: completed (non-stream) Engine calls reuse one client per event
        # loop. A cron tick builds its own loop, so the client is keyed by loop
        # rather than cached globally — the reason this module used to open one
        # per request no longer applies to the completed lane.
        self._clients: dict[int, httpx.AsyncClient] = {}
        self._timeout = timeout
        self._max_response_bytes = max_response_bytes
        self._stream_timeout = stream_timeout
        if client is not None and getattr(client, "follow_redirects", False):
            raise LocalEngineTransportError(
                "local engine client must not follow redirects"
            )

    @property
    def origin(self) -> str:
        return self._origin

    @timed_async('p01')
    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> EngineTransportResponse:
        path, normalized_method, forwarded = self._validated(
            method=method, url=url, headers=headers, body=body
        )
        target = self._origin + path
        if self._client is not None:
            return await self._send(self._client, normalized_method, target, forwarded, body)
        return await self._send(
            self._loop_client(), normalized_method, target, forwarded, body
        )

    def _loop_client(self) -> httpx.AsyncClient:
        """The completed-lane client for the running loop, created on first use."""
        loop_key = id(asyncio.get_running_loop())
        client = self._clients.get(loop_key)
        if client is None:
            client = httpx.AsyncClient(follow_redirects=False, timeout=self._timeout)
            self._clients[loop_key] = client
        return client

    async def aclose(self) -> None:
        """Close every pooled completed-lane client (host shutdown)."""
        clients, self._clients = self._clients, {}
        for client in clients.values():
            await client.aclose()

    async def stream_request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> EngineStreamTransportResponse:
        """Carry the Engine's NDJSON stream one chunk at a time (#3930 parity).

        Same target rules as the Worker transport: POST on the one stream path,
        bounded request body, no redirects. Unlike the completed lane this never
        buffers the answer: each chunk is handed on as it arrives, and closing
        the iterator tears the Engine connection down so the Engine's own
        disconnect watcher stops the Core run.
        """

        path, normalized_method, forwarded = self._validated(
            method=method,
            url=url,
            headers=headers,
            body=body,
            extra_paths=STREAM_PATHS,
        )
        if normalized_method != "POST" or path not in STREAM_PATHS:
            raise LocalEngineTransportError(
                "Engine stream target or request is unsupported"
            )
        target = self._origin + path
        client = self._client
        started = perf_counter()
        owns_client = client is None
        if client is None:
            client = httpx.AsyncClient(
                follow_redirects=False, timeout=self._stream_timeout
            )
        try:
            request = client.build_request(
                normalized_method, target, headers=forwarded, content=body
            )
            response = await client.send(request, stream=True)
        except httpx.HTTPError:
            record_duration('p01', (perf_counter() - started) * 1000)
            if owns_client:
                await client.aclose()
            raise LocalEngineTransportError(
                "local engine stream request failed"
            ) from None
        content_type = str(response.headers.get("content-type", ""))
        status = int(response.status_code)

        if status != 200:
            # The Engine answers an error as JSON, not as events. Read it bounded
            # so the client can report the status instead of parsing garbage.
            buffered = bytearray()
            try:
                async for chunk in response.aiter_bytes():
                    buffered.extend(chunk)
                    if len(buffered) > MAX_STREAM_ERROR_BODY_BYTES:
                        break
            except httpx.HTTPError:
                pass
            finally:
                await response.aclose()
                if owns_client:
                    await client.aclose()
                record_duration('p01', (perf_counter() - started) * 1000)
            return EngineStreamTransportResponse(
                status=status,
                chunks=_once(bytes(buffered)),
                headers={"content-type": content_type or "application/json"},
            )

        async def iter_chunks():
            try:
                async for chunk in response.aiter_bytes():
                    if len(chunk) > MAX_NDJSON_TERMINAL_LINE_BYTES:
                        raise LocalEngineTransportError(
                            "Engine stream chunk exceeded the safety bound"
                        )
                    for start in range(0, len(chunk), STREAM_CHUNK_BYTES):
                        yield chunk[start:start + STREAM_CHUNK_BYTES]
            except httpx.HTTPError:
                raise LocalEngineTransportError(
                    "local engine stream was interrupted"
                ) from None
            finally:
                await response.aclose()
                if owns_client:
                    await client.aclose()
                record_duration('p01', (perf_counter() - started) * 1000)

        return EngineStreamTransportResponse(
            status=status,
            chunks=iter_chunks(),
            headers={"content-type": content_type or "application/x-ndjson"},
        )

    def _validated(
        self,
        *,
        method: object,
        url: object,
        headers: Mapping[str, str],
        body: bytes | None,
        extra_paths: frozenset[str] = frozenset(),
    ) -> tuple[str, str, dict[str, str]]:
        normalized_method = method.upper() if isinstance(method, str) else ""
        parsed = urlparse(url) if isinstance(url, str) else None
        expected_netloc = urlparse(ENGINE_INTERNAL_ORIGIN).netloc
        if (
            parsed is None
            or parsed.scheme != "https"
            or parsed.netloc != expected_netloc
            or parsed.query
            or parsed.fragment
            or parsed.path not in (ALLOWED_PATHS | extra_paths)
            or normalized_method not in {"GET", "POST"}
            or (parsed.path == ENGINE_HEALTH_PATH and normalized_method != "GET")
            or (parsed.path != ENGINE_HEALTH_PATH and normalized_method != "POST")
        ):
            raise LocalEngineTransportError(
                "Engine client requested an unsupported internal target"
            )
        if body is not None:
            if not isinstance(body, bytes):
                raise LocalEngineTransportError("Engine request body must be bytes")
            if len(body) > self._body_limit(parsed.path):
                raise LocalEngineTransportError(
                    "Engine request exceeded the host transport safety limit"
                )
        forwarded = {str(name): str(value) for name, value in dict(headers).items()}
        if body is not None and not any(
            name.lower() == "content-type" for name in forwarded
        ):
            forwarded["content-type"] = "application/json"
        return parsed.path, normalized_method, forwarded

    def _body_limit(self, path: str) -> int:
        if path == ENGINE_MULTIMODAL_ATTACHMENTS_PATH:
            return MAX_ATTACHMENT_REQUEST_BYTES
        if path in MODEL_REQUEST_PATHS:
            return MAX_ENGINE_MODEL_REQUEST_BYTES
        return MAX_ENGINE_REQUEST_BYTES

    async def _send(
        self,
        client: httpx.AsyncClient,
        method: str,
        target: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> EngineTransportResponse:
        received = bytearray()
        try:
            async with client.stream(
                method, target, headers=headers, content=body
            ) as response:
                async for chunk in response.aiter_bytes():
                    received.extend(chunk)
                    if len(received) > self._max_response_bytes:
                        raise LocalEngineTransportError(
                            "Engine response exceeded the host transport safety limit"
                        )
                content_type = response.headers.get("content-type")
                response_headers = (
                    {"content-type": str(content_type)} if content_type else {}
                )
                return EngineTransportResponse(
                    status=int(response.status_code),
                    body=bytes(received),
                    headers=response_headers,
                )
        except httpx.HTTPError:
            # Connection, timeout and protocol failures carry a URL and a type
            # that must not travel into a public status line.
            raise LocalEngineTransportError("local engine request failed") from None


__all__ = [
    "ALLOWED_PATHS",
    "DEFAULT_STREAM_TIMEOUT_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "LOOPBACK_HOSTS",
    "LocalEngineHttpTransport",
    "LocalEngineTransportError",
    "MAX_ATTACHMENT_REQUEST_BYTES",
    "MAX_ENGINE_MODEL_REQUEST_BYTES",
    "MAX_ENGINE_REQUEST_BYTES",
    "MAX_ENGINE_RESPONSE_BYTES",
    "MAX_STREAM_ERROR_BODY_BYTES",
    "MODEL_REQUEST_PATHS",
    "STREAM_PATHS",
    "local_engine_origin",
]


async def _once(payload: bytes):
    """A single-frame iterator for a non-200 Engine answer."""

    if payload:
        yield payload
