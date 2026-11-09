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
import json
from contextvars import ContextVar
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
from app.local_google_oauth_binding import google_oauth_binding_for
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
# The Cloudflare entry receives ``PADIEM_CHAT_SERVICE`` as a Service Binding
# object. The host names the loopback Chat origin instead and this module
# publishes it under the same binding name the unchanged Worker code reads.
CHAT_SERVICE_ENV = "PADIEM_ENGINE_LOCAL_CHAT_ORIGIN"
CHAT_SERVICE_BINDING_NAME = "PADIEM_CHAT_SERVICE"
# The COM2 edge middleware (Chat host, ``com2_edge_middleware.py``) refuses
# every non-health request that does not carry the four ``x-padiem-edge-*``
# headers signed with the same secret file the Chat host reads. The binding
# below signs each forwarded call with exactly that material; without it the
# desktop lane stays off instead of shipping calls that die at the edge.
CHAT_EDGE_SECRET_FILE_ENV = "PADIEM_COM2_EDGE_SECRET_FILE"
# A loopback hop carries no TLS, and the edge verifier accepts exactly these
# two labels; TLSv1.3 is the strongest the scheme admits. What protects this
# hop is the HMAC proof, the one-time request id and the loopback-only binding
# — not transport encryption.
_EDGE_TLS_VERSION = "TLSv1.3"
logger = logging.getLogger(__name__)
DB_PATH_ENV = "PADIEM_ENGINE_LOCAL_DB"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8811
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
# The Worker lets the platform bound a model request. A host has to name one.
MAX_ASGI_REQUEST_BYTES = 24 * 1024 * 1024
ASGI_RESPONSE_MAX_BYTES = 64 * 1024 * 1024

# Correlation only: service identity and app authorization still run in the
# unchanged Engine dispatch before any B14 call. Never persist per-request
# attribution on the shared binding; simultaneous apps must stay independent.
_APPS_AI_CLIENT_APP: ContextVar[str | None] = ContextVar("apps_ai_client_app", default=None)
_APPS_AI_NAMES = frozenset({"storymemory", "bookai"})


def _apps_ai_origin(request: "LocalRequest") -> str | None:
    if request.method != "POST" or urlsplit(request.url).path != "/internal/v1/execute":
        return None
    client_app = request.headers.get("x-padiem-client-app")
    if client_app not in _APPS_AI_NAMES:
        return None
    try:
        payload = json.loads(request.body)
    except (UnicodeError, ValueError):
        return None
    return client_app if isinstance(payload, dict) and payload.get("app_id") == "b61" else None


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


class _PyBuffer:
    """``ArrayBuffer`` stand-in; ``to_py()`` is the Pyodide bridge in use."""

    def __init__(self, payload: bytes) -> None:
        self._payload = bytes(payload)

    def to_py(self) -> bytes:
        return self._payload


class LocalServiceResponse:
    """Service Binding response with the Worker read methods the drivers call."""

    def __init__(
        self, payload: bytes, *, status: int, headers: Mapping[str, str] | None = None,
    ) -> None:
        self._payload = bytes(payload)
        self.status = int(status)
        self.headers = dict(headers or {})

    async def text(self) -> str:
        return self._payload.decode("utf-8", errors="replace")

    async def arrayBuffer(self) -> _PyBuffer:
        return _PyBuffer(self._payload)


def _chat_edge_secret_from_file(path: str) -> str:
    """The COM2 edge proof secret from the same file the Chat host reads.

    Regular file only, group/world bits refused on POSIX, and anything shorter
    than the verifier's 32-byte floor counts as absent.
    """
    if not path:
        return ""
    try:
        st = os.stat(path)
    except OSError:
        return ""
    if not stat.S_ISREG(st.st_mode):
        return ""
    if os.name == "posix" and st.st_mode & 0o077:
        return ""
    try:
        secret = Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""
    return secret if len(secret) >= 32 else ""


