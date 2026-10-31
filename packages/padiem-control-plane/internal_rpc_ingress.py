"""Default-off HTTPS RPC ingress for the private Control Plane Workers (#5573 A2).

The Chat CPython host (PR #6142) signs exactly this contract:

    POST /internal/rpc/<method>
    x-padiem-service-at:    <unix seconds>
    x-padiem-service-proof: v1=hex(hmac_sha256(secret,
        b"v1\\n" + METHOD + b"\\n" + path + b"\\n" + at + b"\\n" + body))

Rules that keep the private binding the primary door:

* Without the worker's secret binding this module never runs — ``fetch`` keeps
  its plain 404 and nothing is registered.
* Only an explicit per-worker allowlist is reachable; anything else answers
  404 so the method inventory is not enumerable.
* The proof is compared in constant time, the timestamp may be at most 300 s
  away from the worker clock, and the body is capped (512 KiB) before and
  after it is read.
* No error envelope echoes method names, secrets, payloads or upstream text.
"""
from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import re
import time
from typing import Any
from urllib.parse import urlsplit

__all__ = [
    "AT_HEADER",
    "MAX_BODY_BYTES",
    "MAX_CLOCK_SKEW_SECONDS",
    "PROOF_HEADER",
    "PROOF_VERSION",
    "RPC_PATH_PREFIX",
    "DEFAULT_SERVICE_ID_POLICY",
    "SERVICE_ID_HEADER",
    "SERVICE_ID_POLICIES",
    "SERVICE_ID_POLICY_ENV",
    "handle_internal_rpc",
    "proof_for",
    "proof_for_v2",
    "resolve_ingress_secret",
    "rpc_method_from_path",
    "service_id_policy_from_env",
]

RPC_PATH_PREFIX = "/internal/rpc/"
PROOF_HEADER = "x-padiem-service-proof"
AT_HEADER = "x-padiem-service-at"
PROOF_VERSION = b"v1"
MAX_BODY_BYTES = 512 * 1024
MAX_CLOCK_SKEW_SECONDS = 300
_METHOD_RE = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

# Replay defence (#6417). Every signed request names itself once, and the id is
# part of the signature, so a captured request cannot be re-signed under another
# id. The clock window alone cannot stop a byte-identical replay inside 300 s;
# ``replay_guard`` records each id for the life of that window.
#
# ``service_id_policy``:
#   "required" — no id, or a v1 proof with an id header, is refused;
#   "optional" — transitional: a v1 proof with no id is still accepted;
#   "legacy"   — v1 only (existing behaviour, retained for one release).
SERVICE_ID_HEADER = "x-padiem-service-id"
PROOF_VERSION_V2 = b"v2"
SERVICE_ID_POLICIES = ("required", "optional", "legacy")
DEFAULT_SERVICE_ID_POLICY = "optional"
SERVICE_ID_POLICY_ENV = "PADIEM_RPC_SERVICE_ID_POLICY"
_SERVICE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$")
_NO_STORE = {"cache-control": "no-store", "content-type": "application/json"}


def _error(status: int, code: str, message: str) -> tuple[int, dict[str, Any], dict[str, str]]:
    return status, {"ok": False, "error": {"code": code, "message": message}}, dict(_NO_STORE)


def proof_for(secret: str, *, method: str, path: str, at: int, body: bytes) -> str:
    signed = b"\n".join(
        (PROOF_VERSION, method.encode("ascii"), path.encode("utf-8"), str(at).encode("ascii"), body)
    )
    return "v1=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def proof_for_v2(
    secret: str, *, method: str, path: str, at: int, service_id: str, body: bytes
) -> str:
    """The id-bound proof: the v1 fields plus the request id, under ``v2``."""

    signed = b"\n".join(
        (
            PROOF_VERSION_V2,
            method.encode("ascii"),
            path.encode("utf-8"),
            str(at).encode("ascii"),
            service_id.encode("utf-8"),
            body,
        )
    )
    return "v2=" + hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()


def service_id_policy_from_env(value: Any) -> str:
    """The configured policy, defaulting to ``optional`` for one release."""

    text = "" if value is None else str(value).strip().lower()
    return text if text in SERVICE_ID_POLICIES else DEFAULT_SERVICE_ID_POLICY


def rpc_method_from_path(path: str) -> str | None:
    if not isinstance(path, str) or not path.startswith(RPC_PATH_PREFIX):
        return None
    name = path[len(RPC_PATH_PREFIX):]
    return name if _METHOD_RE.fullmatch(name) else None


async def resolve_ingress_secret(binding: Any) -> str | None:
    """The secret as a plain string, a Secrets Store capability, or None.

    None means the ingress is not configured and the worker keeps its plain
    404 — the door is not registered, not merely locked.
    """

    if binding is None:
        return None
    value = binding
    getter = getattr(binding, "get", None)
    if callable(getter) and not isinstance(binding, str):
        value = getter()
        if inspect.isawaitable(value):
            value = await value
    text = "" if value is None else str(value).strip()
    return text or None


