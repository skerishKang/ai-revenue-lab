"""#7381 — the common-login refresh re-attaches the Chat default session.

The shared refresh credential lives 30 days while the Chat default session
lives 7. The callback attached the Chat session and the identity shadow once
(#7364), but ``/auth/shared/refresh`` never re-attached them, so a
shared-login-only account lost devices·connectors again as soon as the Chat
session cookie expired — the #7364 symptom on a 7-day timer.

These tests pin the refresh-side half of the fix:

* an expired Chat session cookie is re-established from the renewed common
  login, and the devices directory answers 200 again;
* a still-working Chat session is left alone — no second canonical session;
* a Chat session whose canonical session was revoked behind the browser's back
  is re-established too;
* a composition without a verifier keeps today's behaviour: the refresh still
  answers 200 and sets no Chat session cookie.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest

from padiem_control_plane import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

from app.auth import SESSION_COOKIE, create_session_token, decode_session_claims
from app.config import Settings
from app.connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.main import create_app
from app.shared_auth_adapter import SharedChatAuth
from app.shared_login_flow import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    REFRESH_PATH,
    SharedLoginFlow,
)

BASE = "https://chat.example.test"
USER_ID = "usr_" + "a" * 32
CANONICAL_SUBJECT_ID = "sub_" + "b" * 16
TENANT_ID = "tenant_" + "c" * 32
DEVICES_PATH = "/api/claw/local-access/devices"
STATUS_PATH = "/api/connectors/status"
WORKSPACE_REF = "workspace_7381"
SESSION_SECRET = "shared-refresh-reattach-session-secret-not-real"


class FakeVerifier:
    def verify(self, token):
        return {"accountId": CANONICAL_SUBJECT_ID, "expiresAt": 4102444800}


class FakeAuthority:
    """Authority double with the canonical-session and reverse-lookup contract."""

    def __init__(self):
        self.sessions: dict[str, AuthSessionSnapshot] = {}
        self.revoked: list[str] = []
        self.counter = 0

    async def resolve_product_user_for_subject(self, *, product_id, canonical_subject_id):
        return USER_ID

    async def resolve_active_memberships(self, *, canonical_subject_id):
        return (TENANT_ID,)

    async def create_tenant(self):
        return TENANT_ID

    async def assign_tenant_membership(self, *, tenant_id, canonical_subject_id, role=None):
        return TenantMembership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            state=TenantMembershipState.ACTIVE,
            role=TenantMembershipRole.OWNER,
        )

    async def resolve_active_tenant_membership(self, *, tenant_id, canonical_subject_id, now):
        return TenantMembership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            state=TenantMembershipState.ACTIVE,
            role=TenantMembershipRole.OWNER,
        )

    async def establish_auth_session(self, *, product_id, subject, authenticated_at, not_after):
        self.counter += 1
        session = AuthSessionSnapshot(
            session_id="sess_%032x" % self.counter,
            product_id=product_id,
            subject=subject,
            issued_at=authenticated_at,
            expires_at=not_after,
            state=AuthSessionState.ACTIVE,
            revision=1,
            tenant_id=TENANT_ID,
        )
        self.sessions[session.session_id] = session
        return session

    async def resolve_auth_session(self, *, session_id):
        snapshot = self.sessions.get(session_id)
        if snapshot is None:
            raise LookupError("canonical_auth_session_not_found")
        return snapshot

    async def revoke_auth_session(self, *, product_id, session_id):
        snapshot = self.sessions.get(session_id)
        if snapshot is None:
            raise LookupError("canonical_auth_session_not_found")
        revoked = replace(snapshot, state=AuthSessionState.REVOKED, revision=snapshot.revision + 1)
        self.sessions[session_id] = revoked
        self.revoked.append(session_id)
        return revoked

    async def resolve_connector_workspace(self, *, session_id):
        return WORKSPACE_REF


class FakeShadowStore:
    def __init__(self):
        self.rows: dict[str, IdentityShadowRecord] = {}
        self.saved = 0

    async def save_projection(self, bridged):
        session = bridged.auth_session
        self.rows[bridged.product_user_id] = IdentityShadowRecord(
            product_user_id=bridged.product_user_id,
            canonical_subject_id=bridged.canonical_subject.subject_id,
            auth_session_id=session.session_id,
            session_revision=session.revision,
            session_state=session.state.value,
            session_expires_at=session.expires_at,
            observed_at=datetime.now(timezone.utc),
        )
        self.saved += 1

    async def load_projection(self, product_user_id):
        return self.rows.get(product_user_id)


class FakeHistory:
    async def get_user(self, user_id):
        return SimpleNamespace(user_id=user_id)


class FakeOAuthBinding:
    async def workspace_connector_state(self, payload):
        return {"ok": True, "connectors": [
            {"connector_id": "gmail", "state": "connected", "usable": True,
             "expires_present": True, "ambiguous": False},
        ]}

    async def workspace_calendar_connector_state(self, payload):
        return {"ok": True, "connectors": [
            {"connector_id": "google-calendar", "state": "not_connected",
             "usable": False, "expires_present": False, "ambiguous": False},
        ]}


class Crypto:
    async def sign(self, key, data):
        return b"x" * 64


def _settings():
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=BASE,
        google_client_id="7381-test.apps.googleusercontent.com",
        google_client_secret="unit-test-only-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


def _build_app(authority, shadow, *, verifier=FakeVerifier()):
    """One app with the reviewed flow composition and the canonical bindings."""

    async def exchange(url, data):
        assert data["grant_type"] == "refresh_token"
        return {"access_token": "access-refreshed", "refresh_token": "refresh-two"}

    async def issue(request, user, access, refresh):
        from starlette.responses import RedirectResponse
        from app.shared_login_flow import issue_shared_cookies

        return issue_shared_cookies(RedirectResponse("/", status_code=302), access, refresh)

    async def resolve_account(request, token):
        return USER_ID

    flow = SharedLoginFlow(
        state_key=b"x" * 32,
        client_id="b62",
        kid="test-kid",
        public_base_url=BASE,
        client_jwk={"kty": "EC", "crv": "P-256", "x": "x", "y": "y", "d": "d"},
        operator_guard=lambda request: True,
        legacy_user=lambda request: None,
        comparator=lambda *args: None,
        exchange=exchange,
        crypto=Crypto(),
        resolve_account=resolve_account,
        issue_session=issue,
        revoke_session=lambda data: None,
    )
    flow.auth = SharedChatAuth(verifier=verifier, authority=authority, legacy=lambda request: None)
    settings = _settings()
    app = create_app(settings, history_store=FakeHistory(), shared_login_flow=flow)
    app.state.control_plane_identity_authority = authority
    app.state.identity_shadow_store = shadow
    app.state.google_oauth_workspace_truth = CloudflareGoogleOAuthWorkspaceTruth(
        FakeOAuthBinding()
    )
    return app


def _expired_chat_cookie(settings, canonical_session_id="sess_expired"):
    now = int(datetime.now(timezone.utc).timestamp())
    return create_session_token(
        settings, USER_ID, now=now - 4 * 3600, canonical_session_id=canonical_session_id,
    )


def _client(app, *, session_cookie=None):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)
    client.cookies.set(REFRESH_COOKIE, "refresh-one", domain="chat.example.test", path=REFRESH_PATH)
    if session_cookie is not None:
        client.cookies.set(SESSION_COOKIE, session_cookie, domain="chat.example.test", path="/")
    return client


async def _refresh(client):
    return await client.post("/auth/shared/refresh", headers={"origin": BASE})


def _set_cookie_values(response):
    getter = getattr(response.headers, "getlist", None)
    if callable(getter):
        return getter("set-cookie")
    return [v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"]


def _session_cookie_value(payloads):
    prefix = SESSION_COOKIE.lower() + "="
    for payload in payloads:
        first = payload.split(";", 1)[0].strip()
        if first.lower().startswith(prefix):
            return first[len(prefix):].strip()
    return None


@pytest.mark.asyncio
async def test_refresh_reestablishes_an_expired_chat_session_and_devices_answer():
    authority, shadow = FakeAuthority(), FakeShadowStore()
    app = _build_app(authority, shadow)

    async with _client(app, session_cookie=_expired_chat_cookie(_settings())) as client:
        response = await _refresh(client)
        assert response.status_code == 200, response.text
        refreshed_cookie = _session_cookie_value(_set_cookie_values(response))
        assert refreshed_cookie, "the refresh must re-attach the Chat session"

        claims = decode_session_claims(_settings(), refreshed_cookie)
        assert claims is not None and claims.user_id == USER_ID
        assert claims.canonical_session_id is not None
        assert claims.canonical_session_id in authority.sessions

        devices = await client.get(DEVICES_PATH)
        status = await client.get(STATUS_PATH)

    assert devices.status_code == 200, devices.text
    assert devices.json()["ok"] is True
    assert status.status_code == 200, status.text
    # The shadow pointer the refresh wrote is the one the consumers resolve.
    assert shadow.rows[USER_ID].auth_session_id == claims.canonical_session_id


@pytest.mark.asyncio
async def test_refresh_keeps_a_working_chat_session_and_mints_nothing():
    authority, shadow = FakeAuthority(), FakeShadowStore()
    app = _build_app(authority, shadow)

    # One working Chat session, established the way the callback does.
    from app.shared_login_flow import attach_chat_default_session
    from starlette.responses import JSONResponse

    seeded = JSONResponse({})
    await attach_chat_default_session(
        seeded, SimpleNamespace(app=app, cookies={}), user_id=USER_ID,
        access="synthetic-access", verifier=FakeVerifier(),
    )
    working_cookie = _session_cookie_value(_set_cookie_values(seeded))
    assert working_cookie
    assert len(authority.sessions) == 1

    async with _client(app, session_cookie=working_cookie) as client:
        response = await _refresh(client)

    assert response.status_code == 200, response.text
    # The refresh must not mint a second canonical session for a working one.
    assert len(authority.sessions) == 1
    assert _session_cookie_value(_set_cookie_values(response)) is None


@pytest.mark.asyncio
async def test_refresh_reestablishes_a_chat_session_revoked_behind_the_browsers_back():
    authority, shadow = FakeAuthority(), FakeShadowStore()
    app = _build_app(authority, shadow)

    from app.shared_login_flow import attach_chat_default_session
    from starlette.responses import JSONResponse

    seeded = JSONResponse({})
    await attach_chat_default_session(
        seeded, SimpleNamespace(app=app, cookies={}), user_id=USER_ID,
        access="synthetic-access", verifier=FakeVerifier(),
    )
    working_cookie = _session_cookie_value(_set_cookie_values(seeded))
    claims = decode_session_claims(_settings(), working_cookie)
    assert claims is not None and claims.canonical_session_id

    # Another device ended this one: the canonical session behind the cookie is
    # revoked while the browser keeps holding the cookie.
    await authority.revoke_auth_session(product_id="b62", session_id=claims.canonical_session_id)

    async with _client(app, session_cookie=working_cookie) as client:
        response = await _refresh(client)
        assert response.status_code == 200, response.text
        refreshed_cookie = _session_cookie_value(_set_cookie_values(response))
        assert refreshed_cookie and refreshed_cookie != working_cookie

        devices = await client.get(DEVICES_PATH)

    refreshed_claims = decode_session_claims(_settings(), refreshed_cookie)
    assert refreshed_claims is not None
    assert refreshed_claims.canonical_session_id != claims.canonical_session_id
    assert refreshed_claims.canonical_session_id in authority.sessions
    assert devices.status_code == 200, devices.text


@pytest.mark.asyncio
async def test_a_composition_without_a_verifier_keeps_todays_refresh_behaviour():
    """The pre-#7381 shape: no verifier on the flow, refresh still 200, no cookie."""

    authority, shadow = FakeAuthority(), FakeShadowStore()

    async def exchange(url, data):
        return {"access_token": "access-refreshed", "refresh_token": "refresh-two"}

    async def issue(request, user, access, refresh):
        from starlette.responses import RedirectResponse
        from app.shared_login_flow import issue_shared_cookies

        return issue_shared_cookies(RedirectResponse("/", status_code=302), access, refresh)

    async def resolve_account(request, token):
        return USER_ID

    flow = SharedLoginFlow(
        state_key=b"x" * 32,
        client_id="b62",
        kid="test-kid",
        public_base_url=BASE,
        client_jwk={"kty": "EC", "crv": "P-256", "x": "x", "y": "y", "d": "d"},
        operator_guard=lambda request: True,
        legacy_user=lambda request: None,
        comparator=lambda *args: None,
        exchange=exchange,
        crypto=Crypto(),
        resolve_account=resolve_account,
        issue_session=issue,
        revoke_session=lambda data: None,
    )
    flow.auth = SimpleNamespace()  # no verifier: the attachment is skipped
    settings = _settings()
    app = create_app(settings, history_store=FakeHistory(), shared_login_flow=flow)
    app.state.control_plane_identity_authority = authority
    app.state.identity_shadow_store = shadow

    async with _client(app, session_cookie=_expired_chat_cookie(settings)) as client:
        response = await _refresh(client)

    assert response.status_code == 200, response.text
    assert _session_cookie_value(_set_cookie_values(response)) is None
    assert authority.sessions == {}
    assert shadow.rows == {}
