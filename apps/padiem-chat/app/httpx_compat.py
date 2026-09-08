"""httpx compatibility shim for the Cloudflare Workers Python runtime (Pyodide).

The Workers Python runtime does not include the ``httpx`` package, so production
modules written against httpx's async transport surface (Worker entrypoint,
Google OAuth, B14 streaming, web tools) fail with
``ModuleNotFoundError: No module named 'httpx'`` at import time. This module
provides the subset of the httpx surface actually used by the B62 production
code, backed by ``from js import fetch`` on Workers, and re-exporting the real
``httpx`` on CPython so the existing test suite (which depends on
``httpx.MockTransport``, ``httpx.ASGITransport``, ``httpx.URL`` etc.) is
unchanged.

Surface provided (matches actual usage in worker.py, app/auth.py,
app/b14_client.py, app/web_tools.py):

- ``AsyncClient(transport, timeout, follow_redirects)`` with ``.stream(method, url, ...)``
- ``AsyncBaseTransport`` (subclassable; ``handle_async_request(request) -> Response``)
- ``Request`` (``.url``; async ``.aread() -> bytes``)
- ``Response(status_code, headers, stream, request)`` with ``.status_code``,
  ``.headers``, async ``.aiter_bytes()``, ``.request``
- ``Timeout(timeout, connect=...)`` (signature-compatible; not enforced in fetch)
- ``AsyncByteStream`` (subclassable; ``__aiter__`` yielding ``bytes``, ``aclose``)
- Exception hierarchy: ``HTTPError`` (base) and ``RequestError``, ``ConnectError``,
  ``ReadError``, ``ProtocolError``, ``ReadTimeout`` — all accept ``message`` and
  optional ``request=`` to mirror httpx's constructor surface.

The fetch backend supports ``data=dict`` (form-encoded), ``data=str|bytes``
(passthrough), and ``json=dict`` (JSON-encoded) bodies, with ``follow_redirects``
controlling the js ``redirect`` mode.
"""
from __future__ import annotations
from typing import Any, AsyncIterator


try:
    from js import fetch as _js_fetch  # type: ignore  # Pyodide / Workers only
    _IN_WORKERS = True
except ImportError:
    # CPython (local dev, CI, tests): re-export the real httpx unchanged.
    # The module name is assembled at runtime so that static bundlers
    # (e.g. pywrangler) do not resolve ``httpx`` as a static dependency of
    # this shim. The Workers branch above never enters this path; the
    # CPython/tests path loads real httpx on demand via importlib.
    _IN_WORKERS = False
    import importlib as _il
    _real_httpx = _il.import_module("ht" + "tpx")  # type: ignore

    AsyncClient = _real_httpx.AsyncClient
    AsyncBaseTransport = _real_httpx.AsyncBaseTransport
    Request = _real_httpx.Request
    Response = _real_httpx.Response
    Timeout = _real_httpx.Timeout
    AsyncByteStream = _real_httpx.AsyncByteStream
    HTTPError = _real_httpx.HTTPError
    RequestError = _real_httpx.RequestError
    ConnectError = _real_httpx.ConnectError
    ReadError = _real_httpx.ReadError
    ProtocolError = _real_httpx.ProtocolError
    ReadTimeout = _real_httpx.ReadTimeout


