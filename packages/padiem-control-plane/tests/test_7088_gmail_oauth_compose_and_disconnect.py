"""#7088 Control-Plane 층 시험: Gmail (readonly, compose) 확장·하위 호환·해제 RPC 고정."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from google_oauth_access_lease import (
    GoogleOAuthAccessLease,
    GoogleOAuthAccessLeaseRuntime,
)
from google_oauth_durable_store import (
    GMAIL_COMPOSE_SCOPE,
    GMAIL_READONLY_SCOPE,
    CloudflareDurableGoogleOAuthStore,
    DurableGoogleOAuthCredential,
)
from google_oauth_ingress_runtime import (
    GoogleOAuthIngressConfig,
    GoogleOAuthIngressRuntime,
    GoogleOAuthSessionPayload,
)
from identity_connector_ticket import (
    CONNECT_TICKET_TTL_SECONDS,
    CanonicalConnectorContextStore,
    GoogleConnectTicketIssuer,
    decode_connect_ticket_key,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.connector_connect_ticket import (
    ConnectorConnectTicketAuthority,
)
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)
from test_google_oauth_ingress_runtime import TokenSource as IngressTokenSource
from test_google_oauth_workspace_connector_state import (
    SEALED_REFRESH,
    _Storage,
    _durable_object,
)
from test_identity_connector_ticket import FakeStorage, TokenSource as IdentityTokenSource
from test_internal_rpc_ingress import (
    ADAPTER_ROOT,
    SECRET,
    _Namespace,
    _Request,
    _Stub,
    _env,
    _load_worker,
    _signed_request,
)

NOW = datetime(2026, 11, 11, 9, 0, tzinfo=timezone.utc)
KEY_TEXT = "A" * 43
KEY_BYTES = decode_connect_ticket_key(KEY_TEXT)
WORKSPACE_A = "workspace.7088.owner.a"
WORKSPACE_B = "workspace.7088.owner.b"


class _FakeSealer:
    async def seal_text(self, *, plaintext: str, context) -> str:
        return SEALED_REFRESH

    async def unseal_text(self, *, envelope: str, context) -> str:
        assert envelope == SEALED_REFRESH
        return self._last_plaintext

    def __init__(self, initial_plaintext: str = "long-lived-refresh") -> None:
        self._last_plaintext = initial_plaintext


class _SessionEchoSealer:
    def __init__(self) -> None:
        self.payloads: dict[str, str] = {}
        self.counter = 0

    async def seal_text(self, *, plaintext: str, context) -> str:
        self.counter += 1
        envelope = f"sealed:v1:{'B' * 30}{self.counter:02d}"
        self.payloads[envelope] = plaintext
        return envelope

    async def unseal_text(self, *, envelope: str, context) -> str:
        return self.payloads[envelope]


class _FakeTokenExchange:
    def __init__(self, granted_scope: str) -> None:
        self.granted_scope = granted_scope

    async def exchange_authorization_code(self, **kwargs):
        return {
            "access_token": "short-lived-access",
            "refresh_token": "long-lived-refresh",
            "token_type": "Bearer",
            "scope": self.granted_scope,
            "refresh_token_expires_in": 86_400,
        }


class _FakeRefreshPort:
    def __init__(self, scope: str) -> None:
        self.scope = scope

    async def refresh_access_token(self, **kwargs):
        return {
            "access_token": "leased-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": self.scope,
        }

    def safe_dict(self):
        return {"test_port": True}


def _session() -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id="sess_7088",
        product_id="b62",
        subject=CanonicalSubjectRef(SubjectType.USER, "usr_7088_subject"),
        issued_at=NOW - timedelta(minutes=5),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )


def _config() -> GoogleOAuthIngressConfig:
    return GoogleOAuthIngressConfig(
        client_id="client-7088.apps.googleusercontent.com",
        client_secret="placeholder-client-secret",
        redirect_uri="https://oauth.example.test/v1/google/callback",
    )


def test_7088_five_cp_surfaces_issue_save_and_lease_readonly_plus_compose() -> None:
    ticket_authority = ConnectorConnectTicketAuthority(signing_key=KEY_BYTES)
    source = IdentityTokenSource()
    context_store = CanonicalConnectorContextStore(FakeStorage(), random_hex=source)
    issuer = GoogleConnectTicketIssuer(
        context_store=context_store,
        signing_key=KEY_BYTES,
        clock=lambda: NOW,
        random_hex=source,
    )
    auth_session = _session()
    receipt = issuer.issue(auth_session=auth_session, connector_id="gmail")
    claims = ticket_authority.verify(
        token=receipt.connect_ticket,
        now=NOW,
        expected_connector_id="gmail",
        auth_session=auth_session,
    )
    assert claims.scopes == (GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE)
    assert receipt.expires_at == NOW + timedelta(seconds=CONNECT_TICKET_TTL_SECONDS)

    storage = _Storage()
    store = CloudflareDurableGoogleOAuthStore(storage)
    sealer = _SessionEchoSealer()
    ingress = GoogleOAuthIngressRuntime(
        store=store,
        sealer=sealer,
        ticket_authority=ticket_authority,
        config=_config(),
        token_exchange=_FakeTokenExchange(f"{GMAIL_COMPOSE_SCOPE} {GMAIL_READONLY_SCOPE}"),
        clock=lambda: NOW,
        random_token=IngressTokenSource(),
    )

    started = asyncio.run(ingress.begin(connect_ticket=receipt.connect_ticket))
    parsed_url = urlparse(started.authorization_url)
    query = parse_qs(parsed_url.query)
    assert set(query["scope"][0].split()) == {GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE}
    state_ref = query["state"][0]

    connected = asyncio.run(
        ingress.complete_callback(
            state_ref=state_ref,
            authorization_code="code_7088_valid_12345678",
            provider_error=None,
        )
    )
    assert connected.scopes == (GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE)

    loaded = store.load_active_credential(binding_ref=connected.binding_ref, now=NOW)
    assert loaded.scopes == (GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE)

    lease_runtime = GoogleOAuthAccessLeaseRuntime(
        store=store,
        sealer=sealer,
        config=_config(),
        refresh_port=_FakeRefreshPort(f"{GMAIL_READONLY_SCOPE} {GMAIL_COMPOSE_SCOPE}"),
        clock=lambda: NOW,
    )
    lease = asyncio.run(
        lease_runtime.issue(binding_ref=connected.binding_ref, connector_id="gmail")
    )
    assert lease.scopes == (GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE)


def test_7088_existing_readonly_only_gmail_rows_keep_working_across_cp_surfaces() -> None:
    ticket_authority = ConnectorConnectTicketAuthority(signing_key=KEY_BYTES)
    auth_session = _session()
    legacy_ticket = ticket_authority.issue(
        ticket_id="tkt_legacy_7088",
        connector_id="gmail",
        auth_session=auth_session,
        actor_ref="actor_7088",
        account_ref="account_7088",
        workspace_ref=WORKSPACE_A,
        scopes=(GMAIL_READONLY_SCOPE,),
        now=NOW,
        ttl_seconds=120,
    )
    verified = ticket_authority.verify(
        token=legacy_ticket,
        now=NOW,
        expected_connector_id="gmail",
        auth_session=auth_session,
    )
    assert verified.scopes == (GMAIL_READONLY_SCOPE,)

    session_payload = GoogleOAuthSessionPayload(
        state_ref="state_legacy_7088",
        connector_id="gmail",
        session_id=auth_session.session_id,
        product_id="b62",
        subject_type="user",
        subject_id="usr_7088_subject",
        actor_ref="actor_7088",
        account_ref="account_7088",
        workspace_ref=WORKSPACE_A,
        scopes=(GMAIL_READONLY_SCOPE,),
        code_verifier="v" * 48,
        redirect_uri="https://oauth.example.test/v1/google/callback",
        created_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
    )
    assert session_payload.scopes == (GMAIL_READONLY_SCOPE,)

    storage = _Storage()
    store = CloudflareDurableGoogleOAuthStore(storage)
    sealer = _FakeSealer("legacy-refresh")
    store.save_credential(
        DurableGoogleOAuthCredential(
            binding_ref="binding_7088_legacy_ro",
            connector_id="gmail",
            actor_ref="actor_7088",
            account_ref="account_7088",
            workspace_ref=WORKSPACE_A,
            scopes=(GMAIL_READONLY_SCOPE,),
            sealed_refresh_token=SEALED_REFRESH,
            issued_at=NOW,
        )
    )
    loaded = store.load_active_credential(binding_ref="binding_7088_legacy_ro", now=NOW)
    assert loaded.scopes == (GMAIL_READONLY_SCOPE,)

    lease_runtime = GoogleOAuthAccessLeaseRuntime(
        store=store,
        sealer=sealer,
        config=_config(),
        refresh_port=_FakeRefreshPort(GMAIL_READONLY_SCOPE),
        clock=lambda: NOW,
    )
    lease = asyncio.run(
        lease_runtime.issue(binding_ref="binding_7088_legacy_ro", connector_id="gmail")
    )
    assert lease.scopes == (GMAIL_READONLY_SCOPE,)


@pytest.mark.parametrize(
    "forbidden_scopes",
    [
        ("https://www.googleapis.com/auth/gmail.send",),
        (GMAIL_READONLY_SCOPE, "https://www.googleapis.com/auth/gmail.send"),
        (GMAIL_COMPOSE_SCOPE,),
        (GMAIL_READONLY_SCOPE, "https://www.googleapis.com/auth/gmail.modify"),
        ("https://mail.google.com/",),
    ],
)
def test_7088_send_modify_and_compose_without_readonly_are_rejected(
    forbidden_scopes: tuple[str, ...],
) -> None:
    ticket_authority = ConnectorConnectTicketAuthority(signing_key=KEY_BYTES)
    with pytest.raises(ControlPlaneContractError):
        ticket_authority.issue(
            ticket_id="tkt_bad_7088",
            connector_id="gmail",
            auth_session=_session(),
            actor_ref="actor_7088",
            account_ref="account_7088",
            workspace_ref=WORKSPACE_A,
            scopes=forbidden_scopes,
            now=NOW,
            ttl_seconds=120,
        )
    with pytest.raises(ControlPlaneContractError):
        DurableGoogleOAuthCredential(
            binding_ref="binding_bad_7088",
            connector_id="gmail",
            actor_ref="actor_7088",
            account_ref="account_7088",
            workspace_ref=WORKSPACE_A,
            scopes=forbidden_scopes,
            sealed_refresh_token=SEALED_REFRESH,
            issued_at=NOW,
        )
    with pytest.raises(ControlPlaneContractError):
        GoogleOAuthAccessLease(
            access_token="tok_bad",
            binding_ref="binding_bad_7088",
            connector_id="gmail",
            actor_ref="actor_7088",
            account_ref="account_7088",
            workspace_ref=WORKSPACE_A,
            scopes=forbidden_scopes,
            expires_at=NOW + timedelta(hours=1),
        )


def test_7088_disconnect_gmail_revokes_only_target_workspace_gmail_and_allows_signed_ingress() -> None:
    storage, durable = _durable_object()
    store = CloudflareDurableGoogleOAuthStore(storage)
    store.save_credential(
        DurableGoogleOAuthCredential(
            binding_ref="gmail.a.readonly",
            connector_id="gmail",
            actor_ref="actor_a",
            account_ref="acct_a",
            workspace_ref=WORKSPACE_A,
            scopes=(GMAIL_READONLY_SCOPE,),
            sealed_refresh_token=SEALED_REFRESH,
            issued_at=NOW - timedelta(minutes=10),
        )
    )
    store.save_credential(
        DurableGoogleOAuthCredential(
            binding_ref="gmail.a.compose",
            connector_id="gmail",
            actor_ref="actor_a",
            account_ref="acct_a",
            workspace_ref=WORKSPACE_A,
            scopes=(GMAIL_READONLY_SCOPE, GMAIL_COMPOSE_SCOPE),
            sealed_refresh_token=SEALED_REFRESH,
            issued_at=NOW - timedelta(minutes=5),
        )
    )
    store.save_credential(
        DurableGoogleOAuthCredential(
            binding_ref="gmail.b.readonly",
            connector_id="gmail",
            actor_ref="actor_b",
            account_ref="acct_b",
            workspace_ref=WORKSPACE_B,
            scopes=(GMAIL_READONLY_SCOPE,),
            sealed_refresh_token=SEALED_REFRESH,
            issued_at=NOW - timedelta(minutes=5),
        )
    )

    for bad_payload in (
        {},
        {"workspace_ref": WORKSPACE_A, "binding_ref": "gmail.a.readonly"},
        {"workspace_ref": WORKSPACE_A, "connector_id": "google-drive"},
    ):
        denied = asyncio.run(durable.disconnect_gmail(bad_payload))
        assert denied["ok"] is False

    revoked = asyncio.run(durable.disconnect_gmail({"workspace_ref": WORKSPACE_A}))
    assert revoked == {"ok": True, "revoked": 2}
    assert asyncio.run(durable.disconnect_gmail({"workspace_ref": WORKSPACE_A})) == {
        "ok": True,
        "revoked": 0,
    }

    state_a = {
        row.connector_id: row
        for row in store.list_workspace_connector_state(workspace_ref=WORKSPACE_A, now=NOW)
    }
    state_b = {
        row.connector_id: row
        for row in store.list_workspace_connector_state(workspace_ref=WORKSPACE_B, now=NOW)
    }
    assert state_a["gmail"].state == "not_connected"
    assert state_b["gmail"].state == "connected"

    # Signed HTTPS /internal/rpc/disconnect_gmail ingress check (COM2 path)
    module = _load_worker(ADAPTER_ROOT / "google_oauth_worker.py", "google_oauth_worker_7088_test")
    stub = _Stub({"ok": True, "revoked": 1})
    worker = module.Default(
        env=_env(
            GOOGLE_OAUTH_STATE=_Namespace(stub),
            PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET=SECRET,
        )
    )
    ts = int(__import__("time").time())
    unsigned = _Request("https://state.invalid/internal/rpc/disconnect_gmail", headers={}, body=b"{}")
    assert asyncio.run(worker.fetch(unsigned)).status == 403
    signed = _signed_request(
        method="disconnect_gmail",
        body=b'{"workspace_ref":"ws_7088"}',
        at=ts,
    )
    assert asyncio.run(worker.fetch(signed)).status == 200
    assert stub.calls[-1] == ("disconnect_gmail", {"workspace_ref": "ws_7088"})
