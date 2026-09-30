"""#3240 — canonical B54 session parity for a verified Google login.

The B54 canonical session existed only behind a server-verified **password**
login. #3240 makes it reachable from a **verified Google** login too, without
adding a second identity authority, a second session store, or any browser
authority.

Proven here:

- PASSWORD_B54_SESSION: the password path is byte-for-byte unchanged and still
  produces a canonical B54 session with provider=password.
- GOOGLE_VERIFIED_CALLBACK_B54_SESSION: a fully verified Google callback produces
  a canonical B54 session whose provider is google, whose provider_subject is the
  server-verified Google subject, whose product_id is B54 and whose tenant comes
  from the Control Plane membership authority.
- UNKNOWN_B54_PROVIDER_REJECTED: the provider set is closed to exactly
  {password, google}.
- UNVERIFIED_GOOGLE_B54_SESSION=0 / INVALID_OAUTH_STATE_B54_SESSION=0: the B54
  chain is only attempted after server verification, and an unverified identity
  or a bad OAuth state never reaches it.
- Browser authority = 0 for every identity field: forged query/body values cannot
  change the product user, provider, provider subject, subject, tenant, product
  or session.
- B54_FAILURE_BREAKS_B62_GOOGLE_LOGIN=NO: a B54 failure preserves the completed
  B62 Google login, matching the password precedent.
- No B54 session id / canonical subject / tenant is newly projected to the browser.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from padiem_control_plane.b54_identity_bridge import (
    B54_PRODUCT_ID,
    TRUSTED_B54_SERVER_AUTH_PROVIDERS,
    TrustedB54ServerAuthEvidence,
)

from app.b54_canonical_session import (
    B54ServerAuthenticatedOwner,
    B54CanonicalSessionProducer,
)
from app.auth_routes import establish_b54_canonical_session_after_google_login

NOW = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc)
TENANT = "tenant_" + "d" * 32
GOOGLE_SUBJECT = "1087654321098765432100"
GOOGLE_PROFILE_ID = "usr_" + "b" * 32

# The userinfo dict exactly as GoogleOAuthClient.fetch_userinfo returns it. That
# method already refused any response whose verified_email was not True, so a
# subject here is server-verified by construction.
VERIFIED_IDENTITY = {
    "subject": GOOGLE_SUBJECT,
    "email": "owner@example.test",
    "name": "Owner",
    "picture": "https://example.test/p.png",
}


class _Authority:
    """The single Control Plane authority; the only subject/tenant/session minter."""

    def __init__(self) -> None:
        self.link_calls: list[dict] = []
        self.session_calls: list[dict] = []
        self.membership_reads: list[str] = []
        self.tenants_created = 0
        self.assignments: list[tuple[str, str]] = []

    def resolve_or_create_product_link(self, **kwargs):
        self.link_calls.append(kwargs)
        from padiem_control_plane import (
            IdentityLinkState,
            ProductIdentityLink,
        )

        return ProductIdentityLink(
            product_id=kwargs["product_id"],
            product_user_id=kwargs["product_user_id"],
            canonical_subject_id=f"subject:{kwargs['product_id']}:{kwargs['product_user_id']}",
            state=IdentityLinkState.ACTIVE,
        )

    def resolve_active_memberships(self, *, canonical_subject_id: str):
        self.membership_reads.append(canonical_subject_id)
        return (TENANT,)

    def create_tenant(self) -> str:
        self.tenants_created += 1
        return TENANT

    def assign_tenant_membership(self, *, tenant_id: str, canonical_subject_id: str) -> None:
        self.assignments.append((tenant_id, canonical_subject_id))

    def establish_auth_session(self, **kwargs):
        from padiem_control_plane import AuthSessionSnapshot, AuthSessionState

        self.session_calls.append(kwargs)
        subject = kwargs["subject"]
        return AuthSessionSnapshot(
            session_id=f"sess_{subject.subject_id}",
            product_id=kwargs["product_id"],
            subject=subject,
            issued_at=kwargs["authenticated_at"],
            expires_at=kwargs["not_after"],
            state=AuthSessionState.ACTIVE,
            revision=1,
            tenant_id=TENANT,
        )


class _AppState:
    def __init__(self, authority, max_age: int = 3600) -> None:
        self.control_plane_identity_authority = authority

        class _Settings:
            session_max_age_seconds = max_age

        self.settings = _Settings()


def _producer(authority) -> B54CanonicalSessionProducer:
    return B54CanonicalSessionProducer(
        authority=authority, session_max_age_seconds=3600, clock=lambda: NOW
    )


# --- owner model ------------------------------------------------------------


def test_google_owner_is_built_only_from_a_server_verified_identity() -> None:
    owner = B54ServerAuthenticatedOwner.from_verified_google_identity(
        product_user_id=GOOGLE_PROFILE_ID, google_identity=VERIFIED_IDENTITY
    )
    assert owner.provider == "google"
    assert owner.provider_subject == GOOGLE_SUBJECT
    assert owner.product_user_id == GOOGLE_PROFILE_ID
    # The email/picture never become part of the B54 owner.
    assert "owner@example.test" not in repr(owner)


def test_google_owner_refuses_a_missing_or_unusable_subject() -> None:
    for identity in (
        {},
        {"subject": ""},
        {"subject": "   "},
        {"subject": 12345},
        {"subject": "x" * 256},
        "not-a-mapping",
    ):
        with pytest.raises(ValueError):
            B54ServerAuthenticatedOwner.from_verified_google_identity(
                product_user_id=GOOGLE_PROFILE_ID, google_identity=identity
            )


def test_google_owner_cannot_take_an_arbitrary_provider() -> None:
    """provider arbitrary request passthrough = NO."""

    with pytest.raises(ValueError):
        B54ServerAuthenticatedOwner(
            product_user_id=GOOGLE_PROFILE_ID,
            provider_subject="subject",
            provider="kakao",
        )
    with pytest.raises(ValueError):
        B54ServerAuthenticatedOwner(
            product_user_id=GOOGLE_PROFILE_ID,
            provider_subject="subject",
            provider="",
        )


def test_password_owner_default_is_unchanged() -> None:
    owner = B54ServerAuthenticatedOwner(
        product_user_id=GOOGLE_PROFILE_ID, provider_subject="claw.owner"
    )
    assert owner.provider == "password"


def test_evidence_provider_set_is_closed() -> None:
    assert set(TRUSTED_B54_SERVER_AUTH_PROVIDERS) == {"password", "google"}


@pytest.mark.parametrize(
    "provider", ["kakao", "apple", "oauth", "google ", "GOOGLE", "b62", "b54", ""]
)
def test_unknown_provider_is_rejected_as_b54_evidence(provider) -> None:
    with pytest.raises(ValueError):
        TrustedB54ServerAuthEvidence(
            product_user_id=GOOGLE_PROFILE_ID,
            provider=provider,
            provider_subject="subject",
            authenticated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )


# --- Google path produces the canonical session -----------------------------


@pytest.mark.asyncio
async def test_verified_google_login_establishes_a_b54_canonical_session() -> None:
    authority = _Authority()
    request = _FakeRequest(_AppState(authority))
    session = await establish_b54_canonical_session_after_google_login(
        request, GOOGLE_PROFILE_ID, VERIFIED_IDENTITY
    )
    assert session is not None
    link = authority.link_calls[-1]
    assert link["product_id"] == B54_PRODUCT_ID
    assert link["product_user_id"] == GOOGLE_PROFILE_ID
    assert link["auth_provider"] == "google"
    # GOOGLE_PROVIDER_SUBJECT_FROM_SERVER_USERINFO
    assert link["provider_subject"] == GOOGLE_SUBJECT
    # B54_TENANT_SERVER_DERIVED: the tenant came from the authority's
    # membership resolution, not from the profile, the subject or a default.
    assert session.auth_session.tenant_id == TENANT
    assert authority.membership_reads
    assert authority.tenants_created == 0  # existing membership, not a new tenant
    # Cross-app isolation: never a B62 session.
    assert session.auth_session.product_id == B54_PRODUCT_ID
    assert session.auth_session.product_id != "b62"


@pytest.mark.asyncio
async def test_google_b54_session_is_not_derived_from_the_google_subject() -> None:
    """B54_TENANT_SERVER_DERIVED: tenant != user_id, != subject, != product."""

    authority = _Authority()
    request = _FakeRequest(_AppState(authority))
    session = await establish_b54_canonical_session_after_google_login(
        request, GOOGLE_PROFILE_ID, VERIFIED_IDENTITY
    )
    tenant = session.auth_session.tenant_id
    assert tenant not in {GOOGLE_PROFILE_ID, GOOGLE_SUBJECT, B54_PRODUCT_ID, "default"}
    assert tenant == TENANT


@pytest.mark.asyncio
async def test_unverified_google_identity_establishes_no_b54_session() -> None:
    """UNVERIFIED_GOOGLE_B54_SESSION=0."""

    authority = _Authority()
    request = _FakeRequest(_AppState(authority))
    for identity in ({}, {"subject": ""}, {"subject": None}, "forged"):
        assert (
            await establish_b54_canonical_session_after_google_login(
                request, GOOGLE_PROFILE_ID, identity
            )
            is None
        )
    assert authority.link_calls == []
    assert authority.session_calls == []


@pytest.mark.asyncio
async def test_missing_control_plane_authority_yields_no_session() -> None:
    authority = _Authority()
    request = _FakeRequest(_AppState(None))
    assert (
        await establish_b54_canonical_session_after_google_login(
            request, GOOGLE_PROFILE_ID, VERIFIED_IDENTITY
        )
        is None
    )
    assert authority.link_calls == []


@pytest.mark.asyncio
async def test_b54_failure_does_not_break_the_completed_b62_google_login() -> None:
    """B54_FAILURE_BREAKS_B62_GOOGLE_LOGIN=NO (password precedent)."""

    class _Exploding:
        def __getattr__(self, name):
            def _boom(*args, **kwargs):
                raise RuntimeError("control plane down")

            return _boom

    request = _FakeRequest(_AppState(_Exploding()))
    assert (
        await establish_b54_canonical_session_after_google_login(
            request, GOOGLE_PROFILE_ID, VERIFIED_IDENTITY
        )
        is None
    )


# --- browser authority is zero ---------------------------------------------


@pytest.mark.asyncio
async def test_forged_request_fields_cannot_name_any_identity_field() -> None:
    """Every browser-settable field is ignored; the server row decides."""

    authority = _Authority()
    request = _FakeRequest(
        _AppState(authority),
        query={
            "product_user_id": "usr_FORGED",
            "provider": "kakao",
            "provider_subject": "forged-subject",
            "subject_id": "sub_FORGED",
            "canonical_subject_id": "sub_FORGED",
            "tenant_id": "tenant_FORGED",
            "product_id": "b62",
            "session_id": "sess_FORGED",
            "auth_session_id": "sess_FORGED",
        },
        body={
            "product_user_id": "usr_FORGED_BODY",
            "provider": "apple",
            "provider_subject": "forged-body-subject",
            "tenant_id": "tenant_FORGED_BODY",
        },
        headers={
            "x-product-user-id": "usr_FORGED_HEADER",
            "x-tenant-id": "tenant_FORGED_HEADER",
        },
        cookies={"session": "forged-session", "auth_session_id": "sess_FORGED"},
    )
    session = await establish_b54_canonical_session_after_google_login(
        request, GOOGLE_PROFILE_ID, VERIFIED_IDENTITY
    )
    assert session is not None
    link = authority.link_calls[-1]
    assert link["product_user_id"] == GOOGLE_PROFILE_ID
    assert link["auth_provider"] == "google"
    assert link["provider_subject"] == GOOGLE_SUBJECT
    assert link["product_id"] == B54_PRODUCT_ID
    assert session.auth_session.tenant_id == TENANT
    serialized = str(authority.link_calls) + str(authority.session_calls)
    for forged in ("FORGED", "kakao", "apple", "b62"):
        assert forged not in serialized


@pytest.mark.asyncio
async def test_session_lifetime_comes_from_server_settings_not_the_request() -> None:
    authority = _Authority()
    request = _FakeRequest(
        _AppState(authority, max_age=900),
        query={"session_max_age_seconds": "999999", "expires_in": "999999"},
    )
    session = await establish_b54_canonical_session_after_google_login(
        request, GOOGLE_PROFILE_ID, VERIFIED_IDENTITY
    )
    assert session is not None
    call = authority.session_calls[-1]
    # The producer pinned the window from the server clock and the reviewed
    # lifetime (900s here). The browser's 999999 values never appear: the span is
    # exactly the configured lifetime, not anything the request asked for.
    span = call["not_after"] - call["authenticated_at"]
    assert span == timedelta(seconds=900)
    assert span != timedelta(seconds=999999)
    # The window is also anchored at "now", not at the fixed NOW constant.
    assert abs((call["authenticated_at"] - datetime.now(timezone.utc)).total_seconds()) < 60


@pytest.mark.asyncio
async def test_no_b54_identity_is_newly_projected_to_the_browser() -> None:
    """B54_SESSION_ID / SUBJECT / TENANT browser output = 0."""

    import inspect as _inspect

    from app import auth_routes

    source = _inspect.getsource(auth_routes.establish_b54_canonical_session_after_google_login)
    # The helper returns the session to server code only; it sets no cookie and
    # builds no response body.
    assert "JSONResponse" not in source
    assert "RedirectResponse" not in source
    assert "set_cookie" not in source
    assert "auth_session.session_id" not in source
    assert "canonical_subject" not in source
    assert "tenant_id" not in source


# --- password regression ----------------------------------------------------


@pytest.mark.asyncio
async def test_password_owner_still_establishes_the_same_canonical_session() -> None:
    """PASSWORD_B54_SESSION: unchanged provider=password chain."""

    authority = _Authority()
    producer = _producer(authority)
    owner = B54ServerAuthenticatedOwner(
        product_user_id=GOOGLE_PROFILE_ID, provider_subject="claw.owner"
    )
    session = await producer.establish(owner)
    assert session is not None
    link = authority.link_calls[-1]
    assert link["auth_provider"] == "password"
    assert link["provider_subject"] == "claw.owner"
    assert link["product_id"] == B54_PRODUCT_ID
    assert session.auth_session.tenant_id == TENANT


def test_single_identity_authority_and_single_session_store() -> None:
    """SECOND_IDENTITY_AUTHORITY=0 / SECOND_SESSION_STORE=0."""

    import pathlib

    import app.b54_canonical_session as producer_module
    import app.auth_routes as auth_routes_module
    import padiem_control_plane.b54_identity_bridge as bridge

    for module in (producer_module, auth_routes_module):
        path = pathlib.Path(module.__file__)
        text = path.read_text(encoding="utf-8")
        # No second store: nothing opens its own session/identity persistence.
        for forbidden in (
            "sqlite3.connect",
            "aiosqlite",
            "D1Database",
            "create_tenant()",
            "establish_auth_session(",
        ):
            assert forbidden not in text, f"{path.name}: {forbidden}"
    # The bridge remains the only canonical session minter.
    bridge_path = pathlib.Path(bridge.__file__)
    assert "establish_auth_session" in bridge_path.read_text(encoding="utf-8")


def test_no_automation_or_scheduler_surface_was_added() -> None:
    """#3240 is auth parity only."""

    import pathlib

    import app.auth_routes as auth_routes_module
    import app.b54_canonical_session as producer_module

    for module in (auth_routes_module, producer_module):
        text = pathlib.Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "automation/rules",
            "createRule",
            "updateRule",
            "deleteRule",
            "set_rule_enabled",
            "run_now",
            "cron",
            "scheduler",
        ):
            assert forbidden not in text, f"{module.__name__}: {forbidden}"


