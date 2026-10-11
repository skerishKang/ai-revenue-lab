from __future__ import annotations

import asyncio
from functools import lru_cache
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from padiem_control_plane import AuthSessionSnapshot, ProductIdentityLink

from app.auth import SESSION_COOKIE
from app.auth_abuse import (
    GLOBAL_DAILY_FAILURE_LIMIT,
    IDENTIFIER_DAILY_FAILURE_LIMIT,
    NETWORK_DAILY_FAILURE_LIMIT,
    AuthAbuseGate,
    InMemoryAuthAbuseStore,
)
from app.auth_routes import _parse_locked_until, _password_lock_minutes
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


@lru_cache(maxsize=1)
def _registered_password_hash() -> str:
    """Real production PBKDF2 credential reused by isolated state-machine tests.

    KDF iterations and authentication verification remain unchanged. Tests
    exercising hashing itself still call hash_password afresh, and registration
    still hashes through the real application route for each request.
    """
    return hash_password("correct horse battery staple")


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
    encoded = _registered_password_hash()
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


# Headers that are per-request or transport-level rather than part of the
# route's own public vocabulary, so they cannot be compared for equality:
#   * date / server          — added by the serving transport, not the route
#   * x-request-id           — a fresh correlation id minted for every request
#                              by RequestTelemetryMiddleware (its value is
#                              random, not derived from the login outcome)
# Everything else is compared, because a header that appeared on only one
# failure class would itself be an oracle.
_VOLATILE_PUBLIC_HEADERS = frozenset({"date", "server", "x-request-id"})


def _public_header_projection(response) -> tuple[tuple[str, str], ...]:
    """Headers an unauthenticated caller can observe on this response.

    Included in the public-boundary projection so a header that appears on only
    one failure class — a throttle hint (``Retry-After``), an authentication
    challenge (``WWW-Authenticate``), or a cookie — fails the equality
    assertions instead of going unnoticed.
    """
    return tuple(
        sorted(
            (name.lower(), value)
            for name, value in response.headers.items()
            if name.lower() not in _VOLATILE_PUBLIC_HEADERS
        )
    )


def _raw_header_names(response) -> set[str]:
    """Every header name the response actually carries, before projection."""
    return {name.lower() for name in response.headers}


