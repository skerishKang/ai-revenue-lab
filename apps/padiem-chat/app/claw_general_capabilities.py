"""B54 Claw general: read-only session-specific capabilities (#7809 3/13).

The existing endpoint function is moved verbatim and remains exported through
claw_general_routes. It performs no new identity or entitlement operations.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from .claw_routes import _NO_STORE_HEADERS
from .claw_live_canary import live_stream_allowed


async def claw_general_capabilities(request: Request) -> JSONResponse:
    """Read-only session-specific SSE capability and opt-in pre-dispatch diagnostic.

    The normal browser GET keeps its existing one-field response and does not
    trigger an extra Control Plane lookup when live SSE is disabled. Diagnostic
    mode checks ONLY signed auth, P01 adapter presence, and current canonical
    B54 session: never quota, entitlement, Engine, B14 or Provider.
    """
    from .auth_routes import auth_ready, current_user_id

    adapter = getattr(request.app.state, "claw_p01_adapter", None)
    runner = getattr(adapter, "_runner", None)
    signed_in = bool(auth_ready(request) and current_user_id(request) is not None)
    subject_lane = (
        adapter is not None
        and getattr(adapter, "subject_identity_lane", False) is True
    )
    diagnostic = request.query_params.get("diagnostic") == "pre_dispatch_v1"
    live_candidate = bool(
        signed_in
        and getattr(request.app.state, "claw_live_sse_enabled", False) is True
        and callable(getattr(runner, "run_stream", None))
        and subject_lane
    )

    # One read-only CP session lookup maximum per GET. Normal callers with
    # live SSE disabled do not incur an additional identity roundtrip.
    session = None
    if signed_in and subject_lane and (live_candidate or diagnostic):
        from .b54_canonical_session import resolve_current_b54_canonical_session

        try:
            session = await resolve_current_b54_canonical_session(request)
        except Exception:
            # Read-only diagnostics never disclose Control Plane failures.
            session = None

    enabled = bool(
        live_candidate
        and session is not None
        and live_stream_allowed(
            request.app.state, session.auth_session.subject.subject_id
        )
    )
    result: dict[str, object] = {"live_events_available": enabled}
    if diagnostic:
        # Fixed codes only. No owner, tenant, subject, session, quota, model,
        # credential, request body or raw Control Plane exception is returned.
        if not signed_in:
            state = "authentication_required"
        elif adapter is None:
            state = "p01_adapter_unavailable"
        elif not subject_lane:
            state = "canonical_subject_lane_unverified"
        elif session is None:
            state = "canonical_b54_session_unavailable"
        else:
            state = "pre_quota_ready"
        result["pre_dispatch_status"] = state
        result["pre_dispatch_scope"] = "auth_adapter_session_only"
    return JSONResponse(result, headers=_NO_STORE_HEADERS)
