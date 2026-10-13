"""Real product-owner browser setup: active B54 session, exact routes, no cache."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx

from app import connector_owner_setup_page as setup
from app.app_factory import create_app
from app.config import Settings
from app.connector_owner_runtime_mount import compose_owner_enrollment_from_worker
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from app.worker_config import (
    IDENTITY_AUTHORITY_SERVICE_BINDING_NAME as I,
    LOCAL_AGENT_BROKER_AUTHORITY_SERVICE_BINDING_NAME as B,
)


class PrivateBinding:
    def __getattr__(self, name):
        if name in {
            "grant_connector_enrollment_consent", "revoke_connector_enrollment_consent",
            "resolve_connector_enrollment_consent_for_device",
            "bind_connector_enrollment_challenge", "authorize_connector_enrollment_redeem",
            "issue_enrollment_challenge", "get_enrollment_binding",
            "verify_enrollment_bootstrap", "redeem_enrollment", "revoke_binding",
        }:
            async def placeholder(*args, **kwargs):
                raise AssertionError("no private RPC in GET page")
            return placeholder
        raise AttributeError(name)


def app():
    env = {
        "PADIEM_CONNECTOR_OWNER_ENROLLMENT_ENABLED": "enabled",
        "PADIEM_CONNECTOR_GATEWAY_RELEASE_SCOPE": "isolated-operator-acceptance-4139",
        I: PrivateBinding(), B: PrivateBinding(),
    }
    settings = replace(Settings.from_env(), public_base_url="https://chat.padiem.net")
    return create_app(settings=settings, connector_owner_enrollment=compose_owner_enrollment_from_worker(env))


def get(application, path):
    async def call():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="https://chat.padiem.net",
        ) as client:
            return await client.get(path)
    return asyncio.run(call())


def signed():
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session.owner.1", product_id="b54-padiem-claw",
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER, subject_id="canonical.owner.1",
        ),
        issued_at=now-timedelta(minutes=1),
        expires_at=now+timedelta(hours=1),
        state=AuthSessionState.ACTIVE, tenant_id="tenant.1",
    )


def test_browser_setup_requires_canonical_signed_owner(monkeypatch):
    application = app()
    assert get(application, setup.SETUP_PATH).status_code == 401
    monkeypatch.setattr(setup, "auth_ready", lambda request: True)
    monkeypatch.setattr(setup, "current_user_id", lambda request: "product.owner.1")
    async def other(request):
        return SimpleNamespace(product_user_id="product.owner.2", auth_session=signed())
    monkeypatch.setattr(setup, "resolve_current_b54_canonical_session", other)
    assert get(application, setup.SETUP_PATH).status_code == 401

    async def verified(request):
        return SimpleNamespace(product_user_id="product.owner.1", auth_session=signed())
    monkeypatch.setattr(setup, "resolve_current_b54_canonical_session", verified)
    response = get(application, setup.SETUP_PATH)
    assert response.status_code == 200
    assert "PADIEM Connector" in response.text
    assert "setup.js" in response.text
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


def test_script_does_not_persist_pairing_code_or_use_untrusted_owner_scope():
    application = app()
    script = get(application, setup.SCRIPT_PATH)
    assert script.status_code == 200
    assert script.headers["cache-control"].startswith("no-store")
    assert "localStorage.setItem" not in script.text
    assert "sessionStorage" not in script.text
    assert "console.log" not in script.text
    assert "navigator.clipboard" not in script.text
    assert "credentials: \"same-origin\"" in script.text
    assert "consent/grant" in script.text and "enrollments/issue" in script.text
    assert "enrollments/redeem" not in script.text
    assert "pagehide" in script.text


def test_default_product_app_has_no_setup_page_or_script():
    ordinary = create_app(settings=replace(Settings.from_env(), public_base_url="https://chat.padiem.net"))
    assert not any(getattr(r, "path", "") in {setup.SETUP_PATH, setup.SCRIPT_PATH} for r in ordinary.routes)
