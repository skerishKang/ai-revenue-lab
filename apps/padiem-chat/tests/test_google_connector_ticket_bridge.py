from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.control_plane_identity_shadow import IdentityShadowRecord
from app.control_plane_identity_worker import (
    CloudflareControlPlaneIdentityAuthority,
    PrivateGoogleConnectTicket,
)
from app.history import UserProfile
from app.main import create_app


SESSION_SECRET = "connector-ticket-session-secret-not-real-000000000"
NOW = datetime(2026, 9, 4, 13, 40, tzinfo=timezone.utc)


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="connector-test.apps.googleusercontent.com",
        google_client_secret="unit-test-only-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


class MemoryHistoryStore:
    def __init__(self) -> None:
        self.profile = UserProfile(
            "usr_" + "1" * 32,
            "user@example.test",
            "Connector User",
            "",
        )

    async def get_user(self, user_id):
        return self.profile if user_id == self.profile.id else None

    async def upsert_google_user(self, subject, email, name, picture):
        del subject, email, name, picture
        return self.profile


class MemoryShadowStore:
    def __init__(self, record: IdentityShadowRecord | None = None) -> None:
        self.record = record
        self.saved = []

    async def save_projection(self, bridged) -> None:
        self.saved.append(bridged)
        session = bridged.auth_session
        self.record = IdentityShadowRecord(
            product_user_id=bridged.product_user_id,
            canonical_subject_id=bridged.canonical_subject.subject_id,
            auth_session_id=session.session_id,
            session_revision=session.revision,
            session_state=session.state.value,
            session_expires_at=session.expires_at,
            observed_at=NOW,
        )

    async def load_projection(self, product_user_id):
        if self.record is None or self.record.product_user_id != product_user_id:
            return None
        return self.record


def shadow(profile_id: str) -> IdentityShadowRecord:
    return IdentityShadowRecord(
        product_user_id=profile_id,
        canonical_subject_id="sub_test",
        auth_session_id="sess_test",
        session_revision=1,
        session_state="active",
        session_expires_at=NOW + timedelta(hours=1),
        observed_at=NOW,
    )


class FakeControlPlaneBinding:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.ticket = "opaque-connect-ticket-that-never-appears-in-headers"
        self.ticket_error: dict | None = None

    async def resolve_or_create_product_link(self, payload):
        self.calls.append(("link", dict(payload)))
        return {
            "ok": True,
            "link": {
                "product_id": "b62",
                "product_user_id": payload["product_user_id"],
                "canonical_subject_id": "sub_test",
                "state": "active",
            },
        }

    async def establish_auth_session(self, payload):
        self.calls.append(("establish", dict(payload)))
        return {
            "ok": True,
            "session": {
                "session_id": "sess_test",
                "product_id": "b62",
                "subject": {"subject_type": "user", "subject_id": "sub_test"},
                "issued_at": payload["authenticated_at"],
                "expires_at": payload["not_after"],
                "state": "active",
                "revision": 1,
            },
        }

    async def resolve_auth_session(self, payload):
        self.calls.append(("resolve", dict(payload)))
        return {
            "ok": True,
            "session": {
                "session_id": payload["session_id"],
                "product_id": "b62",
                "subject": {"subject_type": "user", "subject_id": "sub_test"},
                "issued_at": NOW.isoformat(),
                "expires_at": (NOW + timedelta(hours=1)).isoformat(),
                "state": "active",
                "revision": 1,
            },
        }

    async def issue_google_connect_ticket(self, payload):
        self.calls.append(("ticket", dict(payload)))
        if self.ticket_error is not None:
            return {"ok": False, "error": dict(self.ticket_error)}
        return {
            "ok": True,
            "ticket": {
                "connect_ticket": self.ticket,
                "connector_id": payload["connector_id"],
                "expires_at": (NOW + timedelta(minutes=3)).isoformat(),
            },
        }


def cookie_for(profile_id: str) -> str:
    return create_session_token(settings(), profile_id, now=int(NOW.timestamp()))


