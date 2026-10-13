"""#4139 Device-originated HTTPS bootstrap ingress, deliberately NOT MOUNTED.

This is only the public-facing BEGIN/FINISH *shape* for an independently
reviewed TLS device gateway. It is NOT a credential-delivery endpoint and
never calls the canonical redemption owner. No deployment composition enables
this route. Trusted TLS ingress is an explicit server-injected guard; headers
supplied by a PC cannot assert HTTPS trust or Broker authority.

Possession of the owner-displayed single-use pairing code authorizes this
enrolment attempt. It does NOT attest that a device is physical Windows PC.
The real authenticated full-duplex credential delivery and DPAPI ACK channel
must be reviewed separately before either route is mounted.
"""
from __future__ import annotations

import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

CONNECTOR_GATEWAY_BEGIN_PATH = "/api/claw/connector/gateway/bootstrap/begin"
CONNECTOR_GATEWAY_FINISH_PATH = "/api/claw/connector/gateway/bootstrap/finish"
CONNECTOR_GATEWAY_BOOTSTRAP_ROUTES_MOUNTED = False
CONNECTOR_GATEWAY_CREDENTIAL_TRANSFER_WIRED = False

_MAX_BYTES = 1024
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+-]{0,255}$")
_LEASE_REF = re.compile(r"^gateway\.[0-9a-f]{32}$")
_PROOF = re.compile(r"^[0-9a-f]{64}$")
_BEGIN_FIELDS = frozenset({"challenge_id", "device_id"})
_FINISH_FIELDS = frozenset({"challenge_id", "device_id", "lease_ref", "proof_hex"})
_BEGIN_RESULT_FIELDS = frozenset({
    "challenge_id", "device_id", "lease_ref", "nonce_hex",
    "expires_at", "credential", "challenge_consumed",
})
_FINISH_RESULT_FIELDS = frozenset({
    "challenge_id", "device_id", "lease_ref", "verified",
    "credential", "challenge_consumed",
})
_NO_STORE = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


def _result(status: int, data: dict[str, Any]) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers=_NO_STORE)


def _deny(status: int = 503) -> JSONResponse:
    # Private Broker error internals / challenge lookup decisions never echo.
    return _result(status, {"ok": False, "error": "gateway_bootstrap_unavailable"})


def _decode_once(raw: bytes) -> dict[str, Any] | None:
    if not raw or len(raw) > _MAX_BYTES:
        return None
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_pairs)
    except (UnicodeError, ValueError, TypeError):
        return None
    return value if type(value) is dict else None


def _valid(values: dict[str, Any], *, begin: bool) -> bool:
    fields = _BEGIN_FIELDS if begin else _FINISH_FIELDS
    if set(values) != fields:
        return False
    if any(type(values.get(key)) is not str or _SAFE_REF.fullmatch(values[key]) is None
           for key in ("challenge_id", "device_id")):
        return False
    if not begin and (
        type(values["lease_ref"]) is not str
        or _LEASE_REF.fullmatch(values["lease_ref"]) is None
        or type(values["proof_hex"]) is not str
        or _PROOF.fullmatch(values["proof_hex"]) is None
    ):
        return False
    return True


async def _entry(request: Request, *, begin: bool) -> JSONResponse:
    # The only production on-switch must be server-owned. Never accept a
    # browser flag, X-Forwarded-Proto, self-asserted PC ID, or a cookie.
    app = request.app
    if getattr(app.state, "connector_gateway_bootstrap_enabled", False) is not True:
        return _deny()
    gate = getattr(app.state, "connector_gateway_trusted_tls", None)
    broker = getattr(app.state, "connector_gateway_broker_private_rpc", None)
    if (not callable(getattr(gate, "verify", None))
        or not callable(getattr(broker, "gateway_bootstrap_rpc", None))
        or request.url.scheme != "https"
        or "cookie" in request.headers or "origin" in request.headers):
        return _deny()
    try:
        if await gate.verify(request) is not True:
            return _deny(403)
    except Exception:
        return _deny()
    if not request.headers.get("content-type", "").lower().startswith("application/json"):
        return _deny(400)
    try:
        raw = await request.body()
    except Exception:
        return _deny(400)
    payload = _decode_once(raw)
    if payload is None or not _valid(payload, begin=begin):
        return _deny(400)
    name = "begin" if begin else "finish"
    try:
        result = await broker.gateway_bootstrap_rpc({
            "operation": name, "args": payload,
        })
    except Exception:
        return _deny()
    if type(result) is not dict or set(result) != {"ok", "gateway"} or result["ok"] is not True:
        return _deny()
    receipt = result["gateway"]
    expected = _BEGIN_RESULT_FIELDS if begin else _FINISH_RESULT_FIELDS
    if type(receipt) is not dict or set(receipt) != expected:
        return _deny()
    if (
        receipt["challenge_id"] != payload["challenge_id"]
        or receipt["device_id"] != payload["device_id"]
        or receipt.get("credential") is not False
        or receipt.get("challenge_consumed") is not False
        or type(receipt.get("lease_ref")) is not str
        or _LEASE_REF.fullmatch(receipt["lease_ref"]) is None
        or (not begin and (
            receipt["lease_ref"] != payload["lease_ref"]
            or receipt.get("verified") is not True
        ))
    ):
        return _deny()
    if begin and (
        type(receipt.get("nonce_hex")) is not str
        or _PROOF.fullmatch(receipt["nonce_hex"]) is None
        or type(receipt.get("expires_at")) is not str
        or len(receipt["expires_at"]) > 64
    ):
        return _deny()
    # The only permitted successful response is a no-credential nonce or
    # proof-verified receipt. It cannot be interpreted as enrolled or ONLINE.
    return _result(200, {"ok": True, **receipt})


async def connector_gateway_bootstrap_begin(request: Request) -> JSONResponse:
    return await _entry(request, begin=True)


async def connector_gateway_bootstrap_finish(request: Request) -> JSONResponse:
    return await _entry(request, begin=False)


__all__ = [
    "CONNECTOR_GATEWAY_BEGIN_PATH", "CONNECTOR_GATEWAY_FINISH_PATH",
    "CONNECTOR_GATEWAY_BOOTSTRAP_ROUTES_MOUNTED",
    "CONNECTOR_GATEWAY_CREDENTIAL_TRANSFER_WIRED",
    "connector_gateway_bootstrap_begin", "connector_gateway_bootstrap_finish",
]
