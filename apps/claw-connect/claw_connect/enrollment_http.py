"""#4139 Connector enrollment HTTP transport adapter (LOCAL2, fail-closed).

Implements :class:`claw_connect.enrollment.EnrollmentServerPort` against the
CENTRAL product route ``/api/claw/connector/enrollments/redeem``.

Security contract (see ``enrollment.py`` module docstring):

* **Production is blocked by default.** ``allow_production`` is False unless the
  caller explicitly enables it, and the central device-authentication gateway
  is not wired yet (``CENTRAL_DEVICE_GATEWAY_WIRED = False``). With the default
  configuration no request is ever sent.
* **Single pinned HTTPS origin.** Only an exact ``https://host`` origin on port
  443 with no credentials, query or fragment is accepted (same rule as
  ``_BROKER_URL_RE``). No redirects are followed.
* **TLS verified.** Certificate and hostname verification uses the platform
  default context. Verification is never disabled.
* **No ambient authority.** The request carries only ``Content-Type`` and
  ``Accept``. No browser cookie, Google token, or trust header is sent.
* **Possession proof only.** The wire body is exactly the three keys the central
  route accepts (``challenge_id``, ``device_id``, ``proof_ref``). S2's local
  negative-assertion flags are not part of this route's closed key set and are
  not sent. No owner, workspace, consent or session value is ever sent.
* **Bounded, fail-closed.** Timeout, transport, TLS, non-JSON, oversized, or
  shape-mismatched responses raise instead of returning a success.
* **Central response is translated, never invented.** The central success shape
  ``{"ok": true, "enrollment": {...}}`` is mapped onto
  :class:`EnrollmentRedemptionResponse`. CENTRAL #4476 now issues the
  server-owned ``consent_id`` in that receipt, so it is a required field here;
  a receipt without it is a contract violation and is refused, never
  synthesized.
* **Central safety claims are verified against the documented envelope.**
  ``credential_installed_by_canonical_handoff`` must be true, ``lifecycle`` must
  be ``paired_offline`` and every execution permission flag must be false. The
  central flags alone still do not mark the PC as enrolled: local protected
  storage must independently confirm (see ``credential_install.py``).
* **Refusals are bounded by the server's reviewed reason, never its code.**
  CENTRAL sends ``{"ok": false, "error": {"code": ...}, "reason": ...,
  "retryable": false}``; only the ``reason`` is consumed, and only when it is a
  member of ``ENROLLMENT_REFUSAL_REASONS``. ``error.code`` stays a server-side
  diagnostic and is never forwarded to a UI or persisted.
"""

from __future__ import annotations

import json
import re
import ssl
import http.client
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from .enrollment import (
    ENROLLMENT_REFUSAL_REASONS,
    EnrollmentContractError,
    EnrollmentRedemptionRequest,
    EnrollmentRedemptionResponse,
    EnrollmentServerPort,
)

#: Central product route (CENTRAL #4476, ``claw_connector_enrollment_routes.py``).
ENROLLMENT_REDEEM_PATH = "/api/claw/connector/enrollments/redeem"

#: Central device-authentication gateway is not yet mounted or wired. While this
#: is False, production use is refused regardless of configuration.
CENTRAL_DEVICE_GATEWAY_WIRED = False

MAX_RESPONSE_BYTES = 16 * 1024
DEFAULT_TIMEOUT_SECONDS = 10.0

_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?$")

#: Closed HTTP shapes of the CENTRAL device redeem route: ``_redeem_success``
#: and ``_redeem_error`` in ``apps/padiem-chat/app/claw_connector_enrollment_routes.py``.
#: A body outside these key sets is a contract violation, not a response to reinterpret.
_SUCCESS_TOP_LEVEL_KEYS = frozenset({"ok", "enrollment"})
_REFUSAL_TOP_LEVEL_KEYS = frozenset({"ok", "error", "reason", "retryable"})

