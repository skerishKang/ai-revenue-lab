"""#4139: new, UNMOUNTED product handlers reject untrusted requests by default."""
from __future__ import annotations

import asyncio
from dataclasses import replace
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


def test_no_live_product_route_auth_or_server_grant(monkeypatch):
    monkeypatch.setattr(routes, "auth_ready", lambda request: False)
    monkeypatch.setattr(routes, "current_user_id", lambda request: None)
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
            "ok": True, "binding_ref": "binding.1", "device_id": device_id,
            "account_ref": "account.1", "workspace_ref": "workspace.1",
            "consent_id": "consent.canonical.1", "credential_generation": 1,
            "credential_expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            "credential_installed_by_canonical_handoff": True,
            "raw_device_credential": False, "lifecycle": "paired_offline",
            "dispatch_authorized": False, "grants_read": False, "grants_write": False,
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
        # Live session tests must not expire merely because CI runs after
        # 2026-10-13 09:00 UTC; preserve the same relative validity window.
        now = datetime.now(timezone.utc)
        return AuthSessionSnapshot(
            session_id="session.test", product_id="b54-padiem-claw",
            subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub.canonical.test"),
            issued_at=now - timedelta(hours=1), expires_at=now + timedelta(days=1),
            state=AuthSessionState.ACTIVE, tenant_id="tenant.test",
        )


def test_authenticated_issue_requires_csrf_and_closed_request_shape(monkeypatch):
    monkeypatch.setattr(routes, "auth_ready", lambda r: True)
    monkeypatch.setattr(routes, "current_user_id", lambda r: "usr.test")
    server = Server()
    async def current_b54(request):
        del request
        return SimpleNamespace(product_user_id="usr.test", auth_session=BrowserSession().resolve(None))
    monkeypatch.setattr(routes, "resolve_current_b54_canonical_session", current_b54)
    state = SimpleNamespace(
        connector_enrollment_server=server,
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
    # Signed browser's product user and canonical subject IDs are different.
    assert server.issue_calls[0][0].subject.subject_id == "sub.canonical.test"
    assert headers["cache-control"].startswith("no-store")


@pytest.mark.parametrize("case", ["missing", "user_swap", "cross_product", "revoked", "no_tenant"])
def test_browser_issue_refuses_invalid_server_canonical_session(monkeypatch, case):
    monkeypatch.setattr(routes, "auth_ready", lambda r: True)
    monkeypatch.setattr(routes, "current_user_id", lambda r: "usr.test")
    source = BrowserSession().resolve(None)
    async def current_b54(request):
        del request
        if case == "missing":
            return None
        if case == "user_swap":
            return SimpleNamespace(product_user_id="usr.other", auth_session=source)
        if case == "cross_product":
            return SimpleNamespace(product_user_id="usr.test", auth_session=replace(source, product_id="b62"))
        if case == "revoked":
            return SimpleNamespace(product_user_id="usr.test", auth_session=replace(source, state=AuthSessionState.REVOKED))
        return SimpleNamespace(product_user_id="usr.test", auth_session=replace(source, tenant_id=None))
    monkeypatch.setattr(routes, "resolve_current_b54_canonical_session", current_b54)
    server = Server()
    state = SimpleNamespace(connector_enrollment_server=server, connector_enrollment_browser_csrf=Verify(True))
    status, body, _ = response(routes.connector_enrollment_issue, Request({"device_id": "device.1"}, state=state))
    assert status == 401 and body["error"]["code"] == "canonical_session_required"
    assert not server.issue_calls


@pytest.mark.parametrize(
    "mutation",
    [
        ("remove", "grants_read"),
        ("remove", "grants_write"),
        ("remove", "consent_id"),
        ("remove", "credential_installed_by_canonical_handoff"),
        ("add", "credential_b64"),
        ("swap", "device_id"),
    ],
)
def test_legacy_sync_host_redeem_is_unavailable_regardless_of_receipt(
    mutation,
):
    """Legacy bool-only installation cannot redeem or attest a PC over HTTP."""
    operation, field = mutation

    class TamperedServer(Server):
        def redeem(self, *, challenge_id, device_id, proof_ref, now):
            normal = super().redeem(
                challenge_id=challenge_id, device_id=device_id,
                proof_ref=proof_ref, now=now,
            )
            original = normal.safe_dict()
            if operation == "remove":
                original.pop(field)
            elif operation == "add":
                original[field] = "NEVER_ECHO_SECRET"
            else:
                original[field] = "device.someone_else"
            return SimpleNamespace(safe_dict=lambda: original)

    state = SimpleNamespace(
        connector_enrollment_server=TamperedServer(),
        connector_enrollment_device_gateway=Verify(True),
    )
    status, payload, headers = response(
        routes.connector_enrollment_redeem,
        Request({
            "challenge_id": "pairing.test", "device_id": "device.1",
            "proof_ref": "pairing-proof:" + "b" * 64,
        }, state=state),
    )
    assert status == 503
    assert payload == {
        "ok": False,
        "error": {"code": "enrollment_server_dependency_unavailable"},
        "reason": "enrollment_dependency_unavailable",
        "retryable": False,
    }
    assert "enrollment" not in payload
    assert "NEVER_ECHO_SECRET" not in json.dumps(payload)
    assert headers["cache-control"].startswith("no-store")
    assert not state.connector_enrollment_server.redeem_calls


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
    # An inbound gateway verification does not authenticate the separate
    # Windows DPAPI installation acknowledgement. Legacy sync redemption must
    # remain unavailable even with valid scope, possession proof and gateway.
    assert status == 503 and body["ok"] is False
    assert body["error"]["code"] == "enrollment_server_dependency_unavailable"
    assert body["retryable"] is False
    assert not server.redeem_calls
