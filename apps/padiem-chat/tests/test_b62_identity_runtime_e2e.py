"""STEP 6A runtime E2E: B62 connector-ticket route over the real identity authority.

Wires the production B62 Starlette app and the production CloudflareControlPlaneIdentityAuthority
adapter to the real private Control Plane identity worker (Default gateway -> canonical Durable
Object -> SQLite-backed store -> HMAC connect-ticket issuer), with only the workerd runtime and
Durable Object storage replaced by in-process fakes. No production source is modified.
"""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import json
import re
import secrets
import sqlite3
import sys
import types
from pathlib import Path

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.history import UserProfile
from app.main import create_app

from padiem_control_plane.connector_connect_ticket import (
    CONNECT_TICKET_AUDIENCE,
    CONNECT_TICKET_VERSION,
    GMAIL_READONLY_SCOPE,
    ConnectorConnectTicketAuthority,
)
from padiem_control_plane.contracts import ControlPlaneContractError


_CONTROL_PLANE_ROOT = Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane"
_ORIGIN = "https://chat.example.test"
_NOW = datetime.now(timezone.utc).replace(microsecond=0)
_PROVIDER_SUBJECT = "provider-subject-private-e2e"


def _new_key_b64url() -> tuple[str, bytes]:
    raw = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="), raw


def _load_identity_worker():
    """Import the real private identity worker with a minimal workerd-API stub."""
    workers_stub = types.ModuleType("workers")

    class _DurableObject:
        def __init__(self, ctx, env):
            self.ctx = ctx
            self.env = env

    class _WorkerEntrypoint:
        def __init__(self, ctx=None, env=None):
            self.ctx = ctx
            self.env = env

    class _Response:
        def __init__(self, body="", status=200, headers=None):
            self.body = body
            self.status = status
            self.headers = headers or {}

    workers_stub.DurableObject = _DurableObject
    workers_stub.WorkerEntrypoint = _WorkerEntrypoint
    workers_stub.Response = _Response
    sys.modules["workers"] = workers_stub

    root_text = str(_CONTROL_PLANE_ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    import identity_authority_worker

    return identity_authority_worker


class _SqlCursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._rows = []
        if cursor.description:
            columns = [column[0] for column in cursor.description]
            self._rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    def toArray(self):
        return self._rows


class _FakeDurableStorage:
    """SQLite-backed Durable Object storage surface used by the real authority."""

    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", isolation_level=None)
        self.sql = types.SimpleNamespace(
            exec=lambda query, *params: _SqlCursor(self.connection.execute(query, params))
        )

    def transactionSync(self, operation):
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            result = operation()
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise
        self.connection.execute("COMMIT")
        return result


class IdentityRuntime:
    """Real Default gateway + real canonical Durable Object over fake storage/env."""

    def __init__(self) -> None:
        module = _load_identity_worker()
        self.lookup_key_b64, self.lookup_key = _new_key_b64url()
        self.ticket_key_b64, self.ticket_key = _new_key_b64url()
        self.storage = _FakeDurableStorage()
        ctx = types.SimpleNamespace(storage=self.storage)
        self.env = types.SimpleNamespace(
            CONTROL_PLANE_ALLOWED_PRODUCT="b62",
            CONTROL_PLANE_IDENTITY_LOOKUP_KEY=self.lookup_key_b64,
            GOOGLE_CONNECT_TICKET_KEY=self.ticket_key_b64,
        )
        durable_object = module.CanonicalIdentityDurableObject(ctx, self.env)
        self.env.CONTROL_PLANE_IDENTITY = types.SimpleNamespace(
            idFromName=lambda name: f"id-{name}",
            get=lambda object_id: durable_object,
        )
        self.entrypoint = module.Default(ctx, self.env)
        self.calls: list[str] = []

    def service_binding(self):
        runtime = self

        class _RecordingServiceBinding:
            """Stands in for the IDENTITY_AUTHORITY_SERVICE binding, recording RPC names."""

            async def resolve_or_create_product_link(self, payload):
                runtime.calls.append("resolve_or_create_product_link")
                return await runtime.entrypoint.resolve_or_create_product_link(payload)

            async def establish_auth_session(self, payload):
                runtime.calls.append("establish_auth_session")
                return await runtime.entrypoint.establish_auth_session(payload)

            async def resolve_auth_session(self, payload):
                runtime.calls.append("resolve_auth_session")
                return await runtime.entrypoint.resolve_auth_session(payload)

            async def issue_google_connect_ticket(self, payload):
                runtime.calls.append("issue_google_connect_ticket")
                return await runtime.entrypoint.issue_google_connect_ticket(payload)

        return _RecordingServiceBinding()


class MemoryHistoryStore:
    def __init__(self) -> None:
        self.profile = UserProfile("usr_" + "e" * 32, "e2e@example.test", "E2E User", "")

    async def get_user(self, user_id):
        return self.profile if user_id == self.profile.id else None

    async def upsert_google_user(self, subject, email, name, picture):
        del subject, email, name, picture
        return self.profile


class MemoryShadowStore:
    def __init__(self) -> None:
        self.record: IdentityShadowRecord | None = None

    async def save_projection(self, bridged) -> None:
        session = bridged.auth_session
        self.record = IdentityShadowRecord(
            product_user_id=bridged.product_user_id,
            canonical_subject_id=bridged.canonical_subject.subject_id,
            auth_session_id=session.session_id,
            session_revision=session.revision,
            session_state=session.state.value,
            session_expires_at=session.expires_at,
            observed_at=datetime.now(timezone.utc).replace(microsecond=0),
        )

    async def load_projection(self, product_user_id):
        if self.record is None or self.record.product_user_id != product_user_id:
            return None
        return self.record


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url=_ORIGIN,
        google_client_id="e2e-test.apps.googleusercontent.com",
        google_client_secret="unit-test-only-google-secret",
        session_secret="b62-runtime-e2e-session-secret-not-real-00000",
        session_max_age_seconds=3600,
    )