#: The thirteen keys CENTRAL publishes on a redemption receipt. ``consent_id``
#: is issued from the canonical server-side authorization; the device never
#: supplies one and a receipt without it is never completed locally.
_ENROLLMENT_KEYS = frozenset(
    {
        "binding_ref",
        "device_id",
        "account_ref",
        "workspace_ref",
        "consent_id",
        "credential_generation",
        "credential_expires_at",
        "credential_installed_by_canonical_handoff",
        "raw_device_credential",
        "lifecycle",
        "dispatch_authorized",
        "grants_read",
        "grants_write",
    }
)

#: The only lifecycle a freshly redeemed PC may be projected as. ONLINE/CONNECTED
#: requires a separate canonical Broker session proof, never this receipt.
_CENTRAL_REDEEM_LIFECYCLE = "paired_offline"

#: ``error.code`` is a server-side diagnostic. It is shape-checked and discarded;
#: it never reaches the receipt, the UI, or a log.
_DIAGNOSTIC_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")

#: The reference shape CENTRAL itself emits (``_SAFE_VALUE`` in its route
#: module). A receipt value the server could not have produced is refused here
#: as well, so a forged or tampered projection cannot widen the accepted set.
_CENTRAL_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")


class EnrollmentTransportError(EnrollmentContractError):
    """Raised for every transport-level or contract failure. Never a success."""


def _validate_origin(origin: str) -> tuple[str, str]:
    """Return ``(host, origin)`` for an exact https origin on port 443, else raise."""
    if not isinstance(origin, str) or not origin:
        raise EnrollmentTransportError("enrollment_origin_not_configured")
    parts = urlsplit(origin)
    if parts.scheme != "https":
        raise EnrollmentTransportError("enrollment_origin_must_be_https")
    if parts.username or parts.password:
        raise EnrollmentTransportError("enrollment_origin_must_not_carry_credentials")
    if parts.query or parts.fragment:
        raise EnrollmentTransportError("enrollment_origin_must_not_carry_query")
    if parts.path not in ("", "/"):
        raise EnrollmentTransportError("enrollment_origin_must_be_bare_origin")
    if parts.port not in (None, 443):
        raise EnrollmentTransportError("enrollment_origin_port_must_be_443")
    host = parts.hostname or ""
    if not _HOST_RE.fullmatch(host):
        raise EnrollmentTransportError("enrollment_origin_host_invalid")
    return host, f"https://{host}"


