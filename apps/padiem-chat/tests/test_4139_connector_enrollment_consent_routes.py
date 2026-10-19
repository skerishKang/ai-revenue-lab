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


def test_public_consent_success_projects_only_closed_fields(monkeypatch):
    """Customer responses never receive private Identity-owned attributes."""
    authority = ConsentAuthority()
    setup_auth(monkeypatch)
    status, result, headers = run(
        routes.connector_enrollment_consent_grant,
        Request(body(), app_state(authority=authority)),
    )
    assert status == 200 and headers["cache-control"].startswith("no-store")
    assert set(result) == {"ok", "consent"}
    assert set(result["consent"]) == {
        "consent_id", "device_id", "granted_at", "withdrawn_at",
        "dispatch_authorized", "grants_read", "grants_write",
    }
    assert result["consent"]["grants_read"] is False
    assert result["consent"]["grants_write"] is False
    assert result["consent"]["withdrawn_at"] is None


@pytest.mark.parametrize("mutation", [
    {"raw_device_credential": "NEVER_ECHO_CREDENTIAL"},
    {"owner_subject_id": "NEVER_ECHO_OWNER"},
    {"session_id": "NEVER_ECHO_SESSION"},
    {"account_ref": "NEVER_ECHO_ACCOUNT"},
    {"consent_id": None},
    {"consent_id": "invalid consent id"},
    {"device_id": "different-pc"},
    {"dispatch_authorized": True},
    {"grants_read": True},
    {"grants_write": True},
    {"withdrawn_at": NOW.isoformat()},
    {"granted_at": "not-a-time"},
    {"granted_at": "2026-10-12T10:00:00"},
])
def test_grant_rejects_untrusted_identity_receipt_without_echo(monkeypatch, mutation):
    """Route-level validation must not rely on the private typed adapter."""
    class Tampered(ConsentAuthority):
        async def grant_connector_enrollment_consent(self, **kwargs):
            value = await super().grant_connector_enrollment_consent(**kwargs)
            return {**value, **mutation}

    setup_auth(monkeypatch)
    authority = Tampered()
    status, result, headers = run(
        routes.connector_enrollment_consent_grant,
        Request(body(), app_state(authority=authority)),
    )
    assert status == 503
    assert result == {"ok": False, "error": {"code": "connector_enrollment_receipt_invalid"}}
    assert headers["cache-control"].startswith("no-store")
    assert "NEVER_ECHO" not in json.dumps(result)
    assert len(authority.calls) == 1


@pytest.mark.parametrize("mutation", [
    {"credential_b64": "NEVER_ECHO_CREDENTIAL"},
    {"tenant_id": "NEVER_ECHO_TENANT"},
    {"consent_id": "different-consent"},
    {"grants_read": True},
    {"dispatch_authorized": True},
    {"withdrawn_at": None},
    {"withdrawn_at": "2026-10-12T10:00:00"},
    {"withdrawn_at": "2026-10-12T09:00:00+00:00"},
])
def test_revoke_rejects_untrusted_identity_receipt_without_echo(monkeypatch, mutation):
    class Tampered(ConsentAuthority):
        async def revoke_connector_enrollment_consent(self, **kwargs):
            value = await super().revoke_connector_enrollment_consent(**kwargs)
            return {**value, **mutation}

    setup_auth(monkeypatch)
    authority = Tampered()
    status, result, _ = run(
        routes.connector_enrollment_consent_revoke,
        Request({
            "consent_id": "consent.owner.1", "confirmed": True,
            "confirmation_version": "pc-enrollment-consent-v1",
        }, app_state(authority=authority)),
    )
    assert status == 503
    assert result == {"ok": False, "error": {"code": "connector_enrollment_receipt_invalid"}}
    assert "NEVER_ECHO" not in json.dumps(result)




def test_consent_endpoint_not_mounted_and_default_activation_stays_off():
    assert routes.ENROLLMENT_PRODUCT_HTTP_MOUNTED is False
    assert routes.ENROLLMENT_PRODUCT_AUTHENTICATION_WIRED is False
    assert routes.ENROLLMENT_PRODUCT_DURABLE_CONSENT_WIRED is False
    assert routes.ENROLLMENT_PRODUCT_CREDENTIAL_HANDOFF_WIRED is False
    assert routes.ENROLLMENT_PRODUCT_PRODUCTION_ACTIVE is False


class RawJsonRequest(Request):
    """Preserve duplicate JSON keys in the transport-level body."""
    def __init__(self, raw: bytes, state):
        self.app = SimpleNamespace(state=state)
        self.headers = {
            "content-type": "application/json",
            "content-length": str(len(raw)),
        }
        self._raw = raw

    async def body(self):
        return self._raw


@pytest.mark.parametrize("raw", [
    b'{"device_id":"device.owner.1","confirmed":false,"confirmed":true,"confirmation_version":"pc-enrollment-consent-v1"}',
    b'{"device_id":"other.device","device_id":"device.owner.1","confirmed":true,"confirmation_version":"pc-enrollment-consent-v1"}',
    b'{"device_id":"device.owner.1","confirmed":true,"confirmation_version":"ignored","confirmation_version":"pc-enrollment-consent-v1"}',
])
def test_grant_rejects_duplicate_json_fields_before_identity_write(monkeypatch, raw):
    setup_auth(monkeypatch)
    authority = ConsentAuthority()
    status, response, _ = run(
        routes.connector_enrollment_consent_grant,
        RawJsonRequest(raw, app_state(authority=authority)),
    )
    assert status == 400
    assert response == {"ok": False, "error": {"code": "connector_enrollment_explicit_consent_required"}}
    assert authority.calls == []


@pytest.mark.parametrize("raw", [
    b'{"consent_id":"consent.owner.1","confirmed":false,"confirmed":true,"confirmation_version":"pc-enrollment-consent-v1"}',
    b'{"consent_id":"another.consent","consent_id":"consent.owner.1","confirmed":true,"confirmation_version":"pc-enrollment-consent-v1"}',
])
def test_revoke_rejects_duplicate_json_fields_before_identity_write(monkeypatch, raw):
    setup_auth(monkeypatch)
    authority = ConsentAuthority()
    status, response, _ = run(
        routes.connector_enrollment_consent_revoke,
        RawJsonRequest(raw, app_state(authority=authority)),
    )
    assert status == 400
    assert response == {"ok": False, "error": {"code": "connector_enrollment_explicit_consent_required"}}
    assert authority.calls == []


def test_issue_payload_rejects_duplicate_device_id():
    raw = b'{"device_id":"wrong.device","device_id":"device.owner.1"}'
    value = asyncio.run(routes._payload(
        RawJsonRequest(raw, app_state()),
        frozenset({"device_id"}),
    ))
    assert value is None
