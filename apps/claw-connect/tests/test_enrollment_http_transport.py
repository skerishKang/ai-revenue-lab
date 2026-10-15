"""#4139 LOCAL2 enrollment HTTP transport tests (isolated, no real sockets).

Covers the required matrix: normal contract, auth failure, unconfigured server,
TLS failure, tampered response, other-PC id, consent withdrawn, replay,
server field mismatch, and proof that no ambient authority is transmitted.
"""

from __future__ import annotations

import json
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from claw_connect.enrollment import (  # noqa: E402
    ENROLLMENT_REFUSAL_REASONS,
    EnrollmentRedemptionRequest,
    EnrollmentRedemptionResponse,
)
from claw_connect.enrollment_http import (  # noqa: E402
    CENTRAL_DEVICE_GATEWAY_WIRED,
    ENROLLMENT_REDEEM_PATH,
    EnrollmentTransportError,
    HttpsEnrollmentServerPort,
    translate_central_response,
)

ORIGIN = "https://chat.padiem.net"
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def _request(device_id: str = "pc_abc123") -> EnrollmentRedemptionRequest:
    return EnrollmentRedemptionRequest(
        challenge_id="challenge-1",
        device_id=device_id,
        proof_ref="pairing-proof:" + "a" * 64,
    )


def _success_enrollment(**overrides):
    # CENTRAL's post-fix success receipt (_redeem_success at CENTRAL 264437961):
    # the twelve published keys plus the server-owned consent_id.
    payload = {
        "binding_ref": "binding-1",
        "device_id": "pc_abc123",
        "account_ref": "acct-1",
        "workspace_ref": "ws-1",
        "credential_generation": 3,
        "credential_expires_at": "2027-01-01T00:00:00Z",
        "consent_id": "consent-1",
        "lifecycle": "paired_offline",
        "credential_installed_by_canonical_handoff": True,
        "raw_device_credential": False,
        "dispatch_authorized": False,
        "grants_read": False,
        "grants_write": False,
    }
    payload.update(overrides)
    return payload


def _refusal(code: str, reason: str, **overrides):
    """CENTRAL's ``_redeem_error`` envelope: bounded reason, code kept server-side."""
    payload = {
        "ok": False,
        "error": {"code": code},
        "reason": reason,
        "retryable": False,
    }
    payload.update(overrides)
    return payload


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self, _n: int = -1) -> bytes:
        return self._body


class _FakeConnection:
    def __init__(self, *, status=200, payload=None, raw=None, raise_on_request=None):
        self._status = status
        self._payload = payload
        self._raw = raw
        self._raise = raise_on_request
        self.sent = None

    def request(self, method, path, body=None, headers=None):
        if self._raise is not None:
            raise self._raise
        self.sent = {"method": method, "path": path, "body": body, "headers": headers}

    def getresponse(self):
        if self._raw is not None:
            return _FakeResponse(self._status, self._raw)
        return _FakeResponse(self._status, json.dumps(self._payload).encode("utf-8"))

    def close(self):
        pass


def _port(connection: _FakeConnection, monkeypatch, *, allow_production=True):
    monkeypatch.setattr(
        "claw_connect.enrollment_http.CENTRAL_DEVICE_GATEWAY_WIRED", True, raising=False
    )
    return HttpsEnrollmentServerPort(
        origin=ORIGIN,
        allow_production=allow_production,
        connection_factory=lambda host, timeout=None: connection,
    )


# --- configuration and fail-closed gates -----------------------------------
def test_unconfigured_or_production_refused_by_default(monkeypatch):
    connection = _FakeConnection(payload={"ok": True, "enrollment": _success_enrollment()})
    default_port = HttpsEnrollmentServerPort(
        origin=ORIGIN, connection_factory=lambda host, timeout=None: connection
    )
    with pytest.raises(EnrollmentTransportError) as exc:
        default_port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_production_gateway_not_wired"
    # No socket call happened.
    assert connection.sent is None