async def _login_public(client, identifier, password):
    """Project one login attempt onto the unauthenticated public boundary.

    Returns (status, error code, error message, top-level keys, error keys,
    observable headers) so tests compare everything an unauthenticated caller
    can observe — status, body shape and headers alike.
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
        _public_header_projection(response),
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
    encoded = _registered_password_hash()
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
    encoded = _registered_password_hash()
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
    encoded = _registered_password_hash()
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
    encoded = _registered_password_hash()
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
    encoded = _registered_password_hash()
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
async def test_exhausted_abuse_budget_still_relocks_and_escalates() -> None:
    # #3508 blocker regression. Once the dedicated identifier budget is spent,
    # the throttle must get STRONGER, not disappear: a lapsed lock must still
    # be re-formed by the next full failure block, at an escalated duration.
    store = MemoryStore()
    abuse = InMemoryAuthAbuseStore()
    encoded = _registered_password_hash()
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
        # Burn the whole identifier budget and form the first lock.
        for index in range(5):
            assert (
                await client.post(
                    "/api/auth/password/login",
                    json={"identifier": "owner.test", "password": f"wrong-{index}"},
                )
            ).status_code == 401
        assert store.credentials["owner.test"].locked_until is not None

        # Simulate the account lock window expiring while the dedicated abuse
        # window stays spent.
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await store.record_password_failure(profile.id, 5, past)

        # 100 further guesses must not become an unlimited guessing mode: the
        # account must be re-locked over and over, each lock no shorter than the
        # previous one and never shorter than the base window.
        lock_minutes: list[int] = []
        for index in range(100):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": f"guess-{index}"},
            )
            locked_until = _parse_locked_until(store.credentials["owner.test"].locked_until)
            if locked_until is not None:
                minutes = round(
                    (locked_until - datetime.now(timezone.utc)).total_seconds() / 60
                )
                if minutes not in lock_minutes:
                    lock_minutes.append(minutes)
                # Lapse the lock so the next block of guesses can be attempted.
                await store.record_password_failure(profile.id, 5, past)

        # The throttle really did escalate rather than reset: the attacker now
        # pays the full 60 minute ceiling for every further block of guesses.
        assert lock_minutes[-1] == 60
        assert min(lock_minutes) >= 15
        assert max(lock_minutes) <= 60
        assert lock_minutes == sorted(lock_minutes)

        # Correct password is still denied while a lock is in force. The loop above
        # leaves the account either locked or holding a lapsed lock, so spend one
        # more full failure block to guarantee the throttle is engaged.
        for index in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": f"final-{index}"},
            )
        assert store.credentials["owner.test"].locked_until is not None
        denied = await _login_public(
            client, "owner.test", "correct horse battery staple"
        )

    assert denied[0] == 401
    assert denied[1] == "invalid_credentials"


@pytest.mark.asyncio
async def test_lock_escalation_is_monotone_and_capped() -> None:
    # The escalation floor rises with the identifier's own spend and stops at a
    # cap, so exhaustion can never become permanent denial of a correct
    # password.
    observed = [_password_lock_minutes(value) for value in range(40)]
    assert observed[0] == 15
    assert observed == sorted(observed)
    assert set(observed) == {15, 30, 60}
    assert max(observed) == 60


@pytest.mark.asyncio
async def test_saturated_identifier_budget_does_not_weaken_unrelated_account() -> None:
    # One subject spending its whole budget must not change the accounting of a
    # different account reached from the same network.
    store = MemoryStore()
    abuse = InMemoryAuthAbuseStore()
    encoded = _registered_password_hash()
    await store.register_password_user("victim.test", "victim@example.test", "Victim", encoded)
    await store.register_password_user(
        "bystander.test", "bystander@example.test", "Bystander", encoded
    )
    app = create_app(
        password_settings(),
        history_store=store,
        auth_abuse_store=abuse,
    )
    headers = {"cf-connecting-ip": "203.0.113.42"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        for index in range(9):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "victim.test", "password": f"wrong-{index}"},
                headers=headers,
            )
        assert store.credentials["victim.test"].locked_until is not None

        bystander_failures = []
        for index in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "bystander.test", "password": f"wrong-{index}"},
                headers=headers,
            )
            bystander_failures.append(store.credentials["bystander.test"].failed_attempts)

    assert bystander_failures == [1, 2, 3, 4, 5]
    assert store.credentials["bystander.test"].locked_until is not None


@pytest.mark.asyncio
async def test_saturated_network_and_global_scopes_never_disable_protection() -> None:
    # Saturating the shared network scope, then the global scope, must leave
    # per-identifier accounting fully intact. These are the cross-subject
    # fail-open and global fail-open regressions.
    store = MemoryStore()
    abuse = InMemoryAuthAbuseStore()
    encoded = _registered_password_hash()
    await store.register_password_user("bystander.test", "bystander@example.test", "Bystander", encoded)
    settings = password_settings()
    app = create_app(
        settings,
        history_store=store,
        auth_abuse_store=abuse,
    )
    # The same settings/secret, so this gate derives the same opaque keys as the
    # application's own gate. Advisory scopes are spent directly, which is what
    # a saturated edge looks like without paying 50 live logins.
    saturating_gate = AuthAbuseGate(settings, abuse)
    headers = {"cf-connecting-ip": "198.51.100.7"}

    for _ in range(NETWORK_DAILY_FAILURE_LIMIT + 5):
        await saturating_gate.record_failure_window(
            identifier="spray.test", raw_ip=headers["cf-connecting-ip"]
        )
    for _ in range(GLOBAL_DAILY_FAILURE_LIMIT + 5):
        await saturating_gate.record_failure_window(
            identifier="spray.test", raw_ip=None
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        failures = []
        for index in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "bystander.test", "password": f"wrong-{index}"},
                headers=headers,
            )
            failures.append(store.credentials["bystander.test"].failed_attempts)
        missing = await _login_public(client, "nobody.test", "wrong")

    assert failures == [1, 2, 3, 4, 5]
    assert store.credentials["bystander.test"].locked_until is not None
    assert missing[0] == 401
    assert missing[1] == "invalid_credentials"


@pytest.mark.asyncio
async def test_correct_password_recovers_after_attacker_abuse_state() -> None:
    # The intended recovery path: once a lock lapses, a correct password still
    # authenticates even though the attacker burned the whole abuse window.
    store = MemoryStore()
    abuse = InMemoryAuthAbuseStore()
    encoded = _registered_password_hash()
    profile = await store.register_password_user(
        "owner.test", "owner@example.test", "Owner", encoded
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
        for index in range(12):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": f"wrong-{index}"},
            )
        assert store.credentials["owner.test"].locked_until is not None

        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await store.record_password_failure(profile.id, 5, past)

        recovered = await client.post(
            "/api/auth/password/login",
            json={
                "identifier": "owner.test",
                "password": "correct horse battery staple",
            },
        )

    assert recovered.status_code == 200
    assert store.credentials["owner.test"].failed_attempts == 0
    assert store.credentials["owner.test"].locked_until is None


@pytest.mark.asyncio
async def test_missing_existing_locked_and_window_exhausted_are_indistinguishable() -> None:
    # The public failure tuple must be byte-identical for a missing subject, a
    # wrong password, a locked subject, and a subject whose abuse window is
    # spent. No throttle state may leak through status, code, or message.
    store = MemoryStore()
    abuse = InMemoryAuthAbuseStore()
    encoded = _registered_password_hash()
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    await store.register_password_user(
        "second.test", "second@example.test", "Second", encoded
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
        missing = await _login_public(client, "missing.test", "wrong")
        for index in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": f"wrong-{index}"},
            )
        locked_wrong = await _login_public(client, "owner.test", "wrong")
        locked_correct = await _login_public(
            client, "owner.test", "correct horse battery staple"
        )
        # Burn the whole window on a third account without ever locking it, so
        # the exhausted-window projection can be observed directly.
        for index in range(9):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "second.test", "password": f"wrong-{index}"},
            )
        exhausted_wrong = await _login_public(client, "second.test", "wrong")

    assert missing == locked_wrong == locked_correct == exhausted_wrong
    assert missing[0] == 401
    assert missing[1] == "invalid_credentials"


@pytest.mark.asyncio
async def test_public_header_matrix_is_identical_across_failure_classes() -> None:
    # Closes the #3508 review evidence gap: header equality used to rest on
    # source inspection alone. This test names the matrix explicitly, so a
    # throttle hint (Retry-After), an authentication challenge
    # (WWW-Authenticate) or a cookie appearing on any single failure class is a
    # hard failure rather than an unnoticed oracle.
    store = MemoryStore()
    abuse = InMemoryAuthAbuseStore()
    encoded = _registered_password_hash()
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    await store.register_password_user(
        "second.test", "second@example.test", "Second", encoded
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

        async def projection(identifier: str, password: str):
            response = await client.post(
                "/api/auth/password/login",
                json={"identifier": identifier, "password": password},
            )
            return (
                response.status_code,
                _public_header_projection(response),
                _raw_header_names(response),
            )

        missing = await projection("missing.test", "wrong")
        for index in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": f"wrong-{index}"},
            )
        locked_wrong = await projection("owner.test", "wrong")
        locked_correct = await projection("owner.test", "correct horse battery staple")
        for index in range(9):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "second.test", "password": f"wrong-{index}"},
            )
        exhausted = await projection("second.test", "wrong")

    assert missing == locked_wrong == locked_correct == exhausted

    status, headers, raw_names = missing
    assert status == 401
    names = {name for name, _value in headers}
    # Exactly the JSON error projection, nothing else. A non-vacuous assertion:
    # the response really does declare a JSON body.
    assert names == {"content-type", "content-length"}
    # Checked against the raw header names too, so excluding the correlation id
    # above cannot hide a class-specific header.
    for forbidden in (
        "retry-after",
        "www-authenticate",
        "set-cookie",
        "x-lock",
        "x-throttle",
        "x-ratelimit-limit",
        "x-ratelimit-remaining",
    ):
        assert forbidden not in raw_names
    assert raw_names == {"content-type", "content-length", "x-request-id"}


@pytest.mark.asyncio
async def test_verifier_runs_exactly_once_per_attempt(monkeypatch) -> None:
    # Timing/uniformity: the KDF must run exactly once whether the subject is
    # missing, existing, locked, or window-exhausted. A short-circuit before
    # the verifier is the cheapest existence oracle there is.
    import app.auth_routes as auth_routes

    calls: list[object] = []
    original = auth_routes.verify_password

    def counting_verify(password, encoded):
        calls.append(encoded)
        return original(password, encoded)

    monkeypatch.setattr(auth_routes, "verify_password", counting_verify)

    store = MemoryStore()
    abuse = InMemoryAuthAbuseStore()
    encoded = _registered_password_hash()
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    app = create_app(
        password_settings(),
        history_store=store,
        auth_abuse_store=abuse,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        calls.clear()
        await client.post(
            "/api/auth/password/login",
            json={"identifier": "missing.test", "password": "wrong"},
        )
        missing_calls = list(calls)

        calls.clear()
        for index in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": f"wrong-{index}"},
            )
        existing_calls = list(calls)

        calls.clear()
        await client.post(
            "/api/auth/password/login",
            json={"identifier": "owner.test", "password": "wrong"},
        )
        locked_calls = list(calls)

    assert len(missing_calls) == 1
    assert len(existing_calls) == 5
    assert len(locked_calls) == 1
    # A missing subject must still pay one bounded dummy KDF.
    assert missing_calls[0] is None
    assert existing_calls[0] == encoded
    assert locked_calls[0] == encoded


@pytest.mark.asyncio
async def test_abuse_store_outage_keeps_base_lock_without_oracle() -> None:
    # Regression: a dedicated-store outage must fail closed on the base lock.
    # The previous design suppressed failure accounting entirely on outage,
    # which is an unconditional brute-force fail-open.
    class FailingAbuseStore:
        async def record_failure(self, **kwargs):
            del kwargs
            raise RuntimeError("simulated auth-abuse store outage")

    store = MemoryStore()
    encoded = _registered_password_hash()
    profile = await store.register_password_user(
        "owner.test", "owner@example.test", "Owner", encoded
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
        missing = await _login_public(client, "missing.user", "definitely wrong password")
        wrong = None
        for _ in range(5):
            wrong = await _login_public(
                client, "owner.test", "definitely wrong password"
            )
        # The base lock is in force even though the dedicated store is down.
        assert store.credentials["owner.test"].locked_until is not None
        assert store.credentials["owner.test"].failed_attempts == 5
        locked_correct = await _login_public(
            client, "owner.test", "correct horse battery staple"
        )

        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        await store.record_password_failure(profile.id, 5, past)
        recovered = await client.post(
            "/api/auth/password/login",
            json={
                "identifier": "owner.test",
                "password": "correct horse battery staple",
            },
        )

    assert wrong is not None
    assert missing == wrong
    assert missing[0] == 401
    assert missing == locked_correct
    assert recovered.status_code == 200


@pytest.mark.asyncio
async def test_denied_subject_does_not_consume_another_subject_counter() -> None:
    # D1 atomicity regression at the route boundary: a subject that has spent
    # its window and formed its lock must not advance or disable a different
    # subject's counter.
    store = MemoryStore()
    abuse = InMemoryAuthAbuseStore()
    encoded = _registered_password_hash()
    await store.register_password_user("first.test", "first@example.test", "First", encoded)
    await store.register_password_user("second.test", "second@example.test", "Second", encoded)
    app = create_app(
        password_settings(),
        history_store=store,
        auth_abuse_store=abuse,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        for index in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "first.test", "password": f"wrong-{index}"},
            )
        for index in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "second.test", "password": f"wrong-{index}"},
            )

    first_counts = [value for key, value in abuse.counts.items() if key[1].startswith("aab_identifier_")]
    assert len(first_counts) == 2
    # Equal spend, so neither subject's denial touched the other's counter.
    assert sorted(first_counts) == [5, 5]
    assert store.credentials["first.test"].failed_attempts == 5
    assert store.credentials["second.test"].failed_attempts == 5
    assert store.credentials["first.test"].locked_until is not None
    assert store.credentials["second.test"].locked_until is not None


@pytest.mark.asyncio
async def test_durable_abuse_keys_never_contain_raw_identifier_or_ip() -> None:
    # Privacy regression: only opaque HMAC keys may reach the durable store.
    class CapturingStore(InMemoryAuthAbuseStore):
        def __init__(self) -> None:
            super().__init__()
            self.seen: list[dict] = []

        async def record_failure(self, **kwargs):
            self.seen.append(dict(kwargs))
            return await super().record_failure(**kwargs)

    store = MemoryStore()
    abuse = CapturingStore()
    encoded = _registered_password_hash()
    await store.register_password_user(
        "private.user@example.test", "private.user@example.test", "Private", encoded
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
        await client.post(
            "/api/auth/password/login",
            json={"identifier": "private.user@example.test", "password": "wrong"},
            headers={"cf-connecting-ip": "203.0.113.42"},
        )

    assert abuse.seen, "expected the dedicated store to be consulted"
    rendered = repr(abuse.seen) + repr(abuse.counts)
    assert "private.user@example.test" not in rendered
    assert "203.0.113.42" not in rendered
    assert SESSION_SECRET not in rendered
    for key in abuse.counts:
        assert key[1].startswith("aab_identifier_") or key[1].startswith(
            "aab_network_"
        ) or key[1] == "global"


class ShapeProbeAbuseStore(InMemoryAuthAbuseStore):
    """Deterministic operation-shape probe for the timing-oracle repro.

    Counts durable gate transits and can block inside record_failure, so a
    test proves the route awaits the gate (rather than assuming timing).
    Never blocks unless a test clears ``released`` first.
    """

    def __init__(self) -> None:
        super().__init__()
        self.entered = asyncio.Event()
        self.released = asyncio.Event()
        self.released.set()

    async def record_failure(self, **kwargs):
        self.entered.set()
        await self.released.wait()
        return await super().record_failure(**kwargs)


class ShapeProbeHistoryStore(MemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.failure_writes = 0

    async def record_password_failure(self, user_id, failed_attempts, locked_until):
        self.failure_writes += 1
        return await super().record_password_failure(
            user_id, failed_attempts, locked_until
        )


@pytest.mark.asyncio
async def test_failure_durable_shape_is_equalized_across_classes(
    monkeypatch,
) -> None:
    # CENTRAL blocker regression (#3508 section 6): every public failure
    # class performs the same durable gate shape — exactly one KDF and
    # exactly one abuse-gate transit — proved with exact call counters, no
    # wall clock. Shape is (KDF calls, abuse-gate transits, credential
    # failure writes). Missing/locked classes run the fixed-bucket decoy,
    # so their gate count matches the real accounting pass.
    #
    # Documented residual: only a real, unlocked failure performs the
    # single credential-row write. Padding that write for missing/locked
    # classes would require fake credential rows, which is forbidden, so
    # the remaining systematic difference is exactly one PK UPDATE on the
    # real-failure path — not an obvious multi-operation path split.
    import app.auth_routes as auth_routes

    kdf_calls: list[object] = []
    original = auth_routes.verify_password

    def counting_verify(password, encoded):
        kdf_calls.append(encoded)
        return original(password, encoded)

    monkeypatch.setattr(auth_routes, "verify_password", counting_verify)

    abuse = ShapeProbeAbuseStore()
    store = ShapeProbeHistoryStore()
    encoded = _registered_password_hash()
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    await store.register_password_user(
        "second.test", "second@example.test", "Second", encoded
    )
    app = create_app(
        password_settings(), history_store=store, auth_abuse_store=abuse
    )

    async def shape(client, identifier, password):
        kdf_calls.clear()
        abuse_before = abuse.record_calls
        writes_before = store.failure_writes
        response = await client.post(
            "/api/auth/password/login",
            json={"identifier": identifier, "password": password},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_credentials"
        return (
            len(kdf_calls),
            abuse.record_calls - abuse_before,
            store.failure_writes - writes_before,
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        shape_a = await shape(client, "missing.test", "wrong password value")
        shape_b = await shape(client, "owner.test", "wrong password value")
        for index in range(4):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": f"wrong-{index}"},
            )
        assert store.credentials["owner.test"].locked_until is not None
        shape_c = await shape(client, "owner.test", "wrong password value")
        shape_d = await shape(
            client, "owner.test", "correct horse battery staple"
        )
        gate = app.state.auth_abuse_gate
        for _ in range(IDENTIFIER_DAILY_FAILURE_LIMIT + 1):
            await gate.record_failure_window(identifier="second.test", raw_ip=None)
        shape_e = await shape(client, "second.test", "wrong password value")

    assert shape_a == (1, 1, 0)
    assert shape_b == (1, 1, 1)
    assert shape_c == (1, 1, 0)
    assert shape_d == (1, 1, 0)
    assert shape_e == (1, 1, 1)


@pytest.mark.asyncio
async def test_every_failure_path_blocks_on_durable_abuse_gate() -> None:
    # Proves by loop turns (not wall clock) that every public failure class
    # — missing, existing-unlocked, and locked — awaits the durable gate
    # before responding. No failure class may return without transiting it.
    abuse = ShapeProbeAbuseStore()
    abuse.released.clear()
    store = ShapeProbeHistoryStore()
    encoded = _registered_password_hash()
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    app = create_app(
        password_settings(), history_store=store, auth_abuse_store=abuse
    )

    async def settled(task, turns=300):
        for _ in range(turns):
            if task.done():
                return True
            await asyncio.sleep(0)
        return task.done()

    async def stalled_login(identifier, password):
        task = asyncio.create_task(
            client.post(
                "/api/auth/password/login",
                json={"identifier": identifier, "password": password},
            )
        )
        for _ in range(300):
            if abuse.entered.is_set():
                break
            await asyncio.sleep(0)
        assert abuse.entered.is_set()
        assert await settled(task) is False
        abuse.entered.clear()
        return task

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        missing_task = await stalled_login("missing.test", "wrong")
        wrong_task = await stalled_login("owner.test", "wrong")
        abuse.released.set()
        assert (await missing_task).status_code == 401
        assert (await wrong_task).status_code == 401
        assert abuse.record_calls == 2

        # A locked account's failures also transit the gate (via decoy).
        for _ in range(4):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": "wrong"},
            )
        assert store.credentials["owner.test"].locked_until is not None
        abuse.released.clear()
        locked_task = await stalled_login("owner.test", "wrong")
        abuse.released.set()
        assert (await locked_task).status_code == 401


@pytest.mark.asyncio
async def test_decoy_keyspace_stays_bounded_for_arbitrary_missing_identifiers() -> None:
    # Privacy/bounded-growth regression (#3508 section 7/9): inventing
    # arbitrary missing identifiers must not mint durable rows. All decoy
    # traffic lands in exactly one fixed bucket, provably disjoint from
    # every real identifier bucket.
    abuse = InMemoryAuthAbuseStore()
    store = MemoryStore()
    encoded = _registered_password_hash()
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    app = create_app(
        password_settings(), history_store=store, auth_abuse_store=abuse
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        for index in range(50):
            response = await client.post(
                "/api/auth/password/login",
                json={"identifier": f"phantom-{index}.test", "password": "wrong"},
            )
            assert response.status_code == 401
        for _ in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": "wrong"},
            )

    identifier_keys = sorted(
        key[1] for key in abuse.counts if key[0] == "identifier"
    )
    # One decoy bucket for all fifty phantoms, plus the one real bucket.
    assert len(identifier_keys) == 2
    assert store.credentials["owner.test"].locked_until is not None
    rendered = repr(identifier_keys) + repr(abuse.counts)
    for index in range(50):
        assert f"phantom-{index}" not in rendered


@pytest.mark.asyncio
async def test_locked_attempts_never_mutate_real_identifier_counter() -> None:
    # Active-lock equalization must not advance the real escalation meter:
    # hammering a locked account must leave its future lock exactly where
    # the original lock window left it — otherwise the decoy itself would
    # become a new remote lock amplification.
    abuse = InMemoryAuthAbuseStore()
    store = MemoryStore()
    encoded = _registered_password_hash()
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    app = create_app(
        password_settings(), history_store=store, auth_abuse_store=abuse
    )

    def identifier_counts():
        return {
            key[1]: count
            for key, count in abuse.counts.items()
            if key[0] == "identifier"
        }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        for index in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": f"wrong-{index}"},
            )
        frozen_lock = store.credentials["owner.test"].locked_until
        assert frozen_lock is not None
        counts = identifier_counts()
        assert len(counts) == 1
        (owner_key, owner_count) = next(iter(counts.items()))
        assert owner_count == 5
        for _ in range(6):
            response = await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": "wrong-again"},
            )
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "invalid_credentials"
        counts = identifier_counts()

    assert store.credentials["owner.test"].locked_until == frozen_lock
    assert store.credentials["owner.test"].failed_attempts == 5
    # The real meter is frozen; the six locked attempts advanced only the
    # single fixed decoy bucket.
    assert counts[owner_key] == 5
    assert len(counts) == 2
    assert sorted(counts.values()) == [5, 6]


@pytest.mark.asyncio
async def test_decoy_saturation_never_feeds_real_lock_decisions() -> None:
    # The decoy bucket is timing padding only. Spending it directly must
    # not change any real account's failure count, lock formation, or lock
    # escalation floor.
    from app.auth_routes import _LOGIN_DECOY_IDENTIFIER

    abuse = InMemoryAuthAbuseStore()
    store = MemoryStore()
    encoded = _registered_password_hash()
    await store.register_password_user("owner.test", "owner@example.test", "Owner", encoded)
    app = create_app(
        password_settings(), history_store=store, auth_abuse_store=abuse
    )
    gate = app.state.auth_abuse_gate
    for _ in range(12):
        await gate.record_failure_window(
            identifier=_LOGIN_DECOY_IDENTIFIER, raw_ip=None
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        for index in range(5):
            await client.post(
                "/api/auth/password/login",
                json={"identifier": "owner.test", "password": f"wrong-{index}"},
            )

    credential = store.credentials["owner.test"]
    assert credential.failed_attempts == 5
    assert credential.locked_until is not None
    real_counts = [
        count
        for (scope, _key, _day), count in abuse.counts.items()
        if scope == "identifier"
    ]
    # Twelve decoy spends plus five real spends, on strictly separate keys.
    assert sorted(real_counts) == [5, 12]
    # Base escalation floor: five real failures still mean the base window.
    minutes = (
        _parse_locked_until(credential.locked_until) - datetime.now(timezone.utc)
    ).total_seconds() / 60
    assert 10 < minutes <= 15
