from types import SimpleNamespace

import pytest

from app.shared_auth_adapter import SharedAuthUnavailable
from app.shared_login_flow import ACCESS_COOKIE
from app.shared_session_middleware import SharedSessionMiddleware
from app.request_telemetry import _CURRENT_REQUEST_ID
from app.shared_login_timing import record_login_timing


@pytest.mark.asyncio
async def test_disabled_does_not_read_or_verify_shared_session():
    seen = []
    async def app(scope, receive, send):
        seen.append(scope.get('state', {}))
    scope = {'type': 'http', 'headers': [(b'cookie', (ACCESS_COOKIE + '=token').encode())]}
    await SharedSessionMiddleware(app, flow=None)(scope, None, None)
    assert seen == [{}]


@pytest.mark.asyncio
async def test_only_verified_user_is_attached_and_invalid_token_is_guest():
    seen = []
    async def app(scope, receive, send):
        seen.append(scope.get('state', {}).copy())
    class Auth:
        async def user_id(self, request, token):
            if token == 'invalid':
                raise SharedAuthUnavailable()
            return 'verified-user'
    middleware = SharedSessionMiddleware(app, flow=SimpleNamespace(auth=Auth()))
    for token in ('valid', 'invalid'):
        scope = {'type': 'http', 'headers': [(b'cookie', (ACCESS_COOKIE + '=' + token).encode())]}
        await middleware(scope, None, None)
    assert seen == [{'padiem_shared_user_id': 'verified-user'}, {}]


@pytest.mark.asyncio
async def test_shared_identity_timing_has_request_id_stage_ms_only(capsys):
    seen = []
    async def app(scope, receive, send):
        seen.append(scope.get('state', {}).copy())
    class Auth:
        async def user_id(self, request, token):
            record_login_timing('account_token_verify', 1.5)
            record_login_timing('identity_rpc', 2.25)
            return 'verified-user'
    middleware = SharedSessionMiddleware(app, flow=SimpleNamespace(auth=Auth()))
    request_token = _CURRENT_REQUEST_ID.set('synthetic-shared-identity-request')
    try:
        scope = {'type': 'http', 'method': 'GET', 'path': '/api/test', 'query_string': b'',
                 'headers': [(b'cookie', (ACCESS_COOKIE + '=synthetic-access-secret').encode())]}
        await middleware(scope, None, None)
    finally:
        _CURRENT_REQUEST_ID.reset(request_token)

    assert seen == [{'padiem_shared_user_id': 'verified-user'}]
    line = next(item for item in capsys.readouterr().out.splitlines()
                if item.startswith('chat_identity_timing '))
    fields = dict(item.split('=', 1) for item in line.split()[1:])
    assert fields['request_id'] == 'synthetic-shared-identity-request'
    assert fields['account_token_verify_ms'] == '2'
    assert fields['identity_rpc_ms'] == '2'
    assert fields['shared_identity_lookup_ms'].isdigit()
    assert set(fields) == {'request_id', 'total_ms', 'account_token_verify_ms',
                           'identity_rpc_ms', 'shared_identity_lookup_ms'}
    assert 'synthetic-access-secret' not in line and 'verified-user' not in line
