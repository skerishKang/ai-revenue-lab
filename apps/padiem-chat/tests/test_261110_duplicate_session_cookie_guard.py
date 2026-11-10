"""Internal audit H1 (2026-11-10) — duplicate session cookies are refused.

The request-time revocation guard reads the FIRST same-name session cookie in
the Cookie header, while a route that re-parses the header would read the LAST
one. A request carrying two ``padiem_session`` cookies could therefore be
resolved against one session by the guard and authenticated as another by the
route — including a session that was already revoked.

Pinned behaviour:

* a request with two same-name session cookies is refused outright (401 with a
  bounded public code), regardless of which copy comes first and whether either
  copy is revoked;
* an authenticated route resolves the user from the claims the guard verified,
  never by re-parsing the Cookie header;
* a deployment or invocation without the guard keeps the reviewed cookie-only
  behaviour, including the last-cookie read;
* a single session cookie still authenticates as before.
"""
from __future__ import annotations

from dataclasses import replace

import httpx
import pytest
from starlette.requests import Request

from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    ProductIdentityLink,
)
from padiem_control_plane.tenants import (
    TenantMembership,
    TenantMembershipRole,
    TenantMembershipState,
)

from app.auth import SESSION_COOKIE, create_session_token
from app.auth_routes import current_user_id
from app.config import Settings
from app.control_plane_identity import IdentityBridgeError
from app.history import HistoryConflict, PasswordCredential, UserProfile
from app.main import create_app
from app.session_revocation_guard import (
    SESSION_COOKIE_DUPLICATED_CODE,
    SessionVerdict,
)

SESSION_SECRET = "duplicate-cookie-audit-session-secret-not-real-0000"
BASE_URL = "https://chat.example.test"
PROTECTED_PATH = "/api/conversations"


def password_settings(**overrides) -> Settings:
    values = dict(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE_URL,
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    values.update(overrides)
    return Settings.from_values(**values)


class MemoryStore:
    """Minimal in-memory password-auth history store (the #5225 harness shape)."""

    def __init__(self) -> None:
        self.users: dict[str, UserProfile] = {}
        self.credentials: dict[str, PasswordCredential] = {}

    async def register_password_user(self, username, email, name, password_hash):
        if username in self.credentials:
            raise HistoryConflict("duplicate")
        uid = "usr_" + ("%032x" % (len(self.users) + 1))
        profile = UserProfile(uid, email, name, "")
        self.users[uid] = profile
        self.credentials[username] = PasswordCredential(
            user=profile,
            username=username,
            password_hash=password_hash,
            failed_attempts=0,
            locked_until=None,
        )
        return profile

    async def find_password_credential(self, identifier):
        return self.credentials.get(identifier)

    async def find_password_credential_by_user_id(self, user_id):
        for cred in self.credentials.values():
            if cred.user.id == user_id:
                return cred
        return None

    async def update_password_credential(self, user_id, password_hash):
        for username, cred in tuple(self.credentials.items()):
            if cred.user.id == user_id:
                self.credentials[username] = PasswordCredential(
                    user=cred.user,
                    username=cred.username,
                    password_hash=password_hash,
                    failed_attempts=0,
                    locked_until=None,
                )
                return

    async def record_password_failure(self, user_id, failed_attempts, locked_until):
        return None

    async def reset_password_failures(self, user_id):
        return None

    async def get_user(self, user_id):
        return self.users.get(user_id)

    async def list_conversations(self, user_id, *, product_scope, limit=30):
        return []


class ShadowStore:
    async def save_projection(self, bridged):
        return None


class CanonicalAuthority:
    """In-memory canonical authority (the #5225 harness shape)."""

    def __init__(self) -> None:
        self.sessions: dict[str, AuthSessionSnapshot] = {}
        self.memberships: list[str] = ["tenant_0123456789abcdef0123456789abcdef"]
        self.counter = 0

    def resolve_or_create_product_link(self, *, product_id, product_user_id, auth_provider, provider_subject):
        return ProductIdentityLink(
            product_id=product_id,
            product_user_id=product_user_id,
            canonical_subject_id="sub_" + product_user_id[4:],
        )

    def resolve_active_memberships(self, *, canonical_subject_id):
        return tuple(self.memberships)

    def create_tenant(self):
        return self.memberships[0]

    def assign_tenant_membership(self, *, tenant_id, canonical_subject_id, role=None):
        return TenantMembership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            state=TenantMembershipState.ACTIVE,
            role=TenantMembershipRole.OWNER,
        )

    def resolve_active_tenant_membership(self, *, tenant_id, canonical_subject_id, now):
        return TenantMembership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            state=TenantMembershipState.ACTIVE,
            role=TenantMembershipRole.OWNER,
        )

    def establish_auth_session(self, *, product_id, subject, authenticated_at, not_after):
        self.counter += 1
        snapshot = AuthSessionSnapshot(
            session_id="sess_%032x" % self.counter,
            product_id=product_id,
            subject=subject,
            issued_at=authenticated_at,
            expires_at=not_after,
            tenant_id=self.memberships[0],
        )
        self.sessions[snapshot.session_id] = snapshot
        return snapshot

    async def resolve_auth_session(self, *, session_id):
        snapshot = self.sessions.get(session_id)
        if snapshot is None:
            raise IdentityBridgeError(
                401, "canonical_auth_session_not_found", "Canonical session is unavailable."
            )
        return snapshot

    async def revoke_auth_session(self, *, product_id, session_id):
        snapshot = self.sessions.get(session_id)
        if snapshot is None:
            raise IdentityBridgeError(
                401, "canonical_auth_session_not_found", "Canonical session is unavailable."
            )
        revoked = replace(snapshot, state=AuthSessionState.REVOKED, revision=snapshot.revision + 1)
        self.sessions[session_id] = revoked
        return revoked