class LocalChatServiceBinding:
    """The host stand-in for the Chat Service Binding (loopback only).

    The Engine's signed desktop and PC-query drivers call ``fetch`` with a
    request they already signed; this forwards it to the local Chat origin and
    adds the four ``x-padiem-edge-*`` headers Chat's edge middleware requires
    (signed with the shared ``PADIEM_COM2_EDGE_SECRET_FILE`` material, one
    fresh request id per call). A non-loopback origin is refused, so this
    binding can never carry a proof secret off the host.
    """

    def __init__(
        self, origin: str, *, timeout: float = 60.0, client: Any = None,
        values: Mapping[str, str] | None = None,
    ) -> None:
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
            raise LocalRuntimeError("p01_local_chat_origin_invalid")
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._timeout = timeout
        self._client = client
        source = os.environ if values is None else values
        self._edge_file = str(
            source.get(CHAT_EDGE_SECRET_FILE_ENV, "") or ""
        ).strip()

    def _edge_secret(self) -> str:
        """Fresh read per call so an operator rotation lands without a restart."""
        return _chat_edge_secret_from_file(self._edge_file)

    @staticmethod
    def _edge_headers(method: str, path: str, secret: str) -> dict[str, str]:
        """The four headers Chat's edge verifier expects, one fresh id per call.

        The proof signs ``v1\\n{method}\\n{path}\\n{at}\\n{id}\\n{tls}`` — the
        same composition ``EdgeProofVerifier.verify`` checks. A retry of the
        same engine request calls ``fetch`` again and therefore signs with a
        new request id, so Chat's durable replay store never sees a repeat.
        """
        at = str(int(time.time()))
        request_id = os.urandom(32).hex()
        signed = "\n".join(
            ("v1", method, path, at, request_id, _EDGE_TLS_VERSION),
        ).encode("utf-8")
        proof = "v1=" + hmac.new(
            secret.encode("utf-8"), signed, hashlib.sha256,
        ).hexdigest()
        return {
            "x-padiem-edge-at": at,
            "x-padiem-edge-id": request_id,
            "x-padiem-edge-tls": _EDGE_TLS_VERSION,
            "x-padiem-edge-proof": proof,
        }

    async def fetch(self, request: Any) -> LocalServiceResponse:
        parsed = urlsplit(str(request.url))
        forward_path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        raw_headers = getattr(request, "headers", None)
        items = getattr(raw_headers, "items", None)
        headers = dict(items()) if callable(items) else dict(raw_headers or {})
        edge = self._edge_secret()
        if len(edge) < 32:
            # An unsigned forward would die at Chat's edge middleware with a
            # bare 403; refusing here keeps the failure loud and local.
            raise LocalRuntimeError("p01_local_chat_edge_unconfigured")
        method = str(getattr(request, "method", "POST") or "POST").upper()
        headers = {**headers, **self._edge_headers(method, parsed.path, edge)}
        body = getattr(request, "body", b"")
        if not isinstance(body, (bytes, bytearray)):
            body = bytes(body)
        client = (
            self._client
            or httpx.AsyncClient(follow_redirects=False, timeout=self._timeout)
        )
        try:
            response = await client.request(
                method,
                self._origin + forward_path,
                headers=headers,
                content=bytes(body),
            )
        except httpx.HTTPError:
            raise LocalRuntimeError("p01_local_chat_unreachable") from None
        finally:
            if self._client is None:
                await client.aclose()
        return LocalServiceResponse(
            response.content,
            status=response.status_code,
            headers={"content-type": response.headers.get("content-type", "application/json")},
        )


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

    def __init__(
        self,
        origin: str,
        *,
        values: Mapping[str, str] | None = None,
        timeout: float = 600.0,
        client: Any = None,
    ) -> None:
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
        # One client per event loop, created on first use and then reused for every
        # later B14 call (#6614/#6616's pattern). A fresh client per request paid a
        # full TCP handshake and pool teardown on every P01 model request.
        # An injected client belongs to the caller and is never closed here.
        self._client = client
        self._clients: dict[int, tuple[asyncio.AbstractEventLoop, Any]] = {}
        source = os.environ if values is None else values
        self._values = {name: source.get(name, "") for name in (B14_PROOF_SECRET_ENV, B14_SECRET_DIR_ENV)}

    def _loop_client(self) -> Any:
        """The running loop's B14 client, created on first use."""
        if self._client is not None:
            return self._client
        loop = asyncio.get_running_loop()
        loop_key = id(loop)
        # id(loop) is reused once a finished loop is collected: drop clients of
        # closed loops and check the owner, so a later loop never gets a client
        # bound to a dead loop (and entries do not pile up per cron tick).
        for key in [k for k, (owner, _) in self._clients.items() if owner.is_closed()]:
            del self._clients[key]
        entry = self._clients.get(loop_key)
        client = entry[1] if entry is not None and entry[0] is loop else None
        if client is None:
            client = httpx.AsyncClient(follow_redirects=False, timeout=self._timeout)
            self._clients[loop_key] = (loop, client)
        return client

    async def aclose(self) -> None:
        """Close every pooled client on host shutdown; an injected one is the caller's."""
        clients, self._clients = self._clients, {}
        for _owner, client in clients.values():
            await client.aclose()

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
        client_app = _APPS_AI_CLIENT_APP.get()
        if client_app is not None:
            # Existing B14 ledger reads these allowlisted correlation headers
            # alongside its already-measured model, status and attempt outcome.
            # #6954: a request that already carries the turn's product identity
            # (the same chat/claw value the metrics report binds) keeps it —
            # overwriting it here detached every PC-turn metrics report from its
            # ledger row. Only an unbranded lane is attributed to the engine.
            branded = any(str(key).lower() == "x-padiem-product" for key in headers)
            if not branded:
                headers["x-padiem-product"] = "engine"
            headers = {k: v for k, v in headers.items()
                       if str(k).lower() != "x-padiem-client-app"}
            headers["x-padiem-client-app"] = client_app
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
        client = self._loop_client()
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


