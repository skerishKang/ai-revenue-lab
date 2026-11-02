"""Owner model-console writes, carried over the existing B14 caller proof.

The browser never talks to B14 and never holds a Provider key. Chat relays one
bounded JSON document to B14 over the same server-to-server lanes the read-only
credential board uses (``B14_SERVICE`` in the Worker, the configured origin on
the CPython host) and signs the exact bytes it sends.

Every failure is a closed code. An unconfigured lane, an absent proof secret,
an unreachable B14 and a refused request stay distinguishable, and none of them
is reported as a successful write.
"""

from __future__ import annotations

import json
from typing import Any

from .b14_service_proof import MIN_PROOF_SECRET_LENGTH, service_proof_headers

B14_MODEL_ADMIN_PREFIX = "/api/pilot/v1/admin/model-ops"
REGISTRY_PATH = B14_MODEL_ADMIN_PREFIX + "/registry"
PROBE_PATH = B14_MODEL_ADMIN_PREFIX + "/model-probe"
MODEL_APPLY_PATH = B14_MODEL_ADMIN_PREFIX + "/model-apply"
MODEL_RETIRE_PATH = B14_MODEL_ADMIN_PREFIX + "/model-retire"
PROVIDER_APPLY_PATH = B14_MODEL_ADMIN_PREFIX + "/provider-apply"
CREDENTIAL_WRITE_PATH = B14_MODEL_ADMIN_PREFIX + "/credential-write"
AUDIT_PATH = B14_MODEL_ADMIN_PREFIX + "/audit"

ALLOWED_PATHS = frozenset({
    REGISTRY_PATH, PROBE_PATH, MODEL_APPLY_PATH, MODEL_RETIRE_PATH,
    PROVIDER_APPLY_PATH, CREDENTIAL_WRITE_PATH, AUDIT_PATH,
})
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 512 * 1024
REQUEST_TIMEOUT_SECONDS = 20.0

UNAVAILABLE = "b14_model_ops_unconfigured"
PROOF_UNCONFIGURED = "b14_model_ops_proof_unconfigured"
UNREACHABLE = "b14_model_ops_unreachable"
REFUSED = "b14_model_ops_refused"
INVALID = "b14_model_ops_invalid_response"


class ModelOpsUnavailable(RuntimeError):
    """A closed diagnostic code; no URL, proof, body or credential."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _encode(payload: dict[str, Any] | None) -> bytes:
    if payload is None:
        return b""
    return json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")


def _parse(body: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        raise ModelOpsUnavailable(INVALID) from None
    if not isinstance(payload, dict):
        raise ModelOpsUnavailable(INVALID)
    return payload


class HttpsModelOpsSource:
    """CPython host: the configured B14 origin over HTTPS."""

    def __init__(self, origin: str | None, proof_secret: str | None, *, client: Any = None):
        self._origin = str(origin or "").strip().rstrip("/")
        self._secret = proof_secret
        self._client = client

    async def call(self, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        if not self._origin:
            raise ModelOpsUnavailable(UNAVAILABLE)
        if path not in ALLOWED_PATHS:
            raise ValueError("unsupported B14 model-admin path")
        if not isinstance(self._secret, str) or len(self._secret) < MIN_PROOF_SECRET_LENGTH:
            raise ModelOpsUnavailable(PROOF_UNCONFIGURED)
        raw = _encode(payload)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ModelOpsUnavailable(INVALID)
        headers = {
            "Accept": "application/json",
            **service_proof_headers(self._secret, raw),
        }
        import httpx

        owned = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False,
        )
        method = "POST" if payload is not None else "GET"
        if payload is not None:
            headers["Content-Type"] = "application/json"
        raw_response = bytearray()
        try:
            async with client.stream(
                method, self._origin + path, headers=headers,
                content=raw if payload is not None else None,
            ) as response:
                status = int(response.status_code)
                async for chunk in response.aiter_bytes():
                    if len(raw_response) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ModelOpsUnavailable(INVALID)
                    raw_response.extend(chunk)
        except ModelOpsUnavailable:
            raise
        except Exception:
            raise ModelOpsUnavailable(UNREACHABLE) from None
        finally:
            if owned:
                await client.aclose()
        return status, _parse(bytes(raw_response))


class ServiceBindingModelOpsSource:
    """Worker: the deployment's ``B14_SERVICE`` binding."""

    def __init__(self, binding: Any, proof_secret: str | None):
        if binding is None:
            raise ValueError("B14 service binding is required")
        self._binding = binding
        self._secret = proof_secret

    async def call(self, path: str, payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        if path not in ALLOWED_PATHS:
            raise ValueError("unsupported B14 model-admin path")
        if not isinstance(self._secret, str) or len(self._secret) < MIN_PROOF_SECRET_LENGTH:
            raise ModelOpsUnavailable(PROOF_UNCONFIGURED)
        raw = _encode(payload)
        if len(raw) > MAX_REQUEST_BYTES:
            raise ModelOpsUnavailable(INVALID)
        headers = {
            "Accept": "application/json",
            **service_proof_headers(self._secret, raw),
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        from workers import Request

        from .service_binding_response import (
            ServiceBindingResponseError,
            ServiceBindingResponseTooLarge,
            read_bounded_service_binding_body,
        )

        try:
            request = Request(
                "https://b14.internal" + path,
                method="POST" if payload is not None else "GET",
                headers=headers,
                body=raw.decode("utf-8") if payload is not None else None,
            )
            response = await self._binding.fetch(request.js_object)
        except Exception:
            raise ModelOpsUnavailable(UNREACHABLE) from None
        status = int(getattr(response, "status", 0))
        try:
            body = await read_bounded_service_binding_body(
                response, max_bytes=MAX_RESPONSE_BYTES,
            )
        except ServiceBindingResponseTooLarge:
            raise ModelOpsUnavailable(INVALID) from None
        except ServiceBindingResponseError:
            raise ModelOpsUnavailable(UNREACHABLE) from None
        return status, _parse(body)