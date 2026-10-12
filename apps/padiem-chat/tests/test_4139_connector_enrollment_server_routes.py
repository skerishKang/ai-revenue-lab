"""#4139: new, UNMOUNTED product handlers reject untrusted requests by default."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import claw_connector_enrollment_routes as routes
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from padiem_control_plane.padiem_connector_enrollment_server import CanonicalConnectorEnrollmentServer

from datetime import datetime, timedelta, timezone


class Request:
    def __init__(self, data, *, state=None, content_type="application/json"):
        self.app = SimpleNamespace(state=state or SimpleNamespace())
        self.headers = {"content-type": content_type}
        self._data = data

    async def body(self):
        return json.dumps(self._data).encode("utf-8")


def response(handler, request):
    result = asyncio.run(handler(request))
    return result.status_code, json.loads(result.body), result.headers


def test_no_live_product_route_auth_or_server_grant():
    status, body, headers = response(
        routes.connector_enrollment_issue, Request({"device_id": "device.1"})
    )
    assert status == 401
    assert body["error"]["code"] == "canonical_session_required"
    assert headers["cache-control"].startswith("no-store")

    status, body, _ = response(
        routes.connector_enrollment_redeem,
        Request({
            "challenge_id": "pairing.1", "device_id": "device.1",
            "proof_ref": "pairing-proof:" + "a" * 64,
        }),
    )
    assert status == 503
    assert body["error"]["code"] == "enrollment_server_dependency_unavailable"
    assert routes.ENROLLMENT_PRODUCT_HTTP_MOUNTED is False
    assert routes.ENROLLMENT_PRODUCT_PRODUCTION_ACTIVE is False


class Server(CanonicalConnectorEnrollmentServer):
    """Injected server test double; product is NEVER deployed by this test."""

    def __init__(self):
        super().__init__(allowed_product_ids=frozenset({"b54-padiem-claw"}))
        self.issue_calls = []
        self.redeem_calls = []

    def issue(self, *, verified_session, device_id, now):
        self.issue_calls.append((verified_session, device_id, now))
        return SimpleNamespace(
            pairing_code="a" * 32, safe_dict=lambda: {"challenge_id": "pairing.test", "pairing_code": None}
        )

    def redeem(self, *, challenge_id, device_id, proof_ref, now):
        self.redeem_calls.append((challenge_id, device_id, proof_ref, now))
        return SimpleNamespace(safe_dict=lambda: {
            "ok": True, "binding_ref": "binding.1",
            "credential_installed_by_canonical_handoff": True,
            "raw_device_credential": False,
            "lifecycle": "paired_offline",
        })


class Verify:
    def __init__(self, result=True):
        self.result = result

    def verify(self, request):
        del request
        return self.result


class BrowserSession:
    def resolve(self, request):
        del request
        now = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
        return AuthSessionSnapshot(
            session_id="session.test", product_id="b54-padiem-claw",
            subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="usr.test"),
            issued_at=now - timedelta(hours=1), expires_at=now + timedelta(days=1),
            state=AuthSessionState.ACTIVE, tenant_id="tenant.test",
        )


def test_authenticated_issue_requires_csrf_and_closed_request_shape(monkeypatch):
    monkeypatch.setattr(routes, "auth_ready", lambda r: True)
    monkeypatch.setattr(routes, "current_user_id", lambda r: "usr.test")
    server = Server()
    state = SimpleNamespace(
        connector_enrollment_server=server,
        connector_enrollment_browser_session=BrowserSession(),
        connector_enrollment_browser_csrf=Verify(False),
    )
    status, body, _ = response(routes.connector_enrollment_issue, Request({"device_id": "device.1"}, state=state))
    assert status == 403 and not server.issue_calls
    state.connector_enrollment_browser_csrf = Verify(True)
    status, body, _ = response(
        routes.connector_enrollment_issue,
        Request({"device_id": "device.1", "workspace_ref": "forged"}, state=state),
    )
    assert status == 400 and not server.issue_calls
    status, body, headers = response(
        routes.connector_enrollment_issue, Request({"device_id": "device.1"}, state=state)
    )
    assert status == 200
    assert body["enrollment"]["pairing_code"] == "a" * 32
    assert len(server.issue_calls) == 1
    assert headers["cache-control"].startswith("no-store")


def test_device_redeem_requires_attested_gateway_and_forbids_scope_claim():
    server = Server()
    state = SimpleNamespace(
        connector_enrollment_server=server,
        connector_enrollment_device_gateway=Verify(False),
    )
    fields = {
        "challenge_id": "pairing.test", "device_id": "device.1",
        "proof_ref": "pairing-proof:" + "b" * 64,
    }
    status, body, _ = response(routes.connector_enrollment_redeem, Request(fields, state=state))
    assert status == 403 and not server.redeem_calls
    state.connector_enrollment_device_gateway = Verify(True)
    status, body, _ = response(
        routes.connector_enrollment_redeem,
        Request({**fields, "owner_id": "forged"}, state=state),
    )
    assert status == 400 and not server.redeem_calls
    status, body, _ = response(
        routes.connector_enrollment_redeem,
        Request({**fields, "proof_ref": "not-a-proof"}, state=state),
    )
    assert status == 400 and not server.redeem_calls
    status, body, _ = response(routes.connector_enrollment_redeem, Request(fields, state=state))
    assert status == 200 and body["raw_device_credential"] is False
    assert body["lifecycle"] == "paired_offline"
    assert len(server.redeem_calls) == 1
