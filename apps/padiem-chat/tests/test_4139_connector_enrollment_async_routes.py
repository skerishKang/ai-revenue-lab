"""B54 routes select async canonical Identity/Broker host only when explicitly injected."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

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
            "lifecycle":"paired_offline", "raw_device_credential":False,
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
    assert "credential_b64" not in body
    assert host.calls[-1][0] == "redeem"
