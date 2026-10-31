"""CPython host runtime for the P01 Engine (COM2, loopback 8811).

``worker.py`` is and stays the Cloudflare entrypoint and the production binding
authority. This module is the second door for the same application on a host
that has no Workers runtime:

    python3 -m uvicorn asgi:app --host 127.0.0.1 --port 8811

Nothing about the routes, authentication or composition is re-implemented here.
The Worker module is imported unchanged and its own ``Default.fetch`` dispatch
answers the request. Two things differ, and both are transport:

* ``workers`` (the Cloudflare runtime package) does not import on CPython — it
  loads ``js``. A minimal local stand-in provides ``Request``, ``Response`` and
  ``WorkerEntrypoint`` so the same module imports and dispatches. It carries no
  Cloudflare behaviour: it is an HTTP request/response pair.
* B14 is a Service Binding on Cloudflare. On the host it is the loopback B14
  service the runbook already documents (``127.0.0.1:8789``), reached through a
  binding-shaped object with the same ``fetch`` call.

A missing local B14 origin keeps the exact Worker fail-closed shape: the binding
is absent, the composition is the unbound one, and every model route refuses.
"""

from __future__ import annotations

import os
import sys
import types
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

LOCAL_DEV_ENV = "PADIEM_LOCAL_DEV"
HOST_ENV = "PADIEM_ENGINE_CPYTHON_HOST"
BIND_HOST_ENV = "P01_HOST"
BIND_PORT_ENV = "P01_PORT"
B14_ORIGIN_ENV = "PADIEM_ENGINE_LOCAL_B14_ORIGIN"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8811
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# The Worker lets the platform bound a model request. A host has to name one.
MAX_ASGI_REQUEST_BYTES = 24 * 1024 * 1024
ASGI_RESPONSE_MAX_BYTES = 64 * 1024 * 1024


class LocalRuntimeError(RuntimeError):
    """A host-only refusal carrying one bounded, public-safe reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Headers:
    """Lowercase HTTP headers with the ``.get`` shape the Worker code uses."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = {str(name).lower(): str(value) for name, value in values.items()}

    def get(self, name: str, default: Any = None) -> Any:
        return self._values.get(str(name).lower(), default)

    def items(self):
        return self._values.items()

    def __iter__(self):
        return iter(self._values)

    def __contains__(self, name: object) -> bool:
        return str(name).lower() in self._values


class LocalRequest:
    """``workers.Request`` stand-in over one already-read ASGI body."""

    def __init__(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: Mapping[str, str] | None = None,
        body: bytes = b"",
    ) -> None:
        self.url = url
        self.method = method.upper()
        self.headers = _Headers(headers or {})
        # The Worker transport builds this with a decoded JSON string body, the
        # ASGI adapter with raw bytes; both mean the same request.
        self._body = body.encode("utf-8") if isinstance(body, str) else bytes(body)

    @property
    def body(self) -> bytes:
        return self._body

    @property
    def js_object(self) -> "LocalRequest":
        """The Service Binding receives the request wrapper itself."""

        return self

    async def text(self) -> str:
        try:
            return self._body.decode("utf-8")
        except UnicodeDecodeError:
            return self._body.decode("utf-8", errors="replace")

    async def json(self) -> Any:
        import json

        return json.loads(await self.text())


class LocalResponse:
    """``workers.Response`` stand-in: one status, headers and a byte body."""

    def __init__(self, body: Any = b"", *, status: int = 200, headers: Mapping[str, str] | None = None) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        elif not isinstance(body, (bytes, bytearray)):
            body = str(body).encode("utf-8")
        self.body = bytes(body)
        self.status = int(status)
        self.headers = dict(headers or {})


class WorkerEntrypoint:
    """``workers.WorkerEntrypoint`` stand-in holding only the local env."""

    def __init__(self, *args: Any, env: Any = None, **kwargs: Any) -> None:
        del args, kwargs
        self.env = env


