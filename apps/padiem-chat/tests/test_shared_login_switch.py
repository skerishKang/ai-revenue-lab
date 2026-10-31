from urllib.parse import parse_qs, urlparse
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.auth_routes import current_user_id
from app.config import Settings
from app.shared_login_flow import ACCESS_COOKIE, SharedLoginFlow, issue_shared_cookies


async def identity(request):
    return JSONResponse({'user': current_user_id(request)})


class Flow:
    def __init__(self):
        self.auth = self
        self.calls = 0

    async def user_id(self, request, token):
        self.calls += 1
        return 'usr_shared' if token == 'synthetic-token' else None

    def login_routes(self):
        return [Route('/auth/shared/start', lambda request: JSONResponse({'new': True}))]


def make_app(flow=None):
    settings = Settings.from_values(runtime_mode='mock', auth_mode='off', session_secret='test-secret-for-session')
    app = create_app(settings=settings, shared_login_flow=flow)
    app.routes.insert(0, Route('/identity-test', identity))
    return app, settings


def test_switch_off_does_not_mount_or_verify_shared_path():
    app, settings = make_app()
    with TestClient(app) as client:
        result = client.get('/identity-test', cookies={ACCESS_COOKIE: 'synthetic-token'})
        assert result.json()['user'] is None
        assert client.get('/auth/shared/start').status_code == 404


def test_switch_on_preserves_existing_legacy_cookie_and_accepts_shared():
    flow = Flow()
    app, settings = make_app(flow)
    token = create_session_token(settings, 'usr_legacy')
    with TestClient(app) as client:
        assert client.get('/identity-test', cookies={SESSION_COOKIE: token}).json()['user'] == 'usr_legacy'
        assert client.get('/identity-test', cookies={ACCESS_COOKIE: 'synthetic-token'}).json()['user'] == 'usr_shared'
        assert client.get('/identity-test', cookies={SESSION_COOKIE: token, ACCESS_COOKIE: 'synthetic-token'}).json()['user'] == 'usr_legacy'
        assert client.get('/auth/shared/start').status_code == 200
    assert flow.calls == 2


def test_login_callback_refresh_and_logout_roundtrip():
    class Crypto:
        async def sign(self, key, data):
            return b'x' * 64
    class Auth:
        async def user_id(self, request, access):
            return 'usr_shared' if access in ('access-one', 'access-two') else None
    async def exchange(url, data):
        if data['grant_type'] == 'authorization_code':
            return {'access_token': 'access-one', 'refresh_token': 'refresh-one'}
        assert data['refresh_token'] == 'refresh-one'
        return {'access_token': 'access-two', 'refresh_token': 'refresh-two'}
    async def issue(request, user, access, refresh):
        return issue_shared_cookies(RedirectResponse('/', status_code=302), access, refresh)
    revoked = []
    async def revoke(data):
        revoked.append(data['refresh_token'])
    auth = Auth()
    flow = SharedLoginFlow(state_key=b'x' * 32, client_id='b62', kid='test',
        client_jwk={'kty': 'EC', 'crv': 'P-256', 'x': 'x', 'y': 'y', 'd': 'd'},
        operator_guard=lambda request: True, legacy_user=lambda request: None,
        comparator=lambda *args: None, exchange=exchange, crypto=Crypto(),
        resolve_account=auth.user_id, issue_session=issue, revoke_session=revoke)
    flow.auth = auth
    app, _ = make_app(flow)
    with TestClient(app, base_url='https://chat.padiem.net') as client:
        start = client.get('/auth/shared/start', follow_redirects=False)
        state = parse_qs(urlparse(start.headers['location']).query)['state'][0]
        callback = client.get('/auth/shared/callback', params={'state': state, 'code': 'synthetic-code'}, follow_redirects=False)
        assert callback.status_code == 302
        status = client.get('/api/auth/status').json()
        assert status['shared_login_enabled'] is True and status['shared_session_present'] is True
        assert client.get('/identity-test').json()['user'] == 'usr_shared'
        assert client.post('/auth/shared/refresh', headers={'origin': 'https://chat.padiem.net'}).status_code == 200
        assert client.get('/identity-test').json()['user'] == 'usr_shared'
        assert client.post('/auth/shared/logout', headers={'origin': 'https://chat.padiem.net'}).status_code == 200
        assert client.get('/identity-test').json()['user'] is None
    assert revoked == ['refresh-two']


def test_shared_flow_is_ready_without_legacy_auth_and_resolves_verified_profile():
    class Profile:
        def public_dict(self):
            return {'id': 'usr_shared'}

    class Store:
        async def get_user(self, uid):
            return Profile() if uid == 'usr_shared' else None

    settings = Settings.from_values(runtime_mode='mock', auth_mode='off')
    app = create_app(settings=settings, shared_login_flow=Flow(), history_store=Store())
    with TestClient(app) as client:
        assert client.get('/health').json()['auth_configured'] is True
        status = client.get('/api/auth/status', cookies={ACCESS_COOKIE: 'synthetic-token'}).json()
        assert status['ready'] is True
        assert status['authenticated'] is True
        assert status['user']['id'] == 'usr_shared'
        assert status['methods'] == {'google': False, 'password': False}

    app = create_app(settings=settings, history_store=Store())
    with TestClient(app) as client:
        assert client.get('/health').json()['auth_configured'] is False
        assert client.get('/api/auth/status').json()['ready'] is False


def test_shared_auth_failure_logs_only_fixed_marker(caplog):
    from app.shared_auth_adapter import SharedAuthUnavailable

    class BrokenFlow(Flow):
        async def user_id(self, request, token):
            raise SharedAuthUnavailable('sensitive diagnostic should not be logged')

    app, _ = make_app(BrokenFlow())
    with TestClient(app) as client:
        assert client.get('/identity-test', cookies={ACCESS_COOKIE: 'synthetic-token'}).json()['user'] is None
    assert 'shared_session_verification_or_identity_lookup_failed' in caplog.text
    assert 'synthetic-token' not in caplog.text
    assert 'sensitive diagnostic' not in caplog.text