def app_fixture(*, with_shadow=True, binding=None):
    history = MemoryHistoryStore()
    shadow_store = MemoryShadowStore(shadow(history.profile.id) if with_shadow else None)
    binding = binding or FakeControlPlaneBinding()
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    app = create_app(
        settings(),
        history_store=history,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow_store,
    )
    return app, history, shadow_store, binding, authority


@pytest.mark.asyncio
async def test_service_binding_adapter_parses_canonical_link_session_and_private_ticket():
    binding = FakeControlPlaneBinding()
    authority = CloudflareControlPlaneIdentityAuthority(binding)

    link = await authority.resolve_or_create_product_link(
        product_id="b62",
        product_user_id="usr_" + "1" * 32,
        auth_provider="google",
        provider_subject="provider-subject-private",
    )
    session = await authority.establish_auth_session(
        product_id="b62",
        subject=link and __import__("padiem_control_plane").CanonicalSubjectRef(
            __import__("padiem_control_plane").SubjectType.USER,
            link.canonical_subject_id,
        ),
        authenticated_at=NOW,
        not_after=NOW + timedelta(hours=1),
    )
    current = await authority.resolve_auth_session(session_id=session.session_id)
    ticket = await authority.issue_google_connect_ticket(
        session_id=current.session_id,
        connector_id="gmail",
    )

    assert link.product_user_id == "usr_" + "1" * 32
    assert session.session_id == "sess_test"
    assert current.subject.subject_id == "sub_test"
    assert isinstance(ticket, PrivateGoogleConnectTicket)
    assert ticket.connector_id == "gmail"
    assert binding.calls[-1] == ("ticket", {"session_id": "sess_test", "connector_id": "gmail"})
    assert ticket.connect_ticket not in repr(ticket)
    assert ticket.safe_dict()["raw_connect_ticket"] is False


@pytest.mark.asyncio
async def test_authenticated_same_origin_ticket_request_uses_shadow_session_only():
    app, history, _, binding, _ = app_fixture()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(
            SESSION_COOKIE,
            cookie_for(history.profile.id),
            domain="chat.example.test",
            path="/",
        )
        response = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": "https://chat.example.test"},
            json={"connector_id": "gmail"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["ticket"]["connect_ticket"] == binding.ticket
    assert body["ticket"]["connector_id"] == "gmail"
    assert binding.calls == [("ticket", {"session_id": "sess_test", "connector_id": "gmail"})]
    assert response.headers["cache-control"].startswith("no-store")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert binding.ticket not in json.dumps(dict(response.headers), ensure_ascii=False)


@pytest.mark.asyncio
async def test_client_cannot_assert_account_workspace_scopes_or_actor():
    app, history, _, binding, _ = app_fixture()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test", path="/")
        for forbidden in ("account_ref", "workspace_ref", "actor_ref", "scopes"):
            response = await client.post(
                "/api/connectors/google/ticket",
                headers={"Origin": "https://chat.example.test"},
                json={"connector_id": "gmail", forbidden: "client-controlled"},
            )
            assert response.status_code == 400
            assert response.json()["error"]["code"] == "connector_ticket_body_invalid"
    assert binding.calls == []


@pytest.mark.asyncio
async def test_ticket_route_rejects_anonymous_cross_origin_unreviewed_and_missing_shadow_before_rpc():
    app, history, _, binding, _ = app_fixture()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        anonymous = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": "https://chat.example.test"},
            json={"connector_id": "gmail"},
        )
        assert anonymous.status_code == 401

        client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test", path="/")
        cross_origin = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": "https://evil.example.test"},
            json={"connector_id": "gmail"},
        )
        assert cross_origin.status_code == 403

        unreviewed = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": "https://chat.example.test"},
            json={"connector_id": "calendar"},
        )
        assert unreviewed.status_code == 403
    assert binding.calls == []

    missing_app, missing_history, _, missing_binding, _ = app_fixture(with_shadow=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=missing_app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(missing_history.profile.id), domain="chat.example.test", path="/")
        missing = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": "https://chat.example.test"},
            json={"connector_id": "gmail"},
        )
    assert missing.status_code == 503
    assert missing.json()["error"]["code"] == "control_plane_identity_not_linked"
    assert missing_binding.calls == []