async def _google_handler(request):
    if str(request.url).endswith("/token"):
        return httpx.Response(200, json={"access_token": "private", "token_type": "Bearer", "expires_in": 3600})
    return httpx.Response(
        200,
        json={
            "id": _PROVIDER_SUBJECT,
            "email": "e2e@example.test",
            "verified_email": True,
            "name": "E2E User",
            "picture": "",
        },
    )


def build_app(runtime: IdentityRuntime | None):
    history = MemoryHistoryStore()
    shadow_store = MemoryShadowStore()
    authority = CloudflareControlPlaneIdentityAuthority(runtime.service_binding()) if runtime else None
    app = create_app(
        settings(),
        auth_transport=httpx.MockTransport(_google_handler),
        history_store=history,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow_store,
    )
    return app, history, shadow_store


async def _login(client, profile_id: str) -> None:
    start = await client.get("/auth/google/start")
    state = httpx.URL(start.headers["location"]).params["state"]
    callback = await client.get(f"/auth/google/callback?state={state}&code=sample-code")
    assert callback.status_code == 302
    client.cookies.set(SESSION_COOKIE, create_session_token(settings(), profile_id), domain="chat.example.test", path="/")


async def _post_ticket(client, body=None, *, origin=_ORIGIN, raw=None):
    payload = {"connector_id": "gmail"} if body is None else body
    if raw is not None:
        return await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": origin, "Content-Type": "application/json"},
            content=raw,
        )
    return await client.post(
        "/api/connectors/google/ticket",
        headers={"Origin": origin},
        json=payload,
    )


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=_ORIGIN, follow_redirects=False)


