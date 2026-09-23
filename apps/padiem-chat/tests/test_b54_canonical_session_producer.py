"""B54 canonical session producer wired to the real server auth boundary (#2964).

The chain under test is the deployed one:

```text
POST /api/auth/password/login  (PBKDF2 verify against the D1 credential row)
  -> PasswordCredential                       (server row)
  -> B54ServerAuthenticatedOwner              (columns of that row only)
  -> TrustedB54ServerAuthEvidence             (provider/lifetime fixed by the module)
  -> bridge_trusted_b54_server_auth()         (canonical Control Plane authority)
  -> B54BridgedIdentitySession                (product=b54-padiem-claw, tenant-bearing)
```

Proves:
  B54_REAL_SERVER_PRODUCER_PRESENT   = YES
  BROWSER_PRODUCT_USER_AUTHORITY     = 0
  BROWSER_PROVIDER_SUBJECT_AUTHORITY = 0
  BROWSER_SUBJECT_AUTHORITY          = 0
  BROWSER_TENANT_AUTHORITY           = 0
  BROWSER_PRODUCT_AUTHORITY          = 0
  B54_SESSION_PRODUCT_ID             = b54-padiem-claw
  B54_SESSION_TENANT_PRESENT         = YES
  B54_TENANT_SERVER_DERIVED          = YES
  B62_BEHAVIOR_PRESERVED             = YES
  SECOND_IDENTITY_AUTHORITY / SECOND_SESSION_STORE = 0
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import inspect
import pathlib

import httpx
import pytest

from padiem_control_plane import (
    AuthSessionSnapshot,
    AuthSessionState,
    IdentityLinkState,
    ProductIdentityLink,
)
from padiem_control_plane.b54_identity_bridge import (
    B54_PRODUCT_ID,
    B54IdentityBridgeError,
    TrustedB54ServerAuthEvidence,
    bridge_trusted_b54_server_auth,
)

from app.auth import SESSION_COOKIE
from app.auth_routes import establish_b54_canonical_session_after_login
from app.b54_canonical_session import (
    B54_SERVER_AUTH_PROVIDER,
    B54CanonicalSessionProducer,
    B54ServerAuthenticatedOwner,
)
from app.config import Settings
from app.history import PasswordCredential, UserProfile
from app.main import create_app
from app.password_auth import hash_password

SESSION_SECRET = "b54-canonical-session-secret-not-a-real-credential-0001"
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
TENANT = "tenant_0123456789abcdef0123456789abcdef"
PASSWORD = "correct horse battery staple"


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


class MemoryStore:
    """Server-side rows: the only source the producer is allowed to read identity from."""

    def __init__(self) -> None:
        self.users: dict[str, UserProfile] = {}
        self.credentials: dict[str, PasswordCredential] = {}

    def seed(self, *, username: str, email: str, user_id: str) -> None:
        profile = UserProfile(user_id, email, "Owner Test", "")
        self.users[user_id] = profile
        self.credentials[username] = PasswordCredential(
            user=profile,
            username=username,
            password_hash=hash_password(PASSWORD),
            failed_attempts=0,
            locked_until=None,
        )

    async def register_password_user(self, username, email, name, password_hash):
        raise AssertionError("registration is not the boundary under test")

    async def find_password_credential(self, identifier):
        if "@" in identifier:
            for cred in self.credentials.values():
                if cred.user.email.lower() == identifier.lower():
                    return cred
            return None
        return self.credentials.get(identifier.lower())

    async def record_password_failure(self, user_id, failed_attempts, locked_until):
        return None

    async def reset_password_failures(self, user_id):
        return None

    async def get_user(self, user_id):
        return self.users.get(user_id)


class ShadowStore:
    def __init__(self) -> None:
        self.saved: list = []

    async def save_projection(self, bridged) -> None:
        self.saved.append(bridged)


class CanonicalAuthority:
    """One identity/session authority for both products, keyed by product_id.

    Mirrors the deployed private Service Binding adapter: it is the only subject,
    tenant, and session minter in these tests, so a call it did not receive cannot
    produce a session anywhere else.
    """

    def __init__(self) -> None:
        self.link_calls: list[dict] = []
        self.session_calls: list[dict] = []
        self.membership_reads: list[str] = []
        self.tenants_created = 0
        self.assignments: list[tuple[str, str]] = []

    def _subject_id(self, product_id: str, product_user_id: str) -> str:
        return f"subject:{product_id}:{product_user_id}"

    def resolve_or_create_product_link(self, **kwargs):
        self.link_calls.append(kwargs)
        return ProductIdentityLink(
            product_id=kwargs["product_id"],
            product_user_id=kwargs["product_user_id"],
            canonical_subject_id=self._subject_id(
                kwargs["product_id"], kwargs["product_user_id"]
            ),
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


# ---------------------------------------------------------------------------
# The producer exists and its only input shape is a server credential row
# ---------------------------------------------------------------------------


def test_owner_comes_from_the_server_row_and_refuses_any_other_shape():
    """The only factory reads the credential row; a non-server id never validates.

    ``usr_`` plus the bounded length is the server-minted product user grammar used
    by every canonical bridge in this app, so a browser-chosen identifier cannot
    reach the B54 evidence even if a caller tried to build the owner by hand.
    """
    credential = PasswordCredential(
        user=UserProfile("usr_serverowner", "o@example.test", "Owner", ""),
        username="server.owner",
        password_hash="pbkdf2_sha512$x",
        failed_attempts=0,
        locked_until=None,
    )

    owner = B54ServerAuthenticatedOwner.from_password_credential(credential)

    assert owner.product_user_id == "usr_serverowner"
    assert owner.provider_subject == "server.owner"
    with pytest.raises(ValueError):
        B54ServerAuthenticatedOwner.from_password_credential(  # type: ignore[arg-type]
            {"product_user_id": "usr_browser", "username": "browser"}
        )
    with pytest.raises(ValueError):
        B54ServerAuthenticatedOwner(product_user_id="browser-controlled", provider_subject="x")


def test_producer_pins_provider_and_derives_the_lifetime_server_side():
    """No caller argument can choose the provider or widen the session window."""
    seen: list = []

    class Recording:
        def resolve_or_create_product_link(self, **kwargs):
            return ProductIdentityLink(
                product_id=B54_PRODUCT_ID,
                product_user_id=kwargs["product_user_id"],
                canonical_subject_id="subject:b54:usr_pin",
                state=IdentityLinkState.ACTIVE,
            )

        def resolve_active_memberships(self, *, canonical_subject_id: str):
            return (TENANT,)

        def establish_auth_session(self, **kwargs):
            seen.append(kwargs)
            return AuthSessionSnapshot(
                session_id="sess_pinned",
                product_id=kwargs["product_id"],
                subject=kwargs["subject"],
                issued_at=kwargs["authenticated_at"],
                expires_at=kwargs["not_after"],
                tenant_id=TENANT,
            )

    producer = B54CanonicalSessionProducer(
        authority=Recording(),
        session_max_age_seconds=3600,
        clock=lambda: NOW,
    )
    owner = B54ServerAuthenticatedOwner(
        product_user_id="usr_pin", provider_subject="pinned.owner"
    )
    bridged = asyncio.run(producer.establish(owner))

    kwargs = seen[0]
    assert kwargs["product_id"] == B54_PRODUCT_ID
    assert kwargs["subject"].subject_id == "subject:b54:usr_pin"
    assert kwargs["authenticated_at"] == NOW
    assert kwargs["not_after"] == NOW + timedelta(seconds=3600)
    assert bridged.auth_session.session_id == "sess_pinned"
    assert B54_SERVER_AUTH_PROVIDER == "password"


def test_producer_refuses_a_missing_authority_without_minting_anything():
    producer = B54CanonicalSessionProducer(
        authority=None, session_max_age_seconds=3600, clock=lambda: NOW
    )
    owner = B54ServerAuthenticatedOwner(product_user_id="usr_none", provider_subject="n")
    with pytest.raises(B54IdentityBridgeError) as exc:
        asyncio.run(producer.establish(owner))
    assert exc.value.code == "b54_control_plane_identity_unavailable"


def test_producer_rejects_an_owner_that_was_never_server_authenticated():
    producer = B54CanonicalSessionProducer(
        authority=CanonicalAuthority(), session_max_age_seconds=3600, clock=lambda: NOW
    )
    with pytest.raises(ValueError):
        asyncio.run(producer.establish("usr_browser_supplied"))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Route-level proof: browser content cannot name any identity field
# ---------------------------------------------------------------------------


FORGED_BODY = {
    "identifier": "claw.owner",
    "password": PASSWORD,
    "product_user_id": "usr_browser_chosen",
    "user_id": "usr_browser_chosen",
    "provider_subject": "browser-subject",
    "subject_id": "subject:browser",
    "canonical_subject_id": "subject:browser",
    "tenant_id": "tenant_browser_chosen",
    "product_id": "b62",
    "app_id": "b62",
    "session_id": "sess_browser_chosen",
    "auth_session_id": "sess_browser_chosen",
    "workspace_id": "workspace_browser_chosen",
}


async def _login(store: MemoryStore, authority: CanonicalAuthority) -> httpx.Response:
    app = create_app(
        password_settings(),
        history_store=store,
        control_plane_identity_authority=authority,
        identity_shadow_store=ShadowStore(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
        cookies={SESSION_COOKIE: "browser-forged-session-token"},
    ) as client:
        return await client.post("/api/auth/password/login", json=FORGED_BODY)


@pytest.mark.asyncio
async def test_login_establishes_b54_session_from_server_rows_only():
    store = MemoryStore()
    store.seed(username="claw.owner", email="claw@example.test", user_id="usr_server_owner")
    authority = CanonicalAuthority()

    response = await _login(store, authority)

    assert response.status_code == 200
    b54_calls = [c for c in authority.link_calls if c["product_id"] == B54_PRODUCT_ID]
    assert len(b54_calls) == 1, "the producer must run on the real server auth boundary"
    # Every forged value is absent: the row the server read is the only input.
    assert b54_calls[0]["product_user_id"] == "usr_server_owner"
    assert b54_calls[0]["provider_subject"] == "claw.owner"
    assert b54_calls[0]["auth_provider"] == "password"
    for forged in (
        "usr_browser_chosen",
        "browser-subject",
        "subject:browser",
        "tenant_browser_chosen",
        "workspace_browser_chosen",
        "sess_browser_chosen",
    ):
        assert forged not in repr(authority.link_calls)
        assert forged not in repr(authority.session_calls)
        assert forged not in repr(authority.membership_reads)


@pytest.mark.asyncio
async def test_b54_session_carries_the_server_derived_tenant_and_b54_product():
    store = MemoryStore()
    store.seed(username="claw.owner", email="claw@example.test", user_id="usr_server_owner")
    authority = CanonicalAuthority()

    await _login(store, authority)

    sessions = [c for c in authority.session_calls if c["product_id"] == B54_PRODUCT_ID]
    assert len(sessions) == 1
    subject = sessions[0]["subject"]
    assert subject.subject_id == f"subject:{B54_PRODUCT_ID}:usr_server_owner"
    # The subject and tenant were resolved by the authority, never supplied.
    assert f"subject:{B54_PRODUCT_ID}:usr_server_owner" in authority.membership_reads
    assert subject.subject_type.value == "user"


@pytest.mark.asyncio
async def test_login_never_projects_canonical_identity_to_the_browser():
    store = MemoryStore()
    store.seed(username="claw.owner", email="claw@example.test", user_id="usr_server_owner")
    authority = CanonicalAuthority()

    response = await _login(store, authority)

    body = response.text
    assert response.headers["content-type"].startswith("application/json")
    for secret in (
        f"subject:{B54_PRODUCT_ID}:usr_server_owner",
        TENANT,
        "sess_",
        "claw.owner",
    ):
        assert secret not in body
    assert "user" in response.json()


@pytest.mark.asyncio
async def test_b62_login_behavior_is_unchanged_by_the_b54_producer():
    store = MemoryStore()
    store.seed(username="claw.owner", email="claw@example.test", user_id="usr_server_owner")
    authority = CanonicalAuthority()
    shadow = ShadowStore()
    app = create_app(
        password_settings(),
        history_store=store,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test"
    ) as client:
        response = await client.post(
            "/api/auth/password/login",
            json={
                "identifier": "claw.owner",
                "password": PASSWORD,
            },
        )
        status = await client.get("/api/auth/status")

    assert response.status_code == 200
    assert SESSION_COOKIE in response.headers["set-cookie"]
    assert status.json()["authenticated"] is True
    # The B62 shadow write still happens, with the B62 product and tenant policy.
    assert [c["product_id"] for c in authority.link_calls] == ["b62", B54_PRODUCT_ID]
    assert len(shadow.saved) == 1


@pytest.mark.asyncio
async def test_b54_authority_failure_does_not_break_the_b62_login():
    store = MemoryStore()
    store.seed(username="claw.owner", email="claw@example.test", user_id="usr_server_owner")

    class UnboundAuthority(CanonicalAuthority):
        def resolve_or_create_product_link(self, **kwargs):
            if kwargs["product_id"] == B54_PRODUCT_ID:
                raise RuntimeError("b54 product not authorised yet")
            return super().resolve_or_create_product_link(**kwargs)

    authority = UnboundAuthority()
    app = create_app(
        password_settings(),
        history_store=store,
        control_plane_identity_authority=authority,
        identity_shadow_store=ShadowStore(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test"
    ) as client:
        response = await client.post(
            "/api/auth/password/login",
            json={"identifier": "claw.owner", "password": PASSWORD},
        )

    assert response.status_code == 200
    assert [c["product_id"] for c in authority.link_calls] == ["b62"]


# ---------------------------------------------------------------------------
# Google login is not a B54 server authority, and one authority stays in place
# ---------------------------------------------------------------------------


def test_google_provider_is_not_accepted_as_b54_server_evidence():
    """Google is a B62 provider only, so the Google login cannot feed a B54 session."""
    with pytest.raises(ValueError):
        TrustedB54ServerAuthEvidence(
            product_user_id="usr_google_owner",
            provider="google",
            provider_subject="google-subject",
            authenticated_at=NOW,
            expires_at=NOW + timedelta(hours=1),
        )


@pytest.mark.asyncio
async def test_b54_reuses_the_single_control_plane_authority():
    """SECOND_IDENTITY_AUTHORITY=0: B54 reads the same bound authority B62 uses."""
    store = MemoryStore()
    store.seed(username="claw.owner", email="claw@example.test", user_id="usr_server_owner")
    authority = CanonicalAuthority()
    app = create_app(
        password_settings(),
        history_store=store,
        control_plane_identity_authority=authority,
        identity_shadow_store=ShadowStore(),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test"
    ) as client:
        await client.post(
            "/api/auth/password/login",
            json={"identifier": "claw.owner", "password": PASSWORD},
        )

    assert app.state.control_plane_identity_authority is authority
    # Both product scopes resolved through that one object, and nothing else did.
    assert len(authority.link_calls) == 2
    assert len(authority.session_calls) == 2


def test_b54_added_no_second_session_store():
    """The canonical session table has exactly one DDL owner in production source."""
    root = pathlib.Path(__file__).resolve().parents[3]
    production = [
        path
        for path in list(root.glob("packages/**/*.py")) + list(root.glob("apps/**/*.py"))
        if "/tests/" not in path.as_posix() and "/scripts/" not in path.as_posix()
    ]
    ddl_owners = [
        path.relative_to(root).as_posix()
        for path in production
        if "canonical_auth_session (" in path.read_text(encoding="utf-8", errors="ignore")
        and "CREATE TABLE" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert ddl_owners == ["packages/padiem-control-plane/identity_authority_durable.py"]


def test_callsite_signature_exposes_no_identity_lever():
    """The production callsite takes a Request and the server credential row: nothing else."""
    parameters = list(
        inspect.signature(establish_b54_canonical_session_after_login).parameters
    )
    assert parameters == ["request", "credential"]
    assert set(inspect.signature(bridge_trusted_b54_server_auth).parameters) == {
        "authority",
        "evidence",
        "now",
    }
