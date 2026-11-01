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
import re
import json
import time
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
#:
#: This set is complete only while it names every datetime-typed argument of every
#: allowlisted method, and that is a rule a name can silently stop satisfying: on the
#: 2026-10-30 cutover attempt `received_at` was missing, so the presence beat arrived as
#: text, `_stamp()` refused it as "trusted aware receipt time required", and every write
#: answered 502 in 0 ms — reads and the secret kept working, which is exactly what made it
#: look like a broken database. `test_queue_store_boundary` derives this list from the
#: stores' own signatures, so the next argument added without a name here fails CI.
MOMENT_ARGUMENTS = frozenset({"now", "issued_at", "received_at"})

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
    # Reads the conversation side needs when the dispatch rows live here: the pin an
    # original store checks, the terminal receipt of a run, and the run's open commands.
    # They read only the tables the queue owns, and they answer for one named owner.
    "get_oracle_mesh_dispatch_pin",
    "get_oracle_mesh_run_correlation",
    "get_oracle_mesh_run_command",
    "get_oracle_mesh_run_open_state",
    "oracle_mesh_lane_status",
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
DRIVE_METHODS = frozenset({"upsert_drives", "load_drives"})

_NO_STORE = {"Cache-Control": "no-store"}

#: Whether one line is printed per call on this door. The 2026-10-30 cutover attempt
#: could not say whether the Chat Worker's calls reached this process at all: uvicorn is
#: deliberately quiet, the refusal path is a normal response, and nothing in the queue
#: wrote a row - so "blocked at the edge", "refused here" and "answered 200 and disliked"
#: left exactly the same trace, which is none. `refusals` prints the non-2xx answers only
#: (a healthy lane prints nothing), `all` is for a bounded window during a switch.
#: Default `off` is the behaviour every deployment has run with.
LOG_OFF = "off"
LOG_REFUSALS = "refusals"
LOG_ALL = "all"
LOG_MODES = frozenset({LOG_OFF, LOG_REFUSALS, LOG_ALL})


def log_mode(value: Any) -> str:
    """The switch, read the way every other queue switch is read: unknown is `off`."""

    text = value.strip().lower() if isinstance(value, str) else ""
    return text if text in LOG_MODES else LOG_OFF


def log_line(path: str, rpc: str, status: int, elapsed_ms: int, proof: str, run_hash: str = "none", dispatch_id: str = "none") -> str:
    """One line with fixed bounded fields, no spaces inside a value.

    This is the whole surface. The secret, raw headers, the body, every argument (one of
    which can name a customer's path), the caller's address and the method name when it
    was not ours are all absent by construction: `rpc` is only ever filled from the
    allowlist, and an unknown name stays `none`.
    """
    return "MESH_QUEUE_REQUEST path=%s rpc=%s status=%d ms=%d proof=%s run_hash=%s dispatch_id=%s" % (
        path, rpc, status, elapsed_ms, proof, run_hash, dispatch_id)

__all__ = [
    "DISPATCH_METHODS", "DRIVE_METHODS", "MOMENT_ARGUMENTS", "INTERNAL_STORE_PATH", "PAIRING_METHODS",
    "PRESENCE_METHODS", "QUEUE_SERVICE_SECRET_HEADER", "STORE_FAILURE_CLASSES",
    "STORE_FAILURE_PREFIX", "TXN_RECOVERY_PREFIX", "make_internal_handler",
]


#: The door's other two line kinds. Each has a fixed shape and each appears only when the
#: door had to do something it should not have had to do, so `grep -c` on either name is a
#: count of surprises. Neither touches the five-field request line.
TXN_RECOVERY_PREFIX = "MESH_QUEUE_TXN_RECOVERED"
STORE_FAILURE_PREFIX = "MESH_QUEUE_STORE_FAILURE"

#: A store exception's *class name* is ours to print; its text is not — that text can carry
#: the customer path or the value that was rejected. Anything outside this list is printed
#: as `other`, so the label can never become a channel for caller-controlled content.
STORE_FAILURE_CLASSES = frozenset({
    "HistoryError", "MeshDevicePresenceStoreError", "MeshDeviceDriveStoreError", "PcPairingError",
    "IntegrityError", "OperationalError", "ProgrammingError", "DataError",
})


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"code": code}},
                        status_code=status, headers=_NO_STORE)


