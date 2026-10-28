"""#5881 follow-on — the one internal call the 컴2 queue answers for the Chat Worker.

The Chat Worker keeps owning sessions, auth, the conversation rows and R2. What it must
stop owning is the PC-lane state — `oracle_mesh_dispatch`, `mesh_device_presence` and the
pairing directory — because those are the tables the executor claims against, and the
Cloudflare Python runtime cannot serve them reliably (measured: 9 `NoGilError` exceptions
and 3 CPU-limit kills in a 180-second window, all of it on the poll).

One endpoint instead of thirty: a name from the allowlist below is looked up on the REAL
store object and awaited with the arguments as keyword values. No rule is re-implemented
on the Chat side, which was the condition for moving this at all. Names outside the
list are refused before anything is read, and neither the arguments nor their contents
ever reach a log or an error body.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from starlette.requests import Request
from starlette.responses import JSONResponse

INTERNAL_STORE_PATH = "/internal/store"
QUEUE_SERVICE_SECRET_HEADER = "X-Padiem-Queue-Secret"
MAX_INTERNAL_BODY_BYTES = 1_000_000
MAX_METHOD_NAME_CHARS = 64

#: Arguments the store takes as a real instant. JSON has no datetime, and every one of
#: these already arrives as the same ISO `...Z` text the stores write into their columns,
#: so the boundary parses it and nothing else changes.
MOMENT_ARGUMENTS = frozenset({"now", "issued_at"})

#: The dispatch rows the queue owns. Result *content* is deliberately absent: the
#: over-budget original lives in private R2 and the delivered answer lives in the
#: conversation, both of which stay with the Chat Worker.
DISPATCH_METHODS = frozenset({
    "claim_oracle_mesh_dispatch",
    "cancel_oracle_mesh_dispatches_for_run",
    "consume_oracle_mesh_dispatch",
    "create_oracle_mesh_dispatch",
    "finish_oracle_mesh_dispatch",
    "get_oracle_mesh_dispatch_for_owner",
    "mark_oracle_mesh_store_failed",
    "oldest_pending_oracle_mesh_dispatch",
    "oracle_mesh_dispatch_cancellation",
    "oracle_mesh_node_live_claims",
    "record_oracle_mesh_first_result",
    "renew_oracle_mesh_claim",
})

#: The whole pairing directory, so every browser path reads one authority (#5573).
PAIRING_METHODS = frozenset({
    "adopt_link",
    "approve_root",
    "claim",
    "complete_claim_from_observation",
    "consume",
    "device_scope",
    "drive_roots_for_node",
    "issue_code",
    "link_for",
    "list_codes",
    "list_links",
    "links_for_owner",
    "pause_link",
    "peek_pairing_code",
    "redeem_code",
    "resolve_account_ref",
    "resume_link",
    "revoke_link",
    "revoke_root",
    "set_link_label",
})

PRESENCE_METHODS = frozenset({"upsert", "load"})

_NO_STORE = {"Cache-Control": "no-store"}

__all__ = [
    "DISPATCH_METHODS", "MOMENT_ARGUMENTS", "INTERNAL_STORE_PATH", "PAIRING_METHODS",
    "PRESENCE_METHODS", "QUEUE_SERVICE_SECRET_HEADER", "make_internal_handler",
]


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}},
                        status_code=status, headers=_NO_STORE)


def _json_safe(value: Any) -> tuple[bool, Any]:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False, None
    return True, value


def make_internal_handler(*, state: Any, service_secret: str,
                          resolvers: dict[str, Callable[[Any], Any]]) -> Callable:
    """Build the handler bound to one assembled app state.

    `resolvers` maps an allowlisted method name to the function that finds its object on
    the app state, so a name can never reach an object the queue did not declare.
    """

    if not isinstance(service_secret, str) or not 16 <= len(service_secret) <= 256:
        raise ValueError("the queue service secret is required")

    async def handle(request: Request) -> JSONResponse:
        presented = request.headers.get(QUEUE_SERVICE_SECRET_HEADER, "")
        if not _proof_ok(presented, service_secret):
            return _error(403, "queue_channel_rejected")
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdecimal()
                                     or int(declared) > MAX_INTERNAL_BODY_BYTES):
            return _error(413, "queue_body_too_large")
        try:
            raw = await request.body()
        except Exception:
            return _error(400, "queue_invalid_body")
        if len(raw) > MAX_INTERNAL_BODY_BYTES:
            return _error(413, "queue_body_too_large")
        try:
            wire = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return _error(400, "queue_invalid_body")
        if not isinstance(wire, dict) or set(wire) != {"method", "arguments"}:
            return _error(400, "queue_invalid_body")
        name = wire.get("method")
        arguments = wire.get("arguments")
        if not isinstance(name, str) or len(name) > MAX_METHOD_NAME_CHARS:
            return _error(400, "queue_invalid_body")
        if name not in resolvers:
            return _error(400, "queue_method_not_allowed")
        if not isinstance(arguments, dict):
            return _error(400, "queue_invalid_body")
        try:
            arguments = _coerce(arguments)
        except Exception:
            return _error(400, "queue_invalid_body")
        bound = resolvers[name](state)
        method = getattr(bound, name, None)
        if not callable(method):
            return _error(503, "queue_store_unavailable")
        try:
            result = method(**arguments)
            if hasattr(result, "__await__"):
                result = await result
        except Exception:
            # The arguments are never echoed: they can name a customer's path.
            return _error(502, "queue_store_failed")
        safe, decoded = _json_safe(result)
        if not safe:
            return _error(502, "queue_result_not_serializable")
        return JSONResponse({"ok": True, "result": decoded}, headers=_NO_STORE)

    return handle


def _coerce(arguments: dict[str, Any]) -> dict[str, Any]:
    """Turn the ISO text at the boundary back into the instant the store expects."""

    from datetime import datetime

    out = dict(arguments)
    for key in MOMENT_ARGUMENTS:
        value = out.get(key)
        if isinstance(value, str) and value:
            out[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return out


def _proof_ok(presented: str, expected: str) -> bool:
    if not isinstance(presented, str) or len(presented) > 512:
        return False
    return hashlib.sha256(presented.encode("utf-8")).digest() == hashlib.sha256(
        expected.encode("utf-8")).digest()
