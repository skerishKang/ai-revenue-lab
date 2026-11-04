"""LoveTree 4.0 sign-in handoff through the real Google callback.

These tests drive ``lovetree_handoff_start`` and ``app.auth_routes.google_callback`` with a
stubbed Google transport and stubbed B62 session-shadow helpers. What they pin:

* the row is created only for an allowlisted return origin and only for the login request
  LoveTree started with, and nothing is written to the browser;
* the identity that reaches the row is the one this Worker just verified from Google
  (userinfo subject + the upsert profile id) — never a value a request supplied;
* the handoff browser gets no ``padiem_session`` cookie; it gets one ticket, once, back to
  the recorded origin with the login request that created it;
* a signed state for a used, expired, or unknown row, and a plain forged state, never
  reach the bind step;
* the pre-existing OAuth-state rejection and the Android handoff branch stay intact.
"""

from __future__ import annotations

import json
import types
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app import auth_routes
from app.auth import (
    GOOGLE_TOKEN_URL,
    GOOGLE_USERINFO_URL,
    OAUTH_STATE_COOKIE,
    SESSION_COOKIE,
    GoogleOAuthClient,
    create_lovetree_handoff_state,
    verify_lovetree_handoff_state,
)
from app.config import Settings
from app.lovetree_auth_routes import (
    LOVETREE_HANDOFF_CALLBACK_PATH,
    allowed_return_origin,
    bind_lovetree_handoff,
    load_lovetree_handoff_for_callback,
    lovetree_handoff_start,
    return_to_lovetree,
)
from app.password_auth import hash_password, normalize_email
from app.lovetree_auth_store import (
    HANDOFF_STATUS_AWAITING_LOGIN,
    HANDOFF_STATUS_READY,
    InMemoryLoveTreeLoginHandoffStore,
    handoff_digest,
)

SECRET = "l" * 48
CHAT_ORIGIN = "https://chat.example.test"
LOVETREE_ORIGIN = "https://lovetree-4-0.pages.dev"
LOGIN_REQUEST = "abc123DEF456ghi789JKL012"
OTHER_LOGIN_REQUEST = "zzz999YYY888xxx777WWW666"
VERIFIED_SUBJECT = "11223344556677889900"
PROFILE_ID = "usr_lovetree_profile"


def payload(response) -> dict:
    return json.loads(response.body.decode("utf-8"))


def _settings() -> Settings:
    return Settings(
        runtime_mode="test",
        auth_mode="google",
        public_base_url=CHAT_ORIGIN,
        google_client_id="client-id",
        google_client_secret="client-secret",
        session_secret=SECRET,
    )


class _Profile:
    id = PROFILE_ID


class _HistoryStore:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def upsert_google_user(self, subject, email, name, picture):
        self.calls.append((subject, email, name, picture))
        return _Profile()


def _transport(calls: list[str], *, subject: str = VERIFIED_SUBJECT) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == GOOGLE_TOKEN_URL:
            return httpx.Response(200, json={"access_token": "at", "token_type": "Bearer", "expires_in": 3600})
        if str(request.url) == GOOGLE_USERINFO_URL:
            return httpx.Response(
                200,
                json={"id": subject, "email": "attacker-supplied@example.test", "verified_email": True, "name": "LoveTree User", "picture": ""},
            )
        return httpx.Response(404, json={})

    return httpx.MockTransport(handler)


