"""#4139 source-only owner login -> consent -> Broker challenge route E2E.

No Cloudflare credentials, real PCs or production route mutation.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

import httpx
import pytest

from app import claw_connector_enrollment_routes as routes
from app.connector_enrollment_owner_source_composition import (
    OWNER_ENROLLMENT_DEVICE_REDEEM_MOUNTED,
    OWNER_ENROLLMENT_PRODUCTION_MOUNTED,
    build_review_only_owner_enrollment_app,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType


class Identity:
    def __init__(self):
        self.calls = []

    async def grant_connector_enrollment_consent(self, **kw):
        self.calls.append(("grant", kw))
        return {
            "consent_id": "consent.1",
            "device_id": kw["device_id"],
            "granted_at": datetime.now(timezone.utc).isoformat(),
            "withdrawn_at": None,
            "dispatch_authorized": False, "grants_read": False,
            "grants_write": False,
        }

    async def revoke_connector_enrollment_consent(self, **kw):
        self.calls.append(("revoke", kw))
        return {
            "consent_id": kw["consent_id"], "device_id": "device.1",
            "granted_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "withdrawn_at": datetime.now(timezone.utc).isoformat(),
            "dispatch_authorized": False, "grants_read": False,
            "grants_write": False,
        }


class ChallengeHost:
    def __init__(self):
        self.calls = []

    async def issue(self, **kw):
        self.calls.append(kw)
        return {
            "challenge": {"challenge_id": "challenge.1", "device_id": kw["device_id"]},
            "pairing_code": "one-time-code-test-only",
            "code_returned_once": True,
            "raw_device_credential": False,
            "dispatch_authorized": False,
        }


class CSRF:
    def __init__(self, allow=True):
        self.allow = allow

    def verify(self, request):
        del request
        return self.allow is True


def signed_session(product_id="b54-padiem-claw", state=AuthSessionState.ACTIVE):
    now = datetime.now(timezone.utc)
    return AuthSessionSnapshot(
        session_id="session.signed.1", product_id=product_id,
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER, subject_id="canonical.subject.1"),
        issued_at=now - timedelta(minutes=1), expires_at=now + timedelta(hours=1),
        state=state, tenant_id="tenant.1",
    )


def authenticated(monkeypatch, *, session=None):
    monkeypatch.setattr(routes, "auth_ready", lambda request: True)
    monkeypatch.setattr(routes, "current_user_id", lambda request: "product.user.1")

    async def resolved(request):
        del request
        return SimpleNamespace(
            product_user_id="product.user.1",
            auth_session=signed_session() if session is None else session,
        )
    monkeypatch.setattr(routes, "resolve_current_b54_canonical_session", resolved)


def exchange(app, path, data):
    async def send():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://chat.padiem.net",
        ) as client:
            return await client.post(path, json=data)
    return asyncio.run(send())


def test_default_unmounted_and_requires_all_canonical_dependencies():
    assert OWNER_ENROLLMENT_PRODUCTION_MOUNTED is False
    assert OWNER_ENROLLMENT_DEVICE_REDEEM_MOUNTED is False
    identity, host, csrf = Identity(), ChallengeHost(), CSRF()
    with pytest.raises(RuntimeError, match="not activated"):
        build_review_only_owner_enrollment_app(
            identity_authority=identity, async_host=host, browser_csrf=csrf)
    with pytest.raises(ValueError, match="Identity"):
        build_review_only_owner_enrollment_app(
            identity_authority=object(), async_host=host, browser_csrf=csrf,
            source_test_authorized=True)
    with pytest.raises(ValueError, match="issuer"):
        build_review_only_owner_enrollment_app(
            identity_authority=identity, async_host=object(), browser_csrf=csrf,
            source_test_authorized=True)
    with pytest.raises(ValueError, match="CSRF"):
        build_review_only_owner_enrollment_app(
            identity_authority=identity, async_host=host, browser_csrf=None,
            source_test_authorized=True)


def test_signed_owner_can_grant_once_and_issue_a_canonical_challenge(monkeypatch):
    authenticated(monkeypatch)
    identity, host = Identity(), ChallengeHost()
    app = build_review_only_owner_enrollment_app(
        identity_authority=identity, async_host=host,
        browser_csrf=CSRF(), source_test_authorized=True)
    consent = exchange(app, routes.CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH, {
        "device_id": "device.1", "confirmed": True,
        "confirmation_version": "pc-enrollment-consent-v1",
    })
    assert consent.status_code == 200
    assert consent.json()["consent"]["consent_id"] == "consent.1"
    assert consent.headers["cache-control"].startswith("no-store")
    assert len(identity.calls) == 1
    assert identity.calls[0][1]["session_id"] == "session.signed.1"
    assert "account_ref" not in identity.calls[0][1]
    issued = exchange(app, routes.CONNECTOR_ENROLLMENT_ISSUE_PATH, {"device_id": "device.1"})
    assert issued.status_code == 200
    assert issued.json()["enrollment"]["challenge"]["challenge_id"] == "challenge.1"
    assert issued.json()["enrollment"]["dispatch_authorized"] is False
    assert host.calls == [{"canonical_session_id": "session.signed.1", "device_id": "device.1"}]
    # Device redemption lives only on the separately attested WSS path.
    absent = exchange(app, routes.CONNECTOR_ENROLLMENT_REDEEM_PATH, {
        "device_id": "device.1", "challenge_id": "challenge.1",
        "proof_ref": "pairing-proof:" + "a" * 64,
    })
    assert absent.status_code == 404


def test_csrf_blocks_grant_and_challenge_before_private_rpc(monkeypatch):
    authenticated(monkeypatch)
    identity, host = Identity(), ChallengeHost()
    app = build_review_only_owner_enrollment_app(
        identity_authority=identity, async_host=host,
        browser_csrf=CSRF(False), source_test_authorized=True)
    for path, data in (
        (routes.CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH, {
            "device_id": "device.1", "confirmed": True,
            "confirmation_version": "pc-enrollment-consent-v1",
        }),
        (routes.CONNECTOR_ENROLLMENT_ISSUE_PATH, {"device_id": "device.1"}),
    ):
        response = exchange(app, path, data)
        assert response.status_code == 403
        assert response.headers["cache-control"].startswith("no-store")
    assert identity.calls == [] and host.calls == []


@pytest.mark.parametrize("product,state", [
    ("b62-padiem-chat", AuthSessionState.ACTIVE),
    ("b66-quote", AuthSessionState.ACTIVE),
    ("b54-padiem-claw", AuthSessionState.REVOKED),
])
def test_foreign_or_revoked_session_has_no_owner_registration(monkeypatch, product, state):
    authenticated(monkeypatch, session=signed_session(product_id=product, state=state))
    identity, host = Identity(), ChallengeHost()
    app = build_review_only_owner_enrollment_app(
        identity_authority=identity, async_host=host,
        browser_csrf=CSRF(), source_test_authorized=True)
    for path, data in (
        (routes.CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH, {
            "device_id": "device.1", "confirmed": True,
            "confirmation_version": "pc-enrollment-consent-v1",
        }),
        (routes.CONNECTOR_ENROLLMENT_ISSUE_PATH, {"device_id": "device.1"}),
    ):
        response = exchange(app, path, data)
        assert response.status_code == 401
    assert identity.calls == [] and host.calls == []


def test_no_untrusted_owner_scope_or_duplicate_consent_field(monkeypatch):
    authenticated(monkeypatch)
    identity, host = Identity(), ChallengeHost()
    app = build_review_only_owner_enrollment_app(
        identity_authority=identity, async_host=host,
        browser_csrf=CSRF(), source_test_authorized=True)
    asserted = exchange(app, routes.CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH, {
        "device_id": "device.1", "confirmed": True,
        "confirmation_version": "pc-enrollment-consent-v1",
        "workspace_ref": "forged",
    })
    assert asserted.status_code == 400
    async def raw_duplicate():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://chat.padiem.net",
        ) as client:
            return await client.post(
                routes.CONNECTOR_ENROLLMENT_CONSENT_GRANT_PATH,
                content=b'{"device_id":"device.1","confirmed":false,"confirmed":true,"confirmation_version":"pc-enrollment-consent-v1"}',
                headers={"Content-Type":"application/json"})
    duplicate = asyncio.run(raw_duplicate())
    assert duplicate.status_code == 400
    assert identity.calls == [] and host.calls == []


def test_public_worker_and_product_app_are_not_mutated_by_source_composition():
    from pathlib import Path
    import app.app_factory as factory
    root = Path(factory.__file__).resolve().parents[1]
    worker = (root / "worker.py").read_text(encoding="utf-8")
    product = (root / "app" / "app_factory.py").read_text(encoding="utf-8")
    assert "build_review_only_owner_enrollment_app" not in worker
    assert "build_review_only_owner_enrollment_app" not in product