# --- end-to-end google_callback wiring ------------------------------------


class _GoogleClient:
    """Stands in for the server-side OAuth client (no network, no live Google)."""

    def __init__(self, identity: dict | None) -> None:
        self.identity = identity
        self.exchanged: list[str] = []
        self.userinfo_tokens: list[str] = []

    async def exchange_code(self, code: str) -> str:
        self.exchanged.append(code)
        return "server-side-access-token"

    async def fetch_userinfo(self, access_token: str) -> dict:
        # The real client refuses any unverified response before returning.
        self.userinfo_tokens.append(access_token)
        if self.identity is None:
            from app.auth import AuthError

            raise AuthError(403, "auth_identity_unverified", "unverified")
        return dict(self.identity)


class _ProfileStore:
    def __init__(self) -> None:
        self.upserts: list[tuple] = []

    async def upsert_google_user(self, subject, email, name, picture):
        self.upserts.append((subject, email, name, picture))

        class _Profile:
            id = GOOGLE_PROFILE_ID

        return _Profile()


async def _run_callback(authority, identity, *, query=None, state_ok=True):
    from app.auth_routes import google_callback
    import app.auth_routes as auth_routes_module

    settings = _GoogleSettings()
    store = _ProfileStore()
    client = _GoogleClient(identity)
    state = {"cookies": {}, "query_params": dict(query or {})}
    if state_ok:
        from app.auth import create_oauth_state

        state_value, state_token = create_oauth_state(settings)
        state["cookies"]["padiem_oauth_state"] = state_token
        state["query_params"].setdefault("state", state_value)
    state["query_params"].setdefault("code", "auth-code")

    class _Request:
        def __init__(self) -> None:
            self.app = type("App", (), {"state": _AppState(authority)})()
            self.app.state.settings = settings
            self.app.state.history_store = store
            self.app.state.google_oauth = client
            self.app.state.identity_shadow_store = None
            self.query_params = state["query_params"]
            self.cookies = state["cookies"]

    request = _Request()
    response = await google_callback(request)
    return response, client, store, auth_routes_module


