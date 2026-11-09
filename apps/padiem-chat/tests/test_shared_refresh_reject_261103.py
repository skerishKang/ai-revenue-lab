"""Refresh rejection classification and real-stage journal lines.

A token-endpoint 400/401 is a closed authority rejection: the refresh answers
401 and clears the shared cookies. 5xx/timeout/connection failures stay 503
and keep the cookie. The journal line names the stage the failure reached
(refresh_exchange / refresh_account / refresh_issue).
"""
from __future__ import annotations

import pytest
from starlette.requests import Request

from app import httpx_compat
from app.shared_auth_compare_flow import TOKEN_URL, exchange_with_httpx
from app.shared_login_flow import ACCESS_COOKIE, MARKER_COOKIE, REFRESH_COOKIE, SharedLoginFlow


class FakeCrypto:
    async def sign(self, key, data):
        return b'x' * 64


def request(cookie='', origin=None):
    headers = []
    if cookie:
        headers.append((b'cookie', cookie.encode()))
    if origin:
        headers.append((b'origin', origin.encode()))
    return Request({'type': 'http', 'method': 'GET', 'path': '/',
                    'query_string': b'', 'headers': headers})


def make_flow(exchange, resolve=None, issue=None):
    return SharedLoginFlow(
        state_key=b'x' * 32, client_id='b62', kid='test',
        client_jwk={'kty': 'EC', 'crv': 'P-256', 'x': 'x', 'y': 'y', 'd': 'd'},
        operator_guard=lambda request: True,
        legacy_user=lambda request: None,
        comparator=lambda *args: None,
        exchange=exchange, crypto=FakeCrypto(),
        resolve_account=resolve or (lambda *args: 'synthetic-user'),
        issue_session=issue or (lambda *args: None), clock=lambda: 1000,
    )


def refresh_request():
    return request(cookie=REFRESH_COOKIE + '=fake-refresh',
                   origin='https://chat.padiem.net')


class _Response:
    def __init__(self, status):
        self.status_code = status

    async def aiter_bytes(self):
        if False:
            yield b''


class _Stream:
    def __init__(self, status=None, error=None):
        self.status = status
        self.error = error

    async def __aenter__(self):
        if self.error is not None:
            raise self.error
        return _Response(self.status)

    async def __aexit__(self, *args):
        return False


def _fake_client(status=None, error=None):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def stream(self, *args, **kwargs):
            return _Stream(status=status, error=error)

    return _Client


@pytest.mark.parametrize("status", [400, 401])
@pytest.mark.asyncio
async def test_exchange_4xx_maps_to_the_closed_rejection_code(monkeypatch, status):
    monkeypatch.setattr(httpx_compat, "AsyncClient", _fake_client(status=status))
    with pytest.raises(ValueError) as raised:
        await exchange_with_httpx(TOKEN_URL, {'grant_type': 'refresh_token'})
    assert raised.value.args == ('exchange_rejected',)


@pytest.mark.parametrize("status", [500, 502, 503])
@pytest.mark.asyncio
async def test_exchange_5xx_maps_to_unavailable(monkeypatch, status):
    monkeypatch.setattr(httpx_compat, "AsyncClient", _fake_client(status=status))
    with pytest.raises(ValueError) as raised:
        await exchange_with_httpx(TOKEN_URL, {'grant_type': 'refresh_token'})
    assert raised.value.args == ('exchange_unavailable',)


@pytest.mark.asyncio
async def test_exchange_connection_failure_maps_to_unavailable(monkeypatch):
    monkeypatch.setattr(httpx_compat, "AsyncClient",
                        _fake_client(error=httpx_compat.ConnectError('synthetic')))
    with pytest.raises(ValueError) as raised:
        await exchange_with_httpx(TOKEN_URL, {'grant_type': 'refresh_token'})
    assert raised.value.args == ('exchange_unavailable',)


@pytest.mark.parametrize("status", [400, 401])
@pytest.mark.asyncio
async def test_refresh_rejection_answers_401_and_clears_shared_cookies(
    monkeypatch, status, capsys
):
    monkeypatch.setattr(httpx_compat, "AsyncClient", _fake_client(status=status))
    flow = make_flow(exchange_with_httpx)
    response = await flow.refresh(refresh_request())
    assert response.status_code == 401
    cleared = response.headers.getlist('set-cookie')
    assert any(c.startswith(ACCESS_COOKIE + '=') and 'Max-Age=0' in c for c in cleared)
    assert any(c.startswith(REFRESH_COOKIE + '=') and 'Max-Age=0' in c for c in cleared)
    assert any(c.startswith(MARKER_COOKIE + '=') and 'Max-Age=0' in c for c in cleared)
    out = capsys.readouterr().out
    assert ('shared_refresh_result outcome=rejected stage=refresh_exchange '
            'code=exchange_rejected') in out


@pytest.mark.parametrize("status", [500, 502])
@pytest.mark.asyncio
async def test_refresh_5xx_stays_503_and_keeps_cookies(monkeypatch, status, capsys):
    monkeypatch.setattr(httpx_compat, "AsyncClient", _fake_client(status=status))
    flow = make_flow(exchange_with_httpx)
    response = await flow.refresh(refresh_request())
    assert response.status_code == 503
    assert not response.headers.getlist('set-cookie')
    out = capsys.readouterr().out
    assert ('shared_refresh_result outcome=unavailable stage=refresh_exchange '
            'code=exchange_unavailable') in out


@pytest.mark.asyncio
async def test_refresh_timeout_stays_503_and_keeps_cookies(monkeypatch, capsys):
    monkeypatch.setattr(httpx_compat, "AsyncClient",
                        _fake_client(error=httpx_compat.ConnectError('synthetic timeout')))
    flow = make_flow(exchange_with_httpx)
    response = await flow.refresh(refresh_request())
    assert response.status_code == 503
    assert not response.headers.getlist('set-cookie')
    out = capsys.readouterr().out
    assert ('shared_refresh_result outcome=unavailable stage=refresh_exchange '
            'code=exchange_unavailable') in out


@pytest.mark.asyncio
async def test_account_failure_logs_the_account_stage(capsys):
    async def exchange(url, data):
        return {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh'}

    async def resolve(request, access):
        raise ValueError('unknown_account')

    flow = make_flow(exchange, resolve=resolve)
    response = await flow.refresh(refresh_request())
    assert response.status_code == 401
    out = capsys.readouterr().out
    assert ('shared_refresh_result outcome=rejected stage=refresh_account '
            'code=unknown_account') in out


@pytest.mark.asyncio
async def test_cookie_issue_failure_logs_the_issue_stage(monkeypatch, capsys):
    from app import shared_login_flow

    def explode(*args, **kwargs):
        raise RuntimeError('synthetic issue failure')

    monkeypatch.setattr(shared_login_flow, 'issue_shared_cookies', explode)

    async def exchange(url, data):
        return {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh'}

    flow = make_flow(exchange)
    response = await flow.refresh(refresh_request())
    assert response.status_code == 503
    out = capsys.readouterr().out
    assert ('shared_refresh_result outcome=unavailable stage=refresh_issue '
            'code=unavailable') in out
