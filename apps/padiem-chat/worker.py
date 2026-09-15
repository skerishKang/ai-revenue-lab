"""Cloudflare Python Worker entrypoint for Padiem Chat (Business 62).

The deployed Starlette application is built from Cloudflare Worker bindings,
not from browser input and not from stale import-time process environment.
Provider/model execution remains Business 14 authority.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

# The Core B14StreamingClient owns a real httpx.AsyncClient.  Its injected
# Service-Binding transport must use that same httpx Request/Response/stream
# type family; app.httpx_compat is only for app-owned JS-fetch clients.
import httpx
from workers import Request, Response, WorkerEntrypoint

from app.claw_p01_composition import build_claw_p01_adapter_with_diagnostic
from app.config import ConfigError
from app.control_plane_identity_shadow import D1IdentityShadowStore
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.dispatch_quota import DispatchAwareB14Client, DispatchAwareUsageCounterStore
from app.grounding import GroundedChatService
from app.history import D1HistoryStore
from app.main import create_app
from app.orchestration_routes import install_orchestration_routes
from app.project_files import D1ProjectFileStore
from app.saved_outputs import D1SavedOutputStore
from app.usage_gate import D1UsageCounterStore, UsageGate
from app.worker_config import (
    B14_SERVICE_BINDING_NAME,
    D1_BINDING_NAME,
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME,
    WORKSPACE_R2_BINDING_NAME,
    apply_live_deadman_switch,
    binding_value,
    response_headers_for_path,
    settings_from_worker_bindings,
)
from app.worker_orchestration import build_orchestration_bridge

_worker_app = None


def _apply_headers(response: Any, path: str) -> Any:
    for name, value in response_headers_for_path(path).items():
        response.headers[name] = value
    return response


class CloudflareB14ServiceTransport:
    """HTTP-shaped adapter over a Cloudflare Worker Service Binding.

    Routing authority is the fixed `B14_SERVICE` binding. The URL is still fully
    qualified because the Fetcher API expects an absolute URL, but service-binding
    configuration — not the hostname — selects the target Worker.
    """

    def __init__(self, binding: Any):
        if binding is None:
            raise ValueError("B14 service binding is required")
        self.binding = binding

    async def post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, bytes]:
        request = Request(
            url,
            method="POST",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload, ensure_ascii=False),
        )
        response = await self.binding.fetch(request.js_object)
        text = await response.text()
        return int(response.status), str(text).encode("utf-8")


class _CloudflareReadableByteStream(httpx.AsyncByteStream):
    """Expose a Service Binding Response body to httpx without buffering it."""

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
        # A Service Binding ReadableStream hands back one already-delivered
        # chunk at a time. In workerd that chunk is a JS typed array (Uint8Array)
        # surfaced to Python as a proxy object, not a native bytes/bytearray, and
        # it does not carry a ``to_bytes()`` method. Convert the single chunk to
        # bytes without ever buffering the whole stream, and fail closed on shapes
        # we cannot interpret.
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        if isinstance(value, (bytearray, memoryview)):
            return bytes(value)

        # Buffer protocol (JS typed arrays expose this through the proxy).
        try:
            return memoryview(value).tobytes()
        except (TypeError, ValueError):
            pass

        # Explicit byte materialiser (kept for adapters/tests that expose it).
        to_bytes = getattr(value, "to_bytes", None)
        if callable(to_bytes):
            try:
                converted = to_bytes()
            except Exception as exc:
                raise httpx.ReadError(
                    "Business 14 Service Binding returned unreadable stream bytes."
                ) from exc
            if isinstance(converted, (bytes, bytearray, memoryview)):
                return bytes(converted)
            try:
                return bytes(converted)
            except Exception as exc:
                raise httpx.ReadError(
                    "Business 14 Service Binding returned unreadable stream bytes."
                ) from exc

        # Integer-iterable proxy (a Uint8Array yields 0..255 per element).
        try:
            return bytes(value)
        except (TypeError, ValueError):
            pass

        raise httpx.ReadError(
            "Business 14 Service Binding returned an unsupported stream chunk."
        )

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
                "Business 14 Service Binding stream read failed.",
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


class CloudflareB14StreamingServiceTransport(httpx.AsyncBaseTransport):
    """Progressive httpx transport backed by the fixed B14 Service Binding."""

    def __init__(self, binding: Any):
        if binding is None:
            raise ValueError("B14 service binding is required")
        self.binding = binding

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            body = await request.aread()
            body_text = bytes(body).decode("utf-8")
        except Exception as exc:
            raise httpx.RequestError(
                "Business 14 streaming request could not be encoded.",
                request=request,
            ) from exc

        try:
            service_request = Request(
                str(request.url),
                method="POST",
                headers={"Content-Type": "application/json"},
                body=body_text,
            )
        except Exception as exc:
            raise httpx.RequestError(
                "Business 14 streaming request could not be constructed.",
                request=request,
            ) from exc

        try:
            service_response = await self.binding.fetch(service_request.js_object)
        except Exception as exc:
            raise httpx.ConnectError(
                "Business 14 Service Binding is unavailable.",
                request=request,
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

        try:
            headers: dict[str, str] = {}
            if content_type is not None:
                headers["content-type"] = str(content_type)

            return httpx.Response(
                status_code=status_code,
                headers=headers,
                stream=_CloudflareReadableByteStream(response_body),
                request=request,
            )
        except Exception as exc:
            raise httpx.ProtocolError(
                "Business 14 Service Binding response could not be adapted.",
                request=request,
            ) from exc


class _CloudflareExternalFetchByteStream(httpx.AsyncByteStream):
    """Expose a JavaScript fetch Response body to real httpx incrementally."""

    def __init__(
        self,
        body: Any,
        *,
        request: httpx.Request,
        timeout_signal: Any | None,
    ):
        if body is None:
            raise httpx.ProtocolError(
                "Worker fetch response body is unavailable.",
                request=request,
            )
        self._body = body
        self._request = request
        self._timeout_signal = timeout_signal
        self._reader: Any | None = None
        self._closed = False
        self._finished = False

    def _reader_or_create(self) -> Any:
        if self._reader is None:
            try:
                self._reader = self._body.getReader()
            except Exception as exc:
                raise httpx.ReadError(
                    "Worker fetch response body reader is unavailable.",
                    request=self._request,
                ) from exc
        return self._reader

    def _timed_out(self) -> bool:
        if self._timeout_signal is None:
            return False
        try:
            return bool(self._timeout_signal.aborted)
        except Exception:
            return False

    async def __aiter__(self):
        reader = self._reader_or_create()
        try:
            while True:
                result = await reader.read()
                if bool(getattr(result, "done", False)):
                    self._finished = True
                    return
                chunk = _CloudflareReadableByteStream._to_bytes(
                    getattr(result, "value", None)
                )
                if chunk:
                    yield chunk
        except httpx.HTTPError:
            raise
        except Exception as exc:
            if self._timed_out():
                raise httpx.ReadTimeout(
                    "Worker fetch timed out while reading the response body.",
                    request=self._request,
                ) from exc
            raise httpx.ReadError(
                "Worker fetch response body read failed.",
                request=self._request,
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


class _CloudflareEmptyAsyncByteStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        if False:
            yield b""

    async def aclose(self) -> None:
        return None


class CloudflareExternalHttpTransport(httpx.AsyncBaseTransport):
    """Real-httpx transport backed by Workers' JavaScript fetch API.

    Core Firecrawl/Daum providers own a real httpx.AsyncClient, so this adapter
    deliberately stays in the same real-httpx type family while replacing only
    the unsupported socket-backed network boundary with Workers fetch.
    """

    def __init__(
        self,
        *,
        fetch_impl: Any | None = None,
        abort_signal_api: Any | None = None,
    ):
        if fetch_impl is None or abort_signal_api is None:
            try:
                from js import AbortSignal as js_abort_signal  # type: ignore
                from js import fetch as js_fetch  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "Worker external HTTP transport requires the Workers JS runtime."
                ) from exc
            fetch_impl = js_fetch if fetch_impl is None else fetch_impl
            abort_signal_api = (
                js_abort_signal if abort_signal_api is None else abort_signal_api
            )
        self._fetch = fetch_impl
        self._abort_signal_api = abort_signal_api

    @staticmethod
    def _timeout_seconds(request: httpx.Request) -> float | None:
        timeout = request.extensions.get("timeout")
        if not isinstance(timeout, dict):
            return None
        # Core web providers put the full provider deadline in the read timeout.
        # Treat it as one fetch/body deadline because Workers fetch does not
        # expose separate connect/read socket phases.
        raw = timeout.get("read")
        if raw is None:
            raw = timeout.get("connect")
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            return None
        return seconds if seconds > 0 else None

    def _timeout_signal(self, request: httpx.Request) -> Any | None:
        seconds = self._timeout_seconds(request)
        if seconds is None:
            return None
        milliseconds = max(1, int(round(seconds * 1000)))
        try:
            return self._abort_signal_api.timeout(milliseconds)
        except Exception as exc:
            raise httpx.RequestError(
                "Worker fetch timeout signal is unavailable.",
                request=request,
            ) from exc

    @staticmethod
    async def _headers(js_headers: Any) -> dict[str, str]:
        result: dict[str, str] = {}
        try:
            entries = js_headers.entries()
            while True:
                entry = await entries.next()
                if bool(getattr(entry, "done", False)):
                    break
                pair = getattr(entry, "value", None)
                if pair is None:
                    continue
                result[str(pair[0])] = str(pair[1])
            return result
        except Exception:
            pass
        try:
            for key in js_headers:
                result[str(key)] = str(js_headers.get(key))
        except Exception:
            pass
        return result

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        try:
            body = bytes(await request.aread())
            headers = {str(k): str(v) for k, v in request.headers.items()}
        except Exception as exc:
            raise httpx.RequestError(
                "Worker fetch request could not be encoded.",
                request=request,
            ) from exc

        init: dict[str, Any] = {
            "method": request.method,
            "headers": headers,
            "redirect": "manual",
        }
        if body:
            init["body"] = body

        timeout_signal = self._timeout_signal(request)
        if timeout_signal is not None:
            init["signal"] = timeout_signal

        try:
            js_response = await self._fetch(str(request.url), init)
        except Exception as exc:
            timed_out = False
            if timeout_signal is not None:
                try:
                    timed_out = bool(timeout_signal.aborted)
                except Exception:
                    timed_out = False
            if timed_out:
                raise httpx.ReadTimeout(
                    "Worker fetch timed out before response headers.",
                    request=request,
                ) from exc
            raise httpx.ConnectError(
                "Worker external fetch is unavailable.",
                request=request,
            ) from exc

        try:
            status_code = int(js_response.status)
            response_headers = await self._headers(js_response.headers)
            response_body = getattr(js_response, "body", None)
        except Exception as exc:
            raise httpx.ProtocolError(
                "Worker external fetch returned malformed response metadata.",
                request=request,
            ) from exc

        stream: httpx.AsyncByteStream
        if response_body is None:
            stream = _CloudflareEmptyAsyncByteStream()
        else:
            stream = _CloudflareExternalFetchByteStream(
                response_body,
                request=request,
                timeout_signal=timeout_signal,
            )

        return httpx.Response(
            status_code=status_code,
            headers=response_headers,
            stream=stream,
            request=request,
        )


class Default(WorkerEntrypoint):
    async def fetch(self, request: Any) -> Any:
        import asgi

        global _worker_app
        path = urlparse(request.url).path

        if _worker_app is None:
            try:
                settings = apply_live_deadman_switch(settings_from_worker_bindings(self.env))
                db_binding = binding_value(self.env, D1_BINDING_NAME)
                b14_binding = binding_value(self.env, B14_SERVICE_BINDING_NAME)
                identity_binding = binding_value(self.env, IDENTITY_AUTHORITY_SERVICE_BINDING_NAME)
                # Private Claw workspace bytes (#2266). Resolved from trusted
                # Worker bindings only; absent until #2259/#2246 activation, in
                # which case WorkspaceDocumentStore stays None (fail closed).
                r2_binding = binding_value(self.env, WORKSPACE_R2_BINDING_NAME)

                history_store = D1HistoryStore(db_binding) if db_binding is not None else None
                project_file_store = D1ProjectFileStore(db_binding) if db_binding is not None else None
                saved_output_store = D1SavedOutputStore(db_binding) if db_binding is not None else None
                identity_shadow_store = D1IdentityShadowStore(db_binding) if db_binding is not None else None
                identity_authority = (
                    CloudflareControlPlaneIdentityAuthority(identity_binding)
                    if identity_binding is not None
                    else None
                )
                base_usage_store = D1UsageCounterStore(db_binding) if db_binding is not None else None
                usage_store = (
                    DispatchAwareUsageCounterStore(base_usage_store)
                    if base_usage_store is not None
                    else None
                )
                service_transport = (
                    CloudflareB14ServiceTransport(b14_binding)
                    if b14_binding is not None
                    else None
                )
                stream_transport = (
                    CloudflareB14StreamingServiceTransport(b14_binding)
                    if b14_binding is not None
                    else None
                )
                web_transport = CloudflareExternalHttpTransport()
                _worker_app = create_app(
                    settings=settings,
                    history_store=history_store,
                    d1_binding=db_binding,
                    r2_binding=r2_binding,
                    web_transport=web_transport,
                )
                _worker_app.state.control_plane_identity_authority = identity_authority
                _worker_app.state.identity_shadow_store = identity_shadow_store
                _worker_app.state.project_file_store = project_file_store
                _worker_app.state.saved_output_store = saved_output_store
                _worker_app.state.usage_gate = UsageGate(settings, usage_store)
                _worker_app.state.usage_gate_enforced = True
                _worker_app.state.b14_client = DispatchAwareB14Client(
                    settings,
                    service_transport=service_transport,
                    stream_transport=stream_transport,
                    require_service_binding=settings.runtime_mode == "b14",
                )
                _worker_app.state.grounded_chat = GroundedChatService(
                    _worker_app.state.b14_client,
                    _worker_app.state.web_provider,
                )
                _worker_app.state.b14_service_bound = b14_binding is not None
                _worker_app.state.identity_authority_service_bound = identity_binding is not None
                _worker_app.state.claw_p01_adapter, _worker_app.state.claw_p01_composition_diagnostic = (
                    build_claw_p01_adapter_with_diagnostic(
                        self.env,
                        request_factory=Request,
                    )
                )
                install_orchestration_routes(
                    _worker_app,
                    build_orchestration_bridge(
                        self.env,
                        settings=settings,
                        db_binding=db_binding,
                        request_factory=Request,
                    ),
                )
            except ConfigError:
                response = Response(
                    "Padiem Chat runtime configuration is invalid.",
                    status=503,
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
                return _apply_headers(response, path)

        response = await asgi.fetch(_worker_app, request.js_object, self.env)
        return _apply_headers(response, path)
