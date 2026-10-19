"""Bounded non-secret attribution for a refused B62 -> Engine P01 dispatch (#3936).

Why this exists
---------------
The B62 web XLSX P01 start route intentionally keeps ONE generic public refusal
(``409 web_xlsx_p01_pause_refused``) and never echoes private Engine material
back to a browser. That concealment is correct, but it also means the evidence
needed to localize a live failure disappeared with the request: the private
Engine answers with a *bounded, allowlisted* error contract
(``{"ok": false, "error": {"code": ...}}``) and the B62 transport flattened
every one of those answers into the same generic error.

In production (#3936) a single P01 start was refused exactly that way: the B62
D1 reservation stayed ``dispatching``, no durable Engine P01 pause/continuation
was ever created, and the operator could not tell a caller-app authorization
refusal from a missing continuation store or a source-authority denial.

What this module does
---------------------
It converts an Engine refusal into exactly one bounded, non-secret stage code
plus a small closed projection (Engine HTTP status and allowlisted Engine error
code), and emits one structured log event on the Worker log channel. The public
browser response, the one-shot D1 reservation and every authorization rule stay
exactly as they were.

Evidence boundary
-----------------
An emitted event may never contain request material: no owner, workspace, run,
selection, document or conversation identifier, no source hash, no credential,
cookie, token, continuation/pause reference, no workbook bytes, no Engine
message text, no raw response body and no caller-supplied string. The Engine
error code is accepted only when it matches a conservative allowlist grammar,
and every other field is a fixed constant from this module, so a hostile or
future Engine reply can never inject text into the log stream.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Callable

SERVICE_NAME = "padiem-chat"
EVENT_NAME = "web_xlsx_p01_dispatch"

# Bounded stage vocabulary. Every stage is a fixed constant; nothing derived
# from the request, the source file or the Engine response body may become one.
STAGE_PAUSE_ISSUED = "engine_pause_issued"
STAGE_TRANSPORT_UNAVAILABLE = "engine_transport_unavailable"
STAGE_RESPONSE_UNREADABLE = "engine_response_unreadable"
STAGE_REFUSED = "engine_refused"
STAGE_DID_NOT_PAUSE = "engine_did_not_pause"
STAGE_CONTRACT_MISMATCH = "engine_pause_contract_mismatch"
STAGE_RESERVATION_REFUSED = "reservation_refused"
STAGE_PAUSE_COMMIT_FAILED = "pause_commit_failed"
STAGE_DISPATCH_UNKNOWN = "engine_dispatch_unknown"

BOUNDED_STAGES = frozenset({
    STAGE_PAUSE_ISSUED,
    STAGE_TRANSPORT_UNAVAILABLE,
    STAGE_RESPONSE_UNREADABLE,
    STAGE_REFUSED,
    STAGE_DID_NOT_PAUSE,
    STAGE_CONTRACT_MISMATCH,
    STAGE_RESERVATION_REFUSED,
    STAGE_PAUSE_COMMIT_FAILED,
    STAGE_DISPATCH_UNKNOWN,
})

# Bounded Engine-refusal stage vocabulary: the allowlisted Engine error codes
# below map into exactly these constants.
ENGINE_REFUSAL_STAGES = frozenset({
    "engine_caller_unauthenticated",
    "engine_app_not_authorized",
    "engine_identity_unavailable",
    "engine_tool_runtime_unavailable",
    "engine_tool_binding_resolution_failed",
    "engine_source_authority_denied",
    "engine_source_authority_unavailable",
    "engine_approval_verification_unavailable",
    "engine_continuation_store_unavailable",
    "engine_continuation_capacity_exceeded",
    "engine_continuation_unusable",
    "engine_request_rejected",
    "engine_tool_not_authorized",
    "engine_tool_timeout",
    "engine_internal_error",
    "engine_status_client_error",
    "engine_status_server_error",
    "engine_status_unexpected",
})

BOUNDED_STAGES = frozenset(BOUNDED_STAGES | ENGINE_REFUSAL_STAGES)

# Allowlisted Engine error codes -> bounded B62 stage code. The Engine emits
# these as fixed public-safe constants (EngineToolProjectionError / service
# identity / continuation store); a code outside this set is never repeated.
_ENGINE_CODE_STAGES = {
    # Engine caller/app authentication (service_identity + worker.py).
    "service_authentication_failed": "engine_caller_unauthenticated",
    "service_app_not_authorized": "engine_app_not_authorized",
    "service_identity_unavailable": "engine_identity_unavailable",
    "service_identity_misconfigured": "engine_identity_unavailable",
    # Trusted tool binding + source authority.
    "tool_runtime_unavailable": "engine_tool_runtime_unavailable",
    "tool_runtime_dependency_unavailable": "engine_tool_runtime_unavailable",
    "tool_binding_resolution_failed": "engine_tool_binding_resolution_failed",
    "tool_source_authority_denied": "engine_source_authority_denied",
    "tool_source_authority_unavailable": "engine_source_authority_unavailable",
    # Approval pause + durable continuation infrastructure.
    "approval_verification_unavailable": "engine_approval_verification_unavailable",
    "continuation_store_unavailable": "engine_continuation_store_unavailable",
    "tool_continuation_capacity_exceeded": "engine_continuation_capacity_exceeded",
    "continuation_identity_mismatch": "engine_continuation_unusable",
    "continuation_claimed": "engine_continuation_unusable",
    "continuation_consumed": "engine_continuation_unusable",
    "continuation_claim_failed": "engine_continuation_unusable",
    "continuation_expired": "engine_continuation_unusable",
    # Request shape / tool runtime terminal outcomes.
    "invalid_tool_request": "engine_request_rejected",
    "invalid_tool_arguments": "engine_request_rejected",
    "tool_arguments_too_large": "engine_request_rejected",
    "tool_not_registered": "engine_tool_not_authorized",
    "tool_agent_mismatch": "engine_tool_not_authorized",
    "tool_not_allowed": "engine_tool_not_authorized",
    "tool_owner_mismatch": "engine_tool_not_authorized",
    "tool_auth_scope_missing": "engine_tool_not_authorized",
    "tool_timeout": "engine_tool_timeout",
    "engine_internal_error": "engine_internal_error",
}

# Bounded grammar for an accepted Engine error code: lowercase snake case.
_ENGINE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ENGINE_CODE_UNRECOGNIZED = "engine_code_unrecognized"
ENGINE_CODE_ABSENT = "engine_code_absent"

LoggerEmitter = Callable[[dict], None]

_LOGGER = logging.getLogger("padiem_chat.web_xlsx_p01")
_LOGGER.setLevel(logging.INFO)
# Keep this stream off the root logger so this module never reconfigures
# logging for the rest of the Worker.
_LOGGER.propagate = False
if not _LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(_handler)


def parse_engine_error_code(body: object) -> str:
    """Return a bounded Engine error code, never raw response text.

    Accepts only ``body["error"]["code"]`` when it is a lowercase snake-case
    identifier bounded to 64 characters. Anything else collapses to a fixed
    constant, so response prose, identifiers or control characters can never
    reach the event.
    """
    if not isinstance(body, dict):
        return ENGINE_CODE_ABSENT
    error = body.get("error")
    if not isinstance(error, dict):
        return ENGINE_CODE_ABSENT
    code = error.get("code")
    if not isinstance(code, str):
        return ENGINE_CODE_ABSENT
    lowered = code.lower()
    if lowered != code or not _ENGINE_CODE_RE.fullmatch(code):
        return ENGINE_CODE_UNRECOGNIZED
    if code not in _ENGINE_CODE_STAGES:
        return ENGINE_CODE_UNRECOGNIZED
    return code


def classify_engine_refusal(status: object, body: object) -> str:
    """Map one refused private Engine response to a bounded B62 stage code."""
    code = parse_engine_error_code(body)
    if code not in (ENGINE_CODE_ABSENT, ENGINE_CODE_UNRECOGNIZED):
        return _ENGINE_CODE_STAGES[code]
    if isinstance(status, bool) or not isinstance(status, int):
        return STAGE_RESPONSE_UNREADABLE
    if 400 <= status < 500:
        return "engine_status_client_error"
    if 500 <= status < 600:
        return "engine_status_server_error"
    return "engine_status_unexpected"


def build_dispatch_event(
    *,
    stage: str,
    engine_status: object = None,
    engine_code: object = None,
    pause_projected: bool = False,
    reservation: str = "retained",
    service: str = SERVICE_NAME,
    occurred_at: datetime | None = None,
) -> dict:
    """Build the single bounded event emitted per P01 dispatch attempt.

    Every value is either a fixed constant from this module or an integer, so
    the event shape is closed: no caller-supplied or Engine-supplied text can
    widen it.
    """
    bounded_stage = stage if stage in BOUNDED_STAGES else STAGE_DISPATCH_UNKNOWN
    if not isinstance(engine_status, int) or isinstance(engine_status, bool):
        bounded_status: int | None = None
    else:
        bounded_status = engine_status if 100 <= engine_status <= 599 else None
    if not isinstance(engine_code, str) or not (
        engine_code in _ENGINE_CODE_STAGES
        or engine_code in (ENGINE_CODE_ABSENT, ENGINE_CODE_UNRECOGNIZED)
    ):
        bounded_code: str | None = None
    else:
        bounded_code = engine_code
    moment = occurred_at or datetime.now(timezone.utc)
    return {
        "event": EVENT_NAME,
        "service": service,
        "ts": moment.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "stage": bounded_stage,
        "engine_status": bounded_status,
        "engine_code": bounded_code,
        "pause_projected": pause_projected is True,
        "reservation": "retained" if reservation == "retained" else "none",
    }


def default_emitter(event: dict) -> None:
    """Write the event as one line of JSON on the Worker log channel."""
    _LOGGER.info(json.dumps(event, separators=(",", ":"), sort_keys=True))


def emit_dispatch_event(
    *, stage: str, engine_status: object = None, engine_code: object = None,
    pause_projected: bool = False, reservation: str = "retained",
    emitter: LoggerEmitter | None = None,
) -> None:
    """Emit one bounded attribution event; never fail the request path."""
    emit = emitter or default_emitter
    try:
        emit(build_dispatch_event(
            stage=stage, engine_status=engine_status, engine_code=engine_code,
            pause_projected=pause_projected, reservation=reservation,
        ))
    except Exception:
        # Observability must never turn a handled refusal into a crash.
        pass


__all__ = [
    "BOUNDED_STAGES",
    "ENGINE_CODE_ABSENT",
    "ENGINE_CODE_UNRECOGNIZED",
    "ENGINE_REFUSAL_STAGES",
    "EVENT_NAME",
    "SERVICE_NAME",
    "STAGE_CONTRACT_MISMATCH",
    "STAGE_DID_NOT_PAUSE",
    "STAGE_DISPATCH_UNKNOWN",
    "STAGE_PAUSE_COMMIT_FAILED",
    "STAGE_PAUSE_ISSUED",
    "STAGE_REFUSED",
    "STAGE_RESERVATION_REFUSED",
    "STAGE_RESPONSE_UNREADABLE",
    "STAGE_TRANSPORT_UNAVAILABLE",
    "build_dispatch_event",
    "classify_engine_refusal",
    "default_emitter",
    "emit_dispatch_event",
    "parse_engine_error_code",
]