#: Every B14 binding this process composed, so host shutdown can close the
#: pooled clients it handed out. Process-local and append-only; the lifespan hook
#: drains it once.
_B14_BINDINGS: list["LocalB14Binding"] = []


def _local_bindings(values: Mapping[str, str]) -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    origin = str(values.get(B14_ORIGIN_ENV, "")).strip()
    if origin:
        binding = LocalB14Binding(origin, values=values)
        if len(binding._proof_secret()) < 32:
            logger.warning("p01_local_b14_proof_unconfigured")
        _B14_BINDINGS.append(binding)
        bindings["B14_SERVICE"] = binding
    chat_origin = str(values.get(CHAT_SERVICE_ENV, "")).strip()
    if not chat_origin:
        logger.info("p01_local_chat_service=unconfigured")
    elif len(_chat_edge_secret_from_file(
            str(values.get(CHAT_EDGE_SECRET_FILE_ENV, "") or "").strip())) < 32:
        # Loud disable: without the edge material every forwarded call dies at
        # Chat's edge middleware, so the desktop tools stay off instead of
        # publishing a binding that can only produce rejections.
        logger.warning("p01_local_chat_edge_unconfigured")
    else:
        try:
            bindings[CHAT_SERVICE_BINDING_NAME] = LocalChatServiceBinding(
                chat_origin, values=values,
            )
        except LocalRuntimeError:
            # A foreign or malformed origin leaves the binding absent: the
            # desktop tools stay off instead of forwarding a proof off-host.
            logger.warning("p01_local_chat_origin_invalid")
        else:
            logger.info("p01_local_chat_service=configured")
    path = str(values.get(DB_PATH_ENV, "")).strip()
    if path:
        database = _local_database(path)
        bindings["ENGINE_IDEMPOTENCY"] = database
        # Cloudflare declares both names over the SAME provisioned D1 database
        # (wrangler.toml: padiem-engine, migrations/0003 creates the grants
        # table). This host has one engine database with every migration
        # applied, so the second name is the same object — not a second store,
        # not a second schema and not a credential. The Calendar READ lane
        # writes and reads its grants here.
        bindings["ENGINE_CONNECTOR_GRANTS"] = database
        # #7306: the Worker composes three more durable Engine stores over the
        # ENGINE_IMAGE_STORE / ENGINE_EVIDENCE_STORE / ENGINE_CONTINUATION D1
        # bindings (worker_identity.py). This host has one engine database with
        # every migration applied, so the same object answers all three names:
        # the multimodal image byte store, the document evidence store and the
        # approval continuation store. Without these names those lanes fail
        # closed on this host only, while the Worker answers them.
        bindings["ENGINE_IMAGE_STORE"] = database
        bindings["ENGINE_EVIDENCE_STORE"] = database
        bindings["ENGINE_CONTINUATION"] = database
    # The admission authority stays in Cloudflare. A configured https origin and
    # service secret give this host a binding-shaped stand-in, so the reviewed
    # adapter composes unchanged; without them the binding is absent and every
    # model route keeps the Worker's 503 `entitlement_unavailable`.
    bindings.update(admission_binding_for(values))
    # Same session/scope authority as worker_identity.py on Cloudflare. This
    # read does not substitute for Chat's canonical-subject resolution or the
    # admission Worker's own authoritative entitlement/session checks.
    bindings.update(identity_binding_for(values))
    # Same private Google OAuth authority as worker_identity.py's Calendar
    # composition, over the reviewed v2 HTTPS RPC. Unconfigured keeps the
    # binding absent, so the Calendar lane answers today's 503 and no host ever
    # invents a binding selection (see
    # docs/operations/COM2_P01_CONTROL_PLANE_BINDINGS_20261109.md).
    bindings.update(google_oauth_binding_for(values))
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
        origin_token = _APPS_AI_CLIENT_APP.set(_apps_ai_origin(request))
        try:
            response = await self.entry.fetch(request)
        finally:
            _APPS_AI_CLIENT_APP.reset(origin_token)
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
            from app.local_admission_binding import start_admission_warmers

            # (#6972) the admission warm cycle used to wait for the first
            # authority call, so a host that idled between turns stayed cold for
            # hours and paid the handshake and cold-isolate cost on its first
            # turn. The loop exists here: fire the first ping now and let the
            # periodic re-arm take over. Shutdown still cancels everything.
            try:
                start_admission_warmers()
            except Exception:  # noqa: BLE001 - warming is not a boot dependency
                logger.warning("p01_local_admission_warm_start_failed")
            await send({"type": "lifespan.startup.complete"})
        elif message.get("type") == "lifespan.shutdown":
            # The pooled B14 clients outlive individual requests, so the host owns
            # closing them; a failure here must not skip the shutdown handshake.
            while _B14_BINDINGS:
                binding = _B14_BINDINGS.pop()
                try:
                    await binding.aclose()
                except Exception:  # noqa: BLE001 - shutdown never masks the exit
                    logger.warning("p01_local_b14_client_close_failed")
            from app.local_admission_binding import close_pooled_clients

            await close_pooled_clients()
            await send({"type": "lifespan.shutdown.complete"})
            return


def create_local_app(values: Mapping[str, str] | None = None) -> LocalEngineApp:
    """Build the host ASGI app over the unchanged Worker dispatch."""

    source = dict(os.environ if values is None else values)
    entry_requirements(source)
    bind_address(source)
    install_worker_shims()
    # The host configures no application logging; bind the stage-time line to
    # stderr so the COM2 journal receives it. Worker deployments keep theirs.
    from app.engine_timing import ensure_host_visible

    ensure_host_visible()
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
    "LocalChatServiceBinding",
    "LocalEngineApp",
    "LocalReadableStream",
    "LocalRequest",
    "LocalResponse",
    "LocalServiceResponse",
    "LocalRuntimeError",
    "MAX_ASGI_REQUEST_BYTES",
    "bind_address",
    "create_local_app",
    "entry_requirements",
    "install_worker_shims",
]
