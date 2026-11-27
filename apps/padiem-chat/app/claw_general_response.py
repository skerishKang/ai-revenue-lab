"""B54 Claw general composer: terminal SSE response and canary evidence headers (#7809).

Moved verbatim out of ``claw_general_routes``, which re-exports the names other code
imports. Pure response assembly: no request, history, quota or Engine access.
"""

from __future__ import annotations

import json
import re
from typing import Any

from starlette.responses import Response

# #3655 one-shot canary evidence seam. The final Production canary needs the
# existing correlation/route refs projected to the caller, but the normal user
# surface must stay unchanged. Evidence headers are therefore emitted ONLY when
# the request carries the exact opt-in marker below (the owner one-shot harness
# sets it); every value is grammar-checked and omitted when it does not match.
# Values are opaque refs/counts from existing P01/B14 metadata seams — never
# prompts, answers, credentials, or free text.
CLAW_EVIDENCE_REQUEST_HEADER = "X-Padiem-Claw-Evidence"
CLAW_EVIDENCE_MARKER = "one-shot"
_CLAW_RUN_ID_RE = re.compile(r"^run_[0-9a-f]{24}$")
_EVIDENCE_VALUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
# B14 reports its selected route as `platform:<provider>/<model>`, so the
# route header keeps the same bounded grammar plus `/`. Rejecting it dropped
# the header for every real B14 route and left the canary without its
# selected-route evidence (#5484).
_CLAW_SELECTED_ROUTE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./:-]{0,79}$")


def _evidence_header(
    name: str,
    value: Any,
    pattern: re.Pattern[str] = _EVIDENCE_VALUE_RE,
) -> tuple[str, str] | None:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        return None
    return name, value


def _claw_evidence_response_headers(claw_run_id: str | None, outcome: Any) -> dict[str, str]:
    """Bounded opt-in canary evidence headers (#3655).

    Emitted only in evidence mode. A value that fails its grammar is omitted
    rather than degraded, so the canary can never record a fabricated ref.
    """
    headers: dict[str, str] = {}
    run_pair = _evidence_header("X-Padiem-Claw-Run-Id", claw_run_id, _CLAW_RUN_ID_RE)
    if run_pair is not None:
        headers[run_pair[0]] = run_pair[1]
    if outcome is None:
        return headers
    orch_pair = _evidence_header(
        "X-Padiem-Orchestration-Run-Id", getattr(outcome, "p01_run_id", None)
    )
    if orch_pair is not None:
        headers[orch_pair[0]] = orch_pair[1]
    route_pair = _evidence_header(
        "X-Padiem-Selected-Route-Id",
        getattr(outcome, "selected_route_id", None),
        _CLAW_SELECTED_ROUTE_ID_RE,
    )
    if route_pair is not None:
        headers[route_pair[0]] = route_pair[1]
    attempts = getattr(outcome, "provider_attempt_count", None)
    if isinstance(attempts, int) and not isinstance(attempts, bool) and 0 <= attempts <= 99:
        headers["X-Padiem-Provider-Attempts"] = str(attempts)
    fallback_used = getattr(outcome, "fallback_used", None)
    if isinstance(fallback_used, bool):
        headers["X-Padiem-Fallback-Used"] = "true" if fallback_used else "false"
    return headers


def _sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


def _claw_general_sse(
    answer: str,
    evidence_headers: dict[str, str] | None = None,
    *,
    history: tuple[dict[str, object], ...] = (),
    conversation_id: str | None = None,
    sources: tuple[dict[str, str], ...] = (),
    pending_run_id: str | None = None,
) -> Response:
    """Bounded terminal SSE, optionally preceded by real *post-execution* history.

    The current Engine client is synchronous: all P01 events are only available
    AFTER the run. Never misrepresent this event history as live progress.
    Legacy clients still see their canonical delta + done frames unchanged.
    """
    headers = {"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"}
    if evidence_headers:
        headers.update(evidence_headers)
    frames = b""
    if isinstance(history, tuple) and len(history) <= 128:
        # Fixed public fields only: no free-form message/metadata/tool input.
        keys = ("event_id", "run_id", "trace_id", "app_id", "kind", "sequence", "timestamp_iso")
        for event in history:
            if not isinstance(event, dict) or any(key not in event for key in keys):
                frames = b""  # fail closed on malformed provider/history data
                break
            frames += _sse_frame("p01_event", {
                **{key: event[key] for key in keys}, "delivery": "post_execution",
            })
    terminal = {"done": True}
    if pending_run_id is not None:
        terminal.update({"pc_pending": True, "run_id": pending_run_id})
    if conversation_id is not None:
        terminal["conversation_id"] = conversation_id
    if sources:
        terminal["sources"] = list(sources)
    frames += _sse_frame("delta", {"delta": answer}) + _sse_frame("done", terminal)
    return Response(
        frames,
        status_code=200,
        media_type="text/event-stream",
        headers=headers,
    )