def test_production_still_refused_while_central_gateway_unwired(monkeypatch):
    monkeypatch.setattr(
        "claw_connect.enrollment_http.CENTRAL_DEVICE_GATEWAY_WIRED", False, raising=False
    )
    connection = _FakeConnection(payload={"ok": True, "enrollment": _success_enrollment()})
    port = HttpsEnrollmentServerPort(
        origin=ORIGIN,
        allow_production=True,
        connection_factory=lambda host, timeout=None: connection,
    )
    with pytest.raises(EnrollmentTransportError):
        port.redeem_enrollment(_request(), now=NOW)
    assert connection.sent is None
    assert CENTRAL_DEVICE_GATEWAY_WIRED is False


@pytest.mark.parametrize(
    "bad",
    [
        "http://chat.padiem.net",
        "https://user:pass@chat.padiem.net",
        "https://chat.padiem.net/path",
        "https://chat.padiem.net:8443",
        "https://chat.padiem.net?x=1",
        "https://chat.padiem.net#frag",
        "",
    ],
)
def test_origin_allowlist_rejects_non_canonical_origins(bad):
    with pytest.raises(EnrollmentTransportError):
        HttpsEnrollmentServerPort(origin=bad)


# --- normal contract --------------------------------------------------------
def test_normal_contract_translates_to_receipt(monkeypatch):
    connection = _FakeConnection(payload={"ok": True, "enrollment": _success_enrollment()})
    port = _port(connection, monkeypatch)
    result = port.redeem_enrollment(_request(), now=NOW)
    assert isinstance(result, EnrollmentRedemptionResponse)
    assert result.ok is True
    assert result.binding_ref == "binding-1"
    assert result.device_id == "pc_abc123"
    assert result.credential_generation == 3
    assert result.consent_id == "consent-1"
    assert connection.sent["method"] == "POST"
    assert connection.sent["path"] == ENROLLMENT_REDEEM_PATH


def test_central_success_without_consent_id_key_fails_closed(monkeypatch):
    # consent_id is part of the published thirteen keys. A receipt that omits it
    # is a contract violation; the adapter never invents the value.
    payload = {"ok": True, "enrollment": _success_enrollment()}
    del payload["enrollment"]["consent_id"]
    connection = _FakeConnection(payload=payload)
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_field_missing"


@pytest.mark.parametrize("blank", ["", None, 0, "consent 1"])
def test_central_success_with_unusable_consent_id_fails_closed(monkeypatch, blank):
    payload = {"ok": True, "enrollment": _success_enrollment(consent_id=blank)}
    connection = _FakeConnection(payload=payload)
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError):
        port.redeem_enrollment(_request(), now=NOW)


def test_request_sends_only_possession_proof_and_no_ambient_authority(monkeypatch):
    connection = _FakeConnection(payload={"ok": True, "enrollment": _success_enrollment()})
    port = _port(connection, monkeypatch)
    port.redeem_enrollment(_request(), now=NOW)
    body = json.loads(connection.sent["body"].decode("utf-8"))
    assert set(body) == {"challenge_id", "device_id", "proof_ref"}
    headers = {k.lower(): v for k, v in connection.sent["headers"].items()}
    assert set(headers) == {"content-type", "accept"}
    for forbidden in ("cookie", "authorization", "x-forwarded-for", "google", "session"):
        assert not any(forbidden in k for k in headers)


