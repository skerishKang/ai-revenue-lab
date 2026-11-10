"""#7364 — the shared login callback must establish the Chat default session.

The common login (padiem-auth) used to issue only the shared access/refresh
cookies. A shared-login-only account therefore had no Chat session cookie and
no ``control_plane_identity_shadow`` row, so every shadow consumer failed
closed as soon as the account's last legacy session expired:

* ``GET /api/claw/local-access/devices`` -> 503 ``device_directory_workspace_unavailable``
* ``GET /api/connectors/status`` -> Drive / Gmail / Calendar ``workspace_state=unverified``

These tests pin the root fix: the callback binds the verified ``account_id``
claim to one canonical B62 session, writes the shadow pointer, and sets the
Chat session cookie that the existing logout paths revoke (#5225/#7334).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import RedirectResponse

from padiem_control_plane import AuthSessionState
from padiem_control_plane.auth_sessions import AuthSessionSnapshot
from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

from app.auth import SESSION_COOKIE, decode_session_claims
from app.config import Settings
from app.connector_status_projection import WORKSPACE_STATE_UNVERIFIED
from app.connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.main import create_app
from app.shared_login_flow import attach_chat_default_session

BASE = "https://chat.example.test"
USER_ID = "usr_" + "a" * 32
CANONICAL_SUBJECT_ID = "sub_" + "b" * 16
TENANT_ID = "tenant_" + "c" * 32
STALE_SESSION_ID = "sess_stale_0000000000000000"
DEVICES_PATH = "/api/claw/local-access/devices"
STATUS_PATH = "/api/connectors/status"
GMAIL_ID = "connector:google:gmail@1"
DRIVE_ID = "connector:google:drive@1"
CALENDAR_ID = "connector:google:calendar@1"
WORKSPACE_REF = "workspace_7364"


class FakeVerifier:
    def __init__(self, account_id=CANONICAL_SUBJECT_ID):
        self.account_id = account_id

    def verify(self, token):
        return {"accountId": self.account_id, "expiresAt": 4102444800}


class FakeAuthority:
    """Authority double with the reviewed canonical-session contract."""

    def __init__(self):
        self.sessions: dict[str, AuthSessionSnapshot] = {}
        self.revoked: list[tuple[str, str]] = []
        self.memberships: tuple[str, ...] = ()
        self.establish_fail = False

    async def resolve_active_memberships(self, *, canonical_subject_id):
        return self.memberships

    async def create_tenant(self):
        return TENANT_ID

    async def assign_tenant_membership(self, *, tenant_id, canonical_subject_id, role):
        return TenantMembership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            state=TenantMembershipState.ACTIVE,
            role=TenantMembershipRole(role),
        )

    async def resolve_active_tenant_membership(self, *, tenant_id, canonical_subject_id, now):
        return None

    async def establish_auth_session(self, *, product_id, subject, authenticated_at, not_after):
        if self.establish_fail:
            raise RuntimeError("synthetic authority failure")
        session = AuthSessionSnapshot(
            session_id=f"sess_live_{len(self.sessions):016d}",
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
        current = self.sessions.get(session_id)
        if current is None:
            raise RuntimeError("canonical_auth_session_not_found")
        return current

    async def revoke_auth_session(self, *, product_id, session_id):
        self.revoked.append((product_id, session_id))
        return True

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
            {"connector_id": "google-drive", "state": "not_connected",
             "usable": False, "expires_present": False, "ambiguous": False},
        ]}

    async def workspace_calendar_connector_state(self, payload):
        return {"ok": True, "connectors": [
            {"connector_id": "google-calendar", "state": "not_connected",
             "usable": False, "expires_present": False, "ambiguous": False},
        ]}


def _settings():
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=BASE,
        google_client_id="7364-test.apps.googleusercontent.com",
        google_client_secret="unit-test-only-google-secret",
        session_secret="7364-shared-login-session-secret-not-real",
        session_max_age_seconds=3600,
    )


def _app():
    settings = _settings()
    authority = FakeAuthority()
    shadow = FakeShadowStore()
    app = create_app(settings, history_store=FakeHistory())
    app.state.control_plane_identity_authority = authority
    app.state.identity_shadow_store = shadow
    app.state.google_oauth_workspace_truth = CloudflareGoogleOAuthWorkspaceTruth(
        FakeOAuthBinding()
    )
    return settings, app, authority, shadow


def _request(app, cookie=None):
    headers = [(b"cookie", cookie.encode())] if cookie else []
    return Request({
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": headers, "app": app,
    })


async def _issue(app, settings):
    """Run the callback's session step and return (cookie, canonical session id)."""
    response = RedirectResponse("/", status_code=302)
    canonical = await attach_chat_default_session(
        response, _request(app), user_id=USER_ID, access="synthetic-access",
        verifier=FakeVerifier(),
    )
    cookies = response.headers.getlist("set-cookie")
    chat = next((value for value in cookies if value.startswith(SESSION_COOKIE + "=")), None)
    assert chat is not None, cookies
    return chat.split(";", 1)[0], canonical