async def test_runtime_e2e_login_then_authority_minted_ticket_verifies_with_shared_key():
    runtime = IdentityRuntime()
    app, history, shadow_store = build_app(runtime)

    async with _client(app) as client:
        await _login(client, history.profile.id)
        assert re.fullmatch(r"sess_[0-9a-f]{32}", shadow_store.record.auth_session_id)
        assert re.fullmatch(r"sub_[0-9a-f]{32}", shadow_store.record.canonical_subject_id)

        first = await _post_ticket(client, {"connector_id": "gmail"})
        second = await _post_ticket(client, {"connector_id": "gmail"})

    assert first.status_code == 200
    ticket = first.json()["ticket"]["connect_ticket"]
    assert second.status_code == 200
    assert second.json()["ticket"]["connect_ticket"] != ticket

    assert runtime.calls == [
        "resolve_or_create_product_link",
        "establish_auth_session",
        "issue_google_connect_ticket",
        "issue_google_connect_ticket",
    ]

    verifier = ConnectorConnectTicketAuthority(signing_key=runtime.ticket_key)
    claims = verifier.verify(
        token=ticket,
        now=datetime.now(timezone.utc),
        expected_connector_id="gmail",
    )
    assert claims.version == CONNECT_TICKET_VERSION
    assert claims.audience == CONNECT_TICKET_AUDIENCE
    assert claims.product_id == "b62"
    assert claims.connector_id == "gmail"
    assert claims.scopes == (GMAIL_READONLY_SCOPE,)
    assert claims.session_id == shadow_store.record.auth_session_id
    assert claims.subject_id == shadow_store.record.canonical_subject_id
    assert re.fullmatch(r"actor_[0-9a-f]{32}", claims.actor_ref)
    assert re.fullmatch(r"account_[0-9a-f]{32}", claims.account_ref)
    assert re.fullmatch(r"workspace_[0-9a-f]{32}", claims.workspace_ref)
    assert (claims.expires_at - claims.issued_at) == timedelta(seconds=180)

    second_claims = verifier.verify(token=second.json()["ticket"]["connect_ticket"], now=datetime.now(timezone.utc))
    assert second_claims.ticket_id != claims.ticket_id
    assert second_claims.actor_ref == claims.actor_ref
    assert second_claims.account_ref == claims.account_ref
    assert second_claims.workspace_ref == claims.workspace_ref

    assert ticket not in json.dumps(dict(first.headers))
    assert first.headers["cache-control"].startswith("no-store")


async def test_runtime_e2e_ticket_rejected_by_verifier_after_ttl():
    runtime = IdentityRuntime()
    app, history, _ = build_app(runtime)
    async with _client(app) as client:
        await _login(client, history.profile.id)
        response = await _post_ticket(client, {"connector_id": "google-drive"})
    assert response.status_code == 200
    ticket = response.json()["ticket"]["connect_ticket"]
    verifier = ConnectorConnectTicketAuthority(signing_key=runtime.ticket_key)
    claims = verifier.verify(token=ticket, now=datetime.now(timezone.utc))
    with pytest.raises(ControlPlaneContractError) as exc_info:
        verifier.verify(token=ticket, now=claims.expires_at + timedelta(seconds=1))
    assert exc_info.value.code == "expired_connect_ticket"


async def test_runtime_e2e_negative_matrix_rejects_before_reaching_authority():
    runtime = IdentityRuntime()
    app, history, _ = build_app(runtime)
    async with _client(app) as client:
        anonymous = await _post_ticket(client)
        assert anonymous.status_code == 401

        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings(), history.profile.id),
            domain="chat.example.test",
            path="/",
        )
        cross_origin = await _post_ticket(client, origin="https://evil.example.test")
        assert cross_origin.status_code == 403

        unreviewed = await _post_ticket(client, {"connector_id": "calendar"})
        assert unreviewed.status_code == 403
        assert unreviewed.json()["error"]["code"] == "connector_not_reviewed"

        injected = await _post_ticket(client, {"connector_id": "gmail", "account_ref": "client-controlled"})
        assert injected.status_code == 400

        plain = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": _ORIGIN, "Content-Type": "text/plain"},
            content="gmail",
        )
        assert plain.status_code == 415

        oversized = await _post_ticket(client, raw=b'{"connector_id": "gmail", "pad": "' + b"x" * 2048 + b'"}')
        assert oversized.status_code == 400
    assert runtime.calls == []


