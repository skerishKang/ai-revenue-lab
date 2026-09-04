from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.main import create_app


SESSION_SECRET = "b62-1816-session-secret-not-a-real-credential-000000"


class Profile:
    def __init__(self, user_id: str, name: str = "테스트 사용자") -> None:
        self.id = user_id
        self.name = name

    def public_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "email": "user@example.test",
            "name": self.name,
            "picture": "",
        }


class StatusStore:
    def __init__(self, profile: Profile | None = None, *, fail: bool = False) -> None:
        self.profile = profile
        self.fail = fail

    async def get_user(self, user_id: str):
        if self.fail:
            raise RuntimeError("storage unavailable")
        if self.profile and self.profile.id == user_id:
            return self.profile
        return None


def google_settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="google",
        public_base_url="https://chat.example.test",
        google_client_id="b62-1816.apps.googleusercontent.com",
        google_client_secret="unit-test-google-secret",
        session_secret=SESSION_SECRET,
        session_max_age_seconds=3600,
    )


@pytest.mark.asyncio
async def test_auth_status_projects_guest_signed_in_and_expired_for_presentation_only() -> None:
    settings = google_settings()
    user_id = "usr_" + "a" * 32
    profile = Profile(user_id)
    app = create_app(settings, history_store=StatusStore(profile))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        guest = await client.get("/api/auth/status")
        assert guest.status_code == 200
        assert guest.json()["session_state"] == "guest"
        assert guest.json()["authenticated"] is False
        assert guest.json()["user"] is None

        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, user_id),
            domain="chat.example.test",
            path="/",
        )
        signed_in = await client.get("/api/auth/status")
        assert signed_in.status_code == 200
        assert signed_in.json()["session_state"] == "signed_in"
        assert signed_in.json()["authenticated"] is True
        assert signed_in.json()["user"]["name"] == "테스트 사용자"

        client.cookies.set(SESSION_COOKIE, "invalid-session", domain="chat.example.test", path="/")
        expired = await client.get("/api/auth/status")
        assert expired.status_code == 200
        assert expired.json()["session_state"] == "expired"
        assert expired.json()["authenticated"] is False
        assert expired.json()["user"] is None


@pytest.mark.asyncio
async def test_auth_status_omits_session_projection_when_auth_is_unavailable() -> None:
    app = create_app(Settings.from_values())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        status = await client.get("/api/auth/status")
    assert status.status_code == 200
    assert status.json() == {
        "ready": False,
        "authenticated": False,
        "history_ready": False,
        "user": None,
    }


@pytest.mark.asyncio
async def test_auth_status_storage_failure_never_self_asserts_identity() -> None:
    settings = google_settings()
    user_id = "usr_" + "b" * 32
    app = create_app(settings, history_store=StatusStore(fail=True))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://chat.example.test",
    ) as client:
        client.cookies.set(
            SESSION_COOKIE,
            create_session_token(settings, user_id),
            domain="chat.example.test",
            path="/",
        )
        status = await client.get("/api/auth/status")
    body = status.json()
    assert body["authenticated"] is False
    assert body["user"] is None
    assert body["session_state"] == "unavailable"


def test_browser_projection_is_presentation_only_and_has_no_identity_authority() -> None:
    root = Path(__file__).resolve().parents[1]
    js = (root / "static/product-capabilities.js").read_text(encoding="utf-8")
    css = (root / "static/sidebar-utility.css").read_text(encoding="utf-8")

    for marker in (
        '"unavailable", "guest", "signed_in", "expired"',
        'sessionState: "unavailable"',
        'data.user.name',
        'copy.signInAgain',
        'accountContainer.dataset.accountState = state',
    ):
        assert marker in js

    for forbidden in (
        "localStorage",
        "sessionStorage",
        "document.cookie",
        "entitlement",
        "billing",
        "credit",
    ):
        assert forbidden not in js

    assert 'fetch("/api/auth/status"' not in js
    assert 'nativeFetch("/api/auth/status"' in js
    assert "min-height: 44px" in css
    assert '.sidebar-account[data-account-state="expired"]' in css
