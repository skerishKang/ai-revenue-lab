"""HTTPS stand-in for the Engine's CONTROL_PLANE_ENGINE_ADMISSION binding.

On Cloudflare the Engine reaches the admission authority through a same-account
Service Binding (``apps/padiem-ai-engine/wrangler.toml``
``CONTROL_PLANE_ENGINE_ADMISSION`` → ``padiem-control-plane-engine-admission``).
A CPython host has no binding, so this module is the one place where that
authority becomes HTTPS. It is imported only by ``app.local_runtime``.

The wire contract is the existing private RPC ingress (#5573 A2), not a new one::

    POST <origin>/internal/rpc/<method>
    x-padiem-service-at:    <unix seconds>
    x-padiem-service-proof: v1=hex(hmac_sha256(secret,
        b"v1\n" + METHOD + b"\n" + path + b"\n" + at + b"\n" + body))

``proof_for`` reproduces ``packages/padiem-control-plane/internal_rpc_ingress.py``
exactly (same headers, same canonical string), so the target verifies a host
call with the code it already runs. The payload is the same object the binding
call would have carried, and the reply is the same the binding would return.

Shape matters: this object is *binding shaped* — ``fetch_entitlement_snapshot``,
``reserve_usage``, ``record_usage`` — and is put on the host env under the
binding's own name. ``worker_identity._admission_adapter_for_env`` then composes
the reviewed adapter unchanged, so no admission logic is re-implemented here and
the Engine's own fail-closed gate stays the only decision point.

Absent configuration means no binding at all: every model route keeps answering
503 ``entitlement_unavailable``, exactly as it does today. A half-configured or
malformed pair is treated the same way — absent, never permissive.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Mapping

import httpx

__all__ = [
    "ADMISSION_ORIGIN_ENV",
    "ADMISSION_SECRET_ENV",
    "AdmissionBindingConfigError",
    "HttpsAdmissionBinding",
    "admission_binding_for",
    "proof_for",
]

ADMISSION_ORIGIN_ENV = "PADIEM_ENGINE_LOCAL_ADMISSION_ORIGIN"
ADMISSION_SECRET_ENV = "PADIEM_ENGINE_LOCAL_ADMISSION_SECRET"
RPC_PATH_PREFIX = "/internal/rpc/"
AT_HEADER = "x-padiem-service-at"
PROOF_HEADER = "x-padiem-service-proof"
PROOF_VERSION = b"v1"
MIN_SECRET_CHARS = 32
DEFAULT_TIMEOUT_SECONDS = 15.0


class AdmissionBindingConfigError(ValueError):
    """The configured origin/secret pair cannot form a usable binding."""


def proof_for(secret: str, *, method: str, path: str, at: int, body: bytes) -> str:
    """The proof the Control Plane ingress verifies (shared contract)."""

    signed = b"\n".join(
        (PROOF_VERSION, method.encode("ascii"), path.encode("utf-8"),
         str(at).encode("ascii"), body)
    )
    return "v1=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def _require_https_origin(value: str | None) -> str:
    raw = "" if value is None else str(value).strip()
    parsed = httpx.URL(raw) if raw else None
    if not raw or parsed is None or parsed.scheme != "https" or not parsed.host:
        raise AdmissionBindingConfigError("admission origin must be an https origin")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment or parsed.userinfo:
        raise AdmissionBindingConfigError("admission origin must be a bare https origin")
    return raw.rstrip("/")


def _require_secret(value: str | None) -> str:
    raw = "" if value is None else str(value).strip()
    if len(raw) < MIN_SECRET_CHARS:
        raise AdmissionBindingConfigError(
            f"admission service secret must be at least {MIN_SECRET_CHARS} characters"
        )
    return raw


class HttpsAdmissionBinding:
    """``CONTROL_PLANE_ENGINE_ADMISSION`` over HTTPS with the service proof.

    Every error is a plain exception with a generic message: the caller
    (``CloudflareControlPlaneTrustClient``) maps any failure to
    ``entitlement_unavailable``, and no payload, secret or upstream text is
    carried upward.
    """

    def __init__(
        self,
        origin: str,
        secret: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._origin = _require_https_origin(origin)
        self._secret = _require_secret(secret)
        self._client = client
        self._timeout = timeout_seconds

    async def _call(self, method: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        path = RPC_PATH_PREFIX + method
        at = int(time.time())
        headers = {
            "content-type": "application/json",
            "accept": "application/json",
            AT_HEADER: str(at),
            PROOF_HEADER: proof_for(self._secret, method="POST", path=path, at=at, body=body),
        }
        try:
            if self._client is None:
                async with httpx.AsyncClient(
                    timeout=self._timeout, follow_redirects=False
                ) as fresh:
                    response = await fresh.post(self._origin + path, content=body, headers=headers)
            else:
                response = await self._client.post(
                    self._origin + path, content=body, headers=headers
                )
        except httpx.HTTPError as exc:
            raise RuntimeError("admission authority is unreachable") from exc
        if response.status_code != 200:
            raise RuntimeError("admission authority answered a non-success status")
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError("admission authority answered a non-JSON envelope") from exc
        if not isinstance(data, dict):
            raise RuntimeError("admission authority answered a non-object envelope")
        return data

    async def fetch_entitlement_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("fetch_entitlement_snapshot", payload)

    async def reserve_usage(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("reserve_usage", payload)

    async def record_usage(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("record_usage", payload)


def admission_binding_for(values: Mapping[str, Any]) -> dict[str, Any]:
    """The host env entry for the admission binding, or an empty dict.

    Returns nothing when neither name is set (today's fail-closed behaviour).
    A half-configured pair is also treated as absent instead of raising: a boot
    that silently allowed admission would be far worse than a 503, and the
    healthy path is the only one that needs the binding at all.
    """

    origin = str(values.get(ADMISSION_ORIGIN_ENV, "") or "").strip()
    secret = str(values.get(ADMISSION_SECRET_ENV, "") or "").strip()
    if not origin and not secret:
        return {}
    try:
        binding = HttpsAdmissionBinding(origin, secret)
    except AdmissionBindingConfigError:
        return {}
    return {"CONTROL_PLANE_ENGINE_ADMISSION": binding}
