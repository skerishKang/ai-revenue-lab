"""Cloudflare Service Binding transport for the internal Engine Worker.

Cloudflare-specific routing remains app-owned. Padiem AI Core receives only an
ordinary httpx transport and therefore stays platform-neutral.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from padiem_ai_core import B14_CHAT_COMPLETIONS_PATH, B14_STREAM_PREVIEW_PATH
from padiem_ai_core.b14_execution import (
    B14ExecutionConfig,
    MAX_B14_RESPONSE_BYTES,
    MAX_CONFIGURED_B14_RESPONSE_BYTES,
)
from padiem_ai_core.b14_streaming import B14_AUTO_STREAM_PREVIEW_PATH

from app.b14_service_proof import service_proof_headers

B14_INTERNAL_ORIGIN = "https://b14.internal"
# #5784: the same lane can reach Business 14 through the Service Binding or
# through its public https origin. ``binding`` is the default and keeps every
# byte of today's request identical; ``https`` exists so the upstream can move
# to a host the platform edge does not run, without a second client.
B14_UPSTREAM_BINDING = "binding"
B14_UPSTREAM_HTTPS = "https"
B14_UPSTREAM_MODES = frozenset({B14_UPSTREAM_BINDING, B14_UPSTREAM_HTTPS})
# #4379: the model request body has no PADIEM aggregate ceiling. The request is
# read in full and the total is never refused; the platform's own request limit
# and the provider's context window are the real bounds.
_ALLOWED_B14_PATHS = frozenset(
    {
        B14_CHAT_COMPLETIONS_PATH,
        B14_STREAM_PREVIEW_PATH,
        B14_AUTO_STREAM_PREVIEW_PATH,
    }
)


def resolve_b14_upstream(*, mode: str | None = None, url: str | None = None) -> tuple[str, str]:
    """Return ``(mode, origin)`` for the Business 14 lane.

    An unset mode is ``binding``, and the binding branch ignores ``url`` on
    purpose: a deployment that has not chosen https cannot be redirected by a
    stray variable. The https branch accepts an origin only - no port, path,
    query or credentials - because the request path is the fixed allowlist above
    and an operator-supplied path would silently widen it.
    """

    resolved = B14_UPSTREAM_BINDING if mode is None else str(mode).strip().lower()
    if resolved not in B14_UPSTREAM_MODES:
        raise ValueError("B14_UPSTREAM_MODE must be binding or https")
    if resolved == B14_UPSTREAM_BINDING:
        return B14_UPSTREAM_BINDING, B14_INTERNAL_ORIGIN
    parsed = urlsplit((url or "").strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.hostname == "b14.internal"
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "B14_UPSTREAM_URL must be an https origin with no port, path, query or credentials"
        )
    return B14_UPSTREAM_HTTPS, f"https://{parsed.hostname}"


def resolve_b14_upstream_from_env(env: object) -> tuple[str, str]:
    """Read the upstream switch from deployment state, failing closed.

    Unset is ``binding``, which is today's byte-identical Service Binding lane.
    A mistyped mode or a URL that is not a bare https origin raises here, before
    any client exists, so a stray variable cannot quietly redirect the lane that
    spends platform-owned provider credentials.
    """

    def read(name: str) -> str | None:
        try:
            value = getattr(env, name)
        except Exception:
            return None
        if isinstance(value, str) and value.strip():
            return value
        return None

    return resolve_b14_upstream(
        mode=read("B14_UPSTREAM_MODE"), url=read("B14_UPSTREAM_URL")
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
    value = active_request_id()
    return {"X-Request-Id": value} if value is not None else {}


def build_b14_execution_configs(
    *, timeout_seconds: float, base_url: str = B14_INTERNAL_ORIGIN,
) -> tuple[B14ExecutionConfig, B14ExecutionConfig]:
    """Return the Engine's completed-response and stream-frame B14 budgets.

    The two clients bound different things and must not share one number:

    * the completed client materializes one JSON body, so it uses the shared
      Worker memory budget that B14 itself applies to a completed answer;
    * the streaming client bounds a single SSE frame only. The cumulative model
      answer is never capped, exactly as on the B14 server side.

    Sharing the smaller frame bound with the completed client made the Engine
    refuse healthy model answers that Chat/Claw accept (#4379).

    ``base_url`` is the only thing the upstream switch changes; both budgets stay
    identical whichever way the lane is pointed.
    """
    completed = B14ExecutionConfig(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_response_bytes=MAX_CONFIGURED_B14_RESPONSE_BYTES,
    )
    streaming = B14ExecutionConfig(
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        max_response_bytes=MAX_B14_RESPONSE_BYTES,
    )
    return completed, streaming


class B14HTTPSProofTransport(httpx.AsyncBaseTransport):
    """The https twin of the binding transport: same proof, same allowlist.

    Only the dispatch differs. The caller still sees one fixed origin, POST only,
    the three allowed paths, the same correlation header and the same body-bound
    ``x-padiem-b14-proof``; the response is an ordinary httpx response, so Core
    parses exactly what it parses on the binding lane.
    """

    def __init__(
        self,
        *,
        base_url: str,
        proof_secret: str | None = None,
        delegate: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if base_url == B14_INTERNAL_ORIGIN or not base_url.startswith("https://"):
            raise ValueError("B14 https upstream must be an external https origin")
        self._origin = base_url.rstrip("/")
        self._proof_secret = proof_secret
        self._delegate = delegate or httpx.AsyncHTTPTransport()

    def _validate_target(self, url: httpx.URL) -> None:
        parsed = urlsplit(str(url))
        if (
            f"{parsed.scheme}://{parsed.netloc}" != self._origin
            or parsed.scheme != "https"
            or parsed.port is not None
            or parsed.path not in _ALLOWED_B14_PATHS
            or parsed.query
            or parsed.fragment
        ):
            raise httpx.RequestError("Business 14 https target is invalid.")

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "POST":
            raise httpx.RequestError(
                "Business 14 https upstream accepts POST only.", request=request
            )
        self._validate_target(request.url)
        raw_body = bytes(await request.aread())
        outbound = httpx.Request(
            "POST",
            request.url,
            headers={
                "Content-Type": "application/json",
                **_correlation_header(),
                # The same server-to-server proof the binding lane sends: B14
                # refuses an unattested caller on this API either way.
                **service_proof_headers(self._proof_secret, raw_body),
            },
            content=raw_body,
        )
        response = await self._delegate.handle_async_request(outbound)
        response.request = request
        return response


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
        if request.method != "POST":
            raise httpx.RequestError(
                "Business 14 Service Binding accepts POST only.", request=request
            )
        try:
            self._validate_target(request.url)
            raw_body = await self._read_request_body(request)
            body_text = raw_body.decode("utf-8")
        except httpx.RequestError:
            raise
        except Exception as exc:
            raise httpx.RequestError(
                "Business 14 request could not be encoded.", request=request
            ) from exc

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
            ) from exc

        try:
            status_code = int(service_response.status)
            content_type = service_response.headers.get("content-type")
            response_body = service_response.body
        except Exception as exc:
            raise httpx.ProtocolError(
                "Business 14 Service Binding returned malformed response metadata.",
                request=request,
            ) from exc

        headers: dict[str, str] = {}
        if content_type is not None:
            headers["content-type"] = str(content_type)

        return httpx.Response(
            status_code=status_code,
            headers=headers,
            stream=CloudflareReadableByteStream(response_body),
            request=request,
        )
