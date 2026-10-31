"""CPython-mode HTTPS stand-ins for the Chat Worker's Service bindings (#5573 stage 2).

The Worker reaches its siblings through same-account Service bindings: either a
fetch-shaped HTTP contract over a binding, or a direct RPC method on the target
Worker entrypoint. A native CPython process has neither. This module is the one
place where those calls become HTTPS, and it is imported only by
`app.local_cpython` — the Cloudflare path keeps its bindings untouched.

Every call carries the same service-to-service proof the COM2 lanes already use
(a shared secret held on both hosts, HMAC over the exact request, never in a
log or an exception)::

    x-padiem-service-at:     <unix seconds>
    x-padiem-service-proof:  v1=<hex(hmac_sha256(secret, "v1\\n" + method + "\\n" + path + "\\n" + at + "\\n" + body))>

A target accepts the call only when the proof verifies and the timestamp is
inside its own window. The target-side endpoint is a separate PR: until a
target exposes it, the matching port here is simply never constructed, and the
lane keeps failing closed exactly as it does today.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from typing import Any, Callable

import httpx

from .b14_upstream_composition import compose_b14_transports
from .config import ConfigError

__all__ = [
    "HttpRpcBinding",
    "LocalB66PdfRendererClient",
    "ServiceProofConfigError",
    "compose_local_b14_transports",
    "service_proof_headers",
]

PROOF_HEADER = "x-padiem-service-proof"
PROOF_AT_HEADER = "x-padiem-service-at"
PROOF_VERSION = b"v1"
PDF_RENDER_PATH = "/internal/v1/render"
PDF_RESPONSE_MAX_BYTES = 32 * 1024 * 1024
_RPC_PATH_PREFIX = "/internal/rpc/"
_METHOD_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_SECRET_MIN_CHARS = 32


class ServiceProofConfigError(ConfigError):
    """A local-mode service origin/secret is missing or malformed."""


def _require_https_origin(value: str | None, *, name: str) -> str:
    raw = "" if value is None else str(value).strip()
    parsed = httpx.URL(raw) if raw else None
    if not raw or parsed is None or parsed.scheme != "https" or not parsed.host:
        raise ServiceProofConfigError(f"{name} must be an https origin")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.userinfo:
        raise ServiceProofConfigError(f"{name} must be a bare https origin")
    return raw.rstrip("/")


def _require_secret(value: str | None, *, name: str) -> str:
    raw = "" if value is None else str(value).strip()
    if len(raw) < _SECRET_MIN_CHARS:
        raise ServiceProofConfigError(f"{name} must be at least {_SECRET_MIN_CHARS} characters")
    return raw


def service_proof_headers(
    secret: str, *, method: str, path: str, body: bytes, at: int | None = None
) -> dict[str, str]:
    """The exact proof a target verifies: v1 over method, path, time and body."""

    timestamp = str(int(time.time()) if at is None else int(at)).encode("ascii")
    signed = b"\n".join(
        (PROOF_VERSION, method.upper().encode("ascii"), path.encode("utf-8"),
         timestamp, bytes(body))
    )
    proof = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return {PROOF_AT_HEADER: timestamp.decode("ascii"), PROOF_HEADER: "v1=" + proof}


class HttpRpcBinding:
    """A Binding-shaped RPC surface over HTTPS.

    `CloudflareControlPlaneIdentityAuthority`-style adapters call
    ``binding.<method>(payload)``; this object answers the same way by POSTing
    the payload to ``<origin>/internal/rpc/<method>`` and returning the parsed
    JSON object. The response envelope is the target's responsibility; the
    adapter above still validates it exactly as it does over a real binding.
    """

    def __init__(
        self,
        origin: str,
        secret: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 30.0,
    ):
        self._origin = _require_https_origin(origin, name="RPC origin")
        self._secret = _require_secret(secret, name="RPC service secret")
        self._client = client
        self._timeout = timeout_seconds

    def __getattr__(self, method: str):
        if method.startswith("_") or not _METHOD_RE.fullmatch(method):
            raise AttributeError(method)

        async def call(payload: dict[str, Any]) -> dict[str, Any]:
            if not isinstance(payload, dict):
                raise TypeError("RPC payload must be an object")
            body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            path = _RPC_PATH_PREFIX + method
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            headers.update(service_proof_headers(self._secret, method="POST", path=path, body=body))
            client = self._client
            if client is None:
                async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as fresh:
                    response = await fresh.post(self._origin + path, content=body, headers=headers)
            else:
                response = await client.post(self._origin + path, content=body, headers=headers)
            if response.status_code != 200:
                raise RuntimeError("service RPC answered a non-success status")
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("service RPC answered a non-object envelope")
            return data

        return call


class LocalB66PdfRendererClient:
    """The exact `CloudflareB66PdfRendererClient` contract over HTTPS.

    Same path, JSON key set, response ceiling and return shape; only the
    transport changes. Error messages stay generic so provider or document
    material never travels upward.
    """

    def __init__(
        self,
        origin: str,
        secret: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 120.0,
    ):
        self._origin = _require_https_origin(origin, name="B66 PDF origin")
        self._secret = _require_secret(secret, name="B66 PDF service secret")
        self._client = client
        self._timeout = timeout_seconds

    async def render_pdf(
        self, *, saved_skill_id: str, skill_fingerprint: str,
        profile_fingerprint: str, render_model: dict[str, Any],
    ) -> tuple[int, bytes, str]:
        body = json.dumps({
            "saved_skill_id": saved_skill_id,
            "skill_fingerprint": skill_fingerprint,
            "profile_fingerprint": profile_fingerprint,
            "render_model": render_model,
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        headers.update(service_proof_headers(
            self._secret, method="POST", path=PDF_RENDER_PATH, body=body,
        ))
        try:
            client = self._client
            if client is None:
                async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=False) as fresh:
                    response = await fresh.post(self._origin + PDF_RENDER_PATH, content=body, headers=headers)
            else:
                response = await client.post(self._origin + PDF_RENDER_PATH, content=body, headers=headers)
        except httpx.HTTPError as exc:
            raise RuntimeError("B66 PDF renderer response could not be read") from exc
        content = response.content
        if len(content) > PDF_RESPONSE_MAX_BYTES:
            raise RuntimeError("B66 PDF renderer response could not be read")
        return response.status_code, content, response.headers.get("content-type", "")


def compose_local_b14_transports(
    settings: Any,
    proof_secret: str | None,
    *,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> tuple[Any, Any]:
    """B14 transports for the local run — HTTPS only, never a binding fallback.

    `binding` is passed as None on purpose: a native process has no service
    binding, so the default branch can only ever yield (None, None) and the
    dispatch client fails closed instead of pretending the model is reachable.
    """

    def _client() -> httpx.AsyncClient:
        if client_factory is not None:
            return client_factory()
        return httpx.AsyncClient(timeout=None, follow_redirects=False)

    return compose_b14_transports(
        upstream_mode=str(getattr(settings, "b14_upstream_mode", "") or ""),
        origin=getattr(settings, "b14_base_url", None),
        binding=None,
        proof_secret=proof_secret,
        service_binding_factory=lambda _binding, _proof: None,
        stream_binding_factory=lambda _binding, _proof: None,
        https_client_factory=_client,
    )