def install_worker_shims() -> None:
    """Register the Cloudflare runtime stand-in only when it is not installed."""

    try:  # pragma: no cover - the Workers runtime is never present locally
        import workers  # noqa: F401

        return
    except Exception:
        pass
    module = types.ModuleType("workers")
    module.Request = LocalRequest
    module.Response = LocalResponse
    module.WorkerEntrypoint = WorkerEntrypoint
    module.__doc__ = "Local CPython stand-in for the Cloudflare Workers runtime."
    sys.modules["workers"] = module


class _EnvironmentMap:
    """Read-only deployment view the Worker code already expects."""

    def __init__(self, values: Mapping[str, str], bindings: Mapping[str, Any]) -> None:
        self._values = dict(values)
        self._bindings = dict(bindings)

    def __getattr__(self, name: str) -> Any:
        if name in self._bindings:
            return self._bindings[name]
        return self._values.get(name)


class LocalB14Binding:
    """Loopback B14 reached through the Service Binding's own ``fetch`` call."""

    def __init__(self, origin: str, *, timeout: float = 600.0) -> None:
        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in LOOPBACK_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or not parsed.port
        ):
            raise LocalRuntimeError("p01_local_b14_origin_invalid")
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._timeout = timeout

    async def fetch(self, request: Any) -> LocalResponse:
        path = urlsplit(str(request.url)).path
        headers = dict(getattr(request, "headers", {}) or {})
        body = getattr(request, "body", b"")
        if not isinstance(body, (bytes, bytearray)):
            body = bytes(body)
        async with httpx.AsyncClient(follow_redirects=False, timeout=self._timeout) as client:
            try:
                response = await client.request(
                    getattr(request, "method", "POST"),
                    self._origin + path,
                    headers=headers,
                    content=bytes(body),
                )
            except httpx.HTTPError:
                raise LocalRuntimeError("p01_local_b14_unreachable") from None
        return LocalResponse(
            response.content,
            status=response.status_code,
            headers={"content-type": response.headers.get("content-type", "application/json")},
        )


