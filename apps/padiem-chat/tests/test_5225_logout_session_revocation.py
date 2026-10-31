"""#5225: a session cookie stored before a logout stops authenticating.

The Padiem Chat session cookie is a signed bearer value. Before #5225 a logout
only deleted the browser cookie, so a stored copy kept working on every
protected Chat/Claw API until it expired.

These focused regressions bind the behaviour to the existing canonical Control
Plane session authority — no new session store, no second login system:

* the login binds the canonical session id into the signed cookie;
* the logout revokes that exact canonical session;
* a protected Chat API refuses the stored cookie right after the logout;
* another device that signed in normally keeps its own session;
* a revocation the authority cannot confirm is reported as a failure instead of
  being presented as a successful logout.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    ProductIdentityLink,
)

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity import IdentityBridgeError
from app.history import HistoryConflict, PasswordCredential, UserProfile
from app.main import create_app

SESSION_SECRET = "logout-revocation-session-secret-not-real-000000"
BASE_URL = "https://chat.example.test"


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
    """Minimal in-memory password-auth history store."""

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
    def __init__(self) -> None:
        self.saved: list[object] = []

    async def save_projection(self, bridged):
        self.saved.append(bridged)


class CanonicalAuthority:
    """In-memory stand-in for the canonical Control Plane identity authority.

    It keeps one canonical auth-session row per login, exactly like the private
    Durable Object, and exposes the read and revoke paths the Chat app uses.
    """

    def __init__(self) -> None:
        self.sessions: dict[str, AuthSessionSnapshot] = {}
        self.memberships: list[str] = ["tenant_0123456789abcdef0123456789abcdef"]
        self.revoked: list[str] = []
        self.counter = 0
        self.unavailable = False
        self.revoke_calls: list[tuple[str, str]] = []

    # -- canonical link / tenant authority ---------------------------------
    def resolve_or_create_product_link(self, *, product_id, product_user_id, auth_provider, provider_subject):
        return ProductIdentityLink(
            product_id=product_id,
            product_user_id=product_user_id,
            canonical_subject_id="sub_" + product_user_id[4:],
        )

    def resolve_active_memberships(self, *, canonical_subject_id):
        return tuple(self.memberships)

    def create_tenant(self):
        return "tenant_0123456789abcdef0123456789abcdef"

    def assign_tenant_membership(self, *, tenant_id, canonical_subject_id):
        self.memberships[:] = [tenant_id]

    # -- canonical session authority ---------------------------------------
    def establish_auth_session(self, *, product_id, subject, authenticated_at, not_after):
        self.counter += 1
        session_id = "sess_%032x" % self.counter
        snapshot = AuthSessionSnapshot(
            session_id=session_id,
            product_id=product_id,
            subject=subject,
            issued_at=authenticated_at,
            expires_at=not_after,
            tenant_id=self.memberships[0] if len(self.memberships) == 1 else None,
        )
        self.sessions[session_id] = snapshot
        return snapshot

    async def resolve_auth_session(self, *, session_id):
        if self.unavailable:
            raise IdentityBridgeError(
                503, "control_plane_identity_unavailable", "Canonical identity service is unavailable."
            )
        snapshot = self.sessions.get(session_id)
        if snapshot is None:
            raise IdentityBridgeError(
                401, "canonical_auth_session_not_found", "Canonical session is unavailable."
            )
        return snapshot

    async def revoke_auth_session(self, *, product_id, session_id):
        self.revoke_calls.append((product_id, session_id))
        if self.unavailable:
            raise IdentityBridgeError(
                503, "control_plane_identity_unavailable", "Canonical identity service is unavailable."
            )
        snapshot = self.sessions.get(session_id)
        if snapshot is None:
            raise IdentityBridgeError(
                401, "canonical_auth_session_not_found", "Canonical session is unavailable."
            )
        if snapshot.product_id != product_id:
            raise IdentityBridgeError(
                403, "identity_authority_product_mismatch", "Canonical session does not match the product."
            )
        revoked = replace(snapshot, state=AuthSessionState.REVOKED, revision=snapshot.revision + 1)
        self.sessions[session_id] = revoked
        self.revoked.append(session_id)
        return revoked


def build_app(*, store=None, authority=None, shadow=None):
    return create_app(
        password_settings(),
        history_store=store or MemoryStore(),
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow,
    )


def _cookie_header(value: str) -> dict[str, str]:
    return {"Cookie": f"{SESSION_COOKIE}={value}"}


def _session_cookie(response: httpx.Response) -> str:
    raw = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE in raw
    for part in raw.split(";"):
        name, _, value = part.partition("=")
        if name.strip() == SESSION_COOKIE:
            return value.strip()
    raise AssertionError("session cookie was not issued")


async def _register(client: httpx.AsyncClient, account: str = "owner.test") -> httpx.Response:
    # #5424: the email address is the single login identifier, so the
    # registration and the login both use it.
    return await client.post(
        "/api/auth/password/register",
        json={
            "email": f"{account}@example.test",
            "name": "Owner Test",
            "password": "correct horse battery staple",
        },
    )


async def _login(client: httpx.AsyncClient, account: str = "owner.test") -> httpx.Response:
    return await client.post(
        "/api/auth/password/login",
        json={"identifier": f"{account}@example.test", "password": "correct horse battery staple"},
    )


@pytest.mark.asyncio
async def test_stored_session_cookie_is_refused_after_the_logout():
    store = MemoryStore()
    authority = CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        registered = await _register(client)
        assert registered.status_code == 200
        stored_cookie = _session_cookie(registered)

        logout = await client.post("/api/auth/logout")
        assert logout.status_code == 200
        assert logout.json()["ok"] is True
        # Exactly the one canonical session of this login was revoked.
        assert len(authority.revoked) == 1
        assert authority.revoke_calls[0][0] == "b62"

    # A fresh client replays the stored cookie: the browser is gone, the
    # credential is not.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as replay:
        protected = await replay.get("/api/conversations", headers=_cookie_header(stored_cookie))
        status = await replay.get("/api/auth/status", headers=_cookie_header(stored_cookie))
        admin = await replay.get("/api/admin/session", headers=_cookie_header(stored_cookie))

    assert protected.status_code == 401
    assert protected.json()["error"]["code"] == "unauthorized"
    assert status.json()["authenticated"] is False
    # An administrator API grants no capability to a revoked session.
    assert admin.json()["authenticated"] is False
    assert admin.json()["role"] is None
    assert admin.json()["capabilities"]["admin_hub"] is False


@pytest.mark.asyncio
async def test_logout_keeps_another_devices_session_working():
    store = MemoryStore()
    authority = CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as device_a:
        await _register(device_a, "owner.a")
        first = _session_cookie(await _login(device_a, "owner.a"))
        logout = await device_a.post("/api/auth/logout", headers=_cookie_header(first))
        assert logout.status_code == 200

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as device_b:
        second = _session_cookie(await _login(device_b, "owner.a"))
        assert second != first
        survivor = await device_b.get("/api/conversations", headers=_cookie_header(second))

    assert survivor.status_code == 200
    # Only the session of the logout was revoked.
    assert len(authority.revoked) == 1


@pytest.mark.asyncio
async def test_relogin_after_the_logout_works():
    store = MemoryStore()
    authority = CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        await _register(client)
        first = _session_cookie(await _login(client))
        assert (await client.post("/api/auth/logout", headers=_cookie_header(first))).status_code == 200
        again = await _login(client)
        assert again.status_code == 200
        second = _session_cookie(again)
        protected = await client.get("/api/conversations", headers=_cookie_header(second))

    assert protected.status_code == 200
    assert second != first


@pytest.mark.asyncio
async def test_logout_does_not_revoke_the_canonical_b54_session():
    store = MemoryStore()
    authority = CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        registered = await _register(client)
        cookie = _session_cookie(registered)
        logout = await client.post("/api/auth/logout", headers=_cookie_header(cookie))
        assert logout.status_code == 200

    claw_sessions = [
        snapshot
        for snapshot in authority.sessions.values()
        if snapshot.product_id == "b54-padiem-claw"
    ]
    chat_sessions = [
        snapshot
        for snapshot in authority.sessions.values()
        if snapshot.product_id == "b62"
    ]
    assert claw_sessions, "the B54 canonical session must still be established at login"
    assert all(snapshot.state is AuthSessionState.ACTIVE for snapshot in claw_sessions)
    assert all(snapshot.state is AuthSessionState.REVOKED for snapshot in chat_sessions)


@pytest.mark.asyncio
async def test_failed_revocation_is_reported_as_a_failure_not_a_successful_logout():
    store = MemoryStore()
    authority = CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        registered = await _register(client)
        cookie = _session_cookie(registered)
        authority.unavailable = True
        logout = await client.post("/api/auth/logout", headers=_cookie_header(cookie))

    assert logout.status_code == 503
    assert logout.json()["error"]["code"] == "session_revocation_failed"
    # The cookie was not deleted: the session was not ended, so the logout must
    # not be presented as successful.
    assert "Max-Age=0" not in logout.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_unavailable_canonical_authority_is_not_reported_as_signed_out():
    store = MemoryStore()
    authority = CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        registered = await _register(client)
        cookie = _session_cookie(registered)
        authority.unavailable = True
        protected = await client.get("/api/conversations", headers=_cookie_header(cookie))

    assert protected.status_code == 503
    assert protected.json()["error"]["code"] == "session_authority_unavailable"


@pytest.mark.asyncio
async def test_a_session_without_a_canonical_session_keeps_its_reviewed_behaviour():
    """A session the canonical authority never confirmed is not a revocation gap.

    #3240 established that a canonical authority or shadow failure must not
    break the B62 login. Such a session carries no canonical session id, so
    there is no canonical session that could be revoked for it. It keeps the
    pre-existing cookie-only behaviour instead of being refused.
    """

    store = MemoryStore()
    authority = CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())
    settings = password_settings()
    unbound = create_session_token(settings, "usr_" + ("0" * 32))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        protected = await client.get("/api/conversations", headers=_cookie_header(unbound))

    assert protected.status_code == 200


@pytest.mark.asyncio
async def test_a_deployment_without_the_canonical_authority_keeps_its_cookie_behaviour():
    store = MemoryStore()
    app = build_app(store=store, authority=None)
    settings = password_settings()
    plain = create_session_token(settings, "usr_" + ("0" * 32))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        protected = await client.get("/api/conversations", headers=_cookie_header(plain))
        logout = await client.post("/api/auth/logout", headers=_cookie_header(plain))

    assert protected.status_code == 200
    assert logout.status_code == 200
    assert logout.json()["ok"] is True


@pytest.mark.asyncio
async def test_a_canonical_authority_failure_does_not_break_the_compatibility_login():
    """#3240: a canonical hiccup must not turn the sign-in into an error."""

    class BrokenAuthority(CanonicalAuthority):
        def establish_auth_session(self, **kwargs):
            raise RuntimeError("canonical authority unavailable")

    store = MemoryStore()
    authority = BrokenAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        registered = await _register(client)

    assert registered.status_code == 200
    assert SESSION_COOKIE in registered.headers.get("set-cookie", "")


def test_the_signed_cookie_carries_the_canonical_session_id():
    settings = password_settings()
    with_binding = create_session_token(
        settings, "usr_" + ("0" * 32), canonical_session_id="sess_" + ("a" * 32)
    )
    without_binding = create_session_token(settings, "usr_" + ("0" * 32))

    from app.auth import decode_session_claims

    bound = decode_session_claims(settings, with_binding)
    assert bound is not None
    assert bound.canonical_session_id == "sess_" + ("a" * 32)
    plain = decode_session_claims(settings, without_binding)
    assert plain is not None
    assert plain.canonical_session_id is None


def test_a_malformed_canonical_session_claim_invalidates_the_cookie():
    settings = password_settings()
    token = create_session_token(
        settings, "usr_" + ("0" * 32), canonical_session_id="not a safe session id"
    )

    from app.auth import decode_session_claims, decode_session_token

    assert decode_session_claims(settings, token) is None
    assert decode_session_token(settings, token) is None
