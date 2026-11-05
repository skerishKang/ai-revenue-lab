"""Owner decision 2026-11-05: Chat/Claw AI answers are signed-in only.

This module replaces the 2026-10-24 anonymous-Free contract (#5474). It pins
the new boundary:

* A guest gets HTTP 401 ``login_required`` on both Chat routes before the usage
  gate, before any history/provider work, and before B14. The canary client
  proves zero model calls.
* The login gate precedes the usage gate: an enforcing deployment without a
  quota store still answers 401 ``login_required`` (not 503).
* A signed-in member keeps the Free tier and the existing usage gate. The
  second burst call is still 429 ``rate_limited``.
* A signed-in member is never turned into a guest by an expired/tampered
  cookie; that request is 401 ``login_required``.
* The network-free mock runtime keeps its CI harness behavior, matching the
  server-owned ``model_requires_session = false`` projection.

Every test uses a canary B14 client: if a refused path executes a model, the
test fails loudly.
"""
from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.b14_client import B14Client
from app.config import Settings
from app.main import create_app
from app.usage_gate import InMemoryUsageCounterStore

from test_public_streaming import _event

OWNER = "usr_" + "a" * 32
ORIGIN = "https://chat.example.test"
BASE = "chat.example.test"
SECRET = "5474-anonymous-gate-secret-not-real-000000000000"
QUOTA_SALT = "5474-anonymous-gate-quota-salt-not-real-0001"
CLIENT_IP = "203.0.113.30"
PATHS = ("/api/chat", "/api/chat/stream")


def settings(*, runtime_mode: str = "b14") -> Settings:
    return Settings.from_values(
        runtime_mode=runtime_mode,
        b14_base_url="https://b14.internal",
        live_enabled=False,
        auth_mode="google",
        public_base_url=ORIGIN,
        google_client_id="5474-client.apps.googleusercontent.com",
        google_client_secret="5474-test-only-secret",
        session_secret=SECRET,
        session_max_age_seconds=3600,
    )


def quota_settings() -> Settings:
    """Live settings with a real client IP burst limit, like Production."""
    return Settings.from_values(
        runtime_mode="b14",
        b14_base_url="https://b14.internal",
        auth_mode="google",
        public_base_url=ORIGIN,
        google_client_id="5474-client.apps.googleusercontent.com",
        google_client_secret="5474-test-only-secret",
        session_secret=SECRET,
        session_max_age_seconds=3600,
        quota_salt=QUOTA_SALT,
        anonymous_burst_limit=1,
        anonymous_daily_limit=10,
        user_burst_limit=1,
        user_daily_limit=10,
    )


class EmptyHistory:
    """History surface needed by the Chat routes; no conversation is resumed."""

    async def get_conversation(self, user_id, conversation_id, *, product_scope):
        return None

    async def get_conversation_model_context(self, user_id, conversation_id, *, product_scope):
        return None

    async def append_exchange(self, user_id, conversation_id, user_text, assistant_text, project_id=None, *, product_scope):
        return conversation_id or ("chat_" + "1" * 32)


class B14Canary:
    """Fails loudly if a denied request is ever allowed to execute a model."""

    def __init__(self):
        self.calls = 0

    def _boom(self):
        self.calls += 1
        raise AssertionError("denied Chat request reached the signed platform key")

    async def stream_text_auto(self, messages, **kwargs):
        self._boom()
        yield _event("안녕하세요")
        yield _event(None, done=True)

    async def complete(self, messages, **kwargs):
        self._boom()
        return {"answer": "unreachable", "runtime": "test"}


class ScriptedB14:
    """Succeeds and counts every execution, for the allowed paths."""

    def __init__(self):
        self.calls = 0

    async def stream_text_auto(self, messages, **kwargs):
        self.calls += 1
        yield _event("안녕하세요")
        yield _event(None, done=True)

    async def complete(self, messages, **kwargs):
        self.calls += 1
        return {"answer": "정상 답변", "runtime": "test"}


def payload(**extra) -> dict[str, object]:
    body: dict[str, object] = {"messages": [{"role": "user", "content": "안녕하세요"}]}
    body.update(extra)
    return body


def build_app(*, runtime_mode: str = "b14"):
    app = create_app(settings(runtime_mode=runtime_mode), history_store=EmptyHistory())
    # The canary must stand in for the real signed platform key.
    assert isinstance(app.state.b14_client, B14Client)
    app.state.b14_client = B14Canary()
    return app


def build_enforced_app(*, store=None):
    """Production posture: the usage gate is enforcing even without a store."""
    app = create_app(quota_settings(), history_store=EmptyHistory(), usage_store=store)
    app.state.usage_gate_enforced = True
    assert isinstance(app.state.b14_client, B14Client)
    app.state.b14_client = B14Canary()
    return app


