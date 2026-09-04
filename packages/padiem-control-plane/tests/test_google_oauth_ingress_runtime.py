from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import sqlite3
from urllib.parse import parse_qs, urlsplit

import pytest

from google_oauth_durable_store import (
    GMAIL_READONLY_SCOPE,
    CloudflareDurableGoogleOAuthStore,
)
from google_oauth_ingress_runtime import (
    GoogleOAuthIngressConfig,
    GoogleOAuthIngressRuntime,
)
from google_oauth_webcrypto_sealer import (
    AES_GCM_IV_BYTES,
    GoogleOAuthSealContext,
    GoogleOAuthSealPurpose,
    GoogleOAuthWebCryptoSealer,
)
from padiem_control_plane.auth_sessions import AuthSessionSnapshot, AuthSessionState
from padiem_control_plane.connector_connect_ticket import ConnectorConnectTicketAuthority
from padiem_control_plane.contracts import (
    CanonicalSubjectRef,
    ControlPlaneContractError,
    SubjectType,
)


NOW = datetime(2026, 9, 4, 11, 0, tzinfo=timezone.utc)
TICKET_KEY = b"T" * 32
SEAL_KEY_BYTES = b"S" * 32
SEAL_KEY = base64.urlsafe_b64encode(SEAL_KEY_BYTES).decode("ascii").rstrip("=")
CLIENT_SECRET = "client-secret-sensitive"
AUTH_CODE = "authorization-code-sensitive"
ACCESS_TOKEN = "access-token-sensitive"
REFRESH_TOKEN = "refresh-token-sensitive"
PKCE_VERIFIER = "V" * 64


class FakeCursor:
    def __init__(self, *, rows: list[dict], rows_written: int) -> None:
        self._rows = rows
        self.rowsWritten = rows_written

    def toArray(self) -> list[dict]:
        return list(self._rows)


class FakeSql:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def exec(self, statement: str, *args):
        cursor = self._connection.execute(statement, args)
        if statement.lstrip().upper().startswith("SELECT"):
            columns = [item[0] for item in cursor.description or ()]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
            return FakeCursor(rows=rows, rows_written=0)
        rows_written = cursor.rowcount if cursor.rowcount >= 0 else 0
        return FakeCursor(rows=[], rows_written=rows_written)


class FakeDurableStorage:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = FakeSql(self.connection)

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except Exception:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result

    def count(self, table: str) -> int:
        return self.connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def all_text(self) -> str:
        chunks: list[str] = []
        for table in (
            "google_oauth_connect_ticket_use",
            "google_oauth_authorization_state",
            "google_oauth_refresh_credential",
        ):
            for row in self.connection.execute(f"SELECT * FROM {table}").fetchall():
                chunks.extend("" if value is None else str(value) for value in row)
        return "\n".join(chunks)


class DeterministicAeadTestPort:
    def random_bytes(self, length: int) -> bytes:
        assert length == AES_GCM_IV_BYTES
        return bytes(range(1, length + 1))

    async def encrypt(self, *, key: bytes, iv: bytes, plaintext: bytes, additional_data: bytes) -> bytes:
        tag = hashlib.sha256(key + iv + additional_data + plaintext).digest()[:16]
        return plaintext[::-1] + tag

    async def decrypt(self, *, key: bytes, iv: bytes, ciphertext: bytes, additional_data: bytes) -> bytes:
        reversed_plaintext, tag = ciphertext[:-16], ciphertext[-16:]
        plaintext = reversed_plaintext[::-1]
        expected = hashlib.sha256(key + iv + additional_data + plaintext).digest()[:16]
        if not hmac.compare_digest(tag, expected):
            raise ValueError("integrity failure")
        return plaintext

    def safe_dict(self):
        return {"test_port": True, "production_crypto": False}