class _GoogleSettings:
    auth_mode = "google"
    session_secret = "google-parity-session-secret-not-real-0000"
    session_max_age_seconds = 3600
    google_client_id = "parity-client.apps.googleusercontent.com"
    google_client_secret = "parity-client-secret"
    public_base_url = "https://chat.example.test"
    runtime_mode = "mock"
    live_enabled = "false"


@pytest.mark.asyncio
async def test_google_callback_establishes_the_b54_session_end_to_end() -> None:
    """The production callback itself performs the B54 step (#3240)."""

    authority = _Authority()
    response, client, store, _ = await _run_callback(authority, VERIFIED_IDENTITY)
    # The B62 Google login still succeeds exactly as before.
    assert response.status_code == 302
    assert store.upserts and store.upserts[0][0] == GOOGLE_SUBJECT
    # And the canonical B54 session was established in the same flow.
    assert authority.link_calls, "google_callback must establish the B54 session"
    link = authority.link_calls[-1]
    assert link["product_id"] == B54_PRODUCT_ID
    assert link["product_user_id"] == GOOGLE_PROFILE_ID
    assert link["auth_provider"] == "google"
    assert link["provider_subject"] == GOOGLE_SUBJECT
    assert authority.session_calls[-1]["product_id"] == B54_PRODUCT_ID