if _IN_WORKERS:
    from js import URLSearchParams as _JsURLSearchParams  # type: ignore

    class Timeout:
        """Signature-compatible Timeout holder. The fetch backend currently
        does not enforce timeouts (Workers fetch needs AbortController +
        timer to honor connect/total); the field is preserved so call sites
        that construct ``Timeout(15.0, connect=8.0)`` keep working."""

        __slots__ = ("timeout", "connect")

        def __init__(self, timeout: float, *, connect: float | None = None):
            self.timeout = timeout
            self.connect = connect

    class Request:
        """Minimal httpx-compatible Request carrying method/url/body for the
        service-binding transport and the fetch stream context."""

        __slots__ = ("method", "url", "_content", "headers")

        def __init__(
            self,
            method: str,
            url: str,
            *,
            headers: dict | None = None,
            content: bytes | None = None,
        ):
            self.method = method
            self.url = url
            self._content = content or b""
            self.headers = dict(headers or {})

        async def aread(self) -> bytes:
            return self._content

    class AsyncByteStream:
        """Subclassable async byte stream. Subclasses must override
        ``__aiter__`` to yield ``bytes`` chunks and may override ``aclose``."""

        async def __aiter__(self) -> AsyncIterator[bytes]:  # pragma: no cover - abstract
            raise NotImplementedError
            yield b""  # pragma: no cover - unreachable, makes this an async generator

        async def aclose(self) -> None:
            return None

    class _JsBodyStream(AsyncByteStream):
        """Read a js ``ReadableStream`` body as ``bytes`` chunks."""

        def __init__(self, body: Any):
            self._body = body
            self._reader: Any | None = None
            self._closed = False
            self._finished = False

        def _reader_or_create(self) -> Any:
            if self._reader is None:
                try:
                    self._reader = self._body.getReader()
                except Exception as exc:
                    raise ReadError("response body reader is unavailable.") from exc
            return self._reader

        @staticmethod
        def _to_bytes(value: Any) -> bytes:
            if value is None:
                return b""
            if isinstance(value, (bytes, bytearray)):
                return bytes(value)
            if isinstance(value, memoryview):
                return value.tobytes()
            to_bytes = getattr(value, "to_bytes", None)
            if callable(to_bytes):
                try:
                    converted = to_bytes()
                except Exception as exc:
                    raise ReadError("response body returned unreadable bytes.") from exc
                if isinstance(converted, (bytes, bytearray)):
                    return bytes(converted)
                try:
                    return bytes(converted)
                except Exception as exc:
                    raise ReadError("response body returned unreadable bytes.") from exc
            try:
                return bytes(value)
            except Exception as exc:
                raise ReadError("response body returned an unsupported chunk.") from exc

        async def __aiter__(self) -> AsyncIterator[bytes]:
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
            except HTTPError:
                raise
            except Exception as exc:
                raise ReadError("response body read failed.") from exc

        async def aclose(self) -> None:
            if self._closed:
                return
            self._closed = True
            reader = self._reader
            if reader is None:
                return
            try:
                cancel = getattr(reader, "cancel", None)
                if callable(cancel):
                    await cancel()
            except Exception:
                pass

    class Response:
        """Minimal httpx-compatible Response. ``aiter_bytes`` delegates to the
        ``AsyncByteStream`` passed in (or yields nothing if ``stream`` is None).
        ``headers`` is a plain ``dict`` populated from the underlying transport
        or fetch response."""

        __slots__ = ("status_code", "headers", "_stream", "request")

        def __init__(
            self,
            status_code: int,
            *,
            headers: dict | None = None,
            stream: AsyncByteStream | None = None,
            request: Request | None = None,
        ):
            self.status_code = int(status_code)
            self.headers = dict(headers or {})
            self._stream = stream
            self.request = request

        async def aiter_bytes(self) -> AsyncIterator[bytes]:
            if self._stream is None:
                return
            async for chunk in self._stream:
                yield chunk

    class HTTPError(Exception):
        def __init__(self, message: str, *, request: Request | None = None):
            super().__init__(message)
            self.request = request

    class RequestError(HTTPError):
        pass

    class ConnectError(HTTPError):
        pass

    class ReadError(HTTPError):
        pass

    class ProtocolError(HTTPError):
        pass

    class ReadTimeout(HTTPError):
        pass

    class AsyncBaseTransport:
        async def handle_async_request(self, request: Request) -> Response:
            raise NotImplementedError
            yield Response(500)  # pragma: no cover

    def _build_body_and_headers(kwargs: dict) -> tuple[bytes | None, dict]:
        """Translate httpx-style ``data=`` / ``json=`` / ``content=`` kwargs into
        a request body and merged headers."""
        headers = dict(kwargs.get("headers") or {})
        body: bytes | None = None
        if "json" in kwargs and kwargs["json"] is not None:
            import json as _json
            body = _json.dumps(kwargs["json"], ensure_ascii=False).encode("utf-8")
            headers.setdefault("Content-Type", "application/json")
        elif "data" in kwargs and kwargs["data"] is not None:
            data = kwargs["data"]
            if isinstance(data, dict):
                params = _JsURLSearchParams.new()
                for k, v in data.items():
                    params.append(str(k), str(v))
                body = str(params).encode("utf-8")
                headers.setdefault(
                    "Content-Type", "application/x-www-form-urlencoded"
                )
            elif isinstance(data, (bytes, bytearray)):
                body = bytes(data)
            elif isinstance(data, str):
                body = data.encode("utf-8")
            else:
                body = str(data).encode("utf-8")
        elif "content" in kwargs and kwargs["content"] is not None:
            content = kwargs["content"]
            if isinstance(content, (bytes, bytearray)):
                body = bytes(content)
            elif isinstance(content, str):
                body = content.encode("utf-8")
            else:
                body = str(content).encode("utf-8")
        return body, headers

    class _StreamContext:
        def __init__(self, client: "AsyncClient", method: str, url: str, kwargs: dict):
            self._client = client
            self._method = method
            self._url = url
            self._kwargs = kwargs
            self._response: Response | None = None

        async def __aenter__(self) -> Response:
            body, headers = _build_body_and_headers(self._kwargs)
            request = Request(
                self._method,
                self._url,
                headers=headers,
                content=body,
            )

            # Transport path: the caller provided an AsyncBaseTransport (e.g.
            # CloudflareB14StreamingServiceTransport wrapping a Service
            # Binding). The transport returns a Response whose ``stream`` is
            # an AsyncByteStream subclass reading the binding body.
            if self._client._transport is not None:
                try:
                    response = await self._client._transport.handle_async_request(
                        request
                    )
                except HTTPError:
                    raise
                except Exception as exc:
                    raise RequestError(
                        f"transport request failed: {exc}", request=request
                    ) from exc
                # Ensure the response carries the request so callers can
                # correlate (matches httpx behaviour).
                if response.request is None:
                    response.request = request
                self._response = response
                return response

            # Fetch path: ``from js import fetch`` against an HTTP(S) origin.
            init: dict = {"method": self._method, "headers": headers}
            if not self._client._follow_redirects:
                init["redirect"] = "manual"
            if body is not None:
                init["body"] = body
            try:
                js_resp = await _js_fetch(self._url, init)  # type: ignore[misc]
            except Exception as exc:
                raise ConnectError(
                    f"fetch failed: {exc}", request=request
                ) from exc

            try:
                status_code = int(js_resp.status)
                resp_headers: dict = {}
                js_headers = js_resp.headers
                try:
                    entries = js_headers.entries()
                    while True:
                        entry = await entries.next()
                        if bool(getattr(entry, "done", False)):
                            break
                        pair = getattr(entry, "value", None)
                        if pair is None:
                            continue
                        resp_headers[str(pair[0])] = str(pair[1])
                except Exception:
                    # Fall back to ``for..in`` style iteration if entries()
                    # is unavailable in this runtime.
                    try:
                        for key in js_headers:
                            resp_headers[str(key)] = str(js_headers.get(key))
                    except Exception:
                        pass
            except Exception as exc:
                raise ProtocolError(
                    f"fetch returned malformed response metadata: {exc}",
                    request=request,
                ) from exc

            stream: AsyncByteStream | None = None
            try:
                body_stream = js_resp.body
            except Exception:
                body_stream = None
            if body_stream is not None:
                stream = _JsBodyStream(body_stream)

            response = Response(
                status_code=status_code,
                headers=resp_headers,
                stream=stream,
                request=request,
            )
            self._response = response
            return response

        async def __aexit__(self, exc_type, exc, tb) -> None:
            response = self._response
            if response is None or response._stream is None:
                return
            try:
                await response._stream.aclose()
            except Exception:
                pass

    class AsyncClient:
        def __init__(
            self,
            *,
            transport: AsyncBaseTransport | None = None,
            timeout: Any = None,
            follow_redirects: bool = False,
        ):
            self._transport = transport
            self._timeout = timeout
            self._follow_redirects = follow_redirects

        async def __aenter__(self) -> "AsyncClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        def stream(self, method: str, url: str, **kwargs) -> _StreamContext:
            return _StreamContext(self, method, url, kwargs)


__all__ = [
    "AsyncClient",
    "AsyncBaseTransport",
    "Request",
    "Response",
    "Timeout",
    "AsyncByteStream",
    "HTTPError",
    "RequestError",
    "ConnectError",
    "ReadError",
    "ProtocolError",
    "ReadTimeout",
]
