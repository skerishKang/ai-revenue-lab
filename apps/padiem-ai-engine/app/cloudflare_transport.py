"""Cloudflare Service Binding transport for the internal Engine Worker.

Cloudflare-specific routing remains app-owned. Padiem AI Core receives only an
ordinary httpx transport and therefore stays platform-neutral.
"""

from __future__ import annotations

import sys
from functools import partial
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from padiem_ai_core import B14_CHAT_COMPLETIONS_PATH, B14_STREAM_PREVIEW_PATH
from padiem_ai_core.b14_execution import (
    B14ExecutionConfig,
    MAX_B14_RESPONSE_BYTES,
    MAX_CONFIGURED_B14_RESPONSE_BYTES,
)
from padiem_ai_core.b14_upstream import (
    BINDING_ORIGIN as B14_INTERNAL_ORIGIN,
    UPSTREAM_MODE_ENV,
    UPSTREAM_URL_ENV,
    B14HttpsTransport,
    B14Upstream,
    resolve_b14_upstream,
)

from app.b14_service_proof import service_proof_headers
from app.pc_work_metrics_reporter import PC_WORK_METRICS_PATH
# #4379: the model request body has no PADIEM aggregate ceiling. The request is
# read in full and the total is never refused; the platform's own request limit
# and the provider's context window are the real bounds.
_ALLOWED_B14_PATHS = frozenset(
    {
        B14_CHAT_COMPLETIONS_PATH,
        B14_STREAM_PREVIEW_PATH,
        PC_WORK_METRICS_PATH,
    }
)


class CloudflareReadableByteStream(httpx.AsyncByteStream):
    """Expose a Cloudflare/JS ReadableStream to httpx without buffering it."""

    def __init__(self, body: Any):
        if body is None:
            raise httpx.ProtocolError("Business 14 Service Binding response body is unavailable.")
        self._body = body
        self._reader: Any | None = None
        self._closed = False
        self._finished = False

    def _reader_or_create(self) -> Any:
        if self._reader is None:
            try:
                self._reader = self._body.getReader()
            except Exception as exc:
                raise httpx.ReadError(
                    "Business 14 Service Binding stream reader is unavailable."
                ) from exc
        return self._reader

    @staticmethod
    def _to_bytes(value: Any) -> bytes:
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, memoryview):
            return value.tobytes()
        # Workerd/Pyodide hands a stream chunk to Python as a JS proxy, not as
        # native bytes. ``to_py()`` is the canonical Pyodide bridge back to a
        # bytes-shaped value; ``to_bytes()`` covers the shape exposed by older
        # binding stubs. A proxy that only exposes integer iteration/length is
        # still decodable here, exactly like the shared chat streaming adapter.
        to_py = getattr(value, "to_py", None)
        if callable(to_py):
            try:
                converted_py = to_py()
            except Exception:
                converted_py = None
            if converted_py is not None:
                try:
                    return bytes(converted_py)
                except Exception:
                    pass
        to_bytes = getattr(value, "to_bytes", None)
        if callable(to_bytes):
            try:
                converted = to_bytes()
                return converted if isinstance(converted, bytes) else bytes(converted)
            except Exception as exc:
                raise httpx.ReadError(
                    "Business 14 Service Binding returned unreadable response bytes."
                ) from exc
        # A JS typed-array proxy exposes neither converter but still supports
        # integer iteration and length -- the same shape the shared chat
        # streaming adapter decodes -- so decode it instead of failing the whole
        # stream closed.
        try:
            return bytes(value)
        except Exception as exc:
            raise httpx.ReadError(
                "Business 14 Service Binding returned an unsupported response chunk."
            ) from exc

    async def __aiter__(self):
        reader = self._reader_or_create()
        try:
            while True:
                result = await reader.read()
                if bool(getattr(result, "done", False)):
                    self._finished = True
                    return
                chunk = self._to_bytes(getattr(result, "value", None))
                if chunk:
                    yield chunk
        except httpx.HTTPError:
            raise
        except Exception as exc:
            raise httpx.ReadError(
                "Business 14 Service Binding response read failed."
            ) from exc

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        reader = self._reader
        if reader is None:
            return
        try:
            if not self._finished:
                cancel = getattr(reader, "cancel", None)
                if callable(cancel):
                    await cancel()
        except Exception:
            pass
        finally:
            release_lock = getattr(reader, "releaseLock", None)
            if callable(release_lock):
                try:
                    release_lock()
                except Exception:
                    pass