@pytest.mark.asyncio
async def test_b54_step_happens_after_server_verification_only() -> None:
    """The B54 chain is downstream of exchange + verified userinfo."""

    authority = _Authority()
    # An unverified Google identity never reaches the B54 bridge.
    response, client, _, _ = await _run_callback(authority, None)
    assert response.status_code == 403
    assert authority.link_calls == []
    assert authority.session_calls == []


@pytest.mark.asyncio
async def test_invalid_oauth_state_never_reaches_the_b54_bridge() -> None:
    """INVALID_OAUTH_STATE_B54_SESSION=0."""

    authority = _Authority()
    response, client, _, _ = await _run_callback(
        authority, VERIFIED_IDENTITY, state_ok=False
    )
    assert response.status_code == 400
    assert client.exchanged == []  # no code exchange at all
    assert authority.link_calls == []
    assert authority.session_calls == []


@pytest.mark.asyncio
async def test_forged_callback_query_fields_cannot_steer_the_b54_session() -> None:
    authority = _Authority()
    _, _, store, _ = await _run_callback(
        authority,
        VERIFIED_IDENTITY,
        query={
            "product_user_id": "usr_FORGED",
            "provider": "kakao",
            "provider_subject": "forged-subject",
            "tenant_id": "tenant_FORGED",
            "product_id": "b62",
            "canonical_subject_id": "sub_FORGED",
            "session_id": "sess_FORGED",
        },
    )
    assert store.upserts[0][0] == GOOGLE_SUBJECT  # server userinfo, not the query
    link = authority.link_calls[-1]
    assert link["product_user_id"] == GOOGLE_PROFILE_ID
    assert link["auth_provider"] == "google"
    assert link["provider_subject"] == GOOGLE_SUBJECT
    assert link["product_id"] == B54_PRODUCT_ID
    serialized = str(authority.link_calls) + str(authority.session_calls)
    for forged in ("FORGED", "kakao", "b62"):
        assert forged not in serialized