# --- refusals: the bounded reason only, the diagnostic code never -------------
#: Pinned copy of every value CENTRAL can place in the redeem ``reason`` field:
#: the ``_S2_REDEEM_REFUSALS`` set plus every ``_S2_REDEEM_REFUSAL_ALIASES``
#: target in ``apps/padiem-chat/app/claw_connector_enrollment_routes.py``
#: (CENTRAL ``264437961``). Kept here as an alignment pin so a central widening
#: fails this test loudly instead of making every device refuse a valid refusal.
_CENTRAL_EMITTABLE_REASONS = frozenset(
    {
        "canonical_session_required",
        "canonical_session_inactive",
        "enrollment_consent_required",
        "enrollment_consent_withdrawn",
        "enrollment_consent_scope_mismatch",
        "enrollment_binding_absent",
        "enrollment_consent_swap_denied",
        "enrollment_device_swap_denied",
        "enrollment_binding_owner_mismatch",
        "enrollment_binding_scope_mismatch",
        "enrollment_challenge_not_found",
        "enrollment_challenge_expired",
        "enrollment_duplicate_redeem_denied",
        "enrollment_rate_limited",
        "enrollment_duplicate_device_denied",
        "enrollment_binding_revoked_denied",
        "enrollment_dependency_unavailable",
        "enrollment_dependency_refused",
        "enrollment_proof_invalid",
    }
)


def test_every_central_emittable_refusal_reason_is_in_the_s2_vocabulary():
    assert _CENTRAL_EMITTABLE_REASONS <= ENROLLMENT_REFUSAL_REASONS


@pytest.mark.parametrize("code", sorted(_CENTRAL_EMITTABLE_REASONS))
def test_exact_refusal_reason_passes_through_and_stays_non_retryable(monkeypatch, code):
    connection = _FakeConnection(status=403, payload=_refusal(code, code))
    port = _port(connection, monkeypatch)
    result = port.redeem_enrollment(_request(), now=NOW)
    assert result.ok is False
    assert result.reason == code
    assert result.retryable is False


@pytest.mark.parametrize(
    "code,reason",
    [
        ("enrollment_consent_changed_during_redeem", "enrollment_consent_withdrawn"),
        ("enrollment_consent_race_revoke_unconfirmed", "enrollment_dependency_unavailable"),
        ("credential_handoff_unavailable", "enrollment_dependency_unavailable"),
        ("enrollment_credential_handoff_failed", "enrollment_dependency_refused"),
        ("enrollment_handoff_revoke_unconfirmed", "enrollment_dependency_unavailable"),
        ("enrollment_server_dependency_unavailable", "enrollment_dependency_unavailable"),
        ("connector_enrollment_device_gateway_denied", "enrollment_dependency_refused"),
        ("connector_enrollment_invalid_request", "enrollment_dependency_refused"),
        ("invalid_pairing_proof", "enrollment_proof_invalid"),
        ("pairing_challenge_already_redeemed", "enrollment_duplicate_redeem_denied"),
    ],
)
def test_documented_central_code_aliases_map_to_their_bounded_reason(monkeypatch, code, reason):
    # A redeemed challenge is single-use, so even these stay non-retryable: the
    # retry path is a new challenge plus a fresh OWNER consent, never a replay.
    connection = _FakeConnection(status=503, payload=_refusal(code, reason))
    port = _port(connection, monkeypatch)
    result = port.redeem_enrollment(_request(), now=NOW)
    assert result.reason == reason
    assert result.retryable is False
    assert code not in json.dumps(result.safe_dict())


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": False, "error": {"code": "enrollment_challenge_expired"}},
        {"ok": False, "error": {"code": "x"}, "reason": "enrollment_proof_invalid"},
        {
            "ok": False,
            "error": {"code": "x"},
            "reason": "enrollment_proof_invalid",
            "retryable": False,
            "detail": "rows were dropped",
        },
    ],
)
def test_refusal_envelope_outside_the_closed_shape_fails_closed(monkeypatch, payload):
    connection = _FakeConnection(status=403, payload=payload)
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_shape_mismatch"


@pytest.mark.parametrize(
    "reason",
    [
        "connector_enrollment_csrf_denied",
        "connector_enrollment_receipt_invalid",
        "psycopg2.errors.UndefinedColumn: no column",
        "ENROLLMENT_CONSENT_WITHDRAWN",
        "",
        None,
    ],
)
def test_unbounded_refusal_reason_is_never_mapped_or_echoed(monkeypatch, reason):
    connection = _FakeConnection(
        status=403, payload=_refusal("enrollment_dependency_refused", reason)
    )
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_reason_unbounded"


