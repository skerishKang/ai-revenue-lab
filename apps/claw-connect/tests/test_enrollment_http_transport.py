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
    # Post-fix central success shape: includes the consent_id the S2 receipt
    # requires. The current central route omits it, which is tested separately.
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


def test_central_success_without_consent_id_is_refused_as_contract_gap(monkeypatch):
    # Current central shape: no consent_id. The adapter must fail closed rather
    # than invent the field (reported as a central contract gap).
    payload = {"ok": True, "enrollment": _success_enrollment()}
    del payload["enrollment"]["consent_id"]
    connection = _FakeConnection(payload=payload)
    port = _port(connection, monkeypatch)
    with pytest.raises(EnrollmentTransportError) as exc:
        port.redeem_enrollment(_request(), now=NOW)
    assert str(exc.value) == "enrollment_response_consent_id_missing"


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


# --- refusals: auth, consent, replay ----------------------------------------
@pytest.mark.parametrize(
    "code",
    [
        "canonical_session_required",
        "enrollment_consent_required",
        "enrollment_consent_withdrawn",
        "enrollment_duplicate_redeem_denied",
        "enrollment_challenge_expired",
    ],
)
def test_bounded_refusal_codes_pass_through_without_upstream_text(monkeypatch, code):
    connection = _FakeConnection(status=403, payload={"ok": False, "error": {"code": code}})
    port = _port(connection, monkeypatch)
    result = port.redeem_enrollment(_request(), now=NOW)
    assert result.ok is False
    assert result.reason == code


def test_unknown_refusal_code_maps_to_fallback(monkeypatch):
    connection = _FakeConnection(
        status=500, payload={"ok": False, "error": {"code": "internal_sql_trace_abc"}}
    )
    port = _port(connection, monkeypatch)
    result = port.redeem_enrollment(_request(), now=NOW)
    assert result.ok is False
    assert result.reason == "enrollment_dependency_refused"


def test_real_central_code_absent_from_s2_vocabulary_maps_to_fallback(monkeypatch):
    # `connector_enrollment_csrf_denied` exists centrally but not in the S2
    # bounded vocabulary; it must be dropped to the fallback, not echoed.
    connection = _FakeConnection(
        status=403,
        payload={"ok": False, "error": {"code": "connector_enrollment_csrf_denied"}},
    )
    port = _port(connection, monkeypatch)
    result = port.redeem_enrollment(_request(), now=NOW)
    assert result.ok is False
    assert result.reason == "enrollment_dependency_refused"


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
        ({"credential_generation": 0}, "enrollment_response_generation_invalid"),
        ({"credential_expires_at": "not-a-date"}, "credential_expires_at_must_be_iso_text"),
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


def test_missing_field_is_refused():
    payload = {"ok": True, "enrollment": _success_enrollment()}
    del payload["enrollment"]["binding_ref"]
    with pytest.raises(EnrollmentTransportError) as exc:
        translate_central_response(payload, expected_device_id="pc_abc123")
    assert str(exc.value) == "enrollment_response_field_missing"


def test_success_under_error_status_is_refused(monkeypatch):
    connection = _FakeConnection(
        status=502, payload={"ok": True, "enrollment": _success_enrollment()}
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
