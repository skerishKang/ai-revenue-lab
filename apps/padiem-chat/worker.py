"""Cloudflare Python Worker entrypoint for Padiem Chat (Business 62).

The deployed Starlette application is built from Cloudflare Worker bindings,
not from browser input and not from stale import-time process environment.
Provider/model execution remains Business 14 authority.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

import httpx
from workers import Request, Response, WorkerEntrypoint

from app.config import ConfigError
from app.dispatch_quota import DispatchAwareB14Client, DispatchAwareUsageCounterStore
from app.grounding import GroundedChatService
from app.history import D1HistoryStore
from app.main import create_app
from app.project_files import D1ProjectFileStore
from app.saved_outputs import D1SavedOutputStore
from app.usage_gate import D1UsageCounterStore, UsageGate
from app.worker_config import (
    B14_SERVICE_BINDING_NAME,
    D1_BINDING_NAME,
    apply_live_deadman_switch,
    binding_value,
    response_headers_for_path,
    settings_from_worker_bindings,
)

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
        if value is None:
            return b""
        if isinstance(value, bytes):
            return value
        if isinstance(value, bytearray):
            return bytes(value)
        if isinstance(value, memoryview):
            return value.tobytes()

        to_bytes = getattr(value, "to_bytes", None)
        if callable(to_bytes):
            try:
                converted = to_bytes()
            except Exception as exc:
                raise httpx.ReadError(
                    "Business 14 Service Binding returned unreadable stream bytes."
                ) from exc
            if isinstance(converted, bytes):
                return converted
            try:
                return bytes(converted)
            except Exception as exc:
                raise httpx.ReadError(
                    "Business 14 Service Binding returned unreadable stream bytes."
                ) from exc

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
                "Business 14 Service Binding stream read failed."
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
            # Closing is best-effort; never replace the bounded Core error with
            # raw Service Binding/FFI close details.
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

        service_request = Request(
            str(request.url),
            method="POST",
            headers={"Content-Type": "application/json"},
            body=body_text,
        )
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

        headers: dict[str, str] = {}
        if content_type is not None:
            headers["content-type"] = str(content_type)

        return httpx.Response(
            status_code=status_code,
            headers=headers,
            stream=_CloudflareReadableByteStream(response_body),
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
                history_store = D1HistoryStore(db_binding) if db_binding is not None else None
                project_file_store = D1ProjectFileStore(db_binding) if db_binding is not None else None
                saved_output_store = D1SavedOutputStore(db_binding) if db_binding is not None else None
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
                _worker_app = create_app(settings=settings, history_store=history_store)
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
            except ConfigError:
                response = Response(
                    "Padiem Chat runtime configuration is invalid.",
                    status=503,
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
                return _apply_headers(response, path)

        response = await asgi.fetch(_worker_app, request.js_object, self.env)
        return _apply_headers(response, path)
