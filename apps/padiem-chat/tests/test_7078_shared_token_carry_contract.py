"""#7078 — pin the contract behind "the shared token is issued and observable".

The #7294 shadow sample (30 min, N=355) recorded zero requests carrying
``__Host-padiem-shared-access``. Code trace shows the issuance chain (callback
-> token exchange -> cookie set), the periodic/on-401 refresh and the
cached-JWKS local verify are intact, and that a token-carrying request is
classified by the shadow comparator as a token request. These tests pin that
contract so the carry-chain cannot silently regress; they are the "switch off =
today's behavior, switch on = token visible to shadow" checks.

No runtime behavior is changed: the shadow switch stays default-off and the
issuance path keeps its existing cookie names, attributes and lifetimes.
"""

from __future__ import annotations

import io
import time
from contextlib import redirect_stdout
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from starlette.responses import RedirectResponse
from starlette.testclient import TestClient

from app import auth as auth_mod
from app import auth_shadow_verify as shadow
from app.app_factory import create_app
from app.config import Settings
from app.shared_login_flow import (
    ACCESS_COOKIE,
    ACCESS_SECONDS,
    LOGIN_RETURN_COOKIE,
    MARKER_COOKIE,
    REFRESH_COOKIE,
    REFRESH_SECONDS,
    SharedLoginFlow,
    issue_shared_cookies,
)


class Flow:
    """Minimal composition for the callback/refresh issue plumbing."""

    def __init__(self):
        self.auth = self

    async def user_id(self, request, token):
        return "usr_shared" if token in ("access-one", "access-two") else None


class Crypto:
    async def sign(self, key, data):
        return b"x" * 64


def _issue_and_exchange():
    async def exchange(url, data):
        if data["grant_type"] == "authorization_code":
            return {"access_token": "access-one", "refresh_token": "refresh-one"}
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "refresh-one"
        return {"access_token": "access-two", "refresh_token": "refresh-two"}

    async def issue(request, user, access, refresh):
        return issue_shared_cookies(RedirectResponse("/", status_code=302), access, refresh)

    return exchange, issue


def make_app(flow=None, *, history_store=None):
    settings = Settings.from_values(
        runtime_mode="mock",
        auth_mode="off",
        session_secret="test-secret-for-session",
        # The refresh/logout mutations are cookie-authenticated browser POSTs,
        # so the same-origin guard needs the reviewed origin these tests
        # already send as their Origin header.
        public_base_url="https://chat.padiem.net",
    )
    app = create_app(settings=settings, shared_login_flow=flow, history_store=history_store)
    return app, settings


def _set_cookie_values(response):
    """Set-Cookie payloads as strings (header list, order preserved)."""
    getter = getattr(response.headers, "multi_items", None)
    if not callable(getter):
        return []
    return [value for key, value in getter() if str(key).lower() == "set-cookie"]


def _cookie_value(payloads, name):
    prefix = name.lower() + "="
    for payload in payloads:
        first = payload.split(";", 1)[0].strip()
        if first.lower().startswith(prefix):
            return first[len(prefix):].strip()
    return None


def _payload_with(payloads, name):
    prefix = name.lower() + "="
    for payload in payloads:
        first = payload.split(";", 1)[0].strip()
        if first.lower().startswith(prefix):
            return payload
    raise AssertionError(f"no Set-Cookie for {name} in {payloads!r}")


def _assert_cookie_attributes(payload, *, max_age, path):
    lowered = payload.lower()
    assert "secure" in lowered
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert f"path={path}" in lowered
    assert f"max-age={max_age}" in lowered
    assert "domain=" not in lowered, "host-only cookie must not carry a Domain attribute"


def _build_flow(exchange, issue, *, client_jwk=None):
    auth = Flow()
    flow = SharedLoginFlow(
        state_key=b"x" * 32,
        client_id="b62",
        kid="test-kid",
        client_jwk=client_jwk
        or {"kty": "EC", "crv": "P-256", "x": "x", "y": "y", "d": "d"},
        operator_guard=lambda request: True,
        legacy_user=lambda request: None,
        comparator=lambda *args: None,
        exchange=exchange,
        crypto=Crypto(),
        resolve_account=auth.user_id,
        issue_session=issue,
        revoke_session=lambda data: None,
    )
    flow.auth = auth
    return flow


def test_callback_issues_shared_cookie_set():
    """Callback response issues the token trio with the expected cookie shape."""
    exchange, issue = _issue_and_exchange()
    app, _ = make_app(_build_flow(exchange=exchange, issue=issue))
    with TestClient(app, base_url="https://chat.padiem.net") as client:
        start = client.get("/auth/shared/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        callback = client.get(
            "/auth/shared/callback",
            params={"state": state, "code": "synthetic-code"},
            follow_redirects=False,
        )
        assert callback.status_code == 302

    payloads = _set_cookie_values(callback)
    assert _cookie_value(payloads, ACCESS_COOKIE) == "access-one"
    _assert_cookie_attributes(
        _payload_with(payloads, ACCESS_COOKIE), max_age=ACCESS_SECONDS, path="/"
    )
    assert _cookie_value(payloads, REFRESH_COOKIE) == "refresh-one"
    _assert_cookie_attributes(
        _payload_with(payloads, REFRESH_COOKIE), max_age=REFRESH_SECONDS, path="/auth/shared"
    )
    assert _cookie_value(payloads, MARKER_COOKIE) == "1"
    _assert_cookie_attributes(
        _payload_with(payloads, MARKER_COOKIE), max_age=REFRESH_SECONDS, path="/"
    )


