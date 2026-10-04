from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from padiem_control_plane import AuthSessionSnapshot, ProductIdentityLink

from app.auth import SESSION_COOKIE
from app.auth_abuse import InMemoryAuthAbuseStore
from app.config import ConfigError, Settings
from app.history import HistoryConflict, PasswordCredential, UserProfile
from app.main import create_app
from app.password_auth import (
    PasswordAuthError,
    hash_password,
    normalize_email,
    normalize_username,
    validate_password,
    verify_password,
)

SESSION_SECRET = "password-auth-session-secret-not-real-credential-000000"


def password_settings(**overrides) -> Settings:
    values = dict(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url="https://chat.example.test",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    values.update(overrides)
    return Settings.from_values(**values)


def hybrid_settings(**overrides) -> Settings:
    values = dict(
        runtime_mode="mock",
        auth_mode="hybrid",
        public_base_url="https://chat.example.test",
        google_client_id="hybrid.apps.googleusercontent.com",
        google_client_secret="hybrid-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )
    values.update(overrides)
    return Settings.from_values(**values)


class MemoryStore:
    def __init__(self) -> None:
        self.users: dict[str, UserProfile] = {}
        self.credentials: dict[str, PasswordCredential] = {}

    async def register_password_user(self, username, email, name, password_hash):
        if username in self.credentials or any(user.email.lower() == email.lower() for user in self.users.values()):
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
        if "@" in identifier:
            for cred in self.credentials.values():
                if cred.user.email.lower() == identifier.lower():
                    return cred
            return None
        return self.credentials.get(identifier.lower())

    async def record_password_failure(self, user_id, failed_attempts, locked_until):
        for username, cred in tuple(self.credentials.items()):
            if cred.user.id == user_id:
                self.credentials[username] = PasswordCredential(
                    user=cred.user,
                    username=cred.username,
                    password_hash=cred.password_hash,
                    failed_attempts=failed_attempts,
                    locked_until=locked_until,
                )
                return

    async def reset_password_failures(self, user_id):
        await self.record_password_failure(user_id, 0, None)

    async def get_user(self, user_id):
        return self.users.get(user_id)


class ShadowStore:
    def __init__(self) -> None:
        self.saved = []

    async def save_projection(self, bridged):
        self.saved.append(bridged)


class Authority:
    def __init__(self) -> None:
        self.link_calls = []
        self.session_calls = []
        self.memberships: list[str] = []
        self.created = 0
        self.assigned = []

    def resolve_or_create_product_link(self, **kwargs):
        self.link_calls.append(kwargs)
        return ProductIdentityLink(
            product_id="b62",
            product_user_id=kwargs["product_user_id"],
            canonical_subject_id="subject:padiem:user:password-001",
        )

    def resolve_active_memberships(self, *, canonical_subject_id):
        assert canonical_subject_id == "subject:padiem:user:password-001"
        return tuple(self.memberships)

    def create_tenant(self):
        self.created += 1
        return "tenant_0123456789abcdef0123456789abcdef"

    def assign_tenant_membership(self, *, tenant_id, canonical_subject_id):
        self.assigned.append((tenant_id, canonical_subject_id))
        self.memberships[:] = [tenant_id]

    def establish_auth_session(self, **kwargs):
        self.session_calls.append(kwargs)
        return AuthSessionSnapshot(
            session_id="authsession:b62:password-001",
            product_id="b62",
            subject=kwargs["subject"],
            issued_at=kwargs["authenticated_at"],
            expires_at=kwargs["not_after"],
            tenant_id=self.memberships[0] if len(self.memberships) == 1 else None,
        )


def test_password_hash_roundtrip_and_validation() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("pbkdf2_sha512$220000$")
    assert "correct horse battery staple" not in encoded
    assert verify_password("correct horse battery staple", encoded) is True
    assert verify_password("wrong password value", encoded) is False
    assert verify_password("anything", None) is False
    assert normalize_username(" Test.User ") == "test.user"
    assert normalize_email(" User@Example.COM ") == "user@example.com"
    with pytest.raises(PasswordAuthError):
        normalize_username("UPPER CASE")
    with pytest.raises(PasswordAuthError):
        validate_password("short")
    with pytest.raises(PasswordAuthError):
        validate_password("test-user-long-password", username="test-user")


def test_auth_modes_support_password_and_hybrid_without_weakening_google() -> None:
    assert password_settings().auth_mode == "password"
    assert hybrid_settings().auth_mode == "hybrid"
    with pytest.raises(ConfigError):
        hybrid_settings(google_client_id=None)
    with pytest.raises(ConfigError):
        password_settings(session_secret="short")


@pytest.mark.asyncio
async def test_password_register_creates_session_and_personal_tenant() -> None:
    store = MemoryStore()
    shadow = ShadowStore()
    authority = Authority()
    app = create_app(
        password_settings(),
        history_store=store,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        response = await client.post(
            "/api/auth/password/register",
            json={
                "username": "owner.test",
                "email": "owner@example.test",
                "name": "Owner Test",
                "password": "correct horse battery staple",
            },
        )
        status = await client.get("/api/auth/status")

    assert response.status_code == 200
    assert SESSION_COOKIE in response.headers["set-cookie"]
    assert status.json()["authenticated"] is True
    assert status.json()["methods"] == {"google": False, "password": True}
    assert authority.link_calls[0]["auth_provider"] == "password"
    assert authority.link_calls[0]["provider_subject"] == "owner.test"
    assert authority.created == 1
    assert len(authority.assigned) == 1
    assert len(shadow.saved) == 1
    assert shadow.saved[0].auth_session.tenant_id == "tenant_0123456789abcdef0123456789abcdef"


@pytest.mark.asyncio
async def test_password_login_accepts_username_or_email_and_reuses_tenant() -> None:
    store = MemoryStore()
    shadow = ShadowStore()
    authority = Authority()
    encoded = hash_password("correct horse battery staple")
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    authority.memberships[:] = ["tenant_0123456789abcdef0123456789abcdef"]
    app = create_app(
        password_settings(),
        history_store=store,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow,
    )

    for identifier in ("owner.test", "owner@example.test"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://chat.example.test",
        ) as client:
            response = await client.post(
                "/api/auth/password/login",
                json={"identifier": identifier, "password": "correct horse battery staple"},
            )
        assert response.status_code == 200

    assert authority.created == 0
    assert len(shadow.saved) == 2


async def _login_public(client, identifier, password):
    """Project one login attempt onto the unauthenticated public boundary.

    Returns (status, error code, error message, top-level keys, error keys)
    so tests compare everything an unauthenticated caller can observe.
    """
    response = await client.post(
        "/api/auth/password/login",
        json={"identifier": identifier, "password": password},
    )
    body = response.json()
    return (
        response.status_code,
        body["error"]["code"],
        body["error"]["message"],
        sorted(body.keys()),
        sorted(body["error"].keys()),
    )


@pytest.mark.asyncio
async def test_login_failures_are_nondisclosing_across_missing_wrong_and_locked() -> None:
    # #3501 matrix: A nonexistent identifier, B existing + wrong password,
    # C existing at/over the failure threshold (wrong and even correct
    # password while locked) must be observationally identical. D proves
    # the success path still works on an unlocked account.
    store = MemoryStore()
    shadow = ShadowStore()
    authority = Authority()
    encoded = hash_password("correct horse battery staple")
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    await store.register_password_user("second.user", "second@example.test", "Second", encoded)
    authority.memberships[:] = ["tenant_0123456789abcdef0123456789abcdef"]
    app = create_app(
        password_settings(),
        history_store=store,
        auth_abuse_store=InMemoryAuthAbuseStore(),
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        missing = await _login_public(client, "missing.user", "definitely wrong password")
        first_wrong = await _login_public(client, "owner.test", "definitely wrong password")
        for _ in range(4):
            assert await _login_public(client, "owner.test", "definitely wrong password") == first_wrong
        locked_wrong = await _login_public(client, "owner.test", "definitely wrong password")
        locked_correct = await _login_public(client, "owner.test", "correct horse battery staple")
        second_ok = await client.post(
            "/api/auth/password/login",
            json={"identifier": "second.user", "password": "correct horse battery staple"},
        )

    # The internal lock must actually be engaged for this proof to count.
    assert store.credentials["owner.test"].locked_until is not None
    assert missing == first_wrong == locked_wrong == locked_correct
    assert missing[0] == 401
    assert missing[1] == "invalid_credentials"
    assert second_ok.status_code == 200


@pytest.mark.asyncio
async def test_locked_attempts_do_not_extend_lock() -> None:
    # Guesses made while locked change no server state: the lock lapses
    # on schedule and cannot be stretched by further unauthenticated
    # attempts.
    store = MemoryStore()
    encoded = hash_password("correct horse battery staple")
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    app = create_app(
        password_settings(),
        history_store=store,
        auth_abuse_store=InMemoryAuthAbuseStore(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        for _ in range(5):
            response = await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": "definitely wrong password"},
            )
            assert response.status_code == 401
        frozen_lock = store.credentials["owner.test"].locked_until
        assert frozen_lock is not None
        for _ in range(3):
            response = await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": "definitely wrong password"},
            )
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "invalid_credentials"

    assert store.credentials["owner.test"].locked_until == frozen_lock
    assert store.credentials["owner.test"].failed_attempts == 5


@pytest.mark.asyncio
async def test_expired_lock_decays_instead_of_ratcheting() -> None:
    # A lapsed lock restarts the count: one stray failure after expiry
    # must not re-lock the account on its own.
    store = MemoryStore()
    encoded = hash_password("correct horse battery staple")
    profile = await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    await store.record_password_failure(profile.id, 5, past)
    app = create_app(
        password_settings(),
        history_store=store,
        auth_abuse_store=InMemoryAuthAbuseStore(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        response = await client.post(
            "/api/auth/password/login",
            json={"identifier": "owner.test", "password": "definitely wrong password"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
        assert store.credentials["owner.test"].failed_attempts == 1
        assert store.credentials["owner.test"].locked_until is None
        recovered = await client.post(
            "/api/auth/password/login",
            json={"identifier": "owner.test", "password": "correct horse battery staple"},
        )

    assert recovered.status_code == 200


@pytest.mark.asyncio
async def test_success_resets_failure_count() -> None:
    # Four failures followed by success must reset the counter: a second
    # run of four failures stays below the lock threshold, which a stale
    # counter would have crossed.
    store = MemoryStore()
    shadow = ShadowStore()
    authority = Authority()
    encoded = hash_password("correct horse battery staple")
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    authority.memberships[:] = ["tenant_0123456789abcdef0123456789abcdef"]
    app = create_app(
        password_settings(),
        history_store=store,
        auth_abuse_store=InMemoryAuthAbuseStore(),
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        for _ in range(2):
            for _ in range(4):
                response = await client.post(
                    "/api/auth/password/login",
                    json={"identifier": "owner.test", "password": "definitely wrong password"},
                )
                assert response.status_code == 401
            response = await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": "correct horse battery staple"},
            )
            assert response.status_code == 200

    assert store.credentials["owner.test"].failed_attempts == 0
    assert store.credentials["owner.test"].locked_until is None


@pytest.mark.asyncio
async def test_verifier_runs_for_missing_and_existing_identifiers(monkeypatch) -> None:
    # The password KDF must execute exactly once per login attempt whether
    # or not the identifier exists; a missing account takes the dummy-hash
    # path instead of skipping verification.
    from app import auth_routes

    calls = []
    real_verify = auth_routes.verify_password

    def counting(password, encoded):
        calls.append(encoded)
        return real_verify(password, encoded)

    monkeypatch.setattr(auth_routes, "verify_password", counting)
    store = MemoryStore()
    encoded = hash_password("correct horse battery staple")
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    app = create_app(password_settings(), history_store=store)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        missing = await client.post(
            "/api/auth/password/login",
            json={"identifier": "missing.user", "password": "definitely wrong password"},
        )
        wrong = await client.post(
            "/api/auth/password/login",
            json={"identifier": "owner.test", "password": "definitely wrong password"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert len(calls) == 2
    assert calls[0] is None
    assert calls[1] == encoded


@pytest.mark.asyncio
async def test_duplicate_password_signup_is_conflict_and_password_never_returns() -> None:
    store = MemoryStore()
    app = create_app(password_settings(), history_store=store)
    payload = {
        "username": "owner.test",
        "email": "owner@example.test",
        "name": "Owner",
        "password": "correct horse battery staple",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        first = await client.post("/api/auth/password/register", json=payload)
        second = await client.post("/api/auth/password/register", json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "account_exists"
    assert payload["password"] not in first.text
    assert payload["password"] not in second.text


@pytest.mark.asyncio
async def test_hybrid_status_exposes_both_methods() -> None:
    app = create_app(hybrid_settings(), history_store=MemoryStore())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        status = await client.get("/api/auth/status")
        google = await client.get("/auth/google/start", follow_redirects=False)

    assert status.status_code == 200
    assert status.json()["methods"] == {"google": True, "password": True}
    assert google.status_code == 302


@pytest.mark.asyncio
async def test_abuse_gate_prevents_fresh_relock_after_first_threshold() -> None:
    store = MemoryStore()
    abuse = InMemoryAuthAbuseStore()
    encoded = hash_password("correct horse battery staple")
    profile = await store.register_password_user(
        "owner.test",
        "owner@example.test",
        "Owner",
        encoded,
    )
    app = create_app(
        password_settings(),
        history_store=store,
        auth_abuse_store=abuse,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        for _ in range(5):
            response = await client.post(
                "/api/auth/password/login",
                json={
                    "identifier": "owner.test",
                    "password": "definitely wrong password",
                },
            )
            assert response.status_code == 401

        assert store.credentials["owner.test"].locked_until is not None

        # Simulate the account lock window expiring while the dedicated abuse
        # bucket remains at its daily threshold.
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await store.record_password_failure(profile.id, 5, past)

        throttled = await _login_public(
            client,
            "owner.test",
            "definitely wrong password",
        )
        missing = await _login_public(
            client,
            "missing-after-throttle.user",
            "definitely wrong password",
        )
        after_denied = store.credentials["owner.test"]
        recovered = await client.post(
            "/api/auth/password/login",
            json={
                "identifier": "owner.test",
                "password": "correct horse battery staple",
            },
        )

    assert throttled == missing
    assert throttled[0] == 401
    assert throttled[1] == "invalid_credentials"
    assert after_denied.failed_attempts == 5
    assert after_denied.locked_until == past
    assert recovered.status_code == 200
    assert store.credentials["owner.test"].failed_attempts == 0
    assert store.credentials["owner.test"].locked_until is None


@pytest.mark.asyncio
async def test_abuse_store_failure_suppresses_lock_mutation_without_oracle() -> None:
    class FailingAbuseStore:
        async def consume(self, **kwargs):
            del kwargs
            raise RuntimeError("simulated auth-abuse store outage")

    store = MemoryStore()
    encoded = hash_password("correct horse battery staple")
    await store.register_password_user(
        "owner.test",
        "owner@example.test",
        "Owner",
        encoded,
    )
    app = create_app(
        password_settings(),
        history_store=store,
        auth_abuse_store=FailingAbuseStore(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        missing = await _login_public(
            client,
            "missing.user",
            "definitely wrong password",
        )
        wrong = None
        for _ in range(6):
            wrong = await _login_public(
                client,
                "owner.test",
                "definitely wrong password",
            )
        recovered = await client.post(
            "/api/auth/password/login",
            json={
                "identifier": "owner.test",
                "password": "correct horse battery staple",
            },
        )

    assert wrong is not None
    assert missing == wrong
    assert store.credentials["owner.test"].failed_attempts == 0
    assert store.credentials["owner.test"].locked_until is None
    assert recovered.status_code == 200