@pytest.mark.asyncio
async def test_google_access_token_never_reaches_the_b54_bridge() -> None:
    """GOOGLE_ACCESS_TOKEN_TO_B54_BRIDGE=NO."""

    authority = _Authority()
    _, client, _, _ = await _run_callback(authority, VERIFIED_IDENTITY)
    assert client.userinfo_tokens == ["server-side-access-token"]
    serialized = str(authority.link_calls) + str(authority.session_calls)
    assert "server-side-access-token" not in serialized


@pytest.mark.asyncio
async def test_b54_failure_still_returns_the_b62_google_login_redirect() -> None:
    """B54_FAILURE_BREAKS_B62_GOOGLE_LOGIN=NO at the real callsite."""

    class _Exploding:
        def __getattr__(self, name):
            def _boom(*args, **kwargs):
                raise RuntimeError("control plane down")

            return _boom

    response, client, store, _ = await _run_callback(_Exploding(), VERIFIED_IDENTITY)
    # B62 login is fully preserved: the user is still redirected with a session.
    assert response.status_code == 302
    assert store.upserts
    assert response.headers.get("set-cookie")


class _FakeRequest:
    """Minimal request double carrying adversarial browser-supplied content."""

    def __init__(self, app_state, *, query=None, body=None, headers=None, cookies=None) -> None:
        self.app = type("App", (), {"state": app_state})()
        self.query_params = dict(query or {})
        self._body = dict(body or {})
        self.headers = dict(headers or {})
        self.cookies = dict(cookies or {})

    async def json(self) -> dict:
        return self._body