def _correlation_header() -> dict[str, str]:
    from app.stack_telemetry import active_request_id
    from app.pc_work_metrics import current_pc_work_metrics

    value = active_request_id()
    headers = {"X-Request-Id": value} if value is not None else {}
    collector = current_pc_work_metrics()
    identity = getattr(collector, "ledger_identity", None)
    if isinstance(identity, dict):
        for key, header in (("product", "X-Padiem-Product"),
                            ("subject_ref", "X-Padiem-Subject-Ref"),
                            ("session_ref", "X-Padiem-Session-Ref")):
            item = identity.get(key)
            if isinstance(item, str) and item:
                headers[header] = item
    return headers


def _workers_runtime_active() -> bool:
    return "pyodide.ffi" in sys.modules or "js" in sys.modules


def _default_https_client() -> httpx.AsyncClient:
    """The plain-host client. Redirects are never followed for an internal call."""
    return httpx.AsyncClient(timeout=None, follow_redirects=False)


def _worker_https_client(origin: str) -> httpx.AsyncClient:
    """A fetch-backed client for the B14 upstream while this Worker runs.

    `CloudflareB14UpstreamTransport` pins the scheme, port, exact host and method,
    and carries a POST body of any size — the public-web bound belongs to the
    third-party lanes, not to this one.
    """
    from app.cloudflare_external_transport import CloudflareB14UpstreamTransport

    return httpx.AsyncClient(
        transport=CloudflareB14UpstreamTransport(origin=origin),
        timeout=None,
        follow_redirects=False,
    )


def b14_upstream_from_bindings(env: Any) -> B14Upstream:
    """Read the #5784 switch from this deployment's own bindings.

    On Workers the two names are plain vars; on a host they are environment
    variables supplied by the unit. Only values this deployment owns are read,
    so a binding that does not exist cannot be filled in from a stray process
    environment.
    """
    values: dict[str, str] = {}
    for name in (UPSTREAM_MODE_ENV, UPSTREAM_URL_ENV):
        value = getattr(env, name, None) if env is not None else None
        if value is not None:
            values[name] = str(value)
    return resolve_b14_upstream(values)


def build_b14_execution_configs(
    *, timeout_seconds: float, upstream: B14Upstream | None = None
) -> tuple[B14ExecutionConfig, B14ExecutionConfig]:
    """Return the Engine's completed-response and stream-frame B14 budgets.

    The two clients bound different things and must not share one number:

    * the completed client materializes one JSON body, so it uses the shared
      Worker memory budget that B14 itself applies to a completed answer;
    * the streaming client bounds a single SSE frame only. The cumulative model
      answer is never capped, exactly as on the B14 server side.

    Sharing the smaller frame bound with the completed client made the Engine
    refuse healthy model answers that Chat/Claw accept (#4379).

    ``upstream`` is the #5784 switch. Absent, it resolves to the Service Binding
    origin the Engine has always used, and both configs are identical to before.
    """
    origin = (upstream or resolve_b14_upstream()).origin
    completed = B14ExecutionConfig(
        base_url=origin,
        timeout_seconds=timeout_seconds,
        max_response_bytes=MAX_CONFIGURED_B14_RESPONSE_BYTES,
    )
    streaming = B14ExecutionConfig(
        base_url=origin,
        timeout_seconds=timeout_seconds,
        max_response_bytes=MAX_B14_RESPONSE_BYTES,
    )
    return completed, streaming


