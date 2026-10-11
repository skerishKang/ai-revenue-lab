"""Cloudflare Python Worker external HTTP transport for Engine-owned provider GETs.

Uses the Workers JavaScript fetch API while preserving real httpx request/
response types. Production callers pass a fixed allowlist; redirects are manual
and cannot forward bearer credentials to another host.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx


class _WorkerFetchByteStream(httpx.AsyncByteStream):
    def __init__(self, body: Any, *, request: httpx.Request, timeout_signal: Any | None):
        if body is None:
            raise httpx.ProtocolError("Worker fetch response body is unavailable.", request=request)
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
            converted = to_bytes()
            return converted if isinstance(converted, bytes) else bytes(converted)
        raise TypeError("unsupported Worker fetch response chunk")

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
            release = getattr(reader, "releaseLock", None)
            if callable(release):
                try:
                    release()
                except Exception:
                    pass


class _EmptyAsyncByteStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        if False:
            yield b""

    async def aclose(self) -> None:
        return None


class CloudflareExternalHttpTransport(httpx.AsyncBaseTransport):
    """Worker-native external GET transport with a fixed HTTPS host allowlist."""

    def __init__(
        self,
        *,
        allowed_hosts: frozenset[str],
        fetch_impl: Any | None = None,
        abort_signal_api: Any | None = None,
        allow_insecure_localhost: bool = False,
    ) -> None:
        if not isinstance(allowed_hosts, frozenset) or not allowed_hosts:
            raise ValueError("allowed_hosts must be a non-empty frozenset")
        if any(not isinstance(host, str) or not host for host in allowed_hosts):
            raise ValueError("allowed_hosts contains an invalid host")
        if fetch_impl is None or abort_signal_api is None:
            try:
                from js import AbortSignal as js_abort_signal  # type: ignore
                from js import fetch as js_fetch  # type: ignore
            except ImportError as exc:
                raise RuntimeError(
                    "Worker external HTTP transport requires the Workers JS runtime."
                ) from exc
            fetch_impl = js_fetch if fetch_impl is None else fetch_impl
            abort_signal_api = js_abort_signal if abort_signal_api is None else abort_signal_api
        self._allowed_hosts = allowed_hosts
        self._fetch = fetch_impl
        self._abort_signal_api = abort_signal_api
        self._allow_insecure_localhost = bool(allow_insecure_localhost)

    def _validate_target(self, request: httpx.Request) -> None:
        parsed = urlsplit(str(request.url))
        allowed_scheme = parsed.scheme == "https"
        if (
            self._allow_insecure_localhost
            and parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost"}
        ):
            allowed_scheme = True
        if (
            request.method != "GET"
            or not allowed_scheme
            or parsed.hostname not in self._allowed_hosts
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise httpx.RequestError(
                "Worker external HTTP target is not allowed.",
                request=request,
            )

    @staticmethod
    def _timeout_seconds(request: httpx.Request) -> float | None:
        timeout = request.extensions.get("timeout")
        if not isinstance(timeout, dict):
            return None
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
        try:
            return self._abort_signal_api.timeout(max(1, int(round(seconds * 1000))))
        except Exception as exc:
            raise httpx.RequestError(
                "Worker fetch timeout signal is unavailable.",
                request=request,
            ) from exc

    @staticmethod
    async def _headers(js_headers: Any, *, request: httpx.Request) -> dict[str, str]:
        try:
            result: dict[str, str] = {}
            entries = js_headers.entries()
            while True:
                entry = entries.next()
                if hasattr(entry, "__await__"):
                    entry = await entry
                if bool(getattr(entry, "done", False)):
                    return result
                pair = getattr(entry, "value", None)
                if pair is not None:
                    result[str(pair[0])] = str(pair[1])
        except Exception:
            pass
        try:
            return {str(key): str(js_headers.get(key)) for key in js_headers}
        except Exception as exc:
            raise httpx.ProtocolError(
                "Worker external fetch returned malformed response headers.",
                request=request,
            ) from exc

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._validate_target(request)
        transport_managed = {"host", "content-length", "transfer-encoding", "connection"}
        headers = {
            str(key): str(value)
            for key, value in request.headers.items()
            if str(key).lower() not in transport_managed
        }
        # The Workers Fetch API owns transfer/content decoding. Do not ask the
        # origin for a compressed representation that HTTPX may try to decode
        # a second time after Fetch has already exposed decoded body bytes.
        headers["accept-encoding"] = "identity"
        init: dict[str, Any] = {
            "method": "GET",
            "headers": headers,
            "redirect": "manual",
        }
        timeout_signal = self._timeout_signal(request)
        if timeout_signal is not None:
            init["signal"] = timeout_signal

        try:
            try:
                from js import Object as _JsObject  # type: ignore
                from pyodide.ffi import to_js as _to_js  # type: ignore
            except (ImportError, ModuleNotFoundError):
                js_init = init
            else:
                js_init = _to_js(
                    init,
                    dict_converter=_JsObject.fromEntries,
                    create_pyproxies=False,
                )
            js_response = await self._fetch(str(request.url), js_init)
        except httpx.HTTPError:
            raise
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
            response_headers = await self._headers(js_response.headers, request=request)
            # Fetch may expose a decoded body while retaining origin encoding
            # metadata. HTTPX would then apply Content-Encoding again when
            # callers iterate response.aiter_bytes(). The body size can also
            # differ from the origin Content-Length after Fetch processing.
            response_headers = {
                key: value
                for key, value in response_headers.items()
                if key.lower() not in {"content-encoding", "content-length"}
            }
            body = getattr(js_response, "body", None)
        except httpx.ProtocolError:
            raise
        except Exception as exc:
            raise httpx.ProtocolError(
                "Worker external fetch returned malformed response metadata.",
                request=request,
            ) from exc

        stream: httpx.AsyncByteStream = (
            _EmptyAsyncByteStream()
            if body is None
            else _WorkerFetchByteStream(
                body,
                request=request,
                timeout_signal=timeout_signal,
            )
        )
        return httpx.Response(
            status_code=status_code,
            headers=response_headers,
            stream=stream,
            request=request,
        )


def gmail_worker_transport() -> httpx.AsyncBaseTransport | None:
    """Return the Worker-native bounded Gmail GET transport in Pyodide."""

    import sys

    if sys.platform != "emscripten":
        return None
    return CloudflareExternalHttpTransport(
        allowed_hosts=frozenset({"gmail.googleapis.com"}),
    )


def drive_worker_transport() -> httpx.AsyncBaseTransport | None:
    """Return JS-fetch transport only inside the Pyodide Worker runtime.

    CPython tests intentionally keep the ordinary httpx transport so existing
    MockTransport injection and network-free composition tests remain valid.
    """
    import sys

    if sys.platform != "emscripten":
        return None
    return CloudflareExternalHttpTransport(
        allowed_hosts=frozenset({"www.googleapis.com"}),
    )


def calendar_worker_transport() -> httpx.AsyncBaseTransport | None:
    """Return the Worker-native bounded Calendar GET transport in Pyodide.

    Calendar uses the same official ``www.googleapis.com`` host as Drive. CPython
    tests keep the ordinary httpx transport so MockTransport injection and
    network-free composition tests remain valid.
    """
    import sys

    if sys.platform != "emscripten":
        return None
    return CloudflareExternalHttpTransport(
        allowed_hosts=frozenset({"www.googleapis.com"}),
    )


__all__ = [
    "CloudflareExternalHttpTransport",
    "calendar_worker_transport",
    "drive_worker_transport",
    "gmail_worker_transport",
]