def _parse_iso_strict(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise EnrollmentTransportError(f"{field_name}_must_be_iso_text")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise EnrollmentTransportError(f"{field_name}_must_be_iso_text") from exc
    if parsed.tzinfo is None:
        raise EnrollmentTransportError(f"{field_name}_must_be_timezone_aware")
    return parsed.astimezone(timezone.utc)


def _central_ref(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or _CENTRAL_REF_RE.fullmatch(value) is None:
        raise EnrollmentTransportError(f"{field_name}_must_be_bounded_reference")
    return value


def _translate_refusal(payload: dict[str, Any]) -> EnrollmentRedemptionResponse:
    """Consume CENTRAL's bounded refusal; discard its diagnostic code."""
    if set(payload) != _REFUSAL_TOP_LEVEL_KEYS:
        raise EnrollmentTransportError("enrollment_response_shape_mismatch")
    error = payload["error"]
    if type(error) is not dict or set(error) != {"code"}:
        raise EnrollmentTransportError("enrollment_response_error_shape_mismatch")
    code = error["code"]
    if not isinstance(code, str) or _DIAGNOSTIC_CODE_RE.fullmatch(code) is None:
        raise EnrollmentTransportError("enrollment_response_error_code_invalid")
    reason = payload["reason"]
    if not isinstance(reason, str) or reason not in ENROLLMENT_REFUSAL_REASONS:
        raise EnrollmentTransportError("enrollment_response_reason_unbounded")
    # S2 redemption refusals are terminal for this challenge: retry needs a new
    # challenge and a fresh OWNER consent, so a server claim of retryability is
    # a contract violation rather than something to forward.
    if payload["retryable"] is not False:
        raise EnrollmentTransportError("enrollment_response_retryable_not_false")
    return EnrollmentRedemptionResponse(ok=False, reason=reason, retryable=False)


def _translate_success(
    payload: dict[str, Any], *, expected_device_id: str, now: datetime
) -> EnrollmentRedemptionResponse:
    enrollment = payload["enrollment"]
    if type(enrollment) is not dict:
        raise EnrollmentTransportError("enrollment_response_missing_enrollment")
    keys = set(enrollment)
    if _ENROLLMENT_KEYS - keys:
        raise EnrollmentTransportError("enrollment_response_field_missing")
    # Extra keys are how a secret projection or a forged owner claim arrives.
    # Nothing outside the published thirteen fields is accepted, echoed or stored.
    if keys - _ENROLLMENT_KEYS:
        raise EnrollmentTransportError("enrollment_response_unexpected_field")
    # CENTRAL safety flags must hold exactly. A receipt that disagrees is a
    # contract mismatch, not a success to be reinterpreted.
    if enrollment["credential_installed_by_canonical_handoff"] is not True:
        raise EnrollmentTransportError("enrollment_response_install_not_confirmed")
    if enrollment["raw_device_credential"] is not False:
        raise EnrollmentTransportError("enrollment_response_exposed_raw_credential")
    if enrollment["lifecycle"] != _CENTRAL_REDEEM_LIFECYCLE:
        raise EnrollmentTransportError("enrollment_response_lifecycle_not_paired_offline")
    if enrollment["dispatch_authorized"] is not False:
        raise EnrollmentTransportError("enrollment_response_dispatch_not_false")
    if enrollment["grants_read"] is not False or enrollment["grants_write"] is not False:
        raise EnrollmentTransportError("enrollment_response_granted_execution")
    if enrollment["device_id"] != expected_device_id:
        raise EnrollmentTransportError("enrollment_device_swap_denied")
    binding_ref = _central_ref(enrollment["binding_ref"], "binding_ref")
    device_id = _central_ref(enrollment["device_id"], "device_id")
    account_ref = _central_ref(enrollment["account_ref"], "account_ref")
    workspace_ref = _central_ref(enrollment["workspace_ref"], "workspace_ref")
    consent_id = enrollment["consent_id"]
    if not isinstance(consent_id, str) or not consent_id:
        raise EnrollmentTransportError("enrollment_response_consent_id_missing")
    consent_id = _central_ref(consent_id, "consent_id")
    generation = enrollment["credential_generation"]
    if type(generation) is not int or generation < 1:
        raise EnrollmentTransportError("enrollment_response_generation_invalid")
    expires_at = _parse_iso_strict(
        enrollment["credential_expires_at"], "credential_expires_at"
    )
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise EnrollmentTransportError("enrollment_now_must_be_timezone_aware")
    if expires_at <= now.astimezone(timezone.utc):
        raise EnrollmentTransportError("enrollment_response_credential_expired")
    return EnrollmentRedemptionResponse(
        ok=True,
        binding_ref=binding_ref,
        device_id=device_id,
        account_ref=account_ref,
        workspace_ref=workspace_ref,
        credential_generation=generation,
        credential_expires_at=expires_at,
        consent_id=consent_id,
    )


def translate_central_response(
    payload: Any, *, expected_device_id: str, now: datetime
) -> EnrollmentRedemptionResponse:
    """Map CENTRAL's JSON envelope onto the S2 receipt, without inventing fields.

    * ``{"ok": true, "enrollment": {...}}`` -> success receipt, but only when the
      top level and the receipt carry *exactly* the documented keys, the safety
      flags and lifecycle match, and the credential is still live at ``now``.
      ``consent_id`` is required; it is never synthesized.
    * ``{"ok": false, "error": {"code": ...}, "reason": ..., "retryable": false}``
      -> bounded refusal. The reason must already be a member of
      ``ENROLLMENT_REFUSAL_REASONS``; anything else raises instead of being
      mapped, so no upstream code or text reaches a UI.
    """
    if type(payload) is not dict:
        raise EnrollmentTransportError("enrollment_response_shape_mismatch")
    ok = payload.get("ok")
    if ok is False:
        return _translate_refusal(payload)
    if ok is not True:
        raise EnrollmentTransportError("enrollment_response_ok_must_be_boolean")
    if set(payload) != _SUCCESS_TOP_LEVEL_KEYS:
        raise EnrollmentTransportError("enrollment_response_shape_mismatch")
    return _translate_success(
        payload, expected_device_id=expected_device_id, now=now
    )


class HttpsEnrollmentServerPort(EnrollmentServerPort):
    """Pinned-origin HTTPS adapter for the central redeem route.

    Construct with an explicit origin. Production refusal is the default:
    ``allow_production`` must be passed as True *and* the central gateway flag
    must be wired, otherwise every call raises before any socket is opened.
    """

    def __init__(
        self,
        *,
        origin: str,
        allow_production: bool = False,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        connection_factory: Callable[..., http.client.HTTPSConnection] | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._host, self._origin = _validate_origin(origin)
        self._allow_production = allow_production is True
        self._timeout = float(timeout)
        self._connection_factory = connection_factory
        self._ssl_context = ssl_context

    def _refuse_if_not_permitted(self) -> None:
        if not self._allow_production or CENTRAL_DEVICE_GATEWAY_WIRED is not True:
            raise EnrollmentTransportError("enrollment_production_gateway_not_wired")

    def _connection(self) -> http.client.HTTPSConnection:
        if self._connection_factory is not None:
            return self._connection_factory(self._host, timeout=self._timeout)
        context = self._ssl_context or ssl.create_default_context()
        return http.client.HTTPSConnection(
            self._host, 443, timeout=self._timeout, context=context
        )

    def redeem_enrollment(
        self, request: EnrollmentRedemptionRequest, *, now: datetime
    ) -> EnrollmentRedemptionResponse:
        self._refuse_if_not_permitted()
        if not isinstance(request, EnrollmentRedemptionRequest):
            raise EnrollmentTransportError("enrollment_request_shape_mismatch")
        # Closed wire key set: exactly what the central route accepts. S2's
        # local negative-assertion flags are never sent.
        wire = {
            "challenge_id": request.challenge_id,
            "device_id": request.device_id,
            "proof_ref": request.proof_ref,
        }
        body = json.dumps(wire, separators=(",", ":"), sort_keys=True).encode("utf-8")
        connection = None
        try:
            connection = self._connection()
            connection.request(
                "POST",
                ENROLLMENT_REDEEM_PATH,
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response = connection.getresponse()
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, ssl.SSLError, TimeoutError, http.client.HTTPException) as exc:
            raise EnrollmentTransportError("enrollment_transport_unavailable") from exc
        finally:
            if connection is not None:
                connection.close()
        if len(raw) > MAX_RESPONSE_BYTES:
            raise EnrollmentTransportError("enrollment_response_too_large")
        if response.status in (301, 302, 303, 307, 308):
            raise EnrollmentTransportError("enrollment_redirect_refused")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EnrollmentTransportError("enrollment_response_not_json") from exc
        result = translate_central_response(
            payload, expected_device_id=request.device_id, now=now
        )
        # CENTRAL returns a success body only under HTTP 200 and a refusal only
        # under a non-2xx status. Either direction of disagreement is a contract
        # violation and is raised, never translated into a UI message.
        if result.ok != (200 <= response.status < 300):
            raise EnrollmentTransportError("enrollment_status_body_mismatch")
        return result
