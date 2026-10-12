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
        if not isinstance(receipt, dict) or receipt.get("device_id") != wire["device_id"] or receipt.get("dispatch_authorized") is not False:
            return _error(503, "connector_enrollment_receipt_invalid")
        return _json({"ok": True, "consent": receipt}, 200)
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
        if not isinstance(receipt, dict) or receipt.get("consent_id") != wire["consent_id"] or receipt.get("dispatch_authorized") is not False:
            return _error(503, "connector_enrollment_receipt_invalid")
        return _json({"ok": True, "consent": receipt}, 200)
    except Exception as exc:
        code = getattr(exc, "code", "")
        return _error(403 if code in {"connector_enrollment_explicit_consent_required", "enrollment_consent_required", "enrollment_consent_withdrawn"} else 503,
                      code if isinstance(code, str) and _SAFE_VALUE.fullmatch(code) else "enrollment_server_dependency_unavailable")


async def connector_enrollment_issue(request: Request) -> JSONResponse:
    """Browser: current canonical session + origin/CSRF; one named device only."""
    if not auth_ready(request) or not current_user_id(request):
        return _error(401, "canonical_session_required")
    service = _service(request)
    csrf_port = getattr(request.app.state, "connector_enrollment_browser_csrf", None)
    if service is None or not callable(getattr(csrf_port, "verify", None)):
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
        receipt = service.issue(
            verified_session=session, device_id=fields["device_id"], now=moment,
        )
        # Secret is returned ONLY once to the authenticated, origin-verified
        # browser. Neither support projection nor logs can contain the code.
        public = receipt.safe_dict()
        public["pairing_code"] = receipt.pairing_code
        return _json({"ok": True, "enrollment": public}, 200)
    except ControlPlaneContractError as exc:
        return _error(503 if exc.code == "enrollment_server_dependency_unavailable" else 403, exc.code)
    except Exception:
        return _error(503, "enrollment_server_dependency_unavailable")


async def connector_enrollment_redeem(request: Request) -> JSONResponse:
    """Device: trusted gateway/TLS and possession proof; NO browser cookie.

    The gateway must validate HTTPS server identity / rate limits and attach
    a server-owned attestation. Client headers alone MUST NOT set trust.
    """
    service = _service(request)
    gateway = getattr(request.app.state, "connector_enrollment_device_gateway", None)
    if service is None or not callable(getattr(gateway, "verify", None)):
        return _error(503, "enrollment_server_dependency_unavailable")
    try:
        if gateway.verify(request) is not True:
            return _error(403, "connector_enrollment_device_gateway_denied")
        fields = await _payload(
            request, frozenset({"challenge_id", "device_id", "proof_ref"})
        )
        if fields is None or _SAFE_PROOF.fullmatch(fields["proof_ref"]) is None:
            return _error(400, "connector_enrollment_invalid_request")
        result = service.redeem(
            challenge_id=fields["challenge_id"], device_id=fields["device_id"],
            proof_ref=fields["proof_ref"], now=datetime.now(timezone.utc),
        )
        # Only after a trustworthy credential handoff has succeeded does the
        # service permit this secret-free paired_offline projection.
        return _json(result.safe_dict(), 200)
    except ControlPlaneContractError as exc:
        return _error(503 if exc.code in {
            "enrollment_server_dependency_unavailable", "enrollment_credential_handoff_failed"
        } else 403, exc.code)
    except Exception:
        return _error(503, "enrollment_server_dependency_unavailable")
