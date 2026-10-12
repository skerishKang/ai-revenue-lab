"""B54 routes select async canonical Identity/Broker host only when explicitly injected."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.control_plane_identity import IdentityBridgeError

from app import claw_connector_enrollment_routes as routes
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType


class Request:
    def __init__(self, body, state):
        self.app = SimpleNamespace(state=state)
        self.headers = {"content-type": "application/json", "content-length": str(len(json.dumps(body)))}
        self._body = body
    async def body(self):
        return json.dumps(self._body).encode()


class CSRF:
    def verify(self, request):
        del request
        return True


class Gateway:
    def verify(self, request):
        del request
        return True


class AsyncHost:
    def __init__(self):
        self.calls = []
    async def issue(self, *, canonical_session_id, device_id):
        self.calls.append(("issue", canonical_session_id, device_id))
        return {
            "challenge": {"challenge_id":"pairing.challenge.1"},
            "pairing_code":"a"*32, "code_returned_once":True,
            "raw_device_credential":False, "dispatch_authorized":False,
        }
    async def redeem(self, *, challenge_id, device_id, proof_ref):
        self.calls.append(("redeem", challenge_id, device_id, proof_ref))
        return {
            "binding_ref":"binding.1", "device_id":device_id,
            "account_ref":"account.1", "workspace_ref":"workspace.1",
            "consent_id":"consent.server.1",
            "credential_generation":1, "credential_expires_at":(datetime.now(timezone.utc)+timedelta(days=30)).isoformat(),
            "lifecycle":"paired_offline", "raw_device_credential":False,
            "credential_installed_by_canonical_handoff":True,
            "dispatch_authorized":False, "grants_read":False, "grants_write":False,
        }


def make_state(host):
    return SimpleNamespace(
        connector_enrollment_async_host=host,
        connector_enrollment_browser_csrf=CSRF(),
        connector_enrollment_device_gateway=Gateway(),
    )


def active_b54():
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session.canonical.1", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="subject.1"),
        issued_at=now-timedelta(minutes=1), expires_at=now+timedelta(days=1),
        state=AuthSessionState.ACTIVE, tenant_id="tenant.1",
    )


def test_issue_route_uses_async_host_only_after_b54_login_and_csrf(monkeypatch):
    host = AsyncHost()
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "product-user.1")
    async def bridge(request):
        del request
        return SimpleNamespace(product_user_id="product-user.1", auth_session=active_b54())
    monkeypatch.setattr(routes, "resolve_current_b54_canonical_session", bridge)
    response = asyncio.run(routes.connector_enrollment_issue(Request({"device_id":"device.1"}, make_state(host))))
    assert response.status_code == 200
    result = json.loads(response.body)
    assert result["enrollment"]["pairing_code"] == "a"*32
    assert host.calls[-1][0] == "issue"


def test_redeem_route_never_projects_raw_device_credential(monkeypatch):
    host = AsyncHost()
    result = asyncio.run(routes.connector_enrollment_redeem(Request({
        "challenge_id":"pairing.challenge.1", "device_id":"device.1",
        "proof_ref":"pairing-proof:"+"a"*64,
    }, make_state(host))))
    assert result.status_code == 200
    body = json.loads(result.body)
    assert body["enrollment"]["lifecycle"] == "paired_offline"
    assert body["enrollment"]["raw_device_credential"] is False
    assert body["enrollment"]["consent_id"] == "consent.server.1"
    assert body["enrollment"]["credential_installed_by_canonical_handoff"] is True
    assert "credential_b64" not in body
    assert host.calls[-1][0] == "redeem"


@pytest.mark.parametrize(("error_status", "server_code", "http_status", "client_reason"), [
    (403, "enrollment_consent_changed_during_redeem", 403, "enrollment_consent_withdrawn"),
    (503, "credential_handoff_unavailable", 503, "enrollment_dependency_unavailable"),
    (503, "enrollment_credential_handoff_failed", 503, "enrollment_dependency_refused"),
    (503, "enrollment_handoff_revoke_unconfirmed", 503, "enrollment_dependency_unavailable"),
    (409, "pairing_challenge_already_redeemed", 409, "enrollment_duplicate_redeem_denied"),
    (503, "unexpected_internal_failure", 503, "enrollment_dependency_refused"),
])
def test_device_redeem_preserves_canonical_error_and_exposes_only_bounded_s2_reason(
    error_status, server_code, http_status, client_reason,
):
    class FailingHost(AsyncHost):
        async def redeem(self, *, challenge_id, device_id, proof_ref):
            del challenge_id, device_id, proof_ref
            raise IdentityBridgeError(error_status, server_code, "sensitive upstream details")

    response = asyncio.run(routes.connector_enrollment_redeem(Request({
        "challenge_id": "pairing.challenge.1", "device_id": "device.1",
        "proof_ref": "pairing-proof:" + "a" * 64,
    }, make_state(FailingHost()))))
    wire = json.loads(response.body)
    assert response.status_code == http_status
    assert wire == {
        "ok": False, "error": {"code": server_code},
        "reason": client_reason, "retryable": False,
    }
    assert "sensitive" not in response.body.decode()
    assert response.headers["cache-control"].startswith("no-store")


def test_device_redeem_refuses_missing_authenticated_handoff_without_positive_receipt():
    state = make_state(None)
    result = asyncio.run(routes.connector_enrollment_redeem(Request({
        "challenge_id":"pairing.challenge.1", "device_id":"device.1",
        "proof_ref":"pairing-proof:"+"a"*64,
    }, state)))
    assert result.status_code == 503
    body = json.loads(result.body)
    assert body["ok"] is False
    assert body["reason"] == "enrollment_dependency_unavailable"
    assert "enrollment" not in body


def test_issue_preserves_internal_identity_denial_instead_of_masking_as_generic_503(monkeypatch):
    class Denied(AsyncHost):
        async def issue(self, *, canonical_session_id, device_id):
            del canonical_session_id, device_id
            raise IdentityBridgeError(403, "enrollment_consent_required", "sensitive details")

    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "product-user.1")
    async def bridge(request):
        del request
        return SimpleNamespace(product_user_id="product-user.1", auth_session=active_b54())
    monkeypatch.setattr(routes, "resolve_current_b54_canonical_session", bridge)

    result = asyncio.run(routes.connector_enrollment_issue(Request({
        "device_id": "device.1",
    }, make_state(Denied()))))
    assert result.status_code == 403
    body = json.loads(result.body)
    assert body == {"ok": False, "error": {"code": "enrollment_consent_required"}}
    assert "sensitive" not in result.body.decode()


@pytest.mark.parametrize("unsafe_fields", [
    {"credential_b64": "c2VjcmV0"},              # raw credential projection
    {"consent_id": None},                    # missing canonical consent proof
    {"credential_installed_by_canonical_handoff": False},
    {"raw_device_credential": True},
    {"credential_generation": True},        # JSON boolean is not a generation
    {"credential_expires_at": "2000-01-01T00:00:00+00:00"},
    {"grants_read": True},                   # enrollment is NOT a READ approval
    {"grants_write": True},
    {"lifecycle": "online"},                 # receipt is never online evidence
])
def test_redeem_route_rejects_forged_incomplete_or_secret_bearing_success_receipt(unsafe_fields):
    class UnsafeHost(AsyncHost):
        async def redeem(self, *, challenge_id, device_id, proof_ref):
            result = await super().redeem(
                challenge_id=challenge_id, device_id=device_id, proof_ref=proof_ref,
            )
            return {**result, **unsafe_fields}

    response = asyncio.run(routes.connector_enrollment_redeem(Request({
        "challenge_id": "pairing.challenge.1", "device_id": "device.1",
        "proof_ref": "pairing-proof:" + "a" * 64,
    }, make_state(UnsafeHost()))))
    body = json.loads(response.body)
    assert response.status_code == 503
    assert body["ok"] is False
    assert body["reason"] == "enrollment_dependency_unavailable"
    assert "enrollment" not in body
    assert "credential_b64" not in response.body.decode()
    assert response.headers["cache-control"].startswith("no-store")
