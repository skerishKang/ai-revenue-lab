"""B54 login + CSRF boundary tests for the explicit PC-consent endpoints."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app import claw_connector_enrollment_routes as routes
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType

NOW = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)


class Request:
    def __init__(self, data, state):
        self.app = SimpleNamespace(state=state)
        self.headers = {"content-type": "application/json", "content-length": str(len(json.dumps(data)))}
        self._data = data
    async def body(self):
        return json.dumps(self._data).encode()


def run(handler, request):
    response = asyncio.run(handler(request))
    return response.status_code, json.loads(response.body), response.headers


class Csrf:
    def __init__(self, allowed=True):
        self.allowed = allowed
    def verify(self, request):
        del request
        return self.allowed


class ConsentAuthority:
    def __init__(self):
        self.calls = []
    async def grant_connector_enrollment_consent(self, **kwargs):
        self.calls.append(("grant", kwargs))
        return {
            "consent_id": "consent.owner.1", "device_id": kwargs["device_id"],
            "granted_at": NOW.isoformat(), "withdrawn_at": None,
            "dispatch_authorized": False, "grants_read": False, "grants_write": False,
        }
    async def revoke_connector_enrollment_consent(self, **kwargs):
        self.calls.append(("revoke", kwargs))
        return {
            "consent_id": kwargs["consent_id"], "device_id": "device.owner.1",
            "granted_at": NOW.isoformat(), "withdrawn_at": (NOW+timedelta(seconds=1)).isoformat(),
            "dispatch_authorized": False, "grants_read": False, "grants_write": False,
        }


def canonical_session(*, product="b54-padiem-claw", state=AuthSessionState.ACTIVE, tenant="tenant.owner.1"):
    return AuthSessionSnapshot(
        session_id="session.canonical.owner.1", product_id=product,
        subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="subject.canonical.owner.1"),
        issued_at=NOW-timedelta(days=1), expires_at=NOW+timedelta(days=30),
        state=state, tenant_id=tenant,
    )


def app_state(*, authority=None, csrf=True):
    return SimpleNamespace(
        control_plane_identity_authority=authority or ConsentAuthority(),
        connector_enrollment_browser_csrf=Csrf(csrf),
    )


def setup_auth(monkeypatch, *, bridge=None, user="product-user-1"):
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: user)
    async def resolve(request):
        del request
        return bridge if bridge is not None else SimpleNamespace(
            product_user_id=user, auth_session=canonical_session()
        )
    monkeypatch.setattr(routes, "resolve_current_b54_canonical_session", resolve)


def body(device="device.owner.1"):
    return {
        "device_id": device, "confirmed": True,
        "confirmation_version": "pc-enrollment-consent-v1",
    }


def test_grant_calls_only_existing_identity_rpc_after_active_b54_session_and_csrf(monkeypatch):
    authority = ConsentAuthority()
    setup_auth(monkeypatch)
    state = app_state(authority=authority)
    status, result, headers = run(routes.connector_enrollment_consent_grant, Request(body(), state))
    assert status == 200 and result["ok"] is True
    assert result["consent"]["consent_id"] == "consent.owner.1"
    assert result["consent"]["dispatch_authorized"] is False
    assert headers["cache-control"].startswith("no-store")
    assert authority.calls == [("grant", {
        "session_id": "session.canonical.owner.1", "device_id": "device.owner.1",
        "confirmed": True, "confirmation_version": "pc-enrollment-consent-v1",
    })]


def test_grant_requires_csrf_and_explicit_exact_confirmation(monkeypatch):
    authority = ConsentAuthority()
    setup_auth(monkeypatch)
    state = app_state(authority=authority, csrf=False)
    assert run(routes.connector_enrollment_consent_grant, Request(body(), state))[0] == 403
    state.connector_enrollment_browser_csrf = Csrf(True)
    assert run(routes.connector_enrollment_consent_grant, Request({**body(), "confirmed": "true"}, state))[0] == 400
    assert run(routes.connector_enrollment_consent_grant, Request({**body(), "owner_subject_id": "forged"}, state))[0] == 400
    assert authority.calls == []


@pytest.mark.parametrize("bridge", [
    SimpleNamespace(product_user_id=None, auth_session=None),
    SimpleNamespace(product_user_id="another-product-user", auth_session=canonical_session()),
    SimpleNamespace(product_user_id="product-user-1", auth_session=canonical_session(product="b62")),
    SimpleNamespace(product_user_id="product-user-1", auth_session=canonical_session(state=AuthSessionState.REVOKED)),
    SimpleNamespace(product_user_id="product-user-1", auth_session=canonical_session(tenant=None)),
])
def test_grant_denies_missing_switched_foreign_or_inactive_canonical_session(monkeypatch, bridge):
    authority = ConsentAuthority()
    setup_auth(monkeypatch, bridge=bridge)
    status, _, _ = run(routes.connector_enrollment_consent_grant, Request(body(), app_state(authority=authority)))
    assert status == 401
    assert authority.calls == []


def test_revoke_is_separate_explicit_owner_action_and_never_claims_device_offline(monkeypatch):
    authority = ConsentAuthority()
    setup_auth(monkeypatch)
    payload = {
        "consent_id": "consent.owner.1", "confirmed": True,
        "confirmation_version": "pc-enrollment-consent-v1",
    }
    status, result, _ = run(
        routes.connector_enrollment_consent_revoke,
        Request(payload, app_state(authority=authority)),
    )
    assert status == 200 and result["ok"] is True
    assert result["consent"]["withdrawn_at"] is not None
    assert result["consent"]["dispatch_authorized"] is False
    assert authority.calls[0] == ("revoke", {
        "session_id": "session.canonical.owner.1", "consent_id": "consent.owner.1",
        "confirmed": True, "confirmation_version": "pc-enrollment-consent-v1",
    })


def test_consent_endpoint_not_mounted_and_default_activation_stays_off():
    assert routes.ENROLLMENT_PRODUCT_HTTP_MOUNTED is False
    assert routes.ENROLLMENT_PRODUCT_AUTHENTICATION_WIRED is False
    assert routes.ENROLLMENT_PRODUCT_DURABLE_CONSENT_WIRED is False
    assert routes.ENROLLMENT_PRODUCT_CREDENTIAL_HANDOFF_WIRED is False
    assert routes.ENROLLMENT_PRODUCT_PRODUCTION_ACTIVE is False
