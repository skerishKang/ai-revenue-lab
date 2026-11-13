"""In-process route/guard units only; synthetic sessions and local SQLite."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app.auth import SESSION_COOKIE, create_session_token
from app.config import ConfigError, Settings
from app.feedback_routes import feedback, feedback_read, admin_feedback, admin_feedback_status
from app.same_origin_guard import SameOriginGuardMiddleware
from app.worker_config import settings_from_worker_bindings
from test_7680_feedback_store import OWNER, OTHER, BODY, database

BASE = 'https://chat.example.test'
SETTINGS = Settings(auth_mode='password', public_base_url=BASE,
                    session_secret='fixture-feedback-session-signing-only', feedback_daily_limit=2)


class AdminAuthority:
    async def is_global_model_admin(self, *, user_id):
        return user_id == OTHER


def request(store, *, method='GET', user=OWNER, body=None, path='/api/chat/feedback',
            feedback_id='', query='', origin=BASE):
    state = SimpleNamespace(settings=SETTINGS, history_store=object(), feedback_store=store,
                            central_model_admin_authorizer=AdminAuthority())
    headers = [(b'content-type', b'application/json')]
    if user:
        token = create_session_token(SETTINGS, user)
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    if origin is not None:
        headers.append((b'origin', origin.encode()))
    data = json.dumps(body or {}, ensure_ascii=True).encode()
    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}
    return Request({'type': 'http', 'method': method, 'path': path,
                    'query_string': query.encode(), 'headers': headers,
                    'app': SimpleNamespace(state=state), 'path_params': {'feedback_id': feedback_id}}, receive)


def payload(response):
    return json.loads(response.body)


def test_user_admin_flow_and_same_owner_read():
    async def scenario():
        db, store = database()
        try:
            created = await feedback(request(store, method='POST', body={'body': BODY}))
            assert created.status_code == 201
            item = payload(created)['feedback']
            assert item['screen'] is None and item['status'] == 'new'
            own = payload(await feedback(request(store)))
            assert own['feedback'][0]['id'] == item['id']
            assert own['limits'] == {'body_chars': 4000, 'daily_submissions': 2}
            assert payload(await feedback(request(store, user=OTHER)))['feedback'] == []
            assert (await admin_feedback(request(store))).status_code == 403
            assert (await admin_feedback(request(store, user=None))).status_code == 401
            inbox = payload(await admin_feedback(request(store, user=OTHER)))
            assert inbox['feedback'][0]['sender_label'].startswith('••••')
            assert OWNER not in json.dumps(inbox) and '@' not in json.dumps(inbox)
            changed = await admin_feedback_status(request(store, method='PATCH', user=OTHER,
                                                          feedback_id=item['id'], body={'status': 'fixed'}))
            version = payload(changed)['feedback']['fixed_version']
            assert payload(await feedback(request(store)))['unread_fixed_count'] == 1
            foreign = await feedback_read(request(store, user=OTHER, method='POST', feedback_id=item['id'],
                                                  body={'fixed_version': version}))
            assert foreign.status_code == 404
            read = await feedback_read(request(store, method='POST', feedback_id=item['id'],
                                               body={'fixed_version': version}))
            assert not payload(read)['feedback']['unread_fixed']
            for response in (created, changed, read, foreign):
                assert 'no-store' in response.headers['cache-control']
        finally:
            db.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('body', [{}, {'body': ''}, {'body': 'x' * 4001}, {'body': 3},
                                  {'body': 'ok', 'user_id': OTHER}, {'body': 'ok', 'conversation': BODY},
                                  {'body': 'ok', 'screen': {'conversation': BODY}}, {'body': '\ud800'}])
def test_closed_fields_and_text_validation(body):
    async def scenario():
        db, store = database()
        try:
            result = await feedback(request(store, method='POST', body=body))
            assert result.status_code == 400
            assert (await store.list_entries(user_id=OWNER))[0] == []
        finally:
            db.close()
    asyncio.run(scenario())


def test_unicode_body_boundary_screen_minimization_and_limit():
    async def scenario():
        db, store = database()
        try:
            screen = {'url': BASE.replace('://', '://private:fixture@') + '/conversation/hidden-id?text=private#secret',
                      'width': 390, 'height': 844, 'app_version': 'fixture-v1'}
            result = await feedback(request(store, method='POST', body={'body': '😀' * 4000, 'screen': screen}))
            assert result.status_code == 201
            assert payload(result)['feedback']['screen']['url'] == BASE + '/'
            assert (await feedback(request(store, method='POST', body={'body': BODY}))).status_code == 201
            limited = await feedback(request(store, method='POST', body={'body': BODY}))
            assert limited.status_code == 429
            assert payload(limited)['error']['code'] == 'feedback_daily_limit'
            assert 1 <= int(limited.headers['retry-after']) <= 86400
        finally:
            db.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('text', ['가나다\n' * 1250, '😀' * 5000, '"\\\n\t가' * 1000],
                         ids=['korean-lines', 'astral', 'json-escapes'])
def test_configured_character_limit_also_accepts_escaped_unicode_transport(text):
    async def scenario():
        db, store = database()
        try:
            req = request(store, method='POST', body={'body': text})
            req.app.state.settings = replace(SETTINGS, feedback_max_chars=5000)
            result = await feedback(req)
            assert result.status_code == 201
            assert payload(result)['feedback']['body'] == text
            req = request(store, method='POST', body={'body': text + 'x'})
            req.app.state.settings = replace(SETTINGS, feedback_max_chars=5000)
            assert (await feedback(req)).status_code == 400
        finally:
            db.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('origin,expected', [(BASE, None), (None, 403), ('https://foreign.example', 403)])
def test_mutating_feedback_routes_reuse_exact_same_origin_guard(origin, expected):
    guard = SameOriginGuardMiddleware(None)
    for path, method in [('/api/chat/feedback', 'POST'), ('/api/chat/feedback/fb_abc/read', 'POST'),
                         ('/api/admin/feedback/fb_abc', 'PATCH')]:
        req = request(None, method=method, path=path, origin=origin)
        denial = guard.decide(req.scope)
        assert (denial.status_code if denial else None) == expected


def test_route_errors_do_not_expose_body_account_or_storage_exception(caplog, capsys):
    class BrokenStore:
        async def submit(self, *args, **kwargs):
            raise RuntimeError(BODY + OWNER)
    result = asyncio.run(feedback(request(BrokenStore(), method='POST', body={'body': BODY})))
    assert result.status_code == 503
    exposed = result.body.decode() + repr(result) + caplog.text + capsys.readouterr().out
    assert BODY not in exposed and OWNER not in exposed


@pytest.mark.parametrize('handler,method', [(feedback, 'POST'), (feedback, 'GET'),
                                           (feedback_read, 'POST'), (admin_feedback, 'GET'),
                                           (admin_feedback_status, 'PATCH')])
def test_every_route_requires_login_before_storage(handler, method):
    result = asyncio.run(handler(request(None, method=method, user=None)))
    assert result.status_code == 401


def test_config_and_app_factory_wiring(monkeypatch):
    from app.app_factory import create_app
    app = create_app(settings=Settings())
    routes = {route.path: route for route in app.routes}
    assert routes['/api/chat/feedback'].endpoint is feedback
    assert routes['/api/chat/feedback/{feedback_id}/read'].endpoint is feedback_read
    assert routes['/api/admin/feedback'].endpoint is admin_feedback
    assert routes['/api/admin/feedback/{feedback_id}'].endpoint is admin_feedback_status
    assert Settings.from_values().feedback_daily_limit == 10
    assert Settings.from_values().feedback_max_chars == 4000
    assert settings_from_worker_bindings({'PADIEM_CHAT_FEEDBACK_DAILY_LIMIT': '7'}).feedback_daily_limit == 7
    assert settings_from_worker_bindings({'PADIEM_CHAT_FEEDBACK_MAX_CHARS': '5000'}).feedback_max_chars == 5000
    monkeypatch.setenv('PADIEM_CHAT_FEEDBACK_DAILY_LIMIT', '4')
    monkeypatch.setenv('PADIEM_CHAT_FEEDBACK_MAX_CHARS', '5000')
    assert Settings.from_env().feedback_daily_limit == 4
    assert Settings.from_env().feedback_max_chars == 5000
    for value in ('0', '-1', 'wrong', '1.1'):
        with pytest.raises(ConfigError):
            Settings.from_values(feedback_daily_limit=value)
        with pytest.raises(ConfigError):
            Settings.from_values(feedback_max_chars=value)


def test_real_app_auth_admin_roles_csrf_and_deleted_session_in_process():
    """ASGI calls stay in this process; no server or browser is started."""
    import httpx
    from app.app_factory import create_app
    from app.d1_sqlite import SqliteD1
    from app.history import D1HistoryStore, _user_id
    from app.platform_admin_roles import D1PlatformAdminRoleStore
    from app.shared_login_flow import ACCESS_COOKIE

    async def scenario():
        conn, _ = database(full=True)
        db = SqliteD1(conn)
        ids = {name: _user_id('feedback-fixture-' + name) for name in ('member', 'admin', 'super')}
        try:
            for name, uid in ids.items():
                conn.execute("INSERT INTO users (id,auth_provider,provider_subject,email,display_name,picture_url,created_at,updated_at) "
                             "VALUES (?,'google',?,'fixture@example.test','','','','')",
                             (uid, 'feedback-fixture-' + name))
            roles = D1PlatformAdminRoleStore(db)
            for name, role in [('admin', 'ADMIN'), ('super', 'SUPER_ADMIN')]:
                await roles.assign(actor_user_id=ids['super'], target_user_id=ids[name], role=role)
            settings = replace(SETTINGS, session_user_row_check=True)
            async def resolve_session(*args, **kwargs):
                raise AssertionError('Sidless fixture uses the real user-row guard')
            app = create_app(settings=settings, d1_binding=db, history_store=D1HistoryStore(db),
                             platform_admin_role_store=roles,
                             control_plane_identity_authority=SimpleNamespace(resolve_auth_session=resolve_session))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
                async def call(method, path, *, name=None, body=None, origin=BASE, shared=False):
                    headers = {'Origin': origin} if origin else {'x-test-no-origin': '1'}
                    if shared:
                        headers['Cookie'] = ACCESS_COOKIE + '=invalid-fixture'
                    elif name:
                        headers['Cookie'] = SESSION_COOKIE + '=' + create_session_token(settings, ids[name])
                    return await client.request(method, path, json=body, headers=headers)
                assert (await call('GET', '/api/admin/feedback')).status_code == 401
                assert (await call('GET', '/api/admin/feedback', name='member')).status_code == 403
                for name in ('admin', 'super'):
                    assert (await call('GET', '/api/admin/feedback', name=name)).status_code == 200
                created = await call('POST', '/api/chat/feedback', name='member', body={'body': BODY})
                assert created.status_code == 201
                fid = created.json()['feedback']['id']
                for path, method, body in [('/api/chat/feedback', 'POST', {'body': BODY}),
                                           ('/api/chat/feedback/' + fid + '/read', 'POST', {'fixed_version': 1}),
                                           ('/api/admin/feedback/' + fid, 'PATCH', {'status': 'fixed'})]:
                    for origin in (None, 'https://foreign.example'):
                        result = await call(method, path, name='admin', body=body, origin=origin)
                        assert result.status_code == 403
                        assert (await call(method, path, body=body, shared=True, origin=origin)).status_code == 403
                    assert (await call(method, path, body=body, shared=True)).status_code == 401
                conn.execute('DELETE FROM users WHERE id=?', (ids['member'],))
                for method, path, body in [('GET', '/api/chat/feedback', None),
                                           ('POST', '/api/chat/feedback', {'body': BODY}),
                                           ('GET', '/api/admin/feedback', None)]:
                    assert (await call(method, path, name='member', body=body)).status_code == 401
        finally:
            conn.close()
    asyncio.run(scenario())
