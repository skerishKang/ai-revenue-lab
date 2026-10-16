"""Unmounted B54 owner approval endpoint for pending outbound PC link (#4139).

Uses exactly the existing authenticated owner session, same-origin CSRF guard
and canonical consent/Broker service. There is deliberately no route in the
production or acceptance app until a real durable one-use outbound PC
rendezvous provider has been authenticated and bound by server configuration.
"""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse

from .claw_connector_enrollment_routes import (
    _payload, _error, _json, _verified_owner_request,
)
from .connector_one_click_approval import OneClickDenied, OneClickOwnerApproval
from .connector_owner_one_click_factory import VerifiedOwnerOneClickFactory
from .connector_owner_native_pc_completion import CanonicalOwnerNativePcCompletion
from .control_plane_identity import IdentityBridgeError
from .request_telemetry import emit_stage_event

OWNER_APPROVE_LINK_PATH = "/api/claw/connector/enrollments/approve-link"
OWNER_APPROVE_LINK_MOUNTED = False
_REQUEST_KEYS = frozenset({"request_ref"})
_REFUSAL_STATUSES = {
    "canonical_owner_session_required": 401,
    "explicit_pc_consent_required": 400,
    "invalid_pending_pc_request": 400,
    "pending_pc_unavailable": 503,
    "pending_pc_not_authenticated": 403,
    "pending_pc_expired": 409,
    "canonical_consent_unavailable": 503,
    "canonical_consent_unconfirmed": 403,
    "canonical_challenge_unavailable": 503,
    "canonical_challenge_invalid": 503,
    "pc_delivery_unconfirmed": 503,
}
_NATIVE_FAILURE_CODES = frozenset({
    "pending_pc_live_fetch_unavailable", "pending_pc_fetch_invalid",
    "pending_pc_identity_unconfirmed", "pending_pc_claim_unconfirmed",
    "pending_pc_claim_invalid", "pending_pc_identity_changed",
    "native_pc_protected_gateway_unavailable", "native_pc_canonical_result_invalid",
    "enrollment_credential_handoff_failed",
    "native_pc_terminal_unconfirmed", "native_pc_terminal_revoke_unconfirmed",
})


async def owner_approve_pc_link(request: Request) -> JSONResponse:
    """Single explicit browser approval, not a login or a pairing success."""
    session, denial = await _verified_owner_request(request)
    if denial is not None:
        emit_stage_event(stage="pc_owner.owner_guard", outcome="error",
                         duration_ms=0, code="owner_guard_denied")
        return denial

    port = getattr(request.app.state, "connector_one_click_approval", None)
    factory = getattr(request.app.state, "connector_one_click_approval_factory", None)
    if port is None and type(factory) is VerifiedOwnerOneClickFactory:
        try:
            # Per-request: the SAME authoritative signed owner checked above
            # supplies the private Broker caller scope; never browser JSON.
            port = factory.for_verified_owner(signed_owner=session)
        except Exception:
            emit_stage_event(stage="pc_owner.factory", outcome="error",
                             duration_ms=0, code="factory_unavailable")
            return _error(503, "pending_pc_unavailable")
    if type(port) is not OneClickOwnerApproval:
        emit_stage_event(stage="pc_owner.factory", outcome="error",
                         duration_ms=0, code="factory_missing")
        return _error(503, "pending_pc_unavailable")

    wire = await _payload(request, _REQUEST_KEYS)
    if wire is None:
        emit_stage_event(stage="pc_owner.payload", outcome="error",
                         duration_ms=0, code="payload_invalid")
        return _error(400, "invalid_pending_pc_request")

    try:
        result = await port.approve(
            owner_session=session,
            request_ref=wire["request_ref"],
            # The verified POST connect action and same live PC proof,
            # not a browser-provided boolean, authorize the canonical grant.
            confirmed=True,
        )
    except OneClickDenied as exc:
        reason = str(exc)
        # Never export arbitrary exception text, only this route's fixed enum.
        safe = reason if reason in _REFUSAL_STATUSES else "unclassified"
        emit_stage_event(stage="pc_owner.approve", outcome="error",
                         duration_ms=0, code=safe)
        if reason not in _REFUSAL_STATUSES:
            return _error(503, "pending_pc_unavailable")
        return _error(_REFUSAL_STATUSES[reason], reason)
    except Exception:
        emit_stage_event(stage="pc_owner.approve", outcome="error",
                         duration_ms=0, code="unhandled_refusal")
        return _error(503, "pending_pc_unavailable")
    # Strip any unexpected downstream data even if a trusted in-process port
    # is later refactored; credentials and challenge ids are not browser data.
    if (
        type(result) is not dict
        or set(result) != {
            "ok", "state", "device_id", "connected", "registered",
            "dispatch_authorized",
        }
        or result.get("ok") is not True
        or result.get("state") != "awaiting_device_confirmation"
        or any(result.get(name) is not False for name in (
            "connected", "registered", "dispatch_authorized",
        ))
        or not isinstance(result.get("device_id"), str)
    ):
        emit_stage_event(stage="pc_owner.receipt", outcome="error",
                         duration_ms=0, code="receipt_invalid")
        return _error(503, "pending_pc_unavailable")
    emit_stage_event(stage="pc_owner.delivery_requested", outcome="ok",
                     duration_ms=0)
    completion = getattr(request.app.state, "connector_owner_native_pc_completion", None)
    if completion is not None:
        if type(completion) is not CanonicalOwnerNativePcCompletion:
            return _error(503, "native_pc_registration_unconfirmed")
        try:
            installed = await completion.complete(
                signed_owner=session, request_ref=wire["request_ref"],
            )
            if (
                type(installed) is not dict
                or installed.get("device_id") != result["device_id"]
                or installed.get("lifecycle") != "paired_offline"
                or installed.get("credential_installed_by_canonical_handoff") is not True
            ):
                raise ValueError("canonical installation was not confirmed")
        except Exception as exc:
            code = getattr(exc, "code", None)
            safe = code if code in _NATIVE_FAILURE_CODES else "native_pc_registration_unconfirmed"
            emit_stage_event(stage="pc_owner.native_registration", outcome="error",
                             duration_ms=0, code=safe)
            status = exc.status_code if isinstance(exc, IdentityBridgeError) and exc.status_code in (401, 403, 409) else 503
            return _error(status, safe)
        emit_stage_event(stage="pc_owner.native_registration", outcome="ok", duration_ms=0)
        return _json({
            "ok": True, "state": "paired_offline", "device_id": result["device_id"],
            "connected": False, "registered": True, "dispatch_authorized": False,
        }, 200)
    return _json({
        "ok": True, "state": "awaiting_device_confirmation",
        "device_id": result["device_id"], "connected": False,
        "registered": False, "dispatch_authorized": False,
    }, 200)