def build_b14_transport(
    *,
    binding: Any,
    request_factory: Callable[..., Any],
    proof_secret: str | None,
    upstream: B14Upstream | None = None,
    https_client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> httpx.AsyncBaseTransport:
    """Pick the one transport the switch names, and never guess a substitute.

    ``binding`` mode returns the existing Service Binding transport untouched.
    ``https`` mode needs a client, because a Worker has no socket to open; the
    caller supplies one built on the fetch transport it already uses. If that
    factory is missing the Engine refuses to start its B14 lane rather than
    quietly falling back to a binding the deployment just turned off.
    """
    resolved = upstream or resolve_b14_upstream()
    if resolved.uses_service_binding:
        return CloudflareB14ServiceBindingTransport(
            binding=binding,
            request_factory=request_factory,
            proof_secret=proof_secret,
        )
    if https_client_factory is None:
        # On a Worker there is no socket to open, so the upstream rides the same
        # JavaScript fetch the external lanes already use. That transport carries a
        # whole model request instead of truncating it: #4379 removed any
        # Engine-side ceiling on a model request body, and a Service Binding path
        # that sent it full cannot be replaced by one that cuts it off.
        if _workers_runtime_active():
            https_client_factory = partial(_worker_https_client, resolved.origin)
        else:
            https_client_factory = _default_https_client
    return B14HttpsTransport(
        origin=resolved.origin,
        allowed_paths=_ALLOWED_B14_PATHS,
        headers_for_body=lambda body: service_proof_headers(proof_secret, body),
        correlation_headers=_correlation_header,
        client=https_client_factory(),
    )


class CloudflareB14ServiceBindingTransport(httpx.AsyncBaseTransport):
    """Fixed Service Binding bridge used by Core B14 clients."""

    def __init__(
        self,
        *,
        binding: Any,
        request_factory: Callable[..., Any],
        proof_secret: str | None = None,
    ) -> None:
        if binding is None:
            raise ValueError("B14 service binding is required")
        if not callable(request_factory):
            raise ValueError("request_factory must be callable")
        self._binding = binding
        self._request_factory = request_factory
        self._proof_secret = proof_secret

    @staticmethod
    def _validate_target(url: httpx.URL) -> None:
        parsed = urlsplit(str(url))
        if (
            parsed.scheme != "https"
            or parsed.hostname != "b14.internal"
            or parsed.port is not None
            or parsed.path not in _ALLOWED_B14_PATHS
            or parsed.query
            or parsed.fragment
        ):
            raise httpx.RequestError("Business 14 internal target is invalid.")

    @staticmethod
    async def _read_request_body(request: httpx.Request) -> bytes:
        """Read the whole model request. There is no aggregate byte ceiling.

        #4379: the Engine used to refuse any model request larger than 256 KB,
        so a large context could never reach the model even though the product
        side accepted it. The body is read exactly as before and the total is
        never refused: the platform's own request limit and the provider's
        context window are the real bounds.
        """
        return bytes(await request.aread())

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        from app.byok_passthrough import b14_body, safe_cause
        if request.method != "POST":
            raise httpx.RequestError(
                "Business 14 Service Binding accepts POST only.", request=request
            )
        try:
            self._validate_target(request.url)
            raw_body = await self._read_request_body(request)
            if request.url.path != PC_WORK_METRICS_PATH:
                raw_body = b14_body(raw_body)
            body_text = raw_body.decode("utf-8")
        except httpx.RequestError:
            raise
        except Exception as exc:
            raise httpx.RequestError(
                "Business 14 request could not be encoded.", request=request
            ) from safe_cause(exc)

        service_request = self._request_factory(
            str(request.url),
            method="POST",
            headers={
                "Content-Type": "application/json",
                **_correlation_header(),
                # B14 spends platform-owned Provider credentials on this lane.
                # The proof binds this exact body to this deployment.
                **service_proof_headers(
                    self._proof_secret, body_text.encode("utf-8"),
                ),
            },
            body=body_text,
        )
        js_object = getattr(service_request, "js_object", None)
        if js_object is None:
            raise httpx.RequestError(
                "Business 14 internal request wrapper is invalid.", request=request
            )

        try:
            service_response = await self._binding.fetch(js_object)
        except Exception as exc:
            raise httpx.ConnectError(
                "Business 14 Service Binding is unavailable.", request=request
            ) from safe_cause(exc)

        try:
            status_code = int(service_response.status)
            content_type = service_response.headers.get("content-type")
            response_body = service_response.body
        except Exception as exc:
            raise httpx.ProtocolError(
                "Business 14 Service Binding returned malformed response metadata.",
                request=request,
            ) from safe_cause(exc)

        headers: dict[str, str] = {}
        if content_type is not None:
            headers["content-type"] = str(content_type)

        return httpx.Response(
            status_code=status_code,
            headers=headers,
            stream=CloudflareReadableByteStream(response_body),
            request=request,
        )
