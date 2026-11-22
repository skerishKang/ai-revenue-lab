"""Shared general routing test fixtures and injected request adapters."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings

GENERAL_ROUTE_PATH = "/api/claw/general"
SIGNED_IN_USER_ID = "usr_" + "7" * 32


def _settings(**overrides) -> Settings:
    values = {
        "runtime_mode": "mock",
        "auth_mode": "google",
        "public_base_url": "https://chat.example.test",
        "google_client_id": "claw-general-client.apps.googleusercontent.com",
        "google_client_secret": "claw-general-google-secret",
        "session_secret": "claw-general-session-secret-not-a-real-credential",
        "session_max_age_seconds": 3600,
        "byok_via_b14": False,
    }
    values.update(overrides)
    return Settings.from_values(**values)


class _AuthStore:
    """Presence-only auth stub: no history/conversation authority is exercised."""

    async def get_user(self, user_id: str):
        return None

    async def get_conversation(self, user_id: str, conversation_id: str, product_scope: str):
        return {"id": conversation_id} if conversation_id else None


def _make_outcome(*, status: str = "completed", answer: str | None = "P01 결과"):
    status_mock = MagicMock()
    status_mock.value = status
    projection = MagicMock()
    projection.status = status_mock
    projection.run_id = "run_general"
    outcome = MagicMock()
    outcome.projection = projection
    outcome.answer = answer
    outcome.p01_run_id = "p01_general"
    outcome.p01_event_count = 1
    return outcome


def _make_adapter(*, outcome=None, subject_lane: bool = False) -> MagicMock:
    adapter = MagicMock()
    adapter.subject_identity_lane = subject_lane
    adapter.execute = AsyncMock(return_value=outcome or _make_outcome())
    return adapter


@contextmanager
def _client(adapter=None):
    app = create_app(settings=_settings(), history_store=_AuthStore(), claw_p01_adapter=adapter)
    client = TestClient(app, base_url="https://chat.example.test")
    client.cookies.set(
        SESSION_COOKIE,
        create_session_token(_settings(), SIGNED_IN_USER_ID, canonical_session_id="session_test_a"),
        domain="chat.example.test",
        path="/",
    )
    with client:
        yield client


def _payload(**extra) -> dict:
    payload = {"messages": [{"role": "user", "content": "일반 요청입니다."}], "tier": "plus"}
    payload.update(extra)
    return payload


# ── #8060 47차: shipped source sheets, read here not in the contract tests ───


def _shipped(path: str) -> str:
    return (Path(__file__).resolve().parents[2] / path).read_text(encoding="utf-8")


def claw_general_routes_source() -> str:
    return _shipped("app/claw_general_routes.py")


def app_factory_source() -> str:
    return _shipped("app/app_factory.py")


def app_js_source() -> str:
    return _shipped("static/app.js")


def transport_source() -> str:
    return _shipped("static/chat-transport.js")


def streaming_module_source() -> str:
    return _shipped("static/chat-streaming-module.js")
