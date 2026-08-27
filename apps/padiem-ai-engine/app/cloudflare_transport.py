"""Cloudflare Service Binding transport for the internal Engine Worker.

Cloudflare-specific routing remains app-owned. Padiem AI Core receives only an
ordinary httpx transport and therefore stays platform-neutral.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from padiem_ai_core import B14_CHAT_COMPLETIONS_PATH, B14_STREAM_PREVIEW_PATH
from padiem_ai_core.b14_streaming import B14_AUTO_STREAM_PREVIEW_PATH

B14_INTERNAL_ORIGIN = "https://b14.internal"
MAX_OUTBOUND_B14_REQUEST_BYTES = 256 * 1024
_ALLOWED_B14_PATHS = frozenset(
    {
        B14_CHAT_COMPLETIONS_PATH,
        B14_STREAM_PREVIEW_PATH,
        B14_AUTO_STREAM_PREVIEW_PATH,
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
        to_bytes = getattr(value, "to_bytes", None)
        if callable(to_bytes):
            try:
                converted = to_bytes()
                return converted if isinstance(converted, bytes) else bytes(converted)
            except Exception as exc:
                raise httpx.ReadError(
                    "Business 14 Service Binding returned unreadable response bytes."
                ) from exc
        raise httpx.ReadError(
            "Business 14 Service Binding returned an unsupported response chunk."
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


class CloudflareB14ServiceBindingTransport(httpx.AsyncBaseTransport):
    """Fixed Service Binding bridge used by Core B14 clients."""

    def __init__(
        self,
        *,
        binding: Any,
        request_factory: Callable[..., Any],
    ) -> None:
        if binding is None:
            raise ValueError("B14 service binding is required")
        if not callable(request_factory):
            raise ValueError("request_factory must be callable")
        self._binding = binding
        self._request_factory = request_factory

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

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "POST":
            raise httpx.RequestError(
                "Business 14 Service Binding accepts POST only.", request=request
            )
        try:
            self._validate_target(request.url)
            raw_body = bytes(await request.aread())
            if len(raw_body) > MAX_OUTBOUND_B14_REQUEST_BYTES:
                raise httpx.RequestError(
                    "Business 14 request exceeded the Engine transport limit.",
                    request=request,
                )
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
            headers={"Content-Type": "application/json"},
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
