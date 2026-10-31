import hashlib
import json
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.shared_auth_compare_flow import _b64
from app.shared_login_flow import (CALLBACK, STATE_COOKIE, ACCESS_COOKIE, REFRESH_COOKIE,
                                   SharedLoginFlow, create_worker_shared_login_flow)


class FakeCrypto:
    async def sign(self, key, data):
        return b'x' * 64


def request(query='', cookie='', origin=None):
    return Request({'type': 'http', 'method': 'GET', 'path': '/', 'query_string': query.encode(),
                    'headers': [(b'cookie', cookie.encode())] + ([(b'origin', origin.encode())] if origin else [])})


def make_flow(exchange, resolve, issue):
    return SharedLoginFlow(state_key=b'x' * 32, client_id='b62', kid='test',
        client_jwk={'kty': 'EC', 'crv': 'P-256', 'x': 'x', 'y': 'y', 'd': 'd'},
        operator_guard=lambda request: True, legacy_user=lambda request: None,
        comparator=lambda *args: None, exchange=exchange, crypto=FakeCrypto(),
        resolve_account=resolve, issue_session=issue, clock=lambda: 1000)


@pytest.mark.asyncio
async def test_start_and_callback_use_pkce_and_server_side_exchange():
    seen = {}
    async def exchange(url, data):
        seen.update(data)
        return {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh'}
    async def resolve(req, access):
        assert access == 'synthetic-access'
        return 'synthetic-user'
    async def issue(req, user, access, refresh):
        assert (user, refresh) == ('synthetic-user', 'synthetic-refresh')
        return RedirectResponse('/', status_code=302)
    flow = make_flow(exchange, resolve, issue)
    start = await flow.start_login(request())
    q = parse_qs(urlparse(start.headers['location']).query)
    cookie = start.headers['set-cookie'].split(';', 1)[0]
    assert cookie.startswith(STATE_COOKIE + '=') and 'Domain=' not in start.headers['set-cookie']
    assert q['redirect_uri'] == [CALLBACK]
    result = await flow.finish_login(request('state=' + q['state'][0] + '&code=synthetic-code', cookie))
    assert result.status_code == 302
    assert seen['redirect_uri'] == CALLBACK
    assert q['code_challenge'] == [_b64(hashlib.sha256(seen['code_verifier'].encode()).digest())]
    assert 'synthetic-access' not in str(result.headers) and 'synthetic-refresh' not in str(result.headers)


@pytest.mark.asyncio
async def test_tampered_state_does_not_exchange_code():
    calls = []
    async def exchange(*args):
        calls.append(True)
    flow = make_flow(exchange, lambda *args: None, lambda *args: None)
    start = await flow.start_login(request())
    cookie = start.headers['set-cookie'].split(';', 1)[0]
    result = await flow.finish_login(request('state=wrong&code=synthetic-code', cookie))
    assert result.status_code == 503 and not calls


@pytest.mark.asyncio
async def test_failed_mapping_does_not_issue_session():
    issued = []
    async def exchange(*args):
        return {'access_token': 'synthetic-access', 'refresh_token': 'synthetic-refresh'}
    flow = make_flow(exchange, lambda *args: None, lambda *args: issued.append(True))
    start = await flow.start_login(request())
    q = parse_qs(urlparse(start.headers['location']).query)
    result = await flow.finish_login(request('state=' + q['state'][0] + '&code=synthetic-code',
                                             start.headers['set-cookie'].split(';', 1)[0]))
    assert result.status_code == 503 and not issued


@pytest.mark.asyncio
async def test_refresh_uses_authority_rotation_and_verifies_before_setting_cookies():
    calls = []
    async def exchange(url, data):
        calls.append(data)
        return {'access_token': 'new-access', 'refresh_token': 'new-refresh'}
    flow = make_flow(exchange, lambda request, token: 'synthetic-user', lambda *args: None)
    response = await flow.refresh(request(cookie=REFRESH_COOKIE + '=old-refresh', origin='https://chat.padiem.net'))
    assert response.status_code == 200 and calls[0]['grant_type'] == 'refresh_token'
    cookies = response.headers.getlist('set-cookie')
    assert any(c.startswith(ACCESS_COOKIE + '=') and 'Max-Age=900' in c and 'HttpOnly' in c for c in cookies)
    assert any(c.startswith(REFRESH_COOKIE + '=') and 'Max-Age=2592000' in c and 'Path=/auth/shared' in c for c in cookies)
    assert all('Domain=' not in c for c in cookies)


@pytest.mark.asyncio
async def test_logout_fails_closed_when_revoke_fails_and_rejects_cross_origin():
    calls = []
    flow = make_flow(lambda *args: None, lambda *args: None, lambda *args: None)
    async def revoke(data):
        calls.append(data)
        raise ValueError('revoke_failed')
    flow.revoke_session = revoke
    assert (await flow.logout(request(cookie=REFRESH_COOKIE + '=x', origin='https://evil.example'))).status_code == 403
    assert not calls
    result = await flow.logout(request(cookie=REFRESH_COOKIE + '=x', origin='https://chat.padiem.net'))
    assert result.status_code == 503 and calls
    assert not result.headers.getlist('set-cookie')


@pytest.mark.asyncio
async def test_default_off_never_resolves_secrets(monkeypatch):
    from app import worker_config
    reads = []
    monkeypatch.setattr(worker_config, 'binding_value', lambda env, name: None)
    async def read(*args):
        reads.append(True)
        raise AssertionError('secrets must not be read')
    monkeypatch.setattr(worker_config, 'resolve_secret_binding', read)
    assert await create_worker_shared_login_flow(object(), object()) is None
    assert reads == []


@pytest.mark.asyncio
async def test_profile_provision_failure_never_issues_session_or_exposes_profile():
    issued = []
    async def exchange(*args):
        return {'access_token':'synthetic-access', 'refresh_token':'synthetic-refresh',
                'account_id':'sub_a', 'profile':{'email':'private@example.invalid'}}
    async def issue(*args):
        issued.append(True)
        return RedirectResponse('/', status_code=302)
    async def reject(*args):
        raise ValueError('conflicting_account')
    flow = make_flow(exchange, lambda *args:'synthetic-user', issue)
    flow.provision_profile = reject
    start = await flow.start_login(request())
    state = parse_qs(urlparse(start.headers['location']).query)['state'][0]
    result = await flow.finish_login(request('state=' + state + '&code=synthetic-code', start.headers['set-cookie'].split(';', 1)[0]))
    assert result.status_code == 503 and not issued
    assert b'private@example.invalid' not in result.body
    assert all(not value.startswith(ACCESS_COOKIE + '=') for value in result.headers.getlist('set-cookie'))


@pytest.mark.asyncio
async def test_verified_profile_is_provisioned_before_cookie_and_stays_server_side():
    from app.shared_profile_provision import provision_shared_profile
    saved, notified, issued = [], [], []
    uid = 'usr_' + 'a' * 32
    profile = {'email':'private@example.invalid', 'email_verified':True, 'name':'Synthetic', 'picture':''}
    class Verifier:
        async def verify(self, token): return {'accountId':'sub_test'}
    class Store:
        async def upsert_shared_user(self, *args): saved.append(args)
    async def notify(request, user): notified.append(user)
    async def exchange(*args):
        return {'access_token':'synthetic-access', 'refresh_token':'synthetic-refresh', 'account_id':'sub_test', 'profile':profile}
    async def provision(req, user, access, tokens):
        await provision_shared_profile(req, user, access, tokens, verifier=Verifier(), store=Store(), legacy_user=lambda _:None, notify=notify)
    async def issue(req, user, access, refresh):
        assert saved and notified == [uid]
        issued.append(user)
        return RedirectResponse('/', status_code=302)
    flow = make_flow(exchange, lambda *args:uid, issue)
    flow.provision_profile = provision
    start = await flow.start_login(request())
    state = parse_qs(urlparse(start.headers['location']).query)['state'][0]
    result = await flow.finish_login(request('state=' + state + '&code=synthetic-code', start.headers['set-cookie'].split(';', 1)[0]))
    assert result.status_code == 302 and issued == [uid]
    assert 'private@example.invalid' not in str(result.headers)
    assert b'private@example.invalid' not in result.body


@pytest.mark.asyncio
@pytest.mark.parametrize("configured", [False, True])
async def test_worker_configuration_preserves_default_and_uses_staging_origin(configured):
    env = {
        'PADIEM_CHAT_SHARED_LOGIN_ENABLED': 'true',
        'PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK': json.dumps(
            {'kty': 'EC', 'crv': 'P-256', 'x': 'x', 'y': 'y', 'd': 'd'}),
        'PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY': _b64(b'x' * 32),
        'PADIEM_CHAT_SHARED_AUTH_CLIENT_KID': 'synthetic-kid',
    }
    origin = 'https://staging.example.test' if configured else 'https://chat.padiem.net'
    expected_client = 'b62-staging' if configured else 'b62'
    if configured:
        env.update(PADIEM_CHAT_SHARED_AUTH_CLIENT_ID=expected_client, PADIEM_CHAT_PUBLIC_BASE_URL=origin)
    flow = await create_worker_shared_login_flow(env, object())
    assert flow is not None
    assert flow.auth._verifier.audience == expected_client
    start = await flow.start_login(request())
    query = parse_qs(urlparse(start.headers['location']).query)
    assert query['client_id'] == [expected_client]
    assert query['redirect_uri'] == [origin + '/auth/shared/callback']
    assert flow.callback == origin + '/auth/shared/callback'
    assert (await flow.refresh(request(origin='https://wrong.example.test'))).status_code == 403


@pytest.mark.asyncio
async def test_missing_shared_login_configuration_logs_only_missing_names(capsys):
    marker = 'synthetic-private-value-not-for-log'
    env = {'PADIEM_CHAT_SHARED_LOGIN_ENABLED': 'true',
           'PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK': marker}
    assert await create_worker_shared_login_flow(env, object()) is None
    out = capsys.readouterr()
    assert 'PADIEM_CHAT_SHARED_AUTH_COMPARE_STATE_KEY' in out.out
    assert 'PADIEM_CHAT_SHARED_AUTH_CLIENT_KID' in out.out
    assert 'PADIEM_CHAT_SHARED_AUTH_CLIENT_PRIVATE_JWK' not in out.out
    assert marker not in out.out + out.err
