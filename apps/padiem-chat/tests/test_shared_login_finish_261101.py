"""Offline common-login completion against the host's actual identity transport."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.d1_sqlite import SqliteD1, connect
from app.history import D1HistoryStore, _user_id
from app.local_service_bridge import HttpRpcBinding
from app.shared_auth_adapter import SharedChatAuth
from app.shared_auth_compare_flow import _b64, _encoded
from app.shared_login_flow import ACCESS_COOKIE, STATE_COOKIE, SharedLoginFlow
from app.shared_profile_provision import provision_shared_profile


ACCOUNT = "sub_synthetic_finish_identity"
GOOGLE_SUBJECT = "synthetic-google-finish-subject"
ACCESS = "synthetic-finish-access-not-for-logs"
REFRESH = "synthetic-finish-refresh-not-for-logs"
CODE = "synthetic-finish-code-not-for-logs"
PRIVATE = "synthetic-private-exception-not-for-logs"
PROFILE = {"email": "synthetic-finish@example.invalid", "email_verified": True,
           "name": "Synthetic Private Name", "picture": ""}
PRODUCT_UA = "PADIEM-Chat/1.0 (+https://chat.padiem.net)"


def request(query="", cookie=""):
    return Request({"type": "http", "method": "GET", "path": "/auth/shared/callback",
                    "query_string": query.encode(), "headers": [(b"cookie", cookie.encode())]})


class Crypto:
    async def sign(self, key, data):
        return b"x" * 64


class Verifier:
    async def verify(self, token):
        assert token == ACCESS
        return {"accountId": ACCOUNT, "expiresAt": 2000}


async def exchange(*args):
    return {"access_token": ACCESS, "refresh_token": REFRESH,
            "account_id": ACCOUNT, "profile": dict(PROFILE)}


async def issue(*args):
    return RedirectResponse("/", status_code=302)


def make_flow(**overrides):
    values = dict(state_key=b"x" * 32, client_id="b62", kid="synthetic",
                  client_jwk={"kty": "EC", "crv": "P-256", "x": "x", "y": "y", "d": "d"},
                  operator_guard=lambda _: True, legacy_user=lambda _: None,
                  comparator=lambda *args: None, exchange=exchange, crypto=Crypto(),
                  resolve_account=lambda *args: _user_id(GOOGLE_SUBJECT),
                  issue_session=issue, clock=lambda: 1000)
    values.update(overrides)
    return SharedLoginFlow(**values)


async def callback_request(flow):
    start = await flow.start_login(request())
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return request(urlencode({"state": state, "code": CODE}),
                   start.headers["set-cookie"].split(";", 1)[0])


def assert_reason_only(caplog, stage, code):
    records = [record for record in caplog.records if record.name == "app.shared_login_flow"]
    assert [record.getMessage() for record in records] == [
        f"shared_login_finish_failed stage={stage} code={code}"]
    assert all(record.exc_info is None for record in records)
    for private in (ACCOUNT, GOOGLE_SUBJECT, _user_id(GOOGLE_SUBJECT), ACCESS, REFRESH,
                    CODE, PRIVATE, PROFILE["email"], PROFILE["name"]):
        assert private not in caplog.text


@pytest.fixture
def history():
    connection = connect(":memory:")
    connection.execute(
        "CREATE TABLE users (id TEXT PRIMARY KEY, auth_provider TEXT NOT NULL "
        "CHECK(auth_provider='google'), provider_subject TEXT NOT NULL, email TEXT NOT NULL, "
        "display_name TEXT NOT NULL, picture_url TEXT NOT NULL, created_at TEXT NOT NULL, "
        "updated_at TEXT NOT NULL, UNIQUE(auth_provider,provider_subject))")
    yield D1HistoryStore(SqliteD1(connection)), connection
    connection.close()


async def host_roundtrip(history, *, authority_error=None, obsolete_user_agent=False,
                         host_factory=False, monkeypatch=None):
    store, connection = history
    uid = _user_id(GOOGLE_SUBJECT)
    calls, notified, issued = [], [], []

    def edge(req):
        calls.append(req)
        # Model default-agent rejection on the second HTTPS hop. This fixture
        # makes no claim about the live edge's rules or the incident's cause.
        if req.headers.get("user-agent") != PRODUCT_UA:
            return httpx.Response(403)
        assert req.url.path == "/internal/rpc/resolve_product_user_for_subject"
        assert req.headers["x-padiem-service-proof"].startswith("v2=")
        assert req.headers["x-padiem-service-id"]
        assert json.loads(req.content) == {"product_id": "b62", "canonical_subject_id": ACCOUNT}
        if authority_error:
            return httpx.Response(200, json={"ok": False, "error": {
                "code": authority_error, "message": PRIVATE}})
        return httpx.Response(200, json={"ok": True, "product_user_id": uid})

    async def simulate_old_client(req):
        if obsolete_user_agent:
            req.headers["user-agent"] = "python-httpx/synthetic"

    async with httpx.AsyncClient(transport=httpx.MockTransport(edge),
                                event_hooks={"request": [simulate_old_client]}) as client:
        authority = CloudflareControlPlaneIdentityAuthority(HttpRpcBinding(
            "https://identity.example.invalid", "synthetic-rpc-secret-never-for-logs-1234", client=client))
        verifier = Verifier()
        auth = SharedChatAuth(verifier=verifier, authority=authority,
                              legacy=lambda _: None, clock=lambda: 1000)

        async def notify(req, user):
            notified.append(user)

        async def provision(req, user, access, tokens):
            await provision_shared_profile(req, user, access, tokens, verifier=verifier,
                                           store=store, legacy_user=lambda _: None, notify=notify)

        async def issue_session(req, user, access, refresh):
            assert (access, refresh) == (ACCESS, REFRESH)
            assert connection.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
            issued.append(user)
            return await issue()

        if host_factory:
            from app import cpython_shared_login
            from app.config import Settings
            monkeypatch.setattr(cpython_shared_login, "NativeTokenVerifier", lambda audience: verifier)
            monkeypatch.setattr(cpython_shared_login, "NativeES256Signer", Crypto)
            monkeypatch.setattr(cpython_shared_login, "exchange_with_httpx", exchange)
            flow = cpython_shared_login.create_host_shared_login_flow({
                "PADIEM_CHAT_SHARED_LOGIN_ENABLED": "true",
                "PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK": json.dumps(
                    {"kty": "EC", "crv": "P-256", "x": "x", "y": "y", "d": "d"}),
                "PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY": _b64(b"x" * 32),
                "PADIEM_CHAT_SHARED_AUTH_CLIENT_KID": "synthetic",
            }, authority, "https://chat.padiem.net")
            assert flow is not None
            flow.clock = lambda: 1000
            auth = flow.auth
            auth._clock = lambda: 1000

            async def notify_one(user):
                notified.append(user)

            app = SimpleNamespace(state=SimpleNamespace(history_store=store,
                settings=Settings.from_values(runtime_mode="mock", auth_mode="off"),
                b66_signup_notifier=SimpleNamespace(notify_one=notify_one)))
        else:
            flow = make_flow(resolve_account=auth.user_id, provision_profile=provision,
                             issue_session=issue_session)
        results = []
        for _ in range(2):
            # A process restart or expired mapping cache must preserve the same user too.
            auth._mapping.clear()
            callback = await callback_request(flow)
            if host_factory:
                callback.scope["app"] = app
            response = await flow.finish_login(callback)
            results.append(response)
            if host_factory and response.status_code == 302:
                assert any(cookie.startswith(ACCESS_COOKIE + "=" + ACCESS + ";")
                           for cookie in response.headers.getlist("set-cookie"))
                issued.append(await auth.user_id(callback, ACCESS))
    return results, calls, notified, issued


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [True, False], ids=["existing-google-user", "first-shared-login"])
@pytest.mark.parametrize("host_factory", [False, True], ids=["common-flow", "host-factory"])
async def test_host_finish_reuses_canonical_google_account_or_creates_once(
        history, existing, caplog, host_factory, monkeypatch):
    store, connection = history
    uid = _user_id(GOOGLE_SUBJECT)
    if existing:
        original = await store.upsert_google_user(GOOGLE_SUBJECT, "old@example.invalid", "Old", "")
        assert original.id == uid
    responses, calls, notified, issued = await host_roundtrip(
        history, host_factory=host_factory, monkeypatch=monkeypatch)
    assert [response.status_code for response in responses] == [302, 302]
    assert len(calls) == 2 and notified == issued == [uid, uid]
    rows = connection.execute("SELECT * FROM users").fetchall()
    assert len(rows) == 1 and rows[0]["id"] == uid
    assert rows[0]["provider_subject"] == (GOOGLE_SUBJECT if existing else "shared:" + ACCOUNT)
    assert rows[0]["email"] == PROFILE["email"]
    assert "shared_login_finish_failed" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["canonical_product_identity_link_not_found",
                                  "canonical_product_identity_link_not_active"])
async def test_missing_or_inactive_canonical_link_never_creates_an_account(history, caplog, code):
    responses, calls, notified, issued = await host_roundtrip(history, authority_error=code)
    assert [response.status_code for response in responses] == [503, 503]
    assert len(calls) == 2 and notified == issued == []
    assert history[1].execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    messages = [record.getMessage() for record in caplog.records if record.name == "app.shared_login_flow"]
    assert messages == [f"shared_login_finish_failed stage=resolve_account code={code}"] * 2
    assert PRIVATE not in caplog.text and ACCOUNT not in caplog.text and ACCESS not in caplog.text


@pytest.mark.asyncio
async def test_reverting_identity_user_agent_reproduces_post_exchange_failure(history, caplog):
    responses, calls, notified, issued = await host_roundtrip(history, obsolete_user_agent=True)
    assert [response.status_code for response in responses] == [503, 503]
    assert len(calls) == 2 and notified == issued == []
    assert history[1].execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    assert "stage=resolve_account code=service_rpc_forbidden" in caplog.text
    assert "identity.example.invalid" not in caplog.text
    assert "synthetic-rpc-secret" not in caplog.text
    assert "x-padiem-service-proof" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(("code", "stage"), [
    ("invalid_flow", "validate_flow"), ("invalid_cookie", "validate_flow"),
    ("invalid_state", "validate_flow"), ("invalid_exchange", "exchange"),
    ("unknown_account", "resolve_account"), ("invalid_session_response", "issue_session"),
])
async def test_each_finish_rejection_logs_only_its_fixed_reason(code, stage, caplog):
    flow = make_flow()
    callback = await callback_request(flow)
    if code == "invalid_flow":
        callback = request("state=synthetic", callback.headers["cookie"])
    elif code == "invalid_cookie":
        cookie = callback.headers["cookie"].rsplit(".", 1)[0] + ".invalid"
        callback = request(callback.url.query, cookie)
    elif code == "invalid_state":
        data = _encoded({"state": callback.query_params["state"], "verifier": "synthetic", "exp": 1000})
        cookie = STATE_COOKIE + "=" + data + "." + _b64(flow._mac(b"shared-login", data.encode("ascii")))
        callback = request(callback.url.query, cookie)
    elif code == "invalid_exchange":
        flow.exchange = lambda *args: {"access_token": ACCESS, "refresh_token": None}
    elif code == "unknown_account":
        flow.resolve_account = lambda *args: None
    else:
        flow.issue_session = lambda *args: {"private": PRIVATE}
    caplog.set_level(logging.WARNING)
    response = await flow.finish_login(callback)
    assert response.status_code == 503
    assert json.loads(response.body) == {"error": "authentication_unavailable"}
    assert not any(cookie.startswith(ACCESS_COOKIE + "=") for cookie in response.headers.getlist("set-cookie"))
    assert_reason_only(caplog, stage, code)


@pytest.mark.asyncio
@pytest.mark.parametrize(("stage", "attribute"), [
    ("validate_flow", "_mac"), ("client_assertion", "_assertion"),
    ("exchange", "exchange"), ("resolve_account", "resolve_account"),
    ("provision_profile", "provision_profile"), ("issue_session", "issue_session"),
])
async def test_unexpected_finish_exception_logs_stage_without_exception_contents(stage, attribute, caplog):
    flow = make_flow()
    callback = await callback_request(flow)

    def fail(*args):
        raise RuntimeError(PRIVATE + ACCESS + ACCOUNT + PROFILE["email"])

    setattr(flow, attribute, fail)
    response = await flow.finish_login(callback)
    assert response.status_code == 503
    assert_reason_only(caplog, stage, stage + "_failed")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["invalid_profile", "history_conflict", "untrusted_rpc_code"])
async def test_profile_and_authority_reasons_use_closed_codes(failure, caplog):
    from app.control_plane_identity import IdentityBridgeError
    from app.history import HistoryConflict

    flow = make_flow()
    callback = await callback_request(flow)

    def fail(*args):
        if failure == "history_conflict":
            raise HistoryConflict(PRIVATE)
        if failure == "untrusted_rpc_code":
            raise IdentityBridgeError(503, PRIVATE, PROFILE["email"])
        raise ValueError("invalid_profile")

    if failure == "untrusted_rpc_code":
        flow.resolve_account = fail
        stage, code = "resolve_account", "resolve_account_failed"
    else:
        flow.provision_profile = fail
        stage = "provision_profile"
        code = "shared_profile_identity_conflict" if failure == "history_conflict" else failure
    assert (await flow.finish_login(callback)).status_code == 503
    assert_reason_only(caplog, stage, code)