def test_refresh_reissues_the_access_cookie():
    """The 401/periodic refresh re-sets the token trio against the live flow."""
    exchange, issue = _issue_and_exchange()
    app, _ = make_app(_build_flow(exchange=exchange, issue=issue))
    with TestClient(app, base_url="https://chat.padiem.net") as client:
        start = client.get("/auth/shared/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        callback = client.get(
            "/auth/shared/callback",
            params={"state": state, "code": "synthetic-code"},
            follow_redirects=False,
        )
        assert callback.status_code == 302
        assert _cookie_value(_set_cookie_values(callback), REFRESH_COOKIE) == "refresh-one"
        response = client.post(
            "/auth/shared/refresh", headers={"origin": "https://chat.padiem.net"}
        )
        assert response.status_code == 200
        payloads = _set_cookie_values(response)
    assert _cookie_value(payloads, ACCESS_COOKIE) == "access-two"
    assert _cookie_value(payloads, REFRESH_COOKIE) == "refresh-two"
    _assert_cookie_attributes(
        _payload_with(payloads, ACCESS_COOKIE), max_age=ACCESS_SECONDS, path="/"
    )


class FakeVerifier:
    def __init__(self, *, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.calls = 0

    def verify(self, token):
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return dict(self._result or {})


def _scope_with_token(settings, user_id="usr_" + "a" * 32):
    legacy = auth_mod.create_session_token(
        settings, user_id, canonical_session_id="sess_" + "1" * 32
    )
    headers = [
        (b"cookie", f"{auth_mod.SESSION_COOKIE}={legacy}; {ACCESS_COOKIE}=synthetic-access".encode())
    ]
    return {
        "type": "http",
        "headers": headers,
        "app": SimpleNamespace(state=SimpleNamespace(settings=settings)),
        "state": {"padiem_shared_user_id": user_id},
    }


def _verdict(authenticated=True):
    return SimpleNamespace(
        authenticated=authenticated,
        user_id="usr_" + "a" * 32,
        canonical_session_id="sess_" + "1" * 32,
        reason="active",
    )


def _run_compare(monkeypatch, scope, verdict, verifier):
    monkeypatch.setattr(shadow, "_get_shadow_verifier", lambda: verifier)
    buf = io.StringIO()
    with redirect_stdout(buf):
        shadow.run_shadow_compare(scope, verdict)
    return buf.getvalue().strip().splitlines()


def test_shadow_sees_token_on_token_carrying_scope(monkeypatch):
    """When a request carries the token, stage-1 records it as a token request."""
    monkeypatch.setenv("PADIEM_AUTH_LOCAL_VERIFY_SHADOW", "true")
    settings = Settings(session_secret="s" * 32, session_max_age_seconds=7 * 24 * 3600)
    verifier = FakeVerifier(
        result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600}
    )
    lines = _run_compare(monkeypatch, _scope_with_token(settings), _verdict(True), verifier)
    assert verifier.calls == 1
    fields = lines[0].split()
    assert "outcome=match" in fields
    assert "token=present" in fields
    assert "local_ok=yes" in fields


def test_shadow_switch_off_stays_inert_with_token_present(monkeypatch):
    """With the switch off the token-carrying request is unaffected, as today."""
    monkeypatch.delenv("PADIEM_AUTH_LOCAL_VERIFY_SHADOW", raising=False)
    settings = Settings(session_secret="s" * 32, session_max_age_seconds=7 * 24 * 3600)
    verifier = FakeVerifier(
        result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600}
    )
    lines = _run_compare(monkeypatch, _scope_with_token(settings), _verdict(True), verifier)
    assert verifier.calls == 0
    assert lines == []


def test_callback_cookie_jar_reaches_chat_api_and_shadow_reports_token(monkeypatch):
    """아르곤 보강 1: 콜백 Set-Cookie -> 쿠키 자 -> Chat /api -> 그림자 token=present.

    TestClient 쿠키 자가 Set-Cookie를 순방향 전달하고, 그림자 비교기가 그 요청의
    Cookie 헤더에서 토큰을 실제로 읽는지까지 이어 붙인다(주입이 아니라 자 경유).
    오프라인 한계: 검증기는 픽스처로 대체하며, 레거시 쿠키가 없어 verdict는
    none -> outcome=verdict_none_local_ok (실서비스 매치 판정은 라이브 표본 소관).
    """
    monkeypatch.setenv("PADIEM_AUTH_LOCAL_VERIFY_SHADOW", "true")
    exchange, issue = _issue_and_exchange()
    app, _ = make_app(_build_flow(exchange=exchange, issue=issue))
    verifier = FakeVerifier(
        result={"accountId": "sub_" + "b" * 20, "sessionId": "s" * 10, "expiresAt": int(time.time()) + 600}
    )
    monkeypatch.setattr(shadow, "_get_shadow_verifier", lambda: verifier)
    with TestClient(app, base_url="https://chat.padiem.net") as client:
        start = client.get("/auth/shared/start", follow_redirects=False)
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        callback = client.get(
            "/auth/shared/callback",
            params={"state": state, "code": "synthetic-code"},
            follow_redirects=False,
        )
        assert callback.status_code == 302
        payloads = _set_cookie_values(callback)
        access = _cookie_value(payloads, ACCESS_COOKIE)
        assert access is not None
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert client.get(
                "/api/auth/status", cookies={ACCESS_COOKIE: access}
            ).status_code == 200
    lines = buf.getvalue().strip().splitlines()
    assert any("shadow_verify" in line and "token=present" in line
               and "local_ok=yes" in line for line in lines), lines
