"""#5474: the anonymous Chat lane and the usage gate that bounds it.

Originally a verification suite: an anonymous request that omitted ``tier``
reached the usage gate while an explicit ``tier == "free"`` claim was answered
401 by the login check. The Owner decision of 2026-10-24 settles that
asymmetry in favour of anonymous Free on the Chat lane, so both claims now take
the same path and this module pins the resulting contract:

* The Production worker enforces the usage gate unconditionally
  (``worker.py`` sets ``app.state.usage_gate_enforced = True``) and the gate is
  evaluated in both routes before any B14 call. Without a quota store or a
  client IP it denies with 503 and makes zero provider calls.
* With a store bound, anonymous Free — explicit or defaulted — is bounded per
  real client IP and the second burst call is denied with 429 before B14.
* Paid tiers, Custom and projects still require a session: anonymous requests
  are answered 401 before any provider call.
* With no enforcing gate the request executes, which is the documented
  development-stage posture (``app_factory.py``: quotas disabled by default,
  provider-governed rather than locally quota-gated).
* Mock runtime keeps its anonymous harness behaviour.

Every test uses a canary B14 client: if any denied path executes a model, the
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
    body: dict[str, object] = {"messages": [{"role": "user", "content": "안녕하세요"}], "mode": "auto"}
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
def test_enforcing_gate_without_store_denies_anonymous_before_b14(path: str) -> None:
    app = build_enforced_app()
    response = asyncio.run(post(app, path, payload(), origin=ORIGIN))
    assert_code(app, response, expected_status=503, expected_code="live_abuse_gate_unavailable")


@pytest.mark.parametrize("path", PATHS)
def test_enforcing_gate_without_client_ip_denies_anonymous_before_b14(path: str) -> None:
    """Origin is present but there is no Cloudflare IP to attribute the call to."""

    app = build_enforced_app(store=InMemoryUsageCounterStore())
    response = asyncio.run(post(app, path, payload(), origin=ORIGIN))
    assert_code(app, response, expected_status=503, expected_code="live_identity_unavailable")


@pytest.mark.parametrize("path", PATHS)
def test_anonymous_access_is_rate_limited_before_b14(path: str) -> None:
    """The second burst call is denied before any further model execution."""

    app = create_app(quota_settings(), history_store=EmptyHistory(), usage_store=InMemoryUsageCounterStore())
    app.state.usage_gate_enforced = True
    scripted = ScriptedB14()
    app.state.b14_client = scripted

    first = asyncio.run(post(app, path, payload(), origin=ORIGIN, client_ip=CLIENT_IP))
    second = asyncio.run(post(app, path, payload(), origin=ORIGIN, client_ip=CLIENT_IP))

    assert first.status_code == 200, first.text
    assert scripted.calls == 1
    assert second.status_code == 429, second.text
    assert second.json()["error"]["code"] == "rate_limited"
    assert scripted.calls == 1


# --- 2. anonymous Free, explicit or defaulted, shares one bounded path -----


@pytest.mark.parametrize("path", PATHS)
def test_explicit_free_tier_reaches_the_usage_gate_before_b14(path: str) -> None:
    app = build_enforced_app(store=InMemoryUsageCounterStore())
    response = asyncio.run(post(app, path, payload(tier="free"), origin=ORIGIN))
    assert_code(app, response, expected_status=503, expected_code="live_identity_unavailable")


@pytest.mark.parametrize("path", PATHS)
def test_explicit_free_tier_is_quota_bounded_for_anonymous_callers(path: str) -> None:
    app = create_app(quota_settings(), history_store=EmptyHistory(), usage_store=InMemoryUsageCounterStore())
    app.state.usage_gate_enforced = True
    scripted = ScriptedB14()
    app.state.b14_client = scripted

    first = asyncio.run(post(app, path, payload(tier="free"), origin=ORIGIN, client_ip=CLIENT_IP))
    second = asyncio.run(post(app, path, payload(tier="free"), origin=ORIGIN, client_ip=CLIENT_IP))

    assert first.status_code == 200, first.text
    assert scripted.calls == 1
    assert second.status_code == 429, second.text
    assert second.json()["error"]["code"] == "rate_limited"
    assert scripted.calls == 1


@pytest.mark.parametrize("path", PATHS)
def test_omitted_tier_reaches_the_usage_gate_instead_of_the_login_gate(path: str) -> None:
    """Pinning the shared path: the omitted claim is not blocked by a login gate."""

    app = build_enforced_app(store=InMemoryUsageCounterStore())
    response = asyncio.run(post(app, path, payload()))
    assert_code(app, response, expected_status=503, expected_code="live_identity_unavailable")


@pytest.mark.parametrize("path", PATHS)
def test_anonymous_paid_tier_still_requires_login(path: str) -> None:
    app = build_app()
    response = asyncio.run(post(app, path, payload(tier="plus"), origin=ORIGIN))
    assert_code(app, response, expected_status=401, expected_code="unauthorized")


# --- 3. the gate must not over-block a signed-in member ---------------------


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
    response = asyncio.run(post(app, path, payload(tier="plus"), cookie=expired, origin=ORIGIN))
    assert_code(app, response, expected_status=401, expected_code="unauthorized")

    token = create_session_token(settings(), OWNER)
    response = asyncio.run(post(app, path, payload(tier="plus"), cookie=token[:-4] + "AAAA", origin=ORIGIN))
    assert_code(app, response, expected_status=401, expected_code="unauthorized")


@pytest.mark.parametrize("path", PATHS)
def test_expired_session_behaves_as_anonymous_free(path: str) -> None:
    """A dead cookie is no identity, so Free lands on the anonymous usage gate."""

    app = build_enforced_app(store=InMemoryUsageCounterStore())
    expired = create_session_token(settings(), OWNER, now=int(time.time()) - 7200)
    response = asyncio.run(post(app, path, payload(tier="free"), cookie=expired, origin=ORIGIN))
    assert_code(app, response, expected_status=503, expected_code="live_identity_unavailable")


@pytest.mark.parametrize("path", PATHS)
def test_custom_selection_cannot_reach_the_platform_key_without_a_session(path: str) -> None:
    app = build_app()
    response = asyncio.run(
        post(app, path, payload(custom={"provider": "custom-free", "model": "custom-free/gpt-5.5"}), origin=ORIGIN)
    )
    assert_code(app, response, expected_status=401, expected_code="unauthorized")


# --- 4. the documented development-stage posture -----------------------------


@pytest.mark.parametrize("path", PATHS)
def test_development_posture_without_enforcing_gate_executes_anonymously(path: str) -> None:
    """No enforcing gate means no local billing authority, so the request runs."""

    app = create_app(settings(), history_store=EmptyHistory())
    assert app.state.usage_gate_enforced is False
    scripted = ScriptedB14()
    app.state.b14_client = scripted
    response = asyncio.run(post(app, path, payload(), origin=ORIGIN))
    assert response.status_code == 200, response.text
    assert scripted.calls == 1


def test_mock_runtime_keeps_anonymous_chat_available() -> None:
    app = create_app(settings(runtime_mode="mock"), history_store=EmptyHistory())
    response = asyncio.run(post(app, "/api/chat", payload()))
    assert response.status_code == 200, response.text