async def post(app, path: str, body, *, cookie: str | None = None, origin: str | None = None, client_ip: str | None = None):
    headers: dict[str, str] = {}
    if origin is not None:
        headers["Origin"] = origin
    if client_ip is not None:
        headers["cf-connecting-ip"] = client_ip
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url=ORIGIN) as client:
        if cookie is not None:
            client.cookies.set(SESSION_COOKIE, cookie, domain=BASE, path="/")
        return await client.post(path, json=body, headers=headers)


def assert_code(app, response: httpx.Response, *, expected_status: int, expected_code: str) -> None:
    assert response.status_code == expected_status, response.text
    data = response.json()
    assert data["error"]["code"] == expected_code
    assert app.state.b14_client.calls == 0


# --- 1. the enforcing gate stands in front of the platform key -------------


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("body", (
    payload(),
    payload(tier="free"),
    payload(tier="plus"),
    payload(custom={"provider": "custom-free", "model": "custom-free/gpt-5.5"}),
))
def test_guest_chat_is_refused_before_b14(path: str, body) -> None:
    app = build_app()
    response = asyncio.run(post(app, path, body, origin=ORIGIN))
    assert_code(app, response, expected_status=401, expected_code="login_required")


@pytest.mark.parametrize("path", PATHS)
def test_login_gate_precedes_the_usage_gate(path: str) -> None:
    """No quota store and no client IP: the login gate answers first, not 503."""
    app = build_enforced_app()
    response = asyncio.run(post(app, path, payload(tier="free"), origin=ORIGIN))
    assert_code(app, response, expected_status=401, expected_code="login_required")


# --- 2. signed-in members are unchanged and still quota-bounded ------------


@pytest.mark.parametrize("path", PATHS)
def test_signed_in_member_is_still_quota_bounded(path: str) -> None:
    app = create_app(quota_settings(), history_store=EmptyHistory(), usage_store=InMemoryUsageCounterStore())
    app.state.usage_gate_enforced = True
    scripted = ScriptedB14()
    app.state.b14_client = scripted
    cookie = create_session_token(quota_settings(), OWNER)

    first = asyncio.run(post(app, path, payload(), cookie=cookie, origin=ORIGIN, client_ip=CLIENT_IP))
    second = asyncio.run(post(app, path, payload(), cookie=cookie, origin=ORIGIN, client_ip=CLIENT_IP))

    assert first.status_code == 200, first.text
    assert scripted.calls == 1
    assert second.status_code == 429, second.text
    assert second.json()["error"]["code"] == "rate_limited"
    assert scripted.calls == 1


# --- 3. a dead cookie is a guest, and a guest gets the login gate ----------


@pytest.mark.parametrize("path", PATHS)
def test_signed_in_member_still_reaches_the_model(path: str) -> None:
    app = create_app(settings(), history_store=EmptyHistory())
    scripted = ScriptedB14()
    app.state.b14_client = scripted
    cookie = create_session_token(settings(), OWNER)
    response = asyncio.run(post(app, path, payload(), cookie=cookie, origin=ORIGIN))
    assert response.status_code == 200, response.text
    assert scripted.calls == 1


@pytest.mark.parametrize("path", PATHS)
def test_expired_or_tampered_session_is_not_identity(path: str) -> None:
    app = build_app()
    expired = create_session_token(settings(), OWNER, now=int(time.time()) - 7200)
    response = asyncio.run(post(app, path, payload(), cookie=expired, origin=ORIGIN))
    assert_code(app, response, expected_status=401, expected_code="login_required")

    token = create_session_token(settings(), OWNER)
    response = asyncio.run(post(app, path, payload(), cookie=token[:-4] + "AAAA", origin=ORIGIN))
    assert_code(app, response, expected_status=401, expected_code="login_required")


# --- 4. the login gate does not depend on the usage gate -------------------


@pytest.mark.parametrize("path", PATHS)
def test_development_posture_without_enforcing_gate_still_requires_login(path: str) -> None:
    """No enforcing gate means no local quota authority; login still applies."""

    app = create_app(settings(), history_store=EmptyHistory())
    assert app.state.usage_gate_enforced is False
    app.state.b14_client = B14Canary()
    response = asyncio.run(post(app, path, payload(), origin=ORIGIN))
    assert_code(app, response, expected_status=401, expected_code="login_required")


def test_mock_runtime_keeps_anonymous_chat_available() -> None:
    app = create_app(settings(runtime_mode="mock"), history_store=EmptyHistory())
    response = asyncio.run(post(app, "/api/chat", payload()))
    assert response.status_code == 200, response.text