def _client(app, cookie):
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE)
    client.cookies.set(SESSION_COOKIE, cookie.split("=", 1)[1])
    return client


@pytest.mark.asyncio
async def test_shared_callback_issues_the_chat_session_and_the_identity_shadow():
    settings, app, authority, shadow = _app()
    cookie, canonical = await _issue(app, settings)

    claims = decode_session_claims(settings, cookie.split("=", 1)[1])
    assert claims is not None and claims.user_id == USER_ID
    assert canonical is not None and claims.canonical_session_id == canonical

    row = shadow.rows[USER_ID]
    assert row.canonical_subject_id == CANONICAL_SUBJECT_ID
    assert row.auth_session_id == canonical
    assert row.session_revision == 1
    assert row.session_state == "active"
    assert shadow.saved == 1


@pytest.mark.asyncio
async def test_devices_and_connectors_resolve_after_login_and_after_shadow_expiry():
    settings, app, authority, shadow = _app()
    cookie, canonical = await _issue(app, settings)

    async with _client(app, cookie) as client:
        first = await client.get(DEVICES_PATH)
        status = await client.get(STATUS_PATH)

    assert first.status_code == 200, first.text
    assert first.json()["ok"] is True
    rows = {row["connector_id"]: row for row in status.json()["connectors"]}
    for connector_id in (GMAIL_ID, DRIVE_ID, CALENDAR_ID):
        assert rows[connector_id]["workspace_state"] != WORKSPACE_STATE_UNVERIFIED, connector_id

    # Simulate the account's legacy shadow session expiring: the pointer names a
    # dead session while the browser's own Chat session is still valid. The
    # #7233 refresh must re-point the shadow from the request's session.
    stale = AuthSessionSnapshot(
        session_id=STALE_SESSION_ID,
        product_id="b62",
        subject=CanonicalSubjectRef(
            subject_type=SubjectType.USER, subject_id=CANONICAL_SUBJECT_ID,
        ),
        issued_at=datetime.now(timezone.utc) - timedelta(days=2),
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
        tenant_id=TENANT_ID,
    )
    authority.sessions[STALE_SESSION_ID] = stale
    shadow.rows[USER_ID] = IdentityShadowRecord(
        product_user_id=USER_ID,
        canonical_subject_id=CANONICAL_SUBJECT_ID,
        auth_session_id=STALE_SESSION_ID,
        session_revision=1,
        session_state="active",
        session_expires_at=stale.expires_at,
        observed_at=datetime.now(timezone.utc),
    )

    async with _client(app, cookie) as client:
        refreshed = await client.get(DEVICES_PATH)
        status = await client.get(STATUS_PATH)

    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["ok"] is True
    rows = {row["connector_id"]: row for row in status.json()["connectors"]}
    for connector_id in (GMAIL_ID, DRIVE_ID, CALENDAR_ID):
        assert rows[connector_id]["workspace_state"] != WORKSPACE_STATE_UNVERIFIED, connector_id
    assert shadow.rows[USER_ID].auth_session_id == canonical


@pytest.mark.asyncio
async def test_logout_revokes_the_canonical_session_the_callback_established():
    settings, app, authority, _ = _app()
    cookie, canonical = await _issue(app, settings)

    async with _client(app, cookie) as client:
        response = await client.post(
            "/api/auth/logout", headers={"origin": BASE},
        )

    assert response.status_code == 200, response.text
    assert authority.revoked == [("b62", canonical)]
    cleared = response.headers.get_list("set-cookie")
    assert any(value.startswith(SESSION_COOKIE + "=") and "Max-Age=0" in value for value in cleared)


def test_a_shadow_failure_never_fails_the_shared_login():
    settings, app, authority, shadow = _app()
    authority.establish_fail = True
    response = RedirectResponse("/", status_code=302)
    import asyncio

    canonical = asyncio.run(attach_chat_default_session(
        response, _request(app), user_id=USER_ID, access="synthetic-access",
        verifier=FakeVerifier(),
    ))
    assert canonical is None
    assert shadow.rows == {}
    cookies = response.headers.getlist("set-cookie")
    chat = next((value for value in cookies if value.startswith(SESSION_COOKIE + "=")), None)
    assert chat is not None
    claims = decode_session_claims(settings, chat.split(";", 1)[0].split("=", 1)[1])
    assert claims is not None and claims.user_id == USER_ID
    assert claims.canonical_session_id is None
