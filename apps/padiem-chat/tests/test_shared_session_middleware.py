from types import SimpleNamespace

import pytest

from app.shared_auth_adapter import SharedAuthUnavailable
from app.shared_login_flow import ACCESS_COOKIE
from app.shared_session_middleware import SharedSessionMiddleware


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
