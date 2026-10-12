"""#4139 Connector enrollment HTTP product endpoints — source-only, default OFF.

These handlers are NOT inserted into the production app route table. The
existing #3650 nonproduction pairing route cannot substitute for this path.
Hosting requires ALL server-owned authorities, same-origin/CSRF middleware for
the authenticated browser issue call, and a trusted TLS/device entry point
for redeem. Unconfigured public requests always fail closed.

The service wraps S1 #4438 and never accepts owner/workspace/consent/session
from JSON. The client's one-time proof never grants READ/WRITE/P01 execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.padiem_connector_enrollment_server import CanonicalConnectorEnrollmentServer

from .auth_routes import auth_ready, current_user_id
from .b54_canonical_session import resolve_current_b54_canonical_session
from .control_plane_identity import IdentityBridgeError

CONNECTOR_ENROLLMENT_ISSUE_PATH = "/api/claw/connector/enrollments/issue"
CONNECTOR_ENROLLMENT_REDEEM_PATH = "/api/claw/connector/enrollments/redeem"
CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH = "/api/claw/connector/enrollments/consent/grant"
CONNECTOR_ENROLLMENT_CONSENT_REVOKE_PATH = "/api/claw/connector/enrollments/consent/revoke"
MAX_CONNECTOR_ENROLLMENT_BODY_BYTES = 4096
ENROLLMENT_PRODUCT_HTTP_MOUNTED = False
ENROLLMENT_PRODUCT_AUTHENTICATION_WIRED = False
ENROLLMENT_PRODUCT_DURABLE_CONSENT_WIRED = False
ENROLLMENT_PRODUCT_CREDENTIAL_HANDOFF_WIRED = False
ENROLLMENT_PRODUCT_PRODUCTION_ACTIVE = False

_NO_STORE = {
    "Cache-Control": "no-store, max-age=0",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_SAFE_PROOF = re.compile(r"^pairing-proof:[0-9a-f]{64}$")


def _json(body: dict[str, Any], status: int) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def _error(status: int, code: str) -> JSONResponse:
    return _json({"ok": False, "error": {"code": code}}, status)


# The canonical server error code is retained for operator diagnosis.
# LOCAL2 receives only a bounded S1-compatible refusal reason; no arbitrary
# upstream error string is exposed to a device. Unknown failures fail closed.
_S2_REDEEM_REFUSALS = frozenset({
    "canonical_session_required", "canonical_session_inactive",
    "enrollment_consent_required", "enrollment_consent_withdrawn",
    "enrollment_consent_scope_mismatch", "enrollment_binding_absent",
    "enrollment_consent_swap_denied", "enrollment_device_swap_denied",
    "enrollment_binding_owner_mismatch", "enrollment_binding_scope_mismatch",
    "enrollment_challenge_not_found", "enrollment_challenge_expired",
    "enrollment_duplicate_redeem_denied", "enrollment_rate_limited",
    "enrollment_duplicate_device_denied", "enrollment_binding_revoked_denied",
    "enrollment_dependency_unavailable", "enrollment_dependency_refused",
})
_S2_REDEEM_REFUSAL_ALIASES = {
    "enrollment_consent_changed_during_redeem": "enrollment_consent_withdrawn",
    "enrollment_consent_race_revoke_unconfirmed": "enrollment_dependency_unavailable",
    "credential_handoff_unavailable": "enrollment_dependency_unavailable",
    "enrollment_credential_handoff_failed": "enrollment_dependency_refused",
    "enrollment_handoff_revoke_unconfirmed": "enrollment_dependency_unavailable",
    "enrollment_server_dependency_unavailable": "enrollment_dependency_unavailable",
    "connector_enrollment_device_gateway_denied": "enrollment_dependency_refused",
    "connector_enrollment_invalid_request": "enrollment_dependency_refused",
    "invalid_pairing_proof": "enrollment_proof_invalid",
    "pairing_challenge_already_redeemed": "enrollment_duplicate_redeem_denied",
}


def _redeem_error(status: int, code: str) -> JSONResponse:
    # S2's typed EnrollmentRedemptionResponse consumes reason/retryable while
    # diagnostics may retain the canonical code. No raw error text or credential.
    reason = _S2_REDEEM_REFUSAL_ALIASES.get(
        code, code if code in _S2_REDEEM_REFUSALS else "enrollment_dependency_refused"
    )
    return _json({
        "ok": False, "error": {"code": code},
        "reason": reason, "retryable": False,
    }, status)


_PUBLIC_REDEEM_FIELDS = frozenset({
    "binding_ref", "device_id", "account_ref", "workspace_ref", "consent_id",
    "credential_generation", "credential_expires_at",
    "credential_installed_by_canonical_handoff", "raw_device_credential",
    "lifecycle", "dispatch_authorized", "grants_read", "grants_write",
})


def _redeem_success(receipt: dict[str, Any]) -> JSONResponse:
    """One strict, secret-free HTTP envelope for BOTH canonical host paths."""
    if not isinstance(receipt, dict) or set(receipt) - _PUBLIC_REDEEM_FIELDS:
        return _redeem_error(503, "enrollment_server_dependency_unavailable")
    for field in ("binding_ref", "device_id", "account_ref", "workspace_ref", "consent_id"):
        if not isinstance(receipt.get(field), str) or _SAFE_VALUE.fullmatch(receipt[field]) is None:
            return _redeem_error(503, "enrollment_server_dependency_unavailable")
    generation = receipt.get("credential_generation")
    if type(generation) is not int or generation < 1:
        return _redeem_error(503, "enrollment_server_dependency_unavailable")
    try:
        expires = receipt["credential_expires_at"]
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
        if (not isinstance(expires, datetime) or expires.tzinfo is None
                or expires.utcoffset() is None
                or expires.astimezone(timezone.utc) <= datetime.now(timezone.utc)):
            raise ValueError("expired or untrusted credential timestamp")
    except (KeyError, TypeError, ValueError, OverflowError):
        return _redeem_error(503, "enrollment_server_dependency_unavailable")
    if (
        receipt.get("credential_installed_by_canonical_handoff") is not True
        or receipt.get("raw_device_credential") is not False
        or receipt.get("lifecycle") != "paired_offline"
        or receipt.get("dispatch_authorized") is not False
        or receipt.get("grants_read", False) is not False
        or receipt.get("grants_write", False) is not False
    ):
        return _redeem_error(503, "enrollment_server_dependency_unavailable")
    public = {field: receipt[field] for field in (
        "binding_ref", "device_id", "account_ref", "workspace_ref",
        "consent_id", "credential_generation",
    )}
    public.update({
        "credential_expires_at": expires.isoformat(),
        "credential_installed_by_canonical_handoff": True,
        "raw_device_credential": False,
        "lifecycle": "paired_offline",
        "dispatch_authorized": False,
        "grants_read": False,
        "grants_write": False,
    })
    return _json({"ok": True, "enrollment": public}, 200)


# Public consent responses must never echo arbitrary private Identity DO data.
# The private typed RPC validates a known schema today, but route-level closed
# projection is a separate defense against future adapter drift, fake ports,
# or accidentally wired service bindings. Neither owner/tenant/session nor
# credential fields may cross the customer HTTP boundary.
_PUBLIC_CONSENT_FIELDS = frozenset({
    "consent_id", "device_id", "granted_at", "withdrawn_at",
    "dispatch_authorized", "grants_read", "grants_write",
})


def _public_consent_success(
    receipt: Any, *, expected_device_id: str | None = None,
    expected_consent_id: str | None = None, revoked: bool = False,
) -> JSONResponse:
    if type(receipt) is not dict or set(receipt) != _PUBLIC_CONSENT_FIELDS:
        return _error(503, "connector_enrollment_receipt_invalid")
    for name in ("consent_id", "device_id"):
        value = receipt[name]
        if not isinstance(value, str) or _SAFE_VALUE.fullmatch(value) is None:
            return _error(503, "connector_enrollment_receipt_invalid")
    if (
        (expected_device_id is not None and receipt["device_id"] != expected_device_id)
        or (expected_consent_id is not None and receipt["consent_id"] != expected_consent_id)
        or receipt["dispatch_authorized"] is not False
        or receipt["grants_read"] is not False
        or receipt["grants_write"] is not False
    ):
        return _error(503, "connector_enrollment_receipt_invalid")
    try:
        granted = datetime.fromisoformat(receipt["granted_at"].replace("Z", "+00:00"))
        if granted.tzinfo is None or granted.utcoffset() is None:
            raise ValueError("missing timezone")
        withdrawn = receipt["withdrawn_at"]
        if revoked:
            withdrawn = datetime.fromisoformat(withdrawn.replace("Z", "+00:00"))
            if withdrawn.tzinfo is None or withdrawn.utcoffset() is None or withdrawn < granted:
                raise ValueError("invalid revocation timestamp")
        elif withdrawn is not None:
            raise ValueError("grant must still be active")
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError):
        return _error(503, "connector_enrollment_receipt_invalid")
    return _json({"ok": True, "consent": {
        "consent_id": receipt["consent_id"],
        "device_id": receipt["device_id"],
        "granted_at": granted.isoformat(),
        "withdrawn_at": withdrawn.isoformat() if revoked else None,
        "dispatch_authorized": False,
        "grants_read": False,
        "grants_write": False,
    }}, 200)


async def _payload(request: Request, keys: frozenset[str]) -> dict[str, str] | None:
    try:
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdecimal() or int(declared) > MAX_CONNECTOR_ENROLLMENT_BODY_BYTES):
            return None
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return None
        raw = await request.body()
        if len(raw) > MAX_CONNECTOR_ENROLLMENT_BODY_BYTES:
            return None
        value = json.loads(raw)
        if type(value) is not dict or set(value) != keys:
            return None
        if not all(isinstance(v, str) and _SAFE_VALUE.fullmatch(v) is not None for v in value.values()):
            return None
        return value
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _service(request: Request) -> CanonicalConnectorEnrollmentServer | None:
    value = getattr(request.app.state, "connector_enrollment_server", None)
    return value if isinstance(value, CanonicalConnectorEnrollmentServer) else None



async def _consent_payload(request: Request, expected: frozenset[str]) -> dict[str, Any] | None:
    """Closed, bounded owner-consent payload; booleans are exact JSON booleans."""
    try:
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdecimal() or int(declared) > MAX_CONNECTOR_ENROLLMENT_BODY_BYTES):
            return None
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return None
        raw = await request.body()
        if len(raw) > MAX_CONNECTOR_ENROLLMENT_BODY_BYTES:
            return None
        value = json.loads(raw)
        if type(value) is not dict or set(value) != expected:
            return None
        if any(k != "confirmed" and (not isinstance(v, str) or _SAFE_VALUE.fullmatch(v) is None) for k, v in value.items()):
            return None
        if type(value.get("confirmed")) is not bool:
            return None
        return value
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


async def _verified_owner_request(request: Request) -> tuple[AuthSessionSnapshot | None, JSONResponse | None]:
    if not auth_ready(request) or not current_user_id(request):
        return None, _error(401, "canonical_session_required")
    csrf = getattr(request.app.state, "connector_enrollment_browser_csrf", None)
    if not callable(getattr(csrf, "verify", None)):
        return None, _error(503, "enrollment_server_dependency_unavailable")
    try:
        if csrf.verify(request) is not True:
            return None, _error(403, "connector_enrollment_csrf_denied")
        bridged = await resolve_current_b54_canonical_session(request)
        now = datetime.now(timezone.utc)
        uid = current_user_id(request)
        session = getattr(bridged, "auth_session", None)
        if (
            bridged is None
            or getattr(bridged, "product_user_id", None) != uid
            or not isinstance(session, AuthSessionSnapshot)
            or session.product_id != "b54-padiem-claw"
            or not session.is_active(now=now)
            or not session.tenant_id
        ):
            return None, _error(401, "canonical_session_required")
        return session, None
    except Exception:
        return None, _error(503, "enrollment_server_dependency_unavailable")


async def connector_enrollment_consent_grant(request: Request) -> JSONResponse:
    """Owner click handler: existing signed B54 login + CSRF + exact consent UI version."""
    session, denial = await _verified_owner_request(request)
    if denial is not None:
        return denial
    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(authority, "grant_connector_enrollment_consent", None)):
        return _error(503, "enrollment_server_dependency_unavailable")
    wire = await _consent_payload(request, frozenset({"device_id", "confirmed", "confirmation_version"}))
    if wire is None or wire["confirmed"] is not True or wire["confirmation_version"] != "pc-enrollment-consent-v1":
        return _error(400, "connector_enrollment_explicit_consent_required")
    try:
        receipt = await authority.grant_connector_enrollment_consent(
            session_id=session.session_id, device_id=wire["device_id"], confirmed=True,
            confirmation_version=wire["confirmation_version"],
        )
        return _public_consent_success(receipt, expected_device_id=wire["device_id"])
    except Exception as exc:
        code = getattr(exc, "code", "")
        return _error(403 if code in {"connector_enrollment_explicit_consent_required", "enrollment_consent_required", "canonical_tenant_membership_inactive"} else 503,
                      code if isinstance(code, str) and _SAFE_VALUE.fullmatch(code) else "enrollment_server_dependency_unavailable")


async def connector_enrollment_consent_revoke(request: Request) -> JSONResponse:
    """Owner-confirmed revocation; does not claim that the device Broker is offline."""
    session, denial = await _verified_owner_request(request)
    if denial is not None:
        return denial
    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    if not callable(getattr(authority, "revoke_connector_enrollment_consent", None)):
        return _error(503, "enrollment_server_dependency_unavailable")
    wire = await _consent_payload(request, frozenset({"consent_id", "confirmed", "confirmation_version"}))
    if wire is None or wire["confirmed"] is not True or wire["confirmation_version"] != "pc-enrollment-consent-v1":
        return _error(400, "connector_enrollment_explicit_consent_required")
    try:
        receipt = await authority.revoke_connector_enrollment_consent(
            session_id=session.session_id, consent_id=wire["consent_id"], confirmed=True,
            confirmation_version=wire["confirmation_version"],
        )
        return _public_consent_success(receipt, expected_consent_id=wire["consent_id"], revoked=True)
    except Exception as exc:
        code = getattr(exc, "code", "")
        return _error(403 if code in {"connector_enrollment_explicit_consent_required", "enrollment_consent_required", "enrollment_consent_withdrawn"} else 503,
                      code if isinstance(code, str) and _SAFE_VALUE.fullmatch(code) else "enrollment_server_dependency_unavailable")


async def connector_enrollment_issue(request: Request) -> JSONResponse:
    """Browser: current canonical session + origin/CSRF; one named device only."""
    if not auth_ready(request) or not current_user_id(request):
        return _error(401, "canonical_session_required")
    service = _service(request)
    async_host = getattr(request.app.state, "connector_enrollment_async_host", None)
    csrf_port = getattr(request.app.state, "connector_enrollment_browser_csrf", None)
    if (service is None and not callable(getattr(async_host, "issue", None))) or not callable(getattr(csrf_port, "verify", None)):
        return _error(503, "enrollment_server_dependency_unavailable")
    try:
        if csrf_port.verify(request) is not True:
            return _error(403, "connector_enrollment_csrf_denied")
        # The signed product-user ID is NOT the Control Plane subject ID.
        # Resolve the ACTIVE B54 canonical session through the already-reviewed
        # private identity binding. Do not accept a client/current-user string,
        # caller-chosen session ID, or a product-local session-port assertion.
        bridged = await resolve_current_b54_canonical_session(request)
        moment = datetime.now(timezone.utc)
        uid = current_user_id(request)
        session = getattr(bridged, "auth_session", None)
        if (
            bridged is None
            or getattr(bridged, "product_user_id", None) != uid
            or not isinstance(session, AuthSessionSnapshot)
            or session.product_id != "b54-padiem-claw"
            or not session.is_active(now=moment)
            or not session.tenant_id
        ):
            return _error(401, "canonical_session_required")
        fields = await _payload(request, frozenset({"device_id"}))
        if fields is None:
            return _error(400, "connector_enrollment_invalid_request")
        if callable(getattr(async_host, "issue", None)):
            # Network-capable path: consent is re-read through Identity DO,
            # challenge is issued through Broker DO, then original session is
            # durably bound before the one-time pairing code is released.
            public = await async_host.issue(
                canonical_session_id=session.session_id, device_id=fields["device_id"],
            )
        else:
            receipt = service.issue(
                verified_session=session, device_id=fields["device_id"], now=moment,
            )
            public = receipt.safe_dict()
            public["pairing_code"] = receipt.pairing_code
        return _json({"ok": True, "enrollment": public}, 200)
    except ControlPlaneContractError as exc:
        return _error(503 if exc.code == "enrollment_server_dependency_unavailable" else 403, exc.code)
    except IdentityBridgeError as exc:
        status = exc.status_code if exc.status_code in (400, 401, 403, 404, 409, 429, 503) else 503
        return _error(status, exc.code if _SAFE_VALUE.fullmatch(exc.code) else "enrollment_server_dependency_unavailable")
    except Exception:
        return _error(503, "enrollment_server_dependency_unavailable")


async def connector_enrollment_redeem(request: Request) -> JSONResponse:
    """Device: trusted gateway/TLS and possession proof; NO browser cookie.

    The gateway must validate HTTPS server identity / rate limits and attach
    a server-owned attestation. Client headers alone MUST NOT set trust.
    """
    service = _service(request)
    async_host = getattr(request.app.state, "connector_enrollment_async_host", None)
    gateway = getattr(request.app.state, "connector_enrollment_device_gateway", None)
    if (service is None and not callable(getattr(async_host, "redeem", None))) or not callable(getattr(gateway, "verify", None)):
        return _redeem_error(503, "enrollment_server_dependency_unavailable")
    try:
        if gateway.verify(request) is not True:
            return _redeem_error(403, "connector_enrollment_device_gateway_denied")
        fields = await _payload(
            request, frozenset({"challenge_id", "device_id", "proof_ref"})
        )
        if fields is None or _SAFE_PROOF.fullmatch(fields["proof_ref"]) is None:
            return _redeem_error(400, "connector_enrollment_invalid_request")
        if callable(getattr(async_host, "redeem", None)):
            # Async path performs live Identity consent/session recheck, durable
            # Broker redemption and protected OS-credential handoff. Raw device
            # credential is never put in this JSON response.
            result = await async_host.redeem(
                challenge_id=fields["challenge_id"], device_id=fields["device_id"],
                proof_ref=fields["proof_ref"],
            )
            return _redeem_success(result)
        result = service.redeem(
            challenge_id=fields["challenge_id"], device_id=fields["device_id"],
            proof_ref=fields["proof_ref"], now=datetime.now(timezone.utc),
        )
        safe = result.safe_dict()
        if not isinstance(safe, dict) or safe.get("ok") is not True:
            return _redeem_error(503, "enrollment_server_dependency_unavailable")
        return _redeem_success({key: value for key, value in safe.items() if key != "ok"})
    except ControlPlaneContractError as exc:
        status = 503 if exc.code in {
            "enrollment_server_dependency_unavailable", "enrollment_credential_handoff_failed"
        } else 403
        return _redeem_error(status, exc.code)
    except IdentityBridgeError as exc:
        # Preserve reviewed fail-closed error categories: consent loss is
        # forbidden, handoff failure is unavailable, replay is a conflict.
        status = exc.status_code if exc.status_code in (400, 401, 403, 404, 409, 429, 503) else 503
        code = exc.code if isinstance(exc.code, str) and _SAFE_VALUE.fullmatch(exc.code) else "enrollment_server_dependency_unavailable"
        return _redeem_error(status, code)
    except Exception:
        return _redeem_error(503, "enrollment_server_dependency_unavailable")