class FakeTokenExchange:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload or {
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "token_type": "Bearer",
            "scope": GMAIL_READONLY_SCOPE,
        }
        self.error = error
        self.calls: list[dict] = []

    async def exchange_authorization_code(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return dict(self.payload)

    def safe_dict(self):
        return {"test_port": True, "raw_token_public": False}


class TokenSource:
    def __init__(self) -> None:
        self.counts: dict[int, int] = {}

    def __call__(self, size: int) -> str:
        self.counts[size] = self.counts.get(size, 0) + 1
        if size == 32:
            return f"state_{self.counts[size]}"
        if size == 64:
            return PKCE_VERIFIER
        if size == 24:
            return f"bindingtoken_{self.counts[size]}"
        raise AssertionError(f"unexpected token size: {size}")


def auth_session() -> AuthSessionSnapshot:
    return AuthSessionSnapshot(
        session_id="auth_session_1",
        product_id="b54",
        subject=CanonicalSubjectRef(SubjectType.USER, "subject 1 한글"),
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
        state=AuthSessionState.ACTIVE,
        revision=1,
    )


def ticket(authority: ConnectorConnectTicketAuthority, *, ticket_id: str = "ticket_1") -> str:
    return authority.issue(
        auth_session=auth_session(),
        ticket_id=ticket_id,
        connector_id="gmail",
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
        scopes=(GMAIL_READONLY_SCOPE,),
        now=NOW,
        ttl_seconds=180,
    )


def fixture(*, exchange: FakeTokenExchange | None = None):
    storage = FakeDurableStorage()
    durable_store = CloudflareDurableGoogleOAuthStore(storage)
    seal_port = DeterministicAeadTestPort()
    sealer = GoogleOAuthWebCryptoSealer(
        key_secret_b64url=SEAL_KEY,
        crypto_port=seal_port,
    )
    authority = ConnectorConnectTicketAuthority(signing_key=TICKET_KEY)
    token_source = TokenSource()
    token_exchange = exchange or FakeTokenExchange()
    runtime = GoogleOAuthIngressRuntime(
        store=durable_store,
        sealer=sealer,
        ticket_authority=authority,
        config=GoogleOAuthIngressConfig(
            client_id="client-id-public",
            client_secret=CLIENT_SECRET,
            redirect_uri="https://oauth.example.invalid/v1/google/callback",
        ),
        token_exchange=token_exchange,
        clock=lambda: NOW,
        random_token=token_source,
    )
    return runtime, storage, durable_store, sealer, authority, token_exchange


def begin(runtime: GoogleOAuthIngressRuntime, authority: ConnectorConnectTicketAuthority, *, ticket_id="ticket_1"):
    raw_ticket = ticket(authority, ticket_id=ticket_id)
    receipt = asyncio.run(runtime.begin(connect_ticket=raw_ticket))
    return raw_ticket, receipt


def test_signed_connect_ticket_drives_pkce_state_without_browser_identity_authority():
    runtime, storage, _, _, authority, _ = fixture()
    raw_ticket, receipt = begin(runtime, authority)

    parsed = urlsplit(receipt.authorization_url)
    params = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parsed.path == "/o/oauth2/v2/auth"
    assert params["client_id"] == ["client-id-public"]
    assert params["redirect_uri"] == ["https://oauth.example.invalid/v1/google/callback"]
    assert params["scope"] == [GMAIL_READONLY_SCOPE]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["state"] == ["state_1"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"][0] != PKCE_VERIFIER
    assert PKCE_VERIFIER not in receipt.authorization_url
    assert raw_ticket not in receipt.authorization_url
    assert CLIENT_SECRET not in receipt.authorization_url

    assert storage.count("google_oauth_connect_ticket_use") == 1
    assert storage.count("google_oauth_authorization_state") == 1
    persisted = storage.all_text()
    assert raw_ticket not in persisted
    assert PKCE_VERIFIER not in persisted
    assert CLIENT_SECRET not in persisted
    assert "workspace_1" not in persisted

    public = receipt.safe_dict()
    assert public["raw_connect_ticket"] is False
    assert public["raw_pkce_verifier"] is False
    assert public["raw_client_secret"] is False


def test_connect_ticket_is_durably_single_use():
    runtime, storage, _, _, authority, _ = fixture()
    raw_ticket = ticket(authority)
    asyncio.run(runtime.begin(connect_ticket=raw_ticket))

    with pytest.raises(ControlPlaneContractError) as exc:
        asyncio.run(runtime.begin(connect_ticket=raw_ticket))
    assert exc.value.code == "replayed_connect_ticket"
    assert storage.count("google_oauth_connect_ticket_use") == 1
    assert storage.count("google_oauth_authorization_state") == 1


def test_success_callback_consumes_state_and_persists_only_sealed_refresh_credential():
    runtime, storage, durable_store, sealer, authority, exchange = fixture()
    _, receipt = begin(runtime, authority)
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]

    connected = asyncio.run(
        runtime.complete_callback(
            state_ref=state_ref,
            authorization_code=AUTH_CODE,
            provider_error=None,
        )
    )
    assert connected.connector_id == "gmail"
    assert connected.actor_ref == "actor_1"
    assert connected.account_ref == "account_1"
    assert connected.workspace_ref == "workspace_1"
    assert connected.scopes == (GMAIL_READONLY_SCOPE,)
    assert storage.count("google_oauth_authorization_state") == 0
    assert storage.count("google_oauth_refresh_credential") == 1

    assert len(exchange.calls) == 1
    call = exchange.calls[0]
    assert call["code"] == AUTH_CODE
    assert call["code_verifier"] == PKCE_VERIFIER
    assert call["redirect_uri"] == "https://oauth.example.invalid/v1/google/callback"

    record = durable_store.load_active_credential(binding_ref=connected.binding_ref, now=NOW)
    assert REFRESH_TOKEN not in record.sealed_refresh_token
    context = GoogleOAuthSealContext(
        purpose=GoogleOAuthSealPurpose.REFRESH_TOKEN,
        connector_id="gmail",
        record_ref=connected.binding_ref,
        actor_ref="actor_1",
        account_ref="account_1",
        workspace_ref="workspace_1",
    )
    assert asyncio.run(
        sealer.unseal_text(envelope=record.sealed_refresh_token, context=context)
    ) == REFRESH_TOKEN

    persisted = storage.all_text()
    for secret in (AUTH_CODE, ACCESS_TOKEN, REFRESH_TOKEN, CLIENT_SECRET, PKCE_VERIFIER):
        assert secret not in persisted

    public = connected.safe_dict()
    assert public["refresh_token_persisted_sealed"] is True
    assert public["access_token_discarded"] is True
    assert public["raw_authorization_code"] is False
    assert public["raw_access_token"] is False
    assert public["raw_refresh_token"] is False
    assert public["raw_client_secret"] is False

    with pytest.raises(ControlPlaneContractError) as replay:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=AUTH_CODE,
                provider_error=None,
            )
        )
    assert replay.value.code == "missing_google_oauth_state"


