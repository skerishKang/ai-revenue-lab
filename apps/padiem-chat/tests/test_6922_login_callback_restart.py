"""#6922: a shared-login callback that does not match this host's login answers 400, not 503.

11-05 14:50:17 KST ``GET /auth/shared/callback`` answered 503 for
``validate_flow code=invalid_flow``. The patrol counted it as an outage and the
user read "service unavailable", while the cause was the browser's own flow: a
callback without the state this host set. Those cases now answer 400 with a
page that says so and links the login start; the journal names which of them
it was. A host failure inside the same stage stays 503.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlencode, urlparse

import pytest
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app import httpx_compat
from app.shared_auth_compare_flow import _b64, _encoded, exchange_with_httpx
from app.shared_login_flow import (
    ACCESS_COOKIE,
    _EXCHANGE_RESTART_CODES,
    RESTART_LOGIN_PATH,
    STATE_COOKIE,
    SharedLoginFlow,
    _FINISH_FAILURE_CODES,
    _FLOW_RESTART_CODES,
)

CODE = "synthetic-callback-code-not-for-logs"


def _request(query: str = "", cookie: str = "", host: str = "chat.padiem.net") -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/auth/shared/callback",
        "query_string": query.encode(),
        "headers": [(b"cookie", cookie.encode()), (b"host", host.encode())],
    })


async def _issue(*args):
    return RedirectResponse("/", status_code=302)


async def _exchange(*args, **kwargs):
    return {"access_token": "synthetic-access", "refresh_token": "synthetic-refresh"}


def _flow(**overrides) -> SharedLoginFlow:
    values = dict(state_key=b"k" * 32, client_id="b62", kid="synthetic",
                  client_jwk={"kty": "EC", "crv": "P-256", "x": "x", "y": "y", "d": "d"},
                  operator_guard=lambda _: True, legacy_user=lambda _: None,
                  comparator=lambda *args: None, exchange=_exchange, crypto=_Crypto(),
                  resolve_account=lambda *args: "user_synthetic", issue_session=_issue,
                  clock=lambda: 1000)
    values.update(overrides)
    return SharedLoginFlow(**values)


class _Crypto:
    async def sign(self, key, data):
        return b"x" * 64


async def _started(flow):
    """The callback the authority would send back for a login this host started."""
    start = await flow.start_login(_request())
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    cookie = start.headers["set-cookie"].split(";", 1)[0]
    return state, cookie


def _signed(flow, **fields) -> str:
    data = _encoded(fields)
    return STATE_COOKIE + "=" + data + "." + _b64(flow._mac(b"shared-login", data.encode("ascii")))


def _journal(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.name == "app.shared_login_flow"]


def _install_token_endpoint(monkeypatch, *, status=None, body=b"", error=None):
    class _Response:
        headers = {}

        def __init__(self):
            self.status_code = status

        async def aiter_bytes(self):
            if body:
                yield body

    class _Stream:
        async def __aenter__(self):
            if error is not None:
                raise error
            return _Response()

        async def __aexit__(self, *args):
            return False

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, *args, **kwargs):
            return _Stream()

    monkeypatch.setattr(httpx_compat, "AsyncClient", _Client)


# --- which callbacks are the browser's flow, and what they are called ---------


@pytest.mark.asyncio
async def test_a_callback_with_no_state_cookie_restarts_the_login(caplog):
    # Started on another host, older than the cookie's 10 minutes, or cookies
    # blocked: the browser carries nothing this host can match.
    flow = _flow()
    state, _cookie = await _started(flow)
    caplog.set_level(logging.WARNING)

    response = await flow.finish_login(_request(urlencode({"state": state, "code": CODE}), ""))

    assert response.status_code == 400
    assert _journal(caplog)[0] == "shared_login_finish_failed stage=validate_flow code=state_cookie_missing"


@pytest.mark.asyncio
@pytest.mark.parametrize("code, make", [
    ("invalid_flow", lambda flow, state, cookie: _request(urlencode({"state": state}), cookie)),
    ("invalid_flow", lambda flow, state, cookie: _request(urlencode({"code": CODE}), cookie)),
    ("invalid_flow", lambda flow, state, cookie: _request(
        urlencode([("state", state), ("state", state), ("code", CODE)]), cookie)),
    ("invalid_cookie", lambda flow, state, cookie: _request(
        urlencode({"state": state, "code": CODE}), cookie.rsplit(".", 1)[0] + ".forged")),
    ("invalid_cookie", lambda flow, state, cookie: _request(
        urlencode({"state": state, "code": CODE}), STATE_COOKIE + "=no-dot-in-this-value")),
    ("invalid_state", lambda flow, state, cookie: _request(
        urlencode({"state": state, "code": CODE}), _signed(flow, state=state, verifier=None, exp=2000))),
    ("state_expired", lambda flow, state, cookie: _request(
        urlencode({"state": state, "code": CODE}), _signed(flow, state=state, verifier="v", exp=1000))),
    ("state_mismatch", lambda flow, state, cookie: _request(
        urlencode({"state": "a-different-login", "code": CODE}), cookie)),
])
async def test_each_mismatched_callback_is_named_and_restarts(code, make, caplog):
    flow = _flow()
    state, cookie = await _started(flow)
    caplog.set_level(logging.WARNING)

    response = await flow.finish_login(make(flow, state, cookie))

    assert response.status_code == 400, code
    assert _journal(caplog)[0] == f"shared_login_finish_failed stage=validate_flow code={code}"
    assert CODE not in caplog.text


# --- the 400 page -------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_restart_page_says_what_to_do_and_leaks_nothing(caplog):
    flow = _flow()
    state, _cookie = await _started(flow)
    caplog.set_level(logging.WARNING)

    response = await flow.finish_login(_request(urlencode({"state": state, "code": CODE}), ""))

    body = response.body.decode("utf-8")
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "로그인을 처음부터 다시 시작해 주세요" in body
    assert f'href="{RESTART_LOGIN_PATH}"' in body and RESTART_LOGIN_PATH == "/auth/shared/start"
    assert "state_cookie_missing" in body                     # the fixed code, for support
    assert CODE not in body and state not in body              # never the callback's values
    set_cookies = response.headers.getlist("set-cookie")
    assert any(item.startswith(STATE_COOKIE + "=") and "Max-Age=0" in item for item in set_cookies)
    assert not any(item.startswith(ACCESS_COOKIE + "=") for item in set_cookies)


# --- what stays 503 -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_host_failure_inside_validation_is_still_503(caplog):
    # The MAC check itself breaking is this host's fault, not the browser's.
    flow = _flow()
    state, cookie = await _started(flow)

    def broken_mac(*args):
        raise RuntimeError("private-host-failure-not-for-logs")

    flow._mac = broken_mac
    caplog.set_level(logging.WARNING)

    response = await flow.finish_login(_request(urlencode({"state": state, "code": CODE}), cookie))

    assert response.status_code == 503
    assert _journal(caplog)[0] == "shared_login_finish_failed stage=validate_flow code=validate_flow_failed"
    assert "private-host-failure" not in caplog.text


@pytest.mark.asyncio
async def test_a_failure_after_validation_is_still_503(caplog):
    flow = _flow(exchange=lambda *args, **kwargs: {"access_token": None})
    state, cookie = await _started(flow)
    caplog.set_level(logging.WARNING)

    response = await flow.finish_login(_request(urlencode({"state": state, "code": CODE}), cookie))

    assert response.status_code == 503
    assert _journal(caplog)[0] == "shared_login_finish_failed stage=exchange code=invalid_exchange"


@pytest.mark.asyncio
async def test_reused_authorization_code_restarts_login(monkeypatch, caplog):
    _install_token_endpoint(
        monkeypatch,
        status=400,
        body=b'{"error":"invalid_grant","error_description":"private response detail"}',
    )
    flow = _flow(exchange=exchange_with_httpx)
    state, cookie = await _started(flow)
    caplog.set_level(logging.WARNING)

    response = await flow.finish_login(_request(urlencode({"state": state, "code": CODE}), cookie))

    body = response.body.decode("utf-8")
    assert response.status_code == 400
    assert f'href="{RESTART_LOGIN_PATH}"' in body
    assert "invalid_grant" in body
    assert "private response detail" not in body
    assert "private response detail" not in caplog.text
    assert _journal(caplog)[0] == "shared_login_finish_failed stage=exchange code=invalid_grant"


@pytest.mark.asyncio
async def test_auth_server_timeout_stays_503_with_fixed_message(monkeypatch, caplog):
    _install_token_endpoint(
        monkeypatch,
        error=httpx_compat.ReadTimeout("private timeout detail"),
    )
    flow = _flow(exchange=exchange_with_httpx)
    state, cookie = await _started(flow)
    caplog.set_level(logging.WARNING)

    response = await flow.finish_login(_request(urlencode({"state": state, "code": CODE}), cookie))

    assert response.status_code == 503
    # #7699: the browser gets the retry page, not raw JSON.
    assert response.headers['content-type'].startswith('text/html')
    assert '잠시 후 다시 시도해 주세요' in response.body.decode('utf-8')
    assert "private timeout detail" not in caplog.text
    assert _journal(caplog)[0] == "shared_login_finish_failed stage=exchange code=exchange_failed"


@pytest.mark.parametrize("status, body", [
    (400, b'{"error":"invalid_client"}'),
    (503, b'{"error":"server_error"}'),
])
@pytest.mark.asyncio
async def test_other_token_exchange_errors_stay_503(monkeypatch, status, body):
    _install_token_endpoint(monkeypatch, status=status, body=body)
    flow = _flow(exchange=exchange_with_httpx)
    state, cookie = await _started(flow)

    response = await flow.finish_login(_request(urlencode({"state": state, "code": CODE}), cookie))

    assert response.status_code == 503
    assert response.headers['content-type'].startswith('text/html')
    assert '잠시 후 다시 시도해 주세요' in response.body.decode('utf-8')


@pytest.mark.asyncio
async def test_a_matching_callback_still_logs_in():
    flow = _flow()
    state, cookie = await _started(flow)

    response = await flow.finish_login(_request(urlencode({"state": state, "code": CODE}), cookie))

    assert response.status_code == 302


def test_every_restart_code_is_a_fixed_journal_code():
    assert _FLOW_RESTART_CODES <= _FINISH_FAILURE_CODES
    assert _EXCHANGE_RESTART_CODES <= _FINISH_FAILURE_CODES
    assert "validate_flow_failed" not in _FLOW_RESTART_CODES