@pytest.mark.asyncio
async def test_revoked_canonical_session_fails_closed_and_does_not_leak_rpc_message():
    binding = FakeControlPlaneBinding()
    binding.ticket_error = {
        "code": "inactive_auth_session",
        "message": "internal authority detail must not leak",
    }
    app, history, _, _, _ = app_fixture(binding=binding)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as client:
        client.cookies.set(SESSION_COOKIE, cookie_for(history.profile.id), domain="chat.example.test", path="/")
        response = await client.post(
            "/api/connectors/google/ticket",
            headers={"Origin": "https://chat.example.test"},
            json={"connector_id": "google-drive"},
        )
    assert response.status_code == 401
    dumped = response.text
    assert "internal authority detail" not in dumped
    assert binding.ticket not in dumped
    assert binding.calls == [("ticket", {"session_id": "sess_test", "connector_id": "google-drive"})]


@pytest.mark.asyncio
async def test_login_bridge_with_service_binding_adapter_saves_authority_issued_shadow():
    access_token = "login-access-token-private"
    async def google_handler(request):
        if str(request.url).endswith("/token"):
            return httpx.Response(200, json={"access_token": access_token, "token_type": "Bearer", "expires_in": 3600})
        return httpx.Response(
            200,
            json={
                "id": "provider-subject-private",
                "email": "user@example.test",
                "verified_email": True,
                "name": "Connector User",
                "picture": "",
            },
        )

    history = MemoryHistoryStore()
    shadow_store = MemoryShadowStore()
    binding = FakeControlPlaneBinding()
    authority = CloudflareControlPlaneIdentityAuthority(binding)
    app = create_app(
        settings(),
        auth_transport=httpx.MockTransport(google_handler),
        history_store=history,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow_store,
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
        follow_redirects=False,
    ) as client:
        start = await client.get("/auth/google/start")
        state = httpx.URL(start.headers["location"]).params["state"]
        callback = await client.get(f"/auth/google/callback?state={state}&code=sample-code")

    assert callback.status_code == 302
    assert len(shadow_store.saved) == 1
    assert shadow_store.record is not None
    assert shadow_store.record.product_user_id == history.profile.id
    assert shadow_store.record.canonical_subject_id == "sub_test"
    assert shadow_store.record.auth_session_id == "sess_test"
    assert [call[0] for call in binding.calls] == ["link", "establish"]
    assert binding.calls[0][1]["provider_subject"] == "provider-subject-private"
    serialized = callback.text + json.dumps(dict(callback.headers), ensure_ascii=False)
    assert access_token not in serialized
    assert "provider-subject-private" not in serialized


def test_worker_and_wrangler_keep_identity_binding_server_owned():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    worker = (root / "worker.py").read_text(encoding="utf-8")
    wrangler = (root / "wrangler.toml").read_text(encoding="utf-8")
    route = (root / "app/connector_ticket_routes.py").read_text(encoding="utf-8")

    assert 'IDENTITY_AUTHORITY_SERVICE_BINDING_NAME = "IDENTITY_AUTHORITY_SERVICE"' in (
        root / "app/worker_config.py"
    ).read_text(encoding="utf-8")
    assert "CloudflareControlPlaneIdentityAuthority(identity_binding)" in worker
    assert "D1IdentityShadowStore(db_binding)" in worker
    assert 'binding = "IDENTITY_AUTHORITY_SERVICE"' in wrangler
    assert 'service = "padiem-control-plane-identity"' in wrangler
    assert 'set(payload) != {"connector_id"}' in route
    assert "account_ref" not in route
    assert "workspace_ref" not in route
    assert "GOOGLE_CONNECT_TICKET_KEY" not in route
