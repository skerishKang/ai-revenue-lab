from __future__ import annotations

import httpx
import pytest

from padiem_control_plane import AuthSessionSnapshot, CanonicalSubjectRef, ProductIdentityLink, SubjectType

from app.auth import GOOGLE_TOKEN_URL, GOOGLE_USERINFO_URL, SESSION_COOKIE
from app.config import Settings
from app.history import UserProfile
from app.main import create_app

SESSION_SECRET = "shadow-session-secret-not-a-real-credential-0000000"
ACCESS_TOKEN = "shadow-test-access-token-never-persist"


def settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="shadow-client.apps.googleusercontent.com",
        google_client_secret="shadow-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


class MemoryHistoryStore:
    def __init__(self) -> None:
        self.users = {}

    async def upsert_google_user(self, subject, email, name, picture):
        uid = "usr_" + subject.replace("-", "")[:32].ljust(32, "0")
        profile = UserProfile(uid, email, name, picture)
        self.users[uid] = profile
        return profile

    async def get_user(self, user_id):
        return self.users.get(user_id)


class ShadowStore:
    def __init__(self) -> None:
        self.saved = []

    async def save_projection(self, bridged):
        self.saved.append(bridged)


class Authority:
    def __init__(self, *, fail=False) -> None:
        self.fail = fail
        self.link_calls = []
        self.session_calls = []

    def resolve_or_create_product_link(self, **kwargs):
        self.link_calls.append(kwargs)
        if self.fail:
            raise RuntimeError("authority unavailable")
        return ProductIdentityLink(
            product_id="b62",
            product_user_id=kwargs["product_user_id"],
            canonical_subject_id="subject:padiem:user:shadow-123",
        )

    def establish_auth_session(self, **kwargs):
        self.session_calls.append(kwargs)
        if self.fail:
            raise RuntimeError("authority unavailable")
        return AuthSessionSnapshot(
            session_id="authsession:b62:shadow-123",
            product_id="b62",
            subject=kwargs["subject"],
            issued_at=kwargs["authenticated_at"],
            expires_at=kwargs["not_after"],
        )


async def google_transport(request: httpx.Request) -> httpx.Response:
    if str(request.url) == GOOGLE_TOKEN_URL:
        return httpx.Response(
            200,
            json={"access_token": ACCESS_TOKEN, "token_type": "Bearer", "expires_in": 3600},
        )
    if str(request.url) == GOOGLE_USERINFO_URL:
        assert request.headers.get("Authorization") == f"Bearer {ACCESS_TOKEN}"
        return httpx.Response(
            200,
            json={
                "id": "shadow-google-subject-123",
                "email": "shadow@example.test",
                "verified_email": True,
                "name": "Shadow User",
                "picture": "",
            },
        )
    return httpx.Response(404)


async def perform_login(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
        follow_redirects=False,
    ) as client:
        start = await client.get("/auth/google/start")
        state = httpx.URL(start.headers["location"]).params["state"]
        callback = await client.get(f"/auth/google/callback?state={state}&code=shadow-code")
        status = await client.get("/api/auth/status")
        return callback, status


@pytest.mark.asyncio
async def test_google_callback_writes_authority_issued_shadow_without_changing_product_login() -> None:
    authority = Authority()
    shadow = ShadowStore()
    history = MemoryHistoryStore()
    app = create_app(
        settings(),
        auth_transport=httpx.MockTransport(google_transport),
        history_store=history,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow,
    )

    callback, status = await perform_login(app)

    assert callback.status_code == 302
    assert callback.headers["location"] == "/"
    assert SESSION_COOKIE in callback.headers["set-cookie"]
    assert status.status_code == 200
    assert status.json()["authenticated"] is True
    assert len(shadow.saved) == 1
    bridged = shadow.saved[0]
    assert bridged.product_user_id.startswith("usr_")
    assert bridged.canonical_subject == CanonicalSubjectRef(
        subject_type=SubjectType.USER,
        subject_id="subject:padiem:user:shadow-123",
    )
    assert authority.link_calls[0]["auth_provider"] == "google"
    assert authority.link_calls[0]["provider_subject"] == "shadow-google-subject-123"
    session_call = authority.session_calls[0]
    assert session_call["not_after"] > session_call["authenticated_at"]
    assert int((session_call["not_after"] - session_call["authenticated_at"]).total_seconds()) == 3600
    assert ACCESS_TOKEN not in repr(shadow.saved)
    assert ACCESS_TOKEN not in repr(authority.link_calls)
    assert ACCESS_TOKEN not in repr(authority.session_calls)


@pytest.mark.asyncio
async def test_shadow_authority_failure_does_not_break_compatibility_login() -> None:
    authority = Authority(fail=True)
    shadow = ShadowStore()
    history = MemoryHistoryStore()
    app = create_app(
        settings(),
        auth_transport=httpx.MockTransport(google_transport),
        history_store=history,
        control_plane_identity_authority=authority,
        identity_shadow_store=shadow,
    )

    callback, status = await perform_login(app)

    assert callback.status_code == 302
    assert status.json()["authenticated"] is True
    assert shadow.saved == []
    assert len(authority.link_calls) == 1


@pytest.mark.asyncio
async def test_absent_shadow_store_does_not_call_control_plane_or_change_login() -> None:
    authority = Authority()
    history = MemoryHistoryStore()
    app = create_app(
        settings(),
        auth_transport=httpx.MockTransport(google_transport),
        history_store=history,
        control_plane_identity_authority=authority,
        identity_shadow_store=None,
    )

    callback, status = await perform_login(app)

    assert callback.status_code == 302
    assert status.json()["authenticated"] is True
    assert authority.link_calls == []
    assert authority.session_calls == []