def _failure_label(exc: BaseException) -> str:
    return type(exc).__name__ if type(exc).__name__ in STORE_FAILURE_CLASSES else "other"


def _release_transaction(state: Any, facts: dict[str, str]) -> None:
    """Close a transaction the door did not open, before serving a call.

    One connection serves the whole process, so anything that leaves a `BEGIN` open poisons
    every later write for the life of the process - a call cancelled inside `batch()` was
    the route by which that happens. `batch()` no longer leaks it; this is the net under the
    door. It gets its own line kind because a queue that had to clean up after itself should
    not look ordinary in the request log.
    """

    database = getattr(state, "queue_database", None)
    connection = getattr(database, "connection", None)
    if connection is None or not getattr(connection, "in_transaction", False):
        return
    facts["txn"] = "rolled_back"
    try:
        connection.rollback()
    except Exception:
        facts["txn"] = "stuck"


def _json_safe(value: Any) -> tuple[bool, Any]:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return False, None
    return True, value


def make_internal_handler(*, state: Any, service_secret: str,
                          resolvers: dict[str, Callable[[Any], Any]],
                          request_log: str = LOG_OFF) -> Callable:
    """Build the handler bound to one assembled app state.

    `resolvers` maps an allowlisted method name to the function that finds its object on
    the app state, so a name can never reach an object the queue did not declare.
    `request_log` decides whether the door says it was knocked on (see `LOG_MODES`).
    """

    if not isinstance(service_secret, str) or not 16 <= len(service_secret) <= 256:
        raise ValueError("the queue service secret is required")
    mode = log_mode(request_log)

    async def handle(request: Request) -> JSONResponse:
        started = time.monotonic()
        facts = {"rpc": "none", "proof": "absent", "fail": "none", "txn": "none"}
        response = await _answered(request, facts)
        # Accept bounded correlation only from the authenticated internal caller.
        run_hash = dispatch_id = "none"
        if facts["proof"] == "ok":
            candidate = request.headers.get("X-Padiem-PC-Run-Hash", "")
            if re.fullmatch(r"[0-9a-f]{16}", candidate):
                run_hash = candidate
            candidate = request.headers.get("X-Padiem-PC-Dispatch-ID", "")
            if re.fullmatch(r"dsp_[0-9a-f]{32}", candidate):
                dispatch_id = candidate
        if mode != LOG_OFF and (mode == LOG_ALL or response.status_code >= 400):
            print(log_line(INTERNAL_STORE_PATH, facts["rpc"], response.status_code,
                           int((time.monotonic() - started) * 1000), facts["proof"], run_hash, dispatch_id),
                  flush=True)
            if facts["fail"] != "none":
                print("%s path=%s rpc=%s fail=%s run_hash=%s dispatch_id=%s" % (
                    STORE_FAILURE_PREFIX, INTERNAL_STORE_PATH, facts["rpc"], facts["fail"], run_hash, dispatch_id),
                    flush=True)
        if mode != LOG_OFF and facts["txn"] != "none":
            # Printed even when the call answered 200: the door had to repair the
            # connection to get there, and a success that needed that is not a normal lane.
            print("%s path=%s rpc=%s run_hash=%s dispatch_id=%s" % (
                TXN_RECOVERY_PREFIX, INTERNAL_STORE_PATH, facts["rpc"], run_hash, dispatch_id), flush=True)
        return response

    async def _answered(request: Request, facts: dict[str, str]) -> JSONResponse:
        presented = request.headers.get(QUEUE_SERVICE_SECRET_HEADER, "")
        if not presented:
            facts["proof"] = "absent"
        else:
            facts["proof"] = "ok" if _proof_ok(presented, service_secret) else "bad"
        if facts["proof"] != "ok":
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
            # The name itself is not repeated: it is caller-supplied text.
            return _error(400, "queue_method_not_allowed")
        # Only a name from this list can ever reach the log line.
        facts["rpc"] = name
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
        _release_transaction(state, facts)
        try:
            result = method(**arguments)
            if hasattr(result, "__await__"):
                result = await result
        except Exception as exc:
            # The arguments are never echoed: they can name a customer's path, and neither
            # is the exception's own text. The class name, from a fixed list, is enough to
            # tell a refused argument from a broken database - which on 2026-10-30 was the
            # difference between an hour of guessing and one line.
            facts["fail"] = _failure_label(exc)
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
