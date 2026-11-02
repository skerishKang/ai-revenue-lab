"""Read the B14 credential-slot board through the existing caller proof.

Chat never holds a Provider key and never reads B14's credential plane
directly. It asks B14 for metadata over the same server-to-server lanes the
product already uses: the ``B14_SERVICE`` binding in the Worker and the
configured B14 origin in the CPython host. Both carry the existing HMAC proof
over the empty GET body, which is exactly what B14 verifies.

Every failure is a closed code. An unconfigured origin, an absent proof secret,
an unreachable B14 and a refused request are distinct, and none of them is
reported as an empty board.
"""

from __future__ import annotations

from typing import Any

from .b14_service_proof import MIN_PROOF_SECRET_LENGTH, service_proof_headers

B14_SLOT_STATUS_PATH = "/api/pilot/v1/admin/credential-slots"
MAX_RESPONSE_BYTES = 256 * 1024
REQUEST_TIMEOUT_SECONDS = 10.0

UNAVAILABLE = "b14_slot_status_unconfigured"
PROOF_UNCONFIGURED = "b14_slot_status_proof_unconfigured"
UNREACHABLE = "b14_slot_status_unreachable"
REFUSED = "b14_slot_status_refused"
INVALID = "b14_slot_status_invalid_response"


class SlotStatusUnavailable(RuntimeError):
    """A closed diagnostic code; no URL, proof, body or credential."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _proof_headers(secret: str | None) -> dict[str, str]:
    if not isinstance(secret, str) or len(secret) < MIN_PROOF_SECRET_LENGTH:
        raise SlotStatusUnavailable(PROOF_UNCONFIGURED)
    return {"Accept": "application/json", **service_proof_headers(secret, b"")}


def _parse(body: bytes) -> dict[str, Any]:
    import json

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        raise SlotStatusUnavailable(INVALID) from None
    if not isinstance(payload, dict):
        raise SlotStatusUnavailable(INVALID)
    return payload


class HttpsSlotStatusSource:
    """CPython host: the configured B14 origin over HTTPS."""

    def __init__(self, origin: str | None, proof_secret: str | None, *, client: Any = None):
        self._origin = str(origin or "").strip().rstrip("/")
        self._secret = proof_secret
        self._client = client

    async def fetch(self) -> dict[str, Any]:
        if not self._origin:
            raise SlotStatusUnavailable(UNAVAILABLE)
        headers = _proof_headers(self._secret)
        import httpx

        owned = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=False,
        )
        raw = bytearray()
        try:
            async with client.stream(
                "GET", self._origin + B14_SLOT_STATUS_PATH, headers=headers,
            ) as response:
                if response.status_code != 200:
                    raise SlotStatusUnavailable(REFUSED)
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise SlotStatusUnavailable(INVALID)
                    raw.extend(chunk)
        except SlotStatusUnavailable:
            raise
        except Exception:
            raise SlotStatusUnavailable(UNREACHABLE) from None
        finally:
            if owned:
                await client.aclose()
        return _parse(bytes(raw))


class ServiceBindingSlotStatusSource:
    """Worker: the deployment's ``B14_SERVICE`` binding."""

    def __init__(self, binding: Any, proof_secret: str | None):
        if binding is None:
            raise ValueError("B14 service binding is required")
        self._binding = binding
        self._secret = proof_secret

    async def fetch(self) -> dict[str, Any]:
        headers = _proof_headers(self._secret)
        from workers import Request

        from .service_binding_response import (
            ServiceBindingResponseError,
            ServiceBindingResponseTooLarge,
            read_bounded_service_binding_body,
        )

        try:
            request = Request(
                "https://b14.internal" + B14_SLOT_STATUS_PATH,
                method="GET",
                headers=headers,
            )
            response = await self._binding.fetch(request.js_object)
        except Exception:
            raise SlotStatusUnavailable(UNREACHABLE) from None
        if int(getattr(response, "status", 0)) != 200:
            raise SlotStatusUnavailable(REFUSED)
        try:
            body = await read_bounded_service_binding_body(
                response, max_bytes=MAX_RESPONSE_BYTES,
            )
        except ServiceBindingResponseTooLarge:
            raise SlotStatusUnavailable(INVALID) from None
        except ServiceBindingResponseError:
            raise SlotStatusUnavailable(UNREACHABLE) from None
        return _parse(body)