async def test_runtime_e2e_missing_shadow_and_missing_binding_fail_closed():
    runtime = IdentityRuntime()
    app, history, _ = build_app(runtime)
    async with _client(app) as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings(), history.profile.id),
            domain="chat.example.test",
            path="/",
        )
        missing_link = await _post_ticket(client)
    assert missing_link.status_code == 503
    assert missing_link.json()["error"]["code"] == "control_plane_identity_not_linked"
    assert runtime.calls == []

    unbound_app, unbound_history, _ = build_app(None)
    async with _client(unbound_app) as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings(), unbound_history.profile.id),
            domain="chat.example.test",
            path="/",
        )
        unbound = await _post_ticket(client)
    assert unbound.status_code == 503
    assert unbound.json()["error"]["code"] == "connector_ticket_unavailable"


async def test_runtime_e2e_unknown_canonical_session_is_rejected_by_authority():
    runtime = IdentityRuntime()
    app, history, shadow_store = build_app(runtime)
    async with _client(app) as client:
        await _login(client, history.profile.id)
        original = shadow_store.record
        shadow_store.record = IdentityShadowRecord(
            product_user_id=original.product_user_id,
            canonical_subject_id=original.canonical_subject_id,
            auth_session_id="sess_" + "0" * 32,
            session_revision=original.session_revision,
            session_state=original.session_state,
            session_expires_at=original.session_expires_at,
            observed_at=original.observed_at,
        )
        response = await _post_ticket(client)
    assert runtime.calls[-1] == "issue_google_connect_ticket"
    assert response.status_code == 401
    assert response.json()["error"]["message"] != "canonical auth session was not found"
    assert "sess_" not in response.text


async def test_runtime_e2e_authority_enforces_product_and_provider_boundaries():
    runtime = IdentityRuntime()
    binding = runtime.service_binding()

    wrong_product = await binding.resolve_or_create_product_link(
        {"product_id": "b63", "product_user_id": "usr_x", "auth_provider": "google", "provider_subject": "s"}
    )
    assert wrong_product["ok"] is False
    assert wrong_product["error"]["code"] == "identity_authority_product_mismatch"

    bad_provider = await binding.resolve_or_create_product_link(
        {"product_id": "b62", "product_user_id": "usr_x", "auth_provider": "github", "provider_subject": "s"}
    )
    assert bad_provider["ok"] is False
    assert bad_provider["error"]["code"] == "unsupported_identity_provider"

    open_payload = await binding.resolve_or_create_product_link(
        {"product_id": "b62", "product_user_id": "usr_x", "auth_provider": "google", "provider_subject": "s", "extra": 1}
    )
    assert open_payload["ok"] is False
    assert open_payload["error"]["code"] == "invalid_identity_authority_rpc"

    link = await binding.resolve_or_create_product_link(
        {"product_id": "b62", "product_user_id": "usr_x", "auth_provider": "google", "provider_subject": "s"}
    )
    assert link["ok"] is True
    session = await binding.establish_auth_session(
        {
            "product_id": "b62",
            "subject": {"subject_type": "user", "subject_id": link["link"]["canonical_subject_id"]},
            "authenticated_at": _NOW.isoformat(),
            "not_after": (_NOW + timedelta(hours=1)).isoformat(),
        }
    )
    assert session["ok"] is True
    unknown_ticket = await binding.issue_google_connect_ticket(
        {"session_id": "sess_" + "f" * 32, "connector_id": "gmail"}
    )
    assert unknown_ticket["ok"] is False
    assert unknown_ticket["error"]["code"] == "canonical_auth_session_not_found"

    ticket = await binding.issue_google_connect_ticket(
        {"session_id": session["session"]["session_id"], "connector_id": "gmail"}
    )
    assert ticket["ok"] is True
    assert set(ticket["ticket"]) == {"connect_ticket", "connector_id", "expires_at"}

    rows = runtime.storage.sql.exec(
        "SELECT provider, provider_fingerprint FROM canonical_identity_subject"
    ).toArray()
    assert rows and all(set(row) == {"provider", "provider_fingerprint"} for row in rows)
    assert all(re.fullmatch(r"[0-9a-f]{64}", row["provider_fingerprint"]) for row in rows)
    assert _PROVIDER_SUBJECT not in json.dumps(rows)
    assert all(row["provider"] == "google" for row in rows)
