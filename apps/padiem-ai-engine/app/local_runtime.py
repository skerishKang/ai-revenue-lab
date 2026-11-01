"""CPython host runtime for the P01 Engine (COM2, loopback 8811).

``worker_identity.py`` is and stays the Cloudflare entrypoint and the production
binding authority (``wrangler.toml`` ``main``). This module is the second door for
the same application on a host that has no Workers runtime, and it dispatches
through that same entry so a host never answers from the legacy composition:

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

import asyncio
import hashlib
import hmac
import logging
import os
import stat
import time
from pathlib import Path
import sys
import types
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

from app.local_admission_binding import admission_binding_for
from app.local_identity_binding import identity_binding_for
from app.local_sqlite_d1 import (
    LocalSqliteD1,
    apply_engine_migrations,
    connect_local_database,
)

LOCAL_DEV_ENV = "PADIEM_LOCAL_DEV"
HOST_ENV = "PADIEM_ENGINE_CPYTHON_HOST"
BIND_HOST_ENV = "P01_HOST"
BIND_PORT_ENV = "P01_PORT"
B14_ORIGIN_ENV = "PADIEM_ENGINE_LOCAL_B14_ORIGIN"
B14_PROOF_SECRET_ENV = "PADIEM_B14_SERVICE_PROOF_SECRET"
B14_SECRET_DIR_ENV = "B14_SECRET_DIR"
B14_PROOF_HEADER = "x-padiem-b14-proof"
B14_PROOF_TIME_HEADER = "x-padiem-b14-time"
logger = logging.getLogger(__name__)
DB_PATH_ENV = "PADIEM_ENGINE_LOCAL_DB"
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
        get_reader = getattr(body, "getReader", None)
        if callable(get_reader) and not isinstance(body, (bytes, bytearray, str)):
            # A Service Binding response body is read through ``getReader()``.
            self.body = body
            self.status = int(status)
            self.headers = dict(headers or {})
            return
        if isinstance(body, LocalReadableStream):
            # The NDJSON builder hands a stream, not a frame; keep it opaque.
            self.body = body
            self.status = int(status)
            self.headers = dict(headers or {})
            return
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


class _BytesReader:
    """The ``reader`` a JS ReadableStream hands out, over one byte payload."""

    def __init__(self, payload: bytes) -> None:
        self._payload = bytes(payload)
        self._sent = False

    async def read(self) -> Any:
        if self._sent:
            return _ReaderResult(done=True, value=None)
        self._sent = True
        return _ReaderResult(done=False, value=self._payload)

    async def cancel(self) -> None:
        self._sent = True

    def releaseLock(self) -> None:
        return None


class _ReaderResult:
    """``{done, value}`` with attribute access, as the JS reader result has."""

    def __init__(self, *, done: bool, value: Any) -> None:
        self.done = done
        self.value = value


class LocalByteStream:
    """A ReadableStream-shaped byte body for the Service Binding transport.

    ``LocalB14Binding`` answers with an HTTP body, while the binding transport
    reads responses the way a Worker does — through ``body.getReader()``. Without
    this adapter every B14 answer is unreadable and the run reports the model
    service as unavailable even though B14 replied.
    """

    def __init__(self, payload: bytes) -> None:
        self._payload = bytes(payload)

    def getReader(self) -> _BytesReader:
        return _BytesReader(self._payload)


class _StreamController:
    """The ``controller`` the Worker's ``pull`` callback receives."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.closed = False
        self.failed = False

    def enqueue(self, chunk: Any) -> None:
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        self.chunks.append(bytes(chunk))

    def close(self) -> None:
        self.closed = True

    def error(self, _reason: Any = None) -> None:
        self.failed = True
        self.closed = True


class LocalReadableStream:
    """``js.ReadableStream`` stand-in the Worker's NDJSON adapter fills.

    ``worker._ndjson_response`` is reused unchanged: it builds this object with
    its own ``pull``/``cancel`` callbacks, and the ASGI adapter below pumps it
    one chunk at a time. Nothing is buffered, so a client sees each line as the
    Core produced it.
    """

    def __init__(self, source: Any = None) -> None:
        self._source = source if isinstance(source, dict) else {}
        self._finished = False

    async def pump(self, emit: Any) -> None:
        while True:
            controller = _StreamController()
            await self._source["pull"](controller)
            if controller.failed:
                raise LocalRuntimeError("stream_adapter_failed")
            for chunk in controller.chunks:
                await emit(chunk)
            if controller.closed:
                self._finished = True
                return

    async def cancel(self, reason: Any = None) -> None:
        self._finished = True
        cancel = self._source.get("cancel")
        if callable(cancel):
            await cancel(reason)