def build_app(*, store=None, authority=None):
    return create_app(
        password_settings(),
        history_store=store or MemoryStore(),
        control_plane_identity_authority=authority,
        identity_shadow_store=ShadowStore(),
    )


async def _register(client: httpx.AsyncClient, account: str) -> str:
    response = await client.post(
        "/api/auth/password/register",
        json={
            "email": f"{account}@example.test",
            "name": "Audit H1",
            "password": "correct horse battery staple",
        },
    )
    assert response.status_code == 200, response.text
    for part in response.headers.get("set-cookie", "").split(";"):
        name, _, value = part.partition("=")
        if name.strip() == SESSION_COOKIE:
            return value.strip()
    raise AssertionError("no session cookie issued")


async def _login(client: httpx.AsyncClient, account: str) -> str:
    response = await client.post(
        "/api/auth/password/login",
        json={"identifier": f"{account}@example.test", "password": "correct horse battery staple"},
    )
    assert response.status_code == 200, response.text
    for part in response.headers.get("set-cookie", "").split(";"):
        name, _, value = part.partition("=")
        if name.strip() == SESSION_COOKIE:
            return value.strip()
    raise AssertionError("no session cookie issued")


def _cookie_header(*values: str) -> dict[str, str]:
    return {"Cookie": "; ".join(f"{SESSION_COOKIE}={value}" for value in values)}


async def _app_with_active_and_revoked_cookies():
    """One app plus a still-active session cookie and one whose session is gone."""
    store, authority = MemoryStore(), CanonicalAuthority()
    app = build_app(store=store, authority=authority)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as device_a:
        active = await _register(device_a, "audit.active")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as device_b:
        revoked = await _register(device_b, "audit.revoked")
        logout = await device_b.post("/api/auth/logout", headers=_cookie_header(revoked))
        assert logout.status_code == 200, logout.text
    return app, active, revoked


@pytest.mark.asyncio
async def test_active_plus_revoked_duplicate_cookies_are_refused_in_either_order():
    app, active, revoked = await _app_with_active_and_revoked_cookies()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        active_first = await client.get(
            PROTECTED_PATH, headers=_cookie_header(active, revoked))
        revoked_first = await client.get(
            PROTECTED_PATH, headers=_cookie_header(revoked, active))

    for response in (active_first, revoked_first):
        assert response.status_code == 401, response.text
        assert response.json()["error"]["code"] == SESSION_COOKIE_DUPLICATED_CODE


@pytest.mark.asyncio
async def test_two_active_duplicate_cookies_are_refused_too():
    store, authority = MemoryStore(), CanonicalAuthority()
    app = build_app(store=store, authority=authority)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as device:
        first = await _register(device, "audit.first")
        second = await _login(device, "audit.first")
    assert first != second

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        response = await client.get(PROTECTED_PATH, headers=_cookie_header(first, second))

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == SESSION_COOKIE_DUPLICATED_CODE


@pytest.mark.asyncio
async def test_a_single_session_cookie_still_authenticates():
    store, authority = MemoryStore(), CanonicalAuthority()
    app = build_app(store=store, authority=authority)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as device:
        cookie = await _register(device, "audit.single")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        response = await client.get(PROTECTED_PATH, headers=_cookie_header(cookie))

    assert response.status_code == 200, response.text


def _request(app, cookie_values, verdict=None):
    headers = [(b"cookie", "; ".join(
        f"{SESSION_COOKIE}={value}" for value in cookie_values).encode())]
    request = Request({
        "type": "http", "method": "GET", "path": PROTECTED_PATH,
        "query_string": b"", "headers": headers, "app": app,
    })
    if verdict is not None:
        request.state.padiem_session_verdict = verdict
    return request


def test_route_resolves_the_guard_claims_not_a_reparsed_cookie():
    """The guard verified the first cookie; the route must answer with it."""
    app = build_app()
    settings = password_settings()
    user_first = "usr_" + "1" * 32
    user_last = "usr_" + "2" * 32
    first_cookie = create_session_token(settings, user_first, canonical_session_id="sess_" + "a" * 32)
    last_cookie = create_session_token(settings, user_last, canonical_session_id="sess_" + "b" * 32)

    verdict = SessionVerdict(
        authenticated=True, user_id=user_first,
        canonical_session_id="sess_" + "a" * 32, reason="active",
    )
    request = _request(app, [first_cookie, last_cookie], verdict)
    assert current_user_id(request) == user_first


def test_without_a_verdict_the_cookie_only_behaviour_is_unchanged():
    """No guard verdict (compat deployment / direct invocation): last cookie wins."""
    app = build_app()
    settings = password_settings()
    user_first = "usr_" + "3" * 32
    user_last = "usr_" + "4" * 32
    first_cookie = create_session_token(settings, user_first)
    last_cookie = create_session_token(settings, user_last)

    request = _request(app, [first_cookie, last_cookie])
    assert current_user_id(request) == user_last