def test_provider_denial_consumes_state_without_token_exchange():
    runtime, storage, _, _, authority, exchange = fixture()
    _, receipt = begin(runtime, authority)
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]

    with pytest.raises(ControlPlaneContractError) as denied:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=None,
                provider_error="access_denied",
            )
        )
    assert denied.value.code == "google_oauth_authorization_denied"
    assert storage.count("google_oauth_authorization_state") == 0
    assert exchange.calls == []

    with pytest.raises(ControlPlaneContractError) as replay:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=AUTH_CODE,
                provider_error=None,
            )
        )
    assert replay.value.code == "missing_google_oauth_state"


def test_scope_mismatch_fails_closed_after_state_is_consumed():
    exchange = FakeTokenExchange(
        payload={
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "token_type": "Bearer",
            "scope": "https://www.googleapis.com/auth/gmail.modify",
        }
    )
    runtime, storage, _, _, authority, _ = fixture(exchange=exchange)
    _, receipt = begin(runtime, authority)
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]

    with pytest.raises(ControlPlaneContractError) as mismatch:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=AUTH_CODE,
                provider_error=None,
            )
        )
    assert mismatch.value.code == "google_oauth_scope_mismatch"
    assert storage.count("google_oauth_authorization_state") == 0
    assert storage.count("google_oauth_refresh_credential") == 0


def test_token_exchange_failure_consumes_state_and_never_persists_partial_credential():
    exchange = FakeTokenExchange(
        error=ControlPlaneContractError(
            "google_oauth_token_exchange_failed",
            "simulated upstream failure",
        )
    )
    runtime, storage, _, _, authority, _ = fixture(exchange=exchange)
    _, receipt = begin(runtime, authority)
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]

    with pytest.raises(ControlPlaneContractError) as failed:
        asyncio.run(
            runtime.complete_callback(
                state_ref=state_ref,
                authorization_code=AUTH_CODE,
                provider_error=None,
            )
        )
    assert failed.value.code == "google_oauth_token_exchange_failed"
    assert storage.count("google_oauth_authorization_state") == 0
    assert storage.count("google_oauth_refresh_credential") == 0


def test_refresh_token_expiry_is_bounded_and_projected_without_secret():
    exchange = FakeTokenExchange(
        payload={
            "access_token": ACCESS_TOKEN,
            "refresh_token": REFRESH_TOKEN,
            "token_type": "Bearer",
            "scope": GMAIL_READONLY_SCOPE,
            "refresh_token_expires_in": 3600,
        }
    )
    runtime, _, durable_store, _, authority, _ = fixture(exchange=exchange)
    _, receipt = begin(runtime, authority)
    state_ref = parse_qs(urlsplit(receipt.authorization_url).query)["state"][0]
    connected = asyncio.run(
        runtime.complete_callback(
            state_ref=state_ref,
            authorization_code=AUTH_CODE,
            provider_error=None,
        )
    )
    assert connected.expires_at == NOW + timedelta(hours=1)
    record = durable_store.load_active_credential(binding_ref=connected.binding_ref, now=NOW)
    assert record.expires_at == NOW + timedelta(hours=1)


def test_runtime_safe_projection_states_live_boundaries_truthfully():
    runtime, _, _, _, _, _ = fixture()
    public = runtime.safe_dict()
    assert public["trusted_connect_ticket_required"] is True
    assert public["connect_ticket_body_only"] is True
    assert public["state_pkce_server_generated"] is True
    assert public["authorization_session_sealed"] is True
    assert public["callback_state_single_use"] is True
    assert public["refresh_token_persisted_sealed"] is True
    assert public["access_token_persisted"] is False
    assert public["google_write_scope"] is False
    assert public["raw_connect_ticket_persisted"] is False
    assert public["raw_authorization_code_persisted"] is False
    assert public["production_deployment"] is False
    assert public["production_ready"] is False
    assert CLIENT_SECRET not in json.dumps(public)