class _TextEncoder:
    def encode(self, text: Any) -> bytes:
        return str(text).encode("utf-8")


class _TextEncoderFactory:
    """``js.TextEncoder``: the Worker calls ``TextEncoder.new()``."""

    @staticmethod
    def new() -> _TextEncoder:
        return _TextEncoder()


class _ReadableStreamFactory:
    """``js.ReadableStream``: the Worker calls ``ReadableStream.new(source)``."""

    @staticmethod
    def new(source: Any = None) -> LocalReadableStream:
        return LocalReadableStream(source)


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
    # ``worker._ndjson_response`` reaches for the JavaScript stream primitives so
    # the Worker can return a ReadableStream. On the host the same function is
    # reused with a pull/pump stream and identity proxies; no NDJSON logic is
    # restated, and a Worker response is never buffered into one body.
    js = sys.modules.get("js")
    if js is None:
        js = types.ModuleType("js")
        js.__doc__ = "Local CPython stand-in for the JavaScript globals."
        sys.modules["js"] = js
    js.TextEncoder = _TextEncoderFactory
    js.ReadableStream = _ReadableStreamFactory
    if "pyodide" not in sys.modules:
        pyodide = types.ModuleType("pyodide")
        ffi = types.ModuleType("pyodide.ffi")
        ffi.create_proxy = lambda value: value
        ffi.to_js = lambda value: value
        pyodide.ffi = ffi
        sys.modules["pyodide"] = pyodide
        sys.modules["pyodide.ffi"] = ffi


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

    def __init__(self, origin: str, *, values: Mapping[str, str] | None = None, timeout: float = 600.0) -> None:
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
        source = os.environ if values is None else values
        self._values = {name: source.get(name, "") for name in (B14_PROOF_SECRET_ENV, B14_SECRET_DIR_ENV)}

    def _proof_secret(self) -> str:
        """Environment first, then the private named file used by B14."""
        raw = self._values.get(B14_PROOF_SECRET_ENV, "")
        if isinstance(raw, str) and raw:
            return raw
        directory = str(self._values.get(B14_SECRET_DIR_ENV, "") or "").strip()
        if not directory:
            return ""
        path = Path(directory).expanduser() / B14_PROOF_SECRET_ENV
        try:
            mode = path.stat().st_mode
            if not stat.S_ISREG(mode) or (os.name == "posix" and mode & 0o077):
                return ""
            return path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return ""

    async def fetch(self, request: Any) -> LocalResponse:
        path = urlsplit(str(request.url)).path
        # ``LocalRequest.headers`` is a ``_Headers`` view with ``items()`` but no
        # ``keys()``, so ``dict(headers)`` raised here and every B14 call ended as
        # "Service Binding is unavailable" before a socket was opened.
        raw_headers = getattr(request, "headers", None)
        items = getattr(raw_headers, "items", None)
        headers = dict(items()) if callable(items) else dict(raw_headers or {})
        body = getattr(request, "body", b"")
        if not isinstance(body, (bytes, bytearray)):
            body = bytes(body)
        payload = bytes(body)
        secret = self._proof_secret()
        if len(secret) < 32:
            raise LocalRuntimeError("p01_local_b14_proof_unconfigured")
        timestamp = str(int(time.time()))
        proof = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + payload, hashlib.sha256).hexdigest()
        # Replace any incoming proof case-insensitively with one made for these exact bytes.
        headers = {k: v for k, v in headers.items() if str(k).lower() not in {B14_PROOF_HEADER, B14_PROOF_TIME_HEADER}}
        headers[B14_PROOF_TIME_HEADER] = timestamp
        headers[B14_PROOF_HEADER] = proof
        async with httpx.AsyncClient(follow_redirects=False, timeout=self._timeout) as client:
            try:
                response = await client.request(
                    getattr(request, "method", "POST"),
                    self._origin + path,
                    headers=headers,
                    content=payload,
                )
            except httpx.HTTPError:
                raise LocalRuntimeError("p01_local_b14_unreachable") from None
        return LocalResponse(
            # The binding transport reads ``body.getReader()``; hand it a stream
            # rather than raw bytes so a real B14 answer is readable.
            LocalByteStream(response.content),
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
        binding = LocalB14Binding(origin, values=values)
        if len(binding._proof_secret()) < 32:
            logger.warning("p01_local_b14_proof_unconfigured")
        bindings["B14_SERVICE"] = binding
    path = str(values.get(DB_PATH_ENV, "")).strip()
    if path:
        bindings["ENGINE_IDEMPOTENCY"] = _local_database(path)
    # The admission authority stays in Cloudflare. A configured https origin and
    # service secret give this host a binding-shaped stand-in, so the reviewed
    # adapter composes unchanged; without them the binding is absent and every
    # model route keeps the Worker's 503 `entitlement_unavailable`.
    bindings.update(admission_binding_for(values))
    # Same session/scope authority as worker_identity.py on Cloudflare. This
    # read does not substitute for Chat's canonical-subject resolution or the
    # admission Worker's own authoritative entitlement/session checks.
    bindings.update(identity_binding_for(values))
    # Without a configured path the binding stays absent, so every durable lane
    # keeps the Worker's own fail-closed answer instead of a process-local fake.
    return bindings


_DATABASES: dict[str, LocalSqliteD1] = {}


def _local_database(path: str) -> LocalSqliteD1:
    """One migrated Engine database per process, keyed by its own path."""

    existing = _DATABASES.get(path)
    if existing is not None:
        return existing
    connection = connect_local_database(path)
    apply_engine_migrations(connection)
    binding = LocalSqliteD1(connection)
    _DATABASES[path] = binding
    return binding


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
        status = int(getattr(response, "status", 200))
        headers = {
            str(name).lower(): str(value)
            for name, value in dict(getattr(response, "headers", {}) or {}).items()
        }
        if isinstance(raw, LocalReadableStream):
            # The Worker's own ``_ndjson_response`` produced this stream; forward
            # each line the moment it exists instead of collecting the body.
            await _send_stream(send, receive, status, headers, raw)
            return
        if not isinstance(raw, (bytes, bytearray)):
            await _send_response(
                send,
                503,
                {"content-type": "application/json; charset=utf-8"},
                b'{"ok":false,"error":{"code":"engine_stream_not_supported_on_host",'
                b'"message":"Engine response body is not a host-readable frame.",'
                b'"retryable":false,"metadata":null}}',
            )
            return
        _check_response_size(len(raw))
        await _send_response(send, status, headers, bytes(raw))


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


async def _send_stream(
    send: Any,
    receive: Any,
    status: int,
    headers: Mapping[str, str],
    stream: LocalReadableStream,
) -> None:
    """Pump one Worker ReadableStream into ASGI, one chunk at a time."""

    encoded = [
        (str(name).lower().encode("latin-1"), str(value).encode("latin-1"))
        for name, value in headers.items()
    ]
    if not any(name == b"content-length" for name, _ in encoded):
        encoded.append((b"transfer-encoding", b"chunked"))
    await send({"type": "http.response.start", "status": status, "headers": encoded})
    disconnected = asyncio.Event()

    async def watch_disconnect() -> None:
        while True:
            message = await receive()
            if message.get("type") == "http.disconnect":
                disconnected.set()
                return

    async def emit(chunk: bytes) -> None:
        if disconnected.is_set():
            raise LocalRuntimeError("client_disconnected")
        await send({"type": "http.response.body", "body": chunk, "more_body": True})

    watcher = asyncio.create_task(watch_disconnect())
    try:
        await stream.pump(emit)
    except BaseException:
        # Close the Core generator so a broken or abandoned response leaves no
        # work running; a real failure is re-raised so the connection aborts
        # instead of looking like a complete answer.
        await stream.cancel()
        if disconnected.is_set():
            return
        raise
    else:
        if not disconnected.is_set():
            await send({"type": "http.response.body", "body": b"", "more_body": False})
    finally:
        watcher.cancel()


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
    # The deployed Worker's entry is ``worker_identity.py`` (wrangler.toml
    # ``main``). The host must dispatch through the same canonical composition —
    # the legacy ``worker.Default`` carries the narrower preview bundle, and a
    # host running it would answer from a different Engine than Production.
    import worker_identity as engine_worker  # noqa: PLC0415 - after the stand-in

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
    "DB_PATH_ENV",
    "LocalB14Binding",
    "LocalEngineApp",
    "LocalReadableStream",
    "LocalRequest",
    "LocalResponse",
    "LocalRuntimeError",
    "MAX_ASGI_REQUEST_BYTES",
    "bind_address",
    "create_local_app",
    "entry_requirements",
    "install_worker_shims",
]