def test_retryable_claim_is_refused_as_a_contract_violation(monkeypatch):
    connection = _FakeConnection(
        status=503,
        payload=_refusal(
            "enrollment_server_dependency_unavailable",
            "enrollment_dependency_unavailable",
            retryable=True,
        ),
    )
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_retryable_not_false"


@pytest.mark.parametrize("code", ["", "InternalSQLTraceback: at 0x7f", "x" * 65, "CAP_CODE", {"v": 1}, None])
def test_unsanitized_diagnostic_code_fails_closed(monkeypatch, code):
    connection = _FakeConnection(
        status=503, payload=_refusal(code, "enrollment_dependency_unavailable")
    )
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_error_code_invalid"


def test_error_object_carrying_upstream_message_fails_closed(monkeypatch):
    # ``error`` must be exactly ``{"code": ...}``: a server that starts echoing
    # ``message``/``traceback`` is refused rather than surfacing it.
    connection = _FakeConnection(
        status=503,
        payload={
            "ok": False,
            "error": {"code": "enrollment_dependency_refused", "message": "raw upstream text"},
            "reason": "enrollment_dependency_refused",
            "retryable": False,
        },
    )
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_error_shape_mismatch"


# --- tampering and mismatch -------------------------------------------------
def test_device_swap_in_success_body_is_refused(monkeypatch):
    connection = _FakeConnection(
        payload={"ok": True, "enrollment": _success_enrollment(device_id="pc_other")}
    )
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_device_swap_denied"


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"raw_device_credential": True}, "enrollment_response_exposed_raw_credential"),
        ({"dispatch_authorized": True}, "enrollment_response_dispatch_not_false"),
        ({"grants_read": True}, "enrollment_response_granted_execution"),
        ({"grants_write": True}, "enrollment_response_granted_execution"),
        (
            {"credential_installed_by_canonical_handoff": False},
            "enrollment_response_install_not_confirmed",
        ),
        ({"lifecycle": "ONLINE"}, "enrollment_response_lifecycle_not_paired_offline"),
        ({"lifecycle": "update_required"}, "enrollment_response_lifecycle_not_paired_offline"),
        ({"lifecycle": None}, "enrollment_response_lifecycle_not_paired_offline"),
        ({"credential_generation": 0}, "enrollment_response_generation_invalid"),
        ({"credential_generation": True}, "enrollment_response_generation_invalid"),
        ({"credential_expires_at": "not-a-date"}, "credential_expires_at_must_be_iso_text"),
        ({"credential_expires_at": "2026-10-12T11:59:59Z"}, "enrollment_response_credential_expired"),
        ({"credential_expires_at": "2026-10-12T12:00:00Z"}, "enrollment_response_credential_expired"),
        ({"credential_expires_at": "2026-10-12T12:00:00"}, "credential_expires_at_must_be_timezone_aware"),
        ({"binding_ref": "bind/ing"}, "binding_ref_must_be_bounded_reference"),
        ({"workspace_ref": "a" * 257}, "workspace_ref_must_be_bounded_reference"),
        ({"consent_id": None}, "enrollment_response_consent_id_missing"),
    ],
)
def test_tampered_success_body_is_refused(monkeypatch, overrides, expected):
    connection = _FakeConnection(
        payload={"ok": True, "enrollment": _success_enrollment(**overrides)}
    )
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == expected


@pytest.mark.parametrize(
    "extra",
    [
        {"credential_b64": "cGFja2FnZQ=="},
        {"credential": "raw-device-credential-bytes"},
        {"session_token": "tok-1"},
        {"owner_email": "owner@example.com"},
        {"credential_ref_fingerprint": "a" * 64},
        {"pairing_code": "a" * 32},
    ],
)
def test_secret_or_forged_projection_in_success_body_is_refused(monkeypatch, extra):
    # No key outside the published thirteen is accepted, echoed or stored, so a
    # credential projection or an owner/dispatch claim can never reach the PC.
    enrollment = dict(_success_enrollment(), **extra)
    connection = _FakeConnection(payload={"ok": True, "enrollment": enrollment})
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_unexpected_field"