def _flag(values: Mapping[str, str], name: str) -> bool:
    return str(values.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def entry_requirements(values: Mapping[str, str]) -> str:
    """Validate the host entry flags; return the mode or raise a bounded error."""

    local = _flag(values, LOCAL_DEV_ENV)
    host = _flag(values, HOST_ENV)
    if local and host:
        raise LocalRuntimeError("local_dev_and_engine_host_are_mutually_exclusive")
    if not local and not host:
        raise LocalRuntimeError(
            "engine_cpython_entry_requires_PADIEM_LOCAL_DEV_or_PADIEM_ENGINE_CPYTHON_HOST"
        )
    return "dev" if local else "host"


def bind_address(values: Mapping[str, str]) -> tuple[str, int]:
    """Loopback only; a routable bind is a different trust decision."""

    host = str(values.get(BIND_HOST_ENV, DEFAULT_HOST)).strip() or DEFAULT_HOST
    raw_port = str(values.get(BIND_PORT_ENV, DEFAULT_PORT)).strip() or str(DEFAULT_PORT)
    if host not in LOOPBACK_HOSTS:
        raise LocalRuntimeError("p01_bind_not_loopback")
    try:
        port = int(raw_port)
    except ValueError:
        raise LocalRuntimeError("p01_port_invalid") from None
    if not 1 <= port <= 65535:
        raise LocalRuntimeError("p01_port_invalid")
    return host, port


def _local_bindings(values: Mapping[str, str]) -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    origin = str(values.get(B14_ORIGIN_ENV, "")).strip()
    if origin:
        bindings["B14_SERVICE"] = LocalB14Binding(origin)
    # ENGINE_IDEMPOTENCY stays absent: the durable replay lane requires a real
    # store, and the Worker's unbound shape is the truthful host answer.
    return bindings


def _env_view(values: Mapping[str, str]) -> Any:
    return _EnvironmentMap(values, _local_bindings(values))


@dataclass(slots=True)
class LocalEngineApp:
    """ASGI callable around the unchanged Worker dispatch."""

    entry: Any
    values: Mapping[str, str] = field(default_factory=dict)

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            if scope.get("type") == "lifespan":
                await _lifespan(receive, send)
            return
        path = str(scope.get("raw_path", b"/").decode("latin-1") if scope.get("raw_path") else scope.get("path", "/"))
        query = str(scope.get("query_string", b"").decode("latin-1"))
        target = path + (f"?{query}" if query else "")
        method = str(scope.get("method", "GET")).upper()
        headers = {
            str(name.decode("latin-1")).lower(): str(value.decode("latin-1"))
            for name, value in (scope.get("headers") or [])
        }
        body, too_large = await _read_asgi_body(receive)
        if too_large:
            await _send_response(
                send,
                413,
                {"content-type": "application/json; charset=utf-8"},
                b'{"ok":false,"error":{"code":"request_too_large","message":'
                b'"Request body exceeds the host safety limit.","retryable":false,'
                b'"metadata":null}}',
            )
            return
        server_host, server_port = (scope.get("server") or (DEFAULT_HOST, DEFAULT_PORT))[:2]
        url = f"http://{server_host}:{server_port}{target}"
        request = LocalRequest(url, method=method, headers=headers, body=body)
        response = await self.entry.fetch(request)
        raw = getattr(response, "body", None)
        if not isinstance(raw, (bytes, bytearray)):
            # An NDJSON stream lives on the Workers runtime; the host refuses it
            # rather than pretending a buffered body is a stream.
            await _send_response(
                send,
                503,
                {"content-type": "application/json; charset=utf-8"},
                b'{"ok":false,"error":{"code":"engine_stream_not_supported_on_host",'
                b'"message":"Engine streaming is not available on the CPython host.",'
                b'"retryable":false,"metadata":null}}',
            )
            return
        _check_response_size(len(raw))
        await _send_response(
            send,
            int(getattr(response, "status", 200)),
            {str(k).lower(): str(v) for k, v in dict(getattr(response, "headers", {}) or {}).items()},
            bytes(raw),
        )


def _check_response_size(size: int) -> None:
    if size > ASGI_RESPONSE_MAX_BYTES:
        raise LocalRuntimeError("p01_response_too_large")


async def _read_asgi_body(receive: Any) -> tuple[bytes, bool]:
    chunks = bytearray()
    while True:
        message = await receive()
        if message.get("type") == "http.disconnect":
            break
        if message.get("type") != "http.request":
            continue
        chunks.extend(message.get("body", b"") or b"")
        if len(chunks) > MAX_ASGI_REQUEST_BYTES:
            return b"", True
        if not message.get("more_body", False):
            break
    return bytes(chunks), False


async def _send_response(send: Any, status: int, headers: Mapping[str, str], body: bytes) -> None:
    encoded = [(str(name).lower().encode("latin-1"), str(value).encode("latin-1")) for name, value in headers.items()]
    if not any(name == b"content-length" for name, _ in encoded):
        encoded.append((b"content-length", str(len(body)).encode("latin-1")))
    await send({"type": "http.response.start", "status": status, "headers": encoded})
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _lifespan(receive: Any, send: Any) -> None:
    while True:
        message = await receive()
        if message.get("type") == "lifespan.startup":
            await send({"type": "lifespan.startup.complete"})
        elif message.get("type") == "lifespan.shutdown":
            await send({"type": "lifespan.shutdown.complete"})
            return


def create_local_app(values: Mapping[str, str] | None = None) -> LocalEngineApp:
    """Build the host ASGI app over the unchanged Worker dispatch."""

    source = dict(os.environ if values is None else values)
    entry_requirements(source)
    bind_address(source)
    install_worker_shims()
    import worker as engine_worker  # noqa: PLC0415 - after the stand-in is installed

    entry = engine_worker.Default.__new__(engine_worker.Default)
    entry.env = _env_view(source)
    return LocalEngineApp(entry=entry, values=source)


__all__ = [
    "ASGI_RESPONSE_MAX_BYTES",
    "B14_ORIGIN_ENV",
    "BIND_HOST_ENV",
    "BIND_PORT_ENV",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "HOST_ENV",
    "LOCAL_DEV_ENV",
    "LOOPBACK_HOSTS",
    "LocalB14Binding",
    "LocalEngineApp",
    "LocalRequest",
    "LocalResponse",
    "LocalRuntimeError",
    "MAX_ASGI_REQUEST_BYTES",
    "bind_address",
    "create_local_app",
    "entry_requirements",
    "install_worker_shims",
]