async def _read_body(request: Any) -> bytes:
    reader = getattr(request, "text", None)
    if callable(reader):
        raw = await reader()
        return raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
    body = await request.body()
    return bytes(body)


async def handle_internal_rpc(
    request: Any,
    *,
    secret: str,
    allowed_methods: frozenset[str],
    dispatcher: Any,
    now: int | None = None,
    service_id_policy: str = DEFAULT_SERVICE_ID_POLICY,
    replay_guard: Any = None,
) -> tuple[int, dict[str, Any], dict[str, str]] | None:
    """Answer one ingress request, or ``None`` when the path is not ours.

    ``None`` is the caller's signal to keep today's plain 404 untouched.
    """

    path = urlsplit(str(request.url)).path
    method_name = rpc_method_from_path(path)
    if method_name is None:
        return None
    if str(request.method).upper() != "POST":
        return _error(405, "rpc_method_not_allowed", "POST only.")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY_BYTES:
                return _error(413, "rpc_body_too_large", "Request body exceeds the ceiling.")
        except ValueError:
            return _error(400, "rpc_invalid_length", "Invalid content length.")
    body = await _read_body(request)
    if len(body) > MAX_BODY_BYTES:
        return _error(413, "rpc_body_too_large", "Request body exceeds the ceiling.")
    if method_name not in allowed_methods:
        # Same answer as a typo: the inventory is not enumerable.
        return _error(404, "rpc_unknown_method", "Unknown RPC method.")
    at_raw = request.headers.get(AT_HEADER)
    proof_raw = request.headers.get(PROOF_HEADER)
    if not isinstance(at_raw, str) or not isinstance(proof_raw, str):
        return _error(403, "rpc_proof_required", "Service proof required.")
    try:
        at = int(at_raw)
    except ValueError:
        return _error(403, "rpc_proof_invalid", "Service proof invalid.")
    current = int(time.time()) if now is None else int(now)
    if abs(current - at) > MAX_CLOCK_SKEW_SECONDS:
        return _error(403, "rpc_proof_stale", "Service proof expired.")
    policy = service_id_policy if service_id_policy in SERVICE_ID_POLICIES else DEFAULT_SERVICE_ID_POLICY
    service_id = request.headers.get(SERVICE_ID_HEADER)
    if service_id is not None and (
        not isinstance(service_id, str) or not _SERVICE_ID_RE.fullmatch(service_id)
    ):
        return _error(403, "rpc_service_id_invalid", "Service request id invalid.")
    if policy == "required" and service_id is None:
        return _error(403, "rpc_service_id_required", "Service request id required.")
    if service_id is not None:
        expected_v2 = proof_for_v2(
            secret, method="POST", path=path, at=at, service_id=service_id, body=body
        )
        if not hmac.compare_digest(expected_v2, proof_raw):
            # An id that is not inside the signature is not a request identity.
            legacy = proof_for(secret, method="POST", path=path, at=at, body=body)
            if hmac.compare_digest(legacy, proof_raw):
                return _error(403, "rpc_service_id_unsigned", "Service request id is not signed.")
            return _error(403, "rpc_proof_invalid", "Service proof invalid.")
        if replay_guard is None:
            return _error(
                503,
                "rpc_replay_guard_unavailable",
                "Service request replay guard unavailable.",
            )
        try:
            claimed = await replay_guard.claim(
                service_id, expires_at=at + MAX_CLOCK_SKEW_SECONDS
            )
        except Exception:
            return _error(503, "rpc_replay_guard_error", "Service request replay guard failed.")
        if claimed is False:
            return _error(409, "rpc_replay_detected", "Service request was already used.")
        if claimed is not True:
            return _error(503, "rpc_replay_guard_error", "Service request replay guard failed.")
    else:
        expected = proof_for(secret, method="POST", path=path, at=at, body=body)
        if not hmac.compare_digest(expected, proof_raw):
            return _error(403, "rpc_proof_invalid", "Service proof invalid.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _error(400, "rpc_invalid_json", "Body must be one JSON object.")
    if not isinstance(payload, dict):
        return _error(400, "rpc_invalid_json", "Body must be one JSON object.")
    handler = getattr(dispatcher, method_name, None)
    if not callable(handler):
        return _error(404, "rpc_unknown_method", "Unknown RPC method.")
    try:
        result = handler(payload)
        if hasattr(result, "__await__"):
            result = await result
    except Exception:
        return _error(500, "rpc_failed", "The RPC did not complete.")
    if not isinstance(result, dict):
        return _error(500, "rpc_invalid_result", "The RPC answered an invalid result.")
    return 200, result, dict(_NO_STORE)