def _request(app: object, path: str, query: dict[str, str] | None = None, cookies: dict[str, str] | None = None) -> "auth_routes.Request":
    from starlette.requests import Request

    headers = [(b"host", CHAT_ORIGIN.split("//")[1].encode())]
    if cookies:
        headers.append((b"cookie", "; ".join(f"{k}={v}" for k, v in cookies.items()).encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": "&".join(f"{k}={v}" for k, v in (query or {}).items()).encode(),
        "headers": headers,
        "scheme": "https",
        "app": app,
    }
    return Request(scope)


def _app(*, store=None, oauth=None, settings=None, history=None) -> types.SimpleNamespace:
    state = types.SimpleNamespace(
        settings=settings or _settings(),
        google_oauth=oauth,
        history_store=history,
        android_handoff_store=None,
        lovetree_handoff_store=store,
    )
    return types.SimpleNamespace(state=state)


@pytest.fixture
def shadowless(monkeypatch):
    """The B62 session-shadow helpers are not under test and must not run here."""
    async def _noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(auth_routes, "_write_identity_shadow_after_login", _noop)
    monkeypatch.setattr(auth_routes, "establish_b54_canonical_session_after_google_login", _noop)
    monkeypatch.setattr(auth_routes, "establish_b54_canonical_session_after_login", _noop)
    monkeypatch.setattr(auth_routes, "deliver_after_signup", _noop)


async def _start(app) -> tuple[int, dict[str, str], dict]:
    response = await lovetree_handoff_start(
        _request(app, "/auth/lovetree/start", {"state": LOGIN_REQUEST, "return_origin": LOVETREE_ORIGIN})
    )
    return response.status_code, dict(response.headers), response


@pytest.mark.asyncio
async def test_start_records_the_request_and_sends_the_browser_to_google(shadowless) -> None:
    store = InMemoryLoveTreeLoginHandoffStore()
    calls: list[str] = []
    app = _app(
        store=store,
        oauth=GoogleOAuthClient(app_settings := _settings(), transport=_transport(calls)),
        history=_HistoryStore(),
    )
    status, headers, _ = await _start(app)

    assert status == 302
    target = urlparse(headers["location"])
    assert target.scheme == "https" and target.netloc == "accounts.google.com"
    query = parse_qs(target.query)
    # Google의 redirect_uri는 기존 채팅 콜백 하나. 러브트리를 위한 새 공개 표면이 아니다.
    assert query["redirect_uri"] == [f"{CHAT_ORIGIN}/auth/google/callback"]
    signed = query["state"][0]
    assert verify_lovetree_handoff_state(app_settings, signed) == (
        [ticket for ticket in store.records][0],
        LOGIN_REQUEST,
    )
    record = await store.get(list(store.records)[0])
    assert record.status == HANDOFF_STATUS_AWAITING_LOGIN
    assert record.state_sha256 == handoff_digest(LOGIN_REQUEST)
    assert record.return_origin == LOVETREE_ORIGIN
    assert "set-cookie" not in headers, "start는 브라우저에 어떤 쿠키도 심지 않는다"


@pytest.mark.asyncio
async def test_start_closes_on_bad_request_origin_and_store(shadowless) -> None:
    store = InMemoryLoveTreeLoginHandoffStore()
    oauth = GoogleOAuthClient(_settings(), transport=_transport([]))

    short = await lovetree_handoff_start(
        _app(store=store, oauth=oauth, history=_HistoryStore())
        and _request(_app(store=store, oauth=oauth, history=_HistoryStore()), "/auth/lovetree/start",
                     {"state": "short", "return_origin": LOVETREE_ORIGIN})
    )
    assert short.status_code == 400
    assert payload(short)["error"]["code"] == "invalid_lovetree_login_request"

    evil = await lovetree_handoff_start(
        _request(_app(store=store, oauth=oauth, history=_HistoryStore()), "/auth/lovetree/start",
                 {"state": LOGIN_REQUEST, "return_origin": "https://evil.example"})
    )
    assert evil.status_code == 400
    assert payload(evil)["error"]["code"] == "invalid_lovetree_return_origin"

    open_redirect = await lovetree_handoff_start(
        _request(_app(store=store, oauth=oauth, history=_HistoryStore()), "/auth/lovetree/start",
                 {"state": LOGIN_REQUEST, "return_origin": LOVETREE_ORIGIN + "/steal"})
    )
    assert open_redirect.status_code == 400

    no_store = await lovetree_handoff_start(
        _request(_app(store=None, oauth=oauth, history=_HistoryStore()), "/auth/lovetree/start",
                 {"state": LOGIN_REQUEST, "return_origin": LOVETREE_ORIGIN})
    )
    assert no_store.status_code == 503
    assert allowed_return_origin("http://evil.example") is None


@pytest.mark.asyncio
async def test_verified_google_login_returns_one_ticket_and_no_padiem_session(shadowless) -> None:
    store = InMemoryLoveTreeLoginHandoffStore()
    calls: list[str] = []
    settings = _settings()
    history = _HistoryStore()
    app = _app(store=store, oauth=GoogleOAuthClient(settings, transport=_transport(calls)), history=history)
    _, headers, _ = await _start(app)
    signed = parse_qs(urlparse(headers["location"]).query)["state"][0]
    ticket = list(store.records)[0]

    back = await auth_routes.google_callback(
        _request(app, "/auth/google/callback", {"code": "google-code", "state": signed})
    )

    assert back.status_code == 302
    location = urlparse(back.headers["location"])
    assert f"{location.scheme}://{location.netloc}" == LOVETREE_ORIGIN
    assert location.path == LOVETREE_HANDOFF_CALLBACK_PATH
    assert parse_qs(location.query) == {"code": [ticket], "state": [LOGIN_REQUEST]}
    cookie_headers = [value for key, value in back.headers.items() if key.lower() == "set-cookie"]
    assert not any(SESSION_COOKIE in value for value in cookie_headers), 'handoff 브라우저에는 채팅 세션을 심지 않는다'

    record = await store.get(ticket)
    assert record.status == HANDOFF_STATUS_READY
    # 실행된 신원은 권위가 확인한 값뿐: userinfo subject + upsert profile id.
    assert (record.provider_subject, record.pending_user_id, record.auth_provider) == (
        VERIFIED_SUBJECT, PROFILE_ID, "google"
    )
    assert history.calls and history.calls[0][0] == VERIFIED_SUBJECT
    assert "attacker-supplied@example.test" not in repr(record), "이메일은 발급 근거가 아니다"


@pytest.mark.asyncio
async def test_a_state_that_is_not_ours_still_rejects_and_never_binds(shadowless) -> None:
    store = InMemoryLoveTreeLoginHandoffStore()
    settings = _settings()
    calls: list[str] = []
    app = _app(store=store, oauth=GoogleOAuthClient(settings, transport=_transport(calls)), history=_HistoryStore())

    forged = await auth_routes.google_callback(
        _request(app, "/auth/google/callback", {"code": "google-code", "state": "not-a-signed-state"})
    )
    assert forged.status_code == 400
    assert payload(forged)["error"]["code"] == "invalid_oauth_state"
    assert calls == [], "거부된 요청은 Google code를 맞교환하지 않는다"
    assert store.records == {}

    # 서명은 유효하지만 행이 없는(재시작·삭제) 상태는 사용 거부로 닫힌다.
    signed_orphan = create_lovetree_handoff_state(settings, "lovt_" + "q" * 20, LOGIN_REQUEST)
    orphan = await auth_routes.google_callback(
        _request(app, "/auth/google/callback", {"code": "google-code", "state": signed_orphan})
    )
    assert orphan.status_code == 400
    assert payload(orphan)["error"]["code"] == "invalid_lovetree_handoff"


@pytest.mark.asyncio
async def test_a_handoff_row_cannot_be_bound_or_returned_twice(shadowless) -> None:
    store = InMemoryLoveTreeLoginHandoffStore()
    settings = _settings()
    app = _app(store=store, oauth=GoogleOAuthClient(settings, transport=_transport([])), history=_HistoryStore())
    _, headers, _ = await _start(app)
    signed = parse_qs(urlparse(headers["location"]).query)["state"][0]
    ticket = list(store.records)[0]

    first = await auth_routes.google_callback(
        _request(app, "/auth/google/callback", {"code": "google-code", "state": signed})
    )
    assert first.status_code == 302

    second = await auth_routes.google_callback(
        _request(app, "/auth/google/callback", {"code": "google-code", "state": signed})
    )
    assert second.status_code == 400
    assert payload(second)["error"]["code"] == "lovetree_handoff_used"

    pending, refused = await load_lovetree_handoff_for_callback(_request(app, "/auth/google/callback"), signed)
    assert pending is None and refused is not None

    # 남의 로그인 요청 해시로도 bind·return은 성립하지 않는다.
    request = _request(app, "/auth/google/callback")
    other = types.SimpleNamespace(record=await store.get(ticket), login_request=OTHER_LOGIN_REQUEST)
    assert await bind_lovetree_handoff(
        request, other, user_id="usr_x", auth_provider="google", provider_subject="other-subject"
    ) is False
    late = await return_to_lovetree(request, other)
    assert late.status_code == 503


@pytest.mark.asyncio
async def test_expired_row_is_refused_at_the_callback(shadowless) -> None:
    store = InMemoryLoveTreeLoginHandoffStore()
    settings = _settings()
    app = _app(store=store, oauth=GoogleOAuthClient(settings, transport=_transport([])), history=_HistoryStore())
    _, headers, _ = await _start(app)
    signed = parse_qs(urlparse(headers["location"]).query)["state"][0]
    ticket = list(store.records)[0]

    # 같은 표·같은 요청이지만 만료 시각이 지났다.
    live = await store.get(ticket)
    store.records[ticket] = replace(live, expires_at="2000-01-01T00:00:00Z")

    refused = await auth_routes.google_callback(
        _request(app, "/auth/google/callback", {"code": "google-code", "state": signed})
    )
    assert refused.status_code == 400
    assert payload(refused)["error"]["code"] == "lovetree_handoff_expired"

class _User:
    id = PROFILE_ID

    def public_dict(self):
        return {"id": PROFILE_ID, "name": "LoveTree User"}


class _PasswordStore:
    """The six callables the password routes insist on, with one real credential."""

    def __init__(self, *, password: str, identifier: str, user=_User()) -> None:
        self.username = normalize_email(identifier)
        self.user = user
        self.failures: list[str] = []
        self.resets = 0
        self.password_hash = hash_password(password)

    async def find_password_credential(self, identifier):
        if identifier != self.username:
            return None
        return types.SimpleNamespace(
            user=self.user,
            username=self.username,
            password_hash=self.password_hash,
            failed_attempts=0,
            locked_until=None,
        )

    async def find_password_credential_by_user_id(self, user_id):
        return None

    async def register_password_user(self, *args, **kwargs):
        raise AssertionError("not used by login")

    async def update_password_credential(self, *args, **kwargs):
        raise AssertionError("not used by login")

    async def record_password_failure(self, user_id, failures, lock_until):
        self.failures.append(str(user_id))

    async def reset_password_failures(self, user_id):
        self.resets += 1

    async def upsert_google_user(self, subject, email, name, picture):
        self.calls.append((subject, email, name, picture))
        return _Profile()


PASSWORD = "a-verified-password-1234"
IDENTIFIER = "lovetree@example.test"


def _password_app(store, *, settings=None):
    made = settings or Settings(
        runtime_mode="test", auth_mode="password", public_base_url=CHAT_ORIGIN, session_secret=SECRET
    )
    return _app(store=store, oauth=None, settings=made, history=_PasswordStore(password=PASSWORD, identifier=IDENTIFIER))


def _post(app, path: str, payload: dict):
    from starlette.requests import Request

    body = json.dumps(payload).encode("utf-8")
    scope = {
        "type": "http", "method": "POST", "path": path, "raw_path": path.encode(),
        "query_string": b"", "scheme": "https", "app": app,
        "headers": [
            (b"host", CHAT_ORIGIN.split("//")[1].encode()),
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
        ],
    }
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


async def _password_handoff(app) -> tuple[str, str]:
    """Start a LoveTree login on a password-only deployment and return (signed, ticket)."""
    status, headers, _ = await _start(app)
    assert status == 302
    # 화면도 문구도 아닌, 기존 로그인 페이지로만 보낸다.
    location = headers["location"]
    assert location.startswith(f"{CHAT_ORIGIN}/?")
    signed = parse_qs(urlparse(location).query)["handoff"][0]
    return signed, list(app.state.lovetree_handoff_store.records)[0]


@pytest.mark.asyncio
async def test_verified_password_login_binds_the_handoff_and_returns_the_hop(shadowless) -> None:
    store = InMemoryLoveTreeLoginHandoffStore()
    app = _password_app(store)
    signed, ticket = await _password_handoff(app)

    back = await auth_routes.password_login(_post(app, "/api/auth/password/login", {
        "identifier": IDENTIFIER, "password": PASSWORD, "handoff": signed
    }))

    assert back.status_code == 200
    body = payload(back)
    assert body["ok"] is True
    location = urlparse(body["handoff_return"])
    assert f"{location.scheme}://{location.netloc}" == LOVETREE_ORIGIN
    assert location.path == LOVETREE_HANDOFF_CALLBACK_PATH
    assert parse_qs(location.query) == {"code": [ticket], "state": [LOGIN_REQUEST]}
    record = await store.get(ticket)
    assert record.status == HANDOFF_STATUS_READY
    assert (record.auth_provider, record.pending_user_id, record.provider_subject) == (
        "password", PROFILE_ID, normalize_email(IDENTIFIER)
    )
    assert any("padiem_session=" in value for key, value in back.headers.items() if key.lower() == "set-cookie")


@pytest.mark.asyncio
async def test_a_failed_password_login_never_binds_or_returns_a_ticket(shadowless) -> None:
    store = InMemoryLoveTreeLoginHandoffStore()
    app = _password_app(store)
    signed, ticket = await _password_handoff(app)

    for body_payload in (
        {"identifier": IDENTIFIER, "password": "wrong-password", "handoff": signed},
        {"identifier": "nobody@example.test", "password": PASSWORD, "handoff": signed},
        {"identifier": IDENTIFIER, "password": "", "handoff": signed},
    ):
        refused = await auth_routes.password_login(_post(app, "/api/auth/password/login", body_payload))
        assert refused.status_code == 401
        assert "handoff_return" not in payload(refused)

    record = await store.get(ticket)
    assert record.status == HANDOFF_STATUS_AWAITING_LOGIN, "실패한 로그인은 행을 진행시키지 않는다"
    assert record.pending_user_id is None

    # 표가 남아 있으므로 실제 성공 로그인은 그 뒤에도 견착된다.
    ok = await auth_routes.password_login(_post(app, "/api/auth/password/login", {
        "identifier": IDENTIFIER, "password": PASSWORD, "handoff": signed
    }))
    assert payload(ok)["handoff_return"].startswith(LOVETREE_ORIGIN)


@pytest.mark.asyncio
async def test_password_handoff_refusals_and_unchanged_login(shadowless) -> None:
    store = InMemoryLoveTreeLoginHandoffStore()
    app = _password_app(store)
    signed, ticket = await _password_handoff(app)

    # 로그인 창을 그냥 쓴 사용자는 전과 동일한 응답을 받는다.
    plain = await auth_routes.password_login(_post(app, "/api/auth/password/login", {
        "identifier": IDENTIFIER, "password": PASSWORD
    }))
    assert plain.status_code == 200
    assert "handoff_return" not in payload(plain)
    assert (await store.get(ticket)).status == HANDOFF_STATUS_AWAITING_LOGIN

    # 위조·남의 요청·이미 사용·행 없는 값은 모두 견착 없이 로그인만 성립한다.
    for junk in ("not-signed", signed[:-2], "lovt_" + "z" * 20):
        again = await auth_routes.password_login(_post(app, "/api/auth/password/login", {
            "identifier": IDENTIFIER, "password": PASSWORD, "handoff": junk
        }))
        assert again.status_code == 200
        assert "handoff_return" not in payload(again)

    used = await auth_routes.password_login(_post(app, "/api/auth/password/login", {
        "identifier": IDENTIFIER, "password": PASSWORD, "handoff": signed
    }))
    assert "handoff_return" in payload(used)
    replay = await auth_routes.password_login(_post(app, "/api/auth/password/login", {
        "identifier": IDENTIFIER, "password": PASSWORD, "handoff": signed
    }))
    assert "handoff_return" not in payload(replay), "한 번 쓰인 표는 다시 견착되지 않는다"
