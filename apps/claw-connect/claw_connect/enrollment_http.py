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
  :class:`EnrollmentRedemptionResponse`. The S2 receipt requires ``consent_id``
  on success, but the central route does not send it yet, so a central success
  body is refused with ``enrollment_response_consent_id_missing`` (a reported
  contract gap) instead of synthesizing the value.
* **Central installation claim is not trusted alone.** The
  ``credential_installed_by_canonical_handoff`` flag is read but does not by
  itself mark the PC as enrolled. Local secure storage must still confirm.
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
    ENROLLMENT_REFUSAL_FALLBACK,
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

#: Central refusal codes observed on ``claw_connector_enrollment_routes.py``.
#: Intersected with the S2 bounded vocabulary so a mapped reason can never be
#: outside ``ENROLLMENT_REFUSAL_REASONS``. Central codes that are NOT in the S2
#: vocabulary (reported as a contract gap) fall back to
#: ``ENROLLMENT_REFUSAL_FALLBACK`` instead of being echoed.
_CENTRAL_REFUSAL_CODES = frozenset(
    {
        "canonical_session_required",
        "connector_enrollment_csrf_denied",
        "connector_enrollment_explicit_consent_required",
        "connector_enrollment_receipt_invalid",
        "enrollment_consent_required",
        "enrollment_consent_withdrawn",
        "enrollment_device_swap_denied",
        "enrollment_challenge_expired",
        "enrollment_challenge_not_found",
        "enrollment_duplicate_redeem_denied",
        "enrollment_credential_handoff_failed",
        "credential_handoff_unavailable",
        "enrollment_server_dependency_unavailable",
        "invalid_enrollment_request",
        "invalid_pairing_proof",
        "connector_enrollment_invalid_request",
        "connector_enrollment_device_gateway_denied",
    }
)
_CENTRAL_REFUSAL_PASSTHROUGH = _CENTRAL_REFUSAL_CODES & ENROLLMENT_REFUSAL_REASONS

#: Central codes dropped to the fallback because the S2 refusal vocabulary has no
#: matching member yet. Reported to the central CTO; never echoed to the UI.
CENTRAL_REFUSAL_CODES_UNMAPPED = tuple(
    sorted(_CENTRAL_REFUSAL_CODES - ENROLLMENT_REFUSAL_REASONS)
)

#: Central success body has no ``consent_id`` while the S2 receipt requires one.
#: The adapter fails closed with an explicit contract-mismatch error instead of
#: inventing the value. Cleared only when central adds the field.
CENTRAL_SUCCESS_CONSENT_ID_PRESENT = False

_RETRYABLE_REASONS = frozenset({"enrollment_server_dependency_unavailable"}) & ENROLLMENT_REFUSAL_REASONS


_ENROLLMENT_KEYS = frozenset(
    {
        "binding_ref",
        "device_id",
        "account_ref",
        "workspace_ref",
        "credential_generation",
        "credential_expires_at",
        "lifecycle",
        "credential_installed_by_canonical_handoff",
        "raw_device_credential",
        "dispatch_authorized",
        "grants_read",
        "grants_write",
    }
)


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


def translate_central_response(payload: Any, *, expected_device_id: str) -> EnrollmentRedemptionResponse:
    """Map the central JSON envelope onto the S2 receipt, without inventing fields.

    * ``{"ok": true, "enrollment": {...}}`` -> success receipt. Every required
      field must be present and of the right type. The central route does not
      send ``consent_id`` yet, so a central success body is refused with
      ``enrollment_response_consent_id_missing`` (contract gap) rather than
      inventing the value.
    * ``{"ok": false, "error": {"code": ...}}`` -> bounded refusal only.
    """
    if type(payload) is not dict:
        raise EnrollmentTransportError("enrollment_response_shape_mismatch")
    ok = payload.get("ok")
    if ok is False:
        error = payload.get("error")
        code = error.get("code") if type(error) is dict else None
        reason = code if code in _CENTRAL_REFUSAL_PASSTHROUGH else ENROLLMENT_REFUSAL_FALLBACK
        return EnrollmentRedemptionResponse(
            ok=False, reason=reason, retryable=reason in _RETRYABLE_REASONS
        )
    if ok is not True:
        raise EnrollmentTransportError("enrollment_response_ok_must_be_boolean")
    enrollment = payload.get("enrollment")
    if type(enrollment) is not dict:
        raise EnrollmentTransportError("enrollment_response_missing_enrollment")
    missing = _ENROLLMENT_KEYS - set(enrollment)
    if missing:
        raise EnrollmentTransportError("enrollment_response_field_missing")
    # Central safety flags must hold. A central response that disagrees is a
    # contract mismatch, not a success to be reinterpreted.
    if enrollment["raw_device_credential"] is not False:
        raise EnrollmentTransportError("enrollment_response_exposed_raw_credential")
    if enrollment["dispatch_authorized"] is not False:
        raise EnrollmentTransportError("enrollment_response_dispatch_not_false")
    if enrollment["grants_read"] is not False or enrollment["grants_write"] is not False:
        raise EnrollmentTransportError("enrollment_response_granted_execution")
    if enrollment["device_id"] != expected_device_id:
        raise EnrollmentTransportError("enrollment_device_swap_denied")
    generation = enrollment["credential_generation"]
    if type(generation) is not int or generation < 1:
        raise EnrollmentTransportError("enrollment_response_generation_invalid")
    # S2 requires consent_id on a success receipt. Central does not send it yet;
    # never synthesize it. Fail closed with an explicit contract-gap reason.
    consent_id = enrollment.get("consent_id")
    if not isinstance(consent_id, str) or not consent_id:
        raise EnrollmentTransportError("enrollment_response_consent_id_missing")
    return EnrollmentRedemptionResponse(
        ok=True,
        binding_ref=enrollment["binding_ref"],
        device_id=enrollment["device_id"],
        account_ref=enrollment["account_ref"],
        workspace_ref=enrollment["workspace_ref"],
        credential_generation=generation,
        credential_expires_at=_parse_iso_strict(
            enrollment["credential_expires_at"], "credential_expires_at"
        ),
        consent_id=consent_id,
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
        result = translate_central_response(payload, expected_device_id=request.device_id)
        # A central refusal with a 2xx/4xx status is still a bounded refusal;
        # a success body under a non-2xx status is a contract mismatch.
        if result.ok and not (200 <= response.status < 300):
            raise EnrollmentTransportError("enrollment_status_body_mismatch")
        return result