def test_extra_top_level_key_on_success_is_refused(monkeypatch):
    connection = _FakeConnection(
        payload={
            "ok": True,
            "enrollment": _success_enrollment(),
            "credential_b64": "cGFja2FnZQ==",
        }
    )
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_shape_mismatch"


def test_missing_field_is_refused():
    payload = {"ok": True, "enrollment": _success_enrollment()}
    del payload["enrollment"]["binding_ref"]
    with pytest.raises(EnrollmentTransportError) as exc:
        translate_central_response(
            payload, expected_device_id="pc_abc123", now=NOW
        )
    assert str(exc.value) == "enrollment_response_field_missing"


def test_success_receipt_carries_no_credential_material_to_the_ui():
    result = translate_central_response(
        {"ok": True, "enrollment": _success_enrollment()},
        expected_device_id="pc_abc123",
        now=NOW,
    )
    assert result.consent_id == "consent-1"
    assert "credential_b64" not in result.safe_dict()
    assert set(result.safe_dict()) == {
        "ok",
        "binding_ref",
        "device_id",
        "account_ref",
        "workspace_ref",
        "credential_generation",
        "credential_expires_at",
        "consent_id",
        "raw_device_credential",
    }


def test_success_under_error_status_is_refused(monkeypatch):
    connection = _FakeConnection(
        status=502, payload={"ok": True, "enrollment": _success_enrollment()}
    )
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_status_body_mismatch"


def test_refusal_under_success_status_is_refused(monkeypatch):
    # CENTRAL answers a refusal only with a non-2xx status. A 200 carrying
    # ``ok=false`` is a gateway or transport anomaly, not a receipt to display.
    connection = _FakeConnection(
        status=200,
        payload=_refusal("enrollment_dependency_refused", "enrollment_dependency_refused"),
    )
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_status_body_mismatch"


def test_non_json_and_redirect_and_oversize_are_refused(monkeypatch):
    not_json = _FakeConnection(status=200, raw=b"<html>nope</html>")
    with pytest.raises(EnrollmentTransportError) as exc:
        _port(not_json, monkeypatch).redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_not_json"

    redirect = _FakeConnection(status=302, raw=b"")
    with pytest.raises(EnrollmentTransportError) as exc:
        _port(redirect, monkeypatch).redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_redirect_refused"

    oversize = _FakeConnection(status=200, raw=b"x" * (16 * 1024 + 1))
    with pytest.raises(EnrollmentTransportError) as exc:
        _port(oversize, monkeypatch).redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_too_large"


# --- transport failures -----------------------------------------------------
@pytest.mark.parametrize(
    "raised",
    [
        TimeoutError("timed out"),
        ssl.SSLError("certificate verify failed"),
        OSError("connection refused"),
    ],
)
def test_transport_and_tls_failures_fail_closed(monkeypatch, raised):
    connection = _FakeConnection(raise_on_request=raised)
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_transport_unavailable"


def test_tls_verification_is_never_disabled(monkeypatch):
    captured = {}

    class _RecordingFactory:
        def __init__(self, host, timeout=None):
            captured["host"] = host
            captured["timeout"] = timeout
            raise OSError("stop before network")

    monkeypatch.setattr(
        "claw_connect.enrollment_http.CENTRAL_DEVICE_GATEWAY_WIRED", True, raising=False
    )
    port = HttpsEnrollmentServerPort(
        origin=ORIGIN, allow_production=True, connection_factory=_RecordingFactory
    )
    with pytest.raises(EnrollmentTransportError):
        port.redeem_enrollment(_request(), now=NOW)
    assert captured["host"] == "chat.padiem.net"
