"""Internal audit H2 (2026-11-10) — sessions without a canonical session id.

On an authority-backed deployment every login binds its session cookie to one
canonical Control Plane session. A cookie without that binding cannot be
revoked by the logout paths, so it used to survive until its own expiry even
after the account was gone. Pinned behaviour:

* an authority-backed register/login refuses to mint a session cookie when the
  canonical session or its shadow pointer could not be established (503, no
  cookie) instead of degrading to an unbound cookie;
* a deployment without the canonical authority keeps the reviewed
  cookie-only compatibility behaviour unchanged;
* a compatibility cookie without a canonical session id keeps working through
  the fixed 7-day transition window and is refused after it;
* a cookie whose user row no longer exists is refused;
* a store that cannot answer right now does not widen the check into an
  outage of its own.
"""
from __future__ import annotations

import pytest

from app.auth import (
    SESSION_COOKIE,
    create_session_token,
    decode_session_claims,
)
from app.config import Settings
from app.history import HistoryConflict, PasswordCredential, UserProfile
from app.main import create_app

import httpx

SESSION_SECRET = "sidless-policy-session-secret-not-real-00000000"
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
    """Shadow store that either saves or always fails, per the test's need."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.saved: list[object] = []

    async def save_projection(self, bridged):
        if self.fail:
            raise RuntimeError("synthetic shadow store failure")
        self.saved.append(bridged)


class CanonicalAuthority:
    """In-memory canonical authority (the #5225 harness shape)."""

    def __init__(self) -> None:
        self.sessions: dict[str, object] = {}
        self.memberships: list[str] = ["tenant_0123456789abcdef0123456789abcdef"]
        self.counter = 0

    def resolve_or_create_product_link(self, *, product_id, product_user_id, auth_provider, provider_subject):
        from padiem_control_plane import ProductIdentityLink

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
        from padiem_control_plane.tenants import (
            TenantMembership, TenantMembershipRole, TenantMembershipState,
        )

        return TenantMembership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            state=TenantMembershipState.ACTIVE,
            role=TenantMembershipRole.OWNER,
        )

    def resolve_active_tenant_membership(self, *, tenant_id, canonical_subject_id, now):
        from padiem_control_plane.tenants import (
            TenantMembership, TenantMembershipRole, TenantMembershipState,
        )

        return TenantMembership(
            tenant_id=tenant_id,
            canonical_subject_id=canonical_subject_id,
            state=TenantMembershipState.ACTIVE,
            role=TenantMembershipRole.OWNER,
        )

    def establish_auth_session(self, *, product_id, subject, authenticated_at, not_after):
        from padiem_control_plane import AuthSessionSnapshot

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
            from padiem_control_plane.contracts import CanonicalSubjectRef, SubjectType
            from padiem_control_plane import AuthSessionSnapshot, AuthSessionState

            return AuthSessionSnapshot(
                session_id=session_id,
                product_id="b62",
                subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id="sub_x"),
                issued_at=None,
                expires_at=None,
                state=AuthSessionState.REVOKED,
                revision=1,
                tenant_id=self.memberships[0],
            )
        return snapshot


def build_app(*, store=None, authority="default", shadow=None):
    kwargs = dict(history_store=store or MemoryStore())
    if authority != "default":
        kwargs["control_plane_identity_authority"] = authority
    if shadow is not None:
        kwargs["identity_shadow_store"] = shadow
    return create_app(password_settings(), **kwargs)


async def _register(client: httpx.AsyncClient, account: str = "policy.test") -> httpx.Response:
    return await client.post(
        "/api/auth/password/register",
        json={
            "email": f"{account}@example.test",
            "name": "Sidless Policy",
            "password": "correct horse battery staple",
        },
    )


def _session_cookies(response: httpx.Response) -> list[str]:
    getter = getattr(response.headers, "getlist", None)
    payloads = getter("set-cookie") if callable(getter) else [
        v for k, v in response.headers.multi_items() if k.lower() == "set-cookie"
    ]
    values = []
    for payload in payloads:
        for part in payload.split(";"):
            name, _, value = part.partition("=")
            if name.strip() == SESSION_COOKIE:
                values.append(value.strip())
    return values


