"""Which B14 a product calls, and how it proves itself there.

Two upstreams can serve the same B14 contract: the Cloudflare Worker reached
through a Service Binding, and the same application reached over HTTPS on a host
that has no Workers. The choice is one deployment variable, ``B14_UPSTREAM_MODE``,
and the default is the binding — a deployment that does not name a mode keeps the
exact transport, origin, headers and behaviour it has today.

Turning the switch does not create a second client, a second retry policy or a
second authority. It changes where the request goes and how the origin is
validated; the caller proof below is the same HMAC over the same exact body that
the binding transports already send, because B14 authenticates the body, not the
transport.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

import httpx

UPSTREAM_MODE_ENV = "B14_UPSTREAM_MODE"
UPSTREAM_URL_ENV = "B14_UPSTREAM_URL"

MODE_BINDING = "binding"
MODE_HTTPS = "https"

# The Service Binding origin is a routing label, not a resolvable host.
BINDING_ORIGIN = "https://b14.internal"

_ALLOWED_SCHEME = "https"


class B14UpstreamConfigError(ValueError):
    """The switch is set to a state this process must not guess its way out of."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class B14Upstream:
    mode: str
    origin: str

    @property
    def uses_service_binding(self) -> bool:
        return self.mode == MODE_BINDING

    @property
    def uses_https(self) -> bool:
        return self.mode == MODE_HTTPS


def normalize_origin(raw: str) -> str:
    """Return the scheme+host only, refusing anything that could redirect."""
    parsed = urlsplit(raw.strip())
    if parsed.scheme != _ALLOWED_SCHEME:
        raise B14UpstreamConfigError("b14_upstream_url_scheme_invalid")
    if not parsed.hostname:
        raise B14UpstreamConfigError("b14_upstream_url_host_missing")
    if parsed.username or parsed.password:
        raise B14UpstreamConfigError("b14_upstream_url_credentials_forbidden")
    if parsed.query or parsed.fragment:
        raise B14UpstreamConfigError("b14_upstream_url_query_forbidden")
    if parsed.path.strip("/"):
        raise B14UpstreamConfigError("b14_upstream_url_path_forbidden")
    if parsed.hostname == urlsplit(BINDING_ORIGIN).hostname:
        # b14.internal is a binding label. Pointing HTTPS at it would let a
        # mis-set switch look like a working upstream while resolving nowhere.
        raise B14UpstreamConfigError("b14_upstream_url_reserved_origin")
    netloc = parsed.netloc if parsed.port else parsed.hostname
    return urlunsplit((_ALLOWED_SCHEME, netloc, "", "", ""))


def resolve_b14_upstream(environ: Mapping[str, str] | None = None) -> B14Upstream:
    """Read the upstream switch. Never infer a mode from which bindings exist."""
    import os

    values = os.environ if environ is None else environ
    mode = str(values.get(UPSTREAM_MODE_ENV) or MODE_BINDING).strip().lower()
    raw_url = str(values.get(UPSTREAM_URL_ENV) or "").strip()
    if mode == MODE_BINDING:
        if raw_url:
            # A URL beside the binding mode is a half-flipped switch. Refusing
            # beats silently choosing one of the two.
            raise B14UpstreamConfigError("b14_upstream_url_ignored_in_binding_mode")
        return B14Upstream(mode=MODE_BINDING, origin=BINDING_ORIGIN)
    if mode != MODE_HTTPS:
        raise B14UpstreamConfigError("b14_upstream_mode_invalid")
    if not raw_url:
        raise B14UpstreamConfigError("b14_upstream_url_required")
    return B14Upstream(mode=MODE_HTTPS, origin=normalize_origin(raw_url))


class B14HttpsTransport(httpx.AsyncBaseTransport):
    """Reach a B14 origin over HTTPS with the caller's own caller proof.

    The proof is supplied as ``headers_for_body`` rather than being reimplemented
    here: Chat and the Engine each already own one signer with its own pinned
    tests, and a third copy in Core would be a second authority over the same
    credential contract. The construction it must produce is documented once, in
    the B14 server-side verifier.

    The target is pinned twice over: the origin comes from the validated switch,
    and only the caller's fixed path allowlist is accepted, so a value that
    arrives from anywhere else cannot steer this transport.
    """

    def __init__(
        self,
        *,
        origin: str,
        allowed_paths: frozenset[str],
        headers_for_body: Callable[[bytes], Mapping[str, str]] | None = None,
        correlation_headers: Callable[[], Mapping[str, str]] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not allowed_paths:
            raise ValueError("B14 https transport requires a path allowlist")
        self._origin = normalize_origin(origin)
        self._allowed_paths = frozenset(allowed_paths)
        self._headers_for_body = headers_for_body
        self._correlation_headers = correlation_headers
        self._client = client
        self._owns_client = client is None

    @property
    def origin(self) -> str:
        return self._origin

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        target = urlsplit(str(request.url))
        if urlunsplit((target.scheme, target.netloc, "", "", "")) != self._origin:
            raise httpx.RequestError("Business 14 upstream origin is invalid.", request=request)
        if target.path not in self._allowed_paths:
            raise httpx.RequestError("Business 14 upstream path is not allowed.", request=request)
        if target.query or target.fragment:
            raise httpx.RequestError("Business 14 upstream target is invalid.", request=request)
        if request.method not in {"POST", "GET"}:
            raise httpx.RequestError(
                "Business 14 upstream accepts POST and GET only.", request=request
            )

        headers = dict(request.headers)
        body = b""
        if request.method == "POST":
            body = bytes(await request.aread())
            if self._headers_for_body is not None:
                headers.update(dict(self._headers_for_body(body)))
        if self._correlation_headers is not None:
            for name, value in dict(self._correlation_headers()).items():
                headers.setdefault(name, value)

        if self._client is None:
            self._client = httpx.AsyncClient(timeout=None, follow_redirects=False)
        try:
            response = await self._client.send(
                self._client.build_request(
                    request.method,
                    str(request.url),
                    headers=headers,
                    content=body if request.method == "POST" else b"",
                ),
                stream=True,
            )
        except httpx.HTTPError:
            raise
        except Exception as exc:
            raise httpx.ConnectError("Business 14 upstream is unreachable.", request=request) from exc
        response.request = request
        return response

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None


class B14HttpsPostJson:
    """The ``(status, body)`` pair Chat's service transport already returns.

    Chat's B14 client is fed either a Service Binding transport or this one, and
    both answer ``post_json``/``get_json`` with the same bounded shape, so the
    execution logic never learns which upstream it is talking to.
    """

    def __init__(self, *, transport: B14HttpsTransport, max_bytes: int) -> None:
        self._transport = transport
        self._max_bytes = max_bytes

    async def _send(self, method: str, url: str, body: bytes | None) -> tuple[int, bytes]:
        request = httpx.Request(method, url, content=body if body is not None else b"")
        response = await self._transport.handle_async_request(request)
        try:
            payload = await response.aread()
        finally:
            await response.aclose()
        if len(payload) > self._max_bytes:
            raise RuntimeError("B14 upstream response exceeded the read bound")
        return int(response.status_code), bytes(payload)

    async def post_json(self, url: str, payload: Mapping[str, object]) -> tuple[int, bytes]:
        body = json.dumps(dict(payload), ensure_ascii=False).encode("utf-8")
        return await self._send("POST", url, body)

    async def get_json(self, path: str) -> tuple[int, bytes]:
        return await self._send("GET", self._transport.origin + path, None)
