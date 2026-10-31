"""#5080: the Android device enrollment challenge on the canonical contract.

The phone runs the SAME canonical connector enrollment the desktop agent runs.
The owner session and an explicit per-device consent gate the issue, the
one-time pairing code is released to the DEVICE (never to a browser), and the
device redeems that challenge on the canonical broker pairing surface, where
the device credential is returned exactly once.

This route exists only because the browser issue route is guarded by the
browser origin/CSRF check, which a first-party Android client cannot satisfy.
It adds no new enrollment authority: it reuses the canonical Identity consent,
the canonical asynchronous enrollment host and the canonical Broker challenge.

The credential never crosses this route. The one-time pairing code is a
possession proof, not an authority, and the device credential is delivered by
the broker to the device that proved possession of that code.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

from padiem_control_plane.contracts import ControlPlaneContractError

from .control_plane_identity import AuthSessionSnapshot, IdentityBridgeError

ANDROID_ENROLLMENT_CHALLENGE_PATH = "/api/claw/connector/android-enrollment/challenge"
ANDROID_ENROLLMENT_CONFIRMATION_VERSION = "android-enrollment-consent-v1"

MAX_BODY_BYTES = 4096
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_NO_STORE = {"Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"}


def _json(body: dict[str, Any], status: int) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=_NO_STORE)


def _error(status: int, code: str) -> JSONResponse:
    return _json({"ok": False, "error": {"code": code}}, status)


def _reject_duplicate_json_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate json field")
        result[key] = value
    return result


async def _consent_payload(
    request: Request, expected: frozenset[str]
) -> dict[str, Any] | None:
    """Closed, bounded owner-consent payload; booleans are exact JSON booleans."""
    try:
        declared = request.headers.get("content-length")
        if declared is not None and (
            not declared.isdecimal() or int(declared) > MAX_BODY_BYTES
        ):
            return None
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return None
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            return None
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_json_fields)
        if type(value) is not dict or set(value) != expected:
            return None
        if any(
            key != "confirmed" and (not isinstance(item, str) or _SAFE_VALUE.fullmatch(item) is None)
            for key, item in value.items()
        ):
            return None
        if value.get("confirmed") is not True:
            return None
        return value
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


async def android_enrollment_challenge(request: Request) -> JSONResponse:
    """Device: the owner session plus an explicit per-device consent.

    The response releases the one-time pairing code to the DEVICE. The browser
    issue route keeps its own origin/CSRF guard; this route is reached by the
    first-party Android client with the same ``padiem_session`` cookie, which
    is ``SameSite=Lax`` and therefore not carried on a cross-site POST.
    """
    from .auth_routes import auth_ready, current_user_id
    from .b54_canonical_session import resolve_current_b54_canonical_session

    if not auth_ready(request) or not current_user_id(request):
        return _error(401, "canonical_session_required")
    async_host = getattr(request.app.state, "connector_enrollment_async_host", None)
    identity = getattr(request.app.state, "control_plane_identity_authority", None)
    if (
        not callable(getattr(async_host, "issue", None))
        or not callable(getattr(identity, "grant_connector_enrollment_consent", None))
    ):
        return _error(503, "enrollment_server_dependency_unavailable")
    try:
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
        fields = await _consent_payload(
            request,
            frozenset({"device_id", "confirmed", "confirmation_version"}),
        )
        if fields is None:
            return _error(400, "connector_enrollment_invalid_request")
        if fields["confirmation_version"] != ANDROID_ENROLLMENT_CONFIRMATION_VERSION:
            return _error(400, "connector_enrollment_invalid_request")
        device_id = fields["device_id"]
        # The explicit owner consent for THIS device, through the canonical
        # Identity DO. The client never supplies an account, workspace,
        # consent, binding or credential reference.
        await identity.grant_connector_enrollment_consent(
            session_id=session.session_id,
            device_id=device_id,
            confirmed=True,
            confirmation_version=fields["confirmation_version"],
        )
        # The canonical challenge through the canonical Broker DO, with the
        # current consent re-read and the owner session durably bound before the
        # one-time pairing code is released.
        public = await async_host.issue(
            canonical_session_id=session.session_id,
            device_id=device_id,
        )
        challenge = public.get("challenge") or {}
        pairing_code = public.get("pairing_code")
        challenge_id = challenge.get("challenge_id")
        if (
            not isinstance(challenge_id, str)
            or not challenge_id
            or not isinstance(pairing_code, str)
            or not pairing_code
        ):
            return _error(503, "enrollment_server_dependency_unavailable")
        return _json(
            {
                "ok": True,
                "challenge_id": challenge_id,
                "pairing_code": pairing_code,
                "expires_at": challenge.get("expires_at"),
            },
            200,
        )
    except (ControlPlaneContractError, IdentityBridgeError) as exc:
        status = getattr(exc, "status_code", 503)
        code = getattr(exc, "code", "enrollment_server_dependency_unavailable")
        return _error(int(status), str(code))
    except Exception:
        return _error(503, "enrollment_server_dependency_unavailable")