@pytest.mark.asyncio
async def test_authority_backed_register_refuses_to_mint_an_unbound_session_cookie():
    store, authority = MemoryStore(), CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore(fail=True))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        response = await _register(client)

    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "auth_storage_error"
    assert _session_cookies(response) == []


@pytest.mark.asyncio
async def test_authority_backed_login_fails_closed_when_the_shadow_store_fails():
    store, authority = MemoryStore(), CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore(fail=True))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        registered = await _register(client)
        assert registered.status_code == 503  # the account row exists, no cookie was minted
        login = await client.post(
            "/api/auth/password/login",
            json={"identifier": "policy.test@example.test",
                  "password": "correct horse battery staple"},
        )

    assert login.status_code == 503, login.text
    assert login.json()["error"]["code"] == "auth_storage_error"
    assert _session_cookies(login) == []


@pytest.mark.asyncio
async def test_authority_backed_login_mints_a_bound_session_cookie_when_it_succeeds():
    store, authority = MemoryStore(), CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        registered = await _register(client)

    assert registered.status_code == 200, registered.text
    cookies = _session_cookies(registered)
    assert len(cookies) == 1
    claims = decode_session_claims(password_settings(), cookies[0])
    assert claims is not None and claims.canonical_session_id is not None


@pytest.mark.asyncio
async def test_compat_deployment_keeps_the_cookie_only_behaviour():
    app = build_app(authority=None)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        registered = await _register(client)

    assert registered.status_code == 200, registered.text
    cookies = _session_cookies(registered)
    assert len(cookies) == 1
    claims = decode_session_claims(password_settings(), cookies[0])
    assert claims is not None and claims.canonical_session_id is None


@pytest.mark.asyncio
async def test_sidless_cookie_is_refused_after_the_transition_window(
    monkeypatch: pytest.MonkeyPatch,
):
    store, authority = MemoryStore(), CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as device:
        await _register(device)
    user_id = next(iter(store.users))
    # A compatibility cookie minted before the binding rule: no canonical id.
    sidless = create_session_token(password_settings(), user_id)
    assert decode_session_claims(password_settings(), sidless).canonical_session_id is None

    monkeypatch.setattr(
        "app.session_revocation_guard.sidless_session_cutoff_passed", lambda now=None: True,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        response = await client.get(
            PROTECTED_PATH, headers={"Cookie": f"{SESSION_COOKIE}={sidless}"})

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_sidless_cookie_keeps_working_during_the_transition_window(
    monkeypatch: pytest.MonkeyPatch,
):
    store, authority = MemoryStore(), CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as device:
        await _register(device)
    user_id = next(iter(store.users))
    sidless = create_session_token(password_settings(), user_id)

    monkeypatch.setattr(
        "app.session_revocation_guard.sidless_session_cutoff_passed", lambda now=None: False,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        response = await client.get(
            PROTECTED_PATH, headers={"Cookie": f"{SESSION_COOKIE}={sidless}"})

    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_a_cookie_for_a_deleted_user_row_is_refused():
    """A compatibility cookie has no canonical session for account deletion to
    revoke, so the user row is the last guard against its reuse."""
    store, authority = MemoryStore(), CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as device:
        await _register(device)
    user_id = next(iter(store.users))
    cookie = create_session_token(password_settings(), user_id)  # no canonical id

    # The account is gone; only the browser-held cookie remains.
    del store.users[user_id]
    del store.credentials[next(iter(store.credentials))]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        response = await client.get(
            PROTECTED_PATH, headers={"Cookie": f"{SESSION_COOKIE}={cookie}"})

    assert response.status_code == 401, response.text


@pytest.mark.asyncio
async def test_a_store_outage_does_not_refuse_a_valid_cookie():
    store, authority = MemoryStore(), CanonicalAuthority()
    app = build_app(store=store, authority=authority, shadow=ShadowStore())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as device:
        await _register(device)
    user_id = next(iter(store.users))
    cookie = create_session_token(password_settings(), user_id)  # no canonical id

    async def broken_get_user(user_id):
        raise RuntimeError("synthetic store outage")

    store.get_user = broken_get_user

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE_URL) as client:
        response = await client.get(
            PROTECTED_PATH, headers={"Cookie": f"{SESSION_COOKIE}={cookie}"})

    assert response.status_code == 200, response.text
