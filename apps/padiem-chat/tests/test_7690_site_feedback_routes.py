"""#7690 public route units: CORS, anonymous submit, bot/rate limits, admin-only view."""
import asyncio
import json
import secrets
from types import SimpleNamespace

from starlette.requests import Request

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.site_feedback_routes import (_rate_hash, admin_site_feedback, admin_site_feedback_status,
                                      site_feedback)
from app.site_feedback_store import D1SiteFeedbackStore
from _support.feedback_store import database

BASE = 'https://chat.example.test'
# 서명 키는 실행 때 만든다 — 시험 파일에 비밀값처럼 보이는 글자를 두지 않는다.
_SESSION_SECRET = secrets.token_urlsafe(32)
SETTINGS = Settings(auth_mode='password', public_base_url=BASE,
                    session_secret=_SESSION_SECRET)
SETTINGS_LIMIT = Settings(auth_mode='password', public_base_url=BASE,
                           session_secret=_SESSION_SECRET,
                           site_feedback_daily_limit=2)
ADMIN = 'usr_' + 'b' * 32
USER = 'usr_' + 'a' * 32
BODY = 'site-feedback-body'
ORIGIN = 'https://councillor-prototype-v2.pages.dev'


class AdminAuthority:
    async def is_global_model_admin(self, *, user_id):
        return user_id == ADMIN


def request(store, *, method='GET', user=None, body=None, path='/api/site-feedback',
            feedback_id='', query='', origin=ORIGIN, ip='203.0.113.9', settings=SETTINGS):
    state = SimpleNamespace(settings=settings, history_store=object(), site_feedback_store=store,
                            central_model_admin_authorizer=AdminAuthority())
    headers = [(b'content-type', b'application/json'), (b'origin', origin.encode()),
               (b'cf-connecting-ip', ip.encode()), (b'user-agent', b'fixture')]
    if user:
        token = create_session_token(settings, user, canonical_session_id="session_test_a")
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    data = json.dumps(body or {}, ensure_ascii=True).encode()

    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}

    return Request({'type': 'http', 'method': method, 'path': path,
                    'query_string': query.encode(), 'headers': headers,
                    'app': SimpleNamespace(state=state), 'path_params': {'feedback_id': feedback_id},
                    'client': (ip, 12345)}, receive)


def payload(response):
    return json.loads(response.body)


def test_public_submit_cors_rate_and_admin_only(monkeypatch):
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1SiteFeedbackStore(SqliteD1(db))
            now_ms = 1_700_000_000_000
            monkeypatch.setattr('app.site_feedback_routes._now_ms', lambda: now_ms)
            monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-15T00:00:00Z')
            body = {'site': 'miraen-home', 'body': BODY,
                    'screen': {'url': ORIGIN + '/', 'width': 390, 'height': 844},
                    'rendered_at': now_ms - 2000, 'honeypot': ''}
            created = await site_feedback(request(store, method='POST', body=body))
            assert created.status_code == 201
            item = payload(created)['feedback']
            assert item['site'] == 'miraen-home' and item['status'] == 'new'
            assert created.headers['access-control-allow-origin'] == ORIGIN
            for _ in range(4):
                assert (await site_feedback(request(store, method='POST', body=body))).status_code == 201
            limited = await site_feedback(request(store, method='POST', body=body))
            assert limited.status_code == 429 and 'retry-after' in limited.headers
            for bad in ({**body, 'site': 'other'}, {**body, 'body': 'x' * 2001},
                        {**body, 'rendered_at': now_ms - 500}, {**body, 'honeypot': 'x'},
                        {**body, 'screen': {'url': 'https://evil.test/', 'width': 390, 'height': 844}}):
                assert (await site_feedback(request(store, method='POST', body=bad))).status_code == 400
            options = await site_feedback(request(store, method='OPTIONS', query='site=miraen-home'))
            assert options.status_code == 204 and options.headers['access-control-allow-origin'] == ORIGIN
            # The page posts to the bare endpoint, so a real browser preflight has no
            # site in the query: the registered Origin alone must pass it.
            bare = await site_feedback(request(store, method='OPTIONS'))
            assert bare.status_code == 204 and bare.headers['access-control-allow-origin'] == ORIGIN
            assert 'Content-Type' in bare.headers['access-control-allow-headers']
            assert bare.body == b'' and bare.headers.get('content-length', '0') == '0'
            stranger = await site_feedback(request(store, method='OPTIONS', origin='https://evil.test'))
            assert stranger.status_code == 400 and 'access-control-allow-origin' not in stranger.headers
            assert (await admin_site_feedback(request(store))).status_code == 401
            assert (await admin_site_feedback(request(store, user=USER))).status_code == 403
            admin = await admin_site_feedback(request(store, user=ADMIN))
            assert admin.status_code == 200 and len(payload(admin)['feedback']) == 5
            assert len(payload(await admin_site_feedback(
                request(store, user=ADMIN, query='site=miraen-home')))['feedback']) == 5
            changed = await admin_site_feedback_status(
                request(store, method='PATCH', user=ADMIN, feedback_id=item['id'], body={'status': 'fixed'}))
            assert changed.status_code == 200 and payload(changed)['feedback']['status'] == 'fixed'
            memo = await admin_site_feedback_status(
                request(store, method='PATCH', user=ADMIN, feedback_id=item['id'], body={'ops_memo': 'memo'}))
            assert memo.status_code == 200 and payload(memo)['feedback']['ops_memo'] == 'memo'
        finally:
            db.close()
    asyncio.run(scenario())


def test_site_wide_daily_limit_and_day_reset(monkeypatch):
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1SiteFeedbackStore(SqliteD1(db))
            now_ms = 1_700_000_000_000
            monkeypatch.setattr('app.site_feedback_routes._now_ms', lambda: now_ms)
            monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-15T00:00:00Z')
            body = {'site': 'miraen-home', 'body': BODY,
                    'screen': {'url': ORIGIN + '/', 'width': 390, 'height': 844},
                    'rendered_at': now_ms - 2000, 'honeypot': ''}
            first = await site_feedback(request(store, method='POST', body=body,
                                                settings=SETTINGS_LIMIT, ip='203.0.113.1'))
            second = await site_feedback(request(store, method='POST', body=body,
                                                 settings=SETTINGS_LIMIT, ip='203.0.113.2'))
            third = await site_feedback(request(store, method='POST', body=body,
                                                settings=SETTINGS_LIMIT, ip='203.0.113.3'))
            assert first.status_code == 201 and second.status_code == 201 and third.status_code == 429
            next_ms = now_ms + 86_400_000
            monkeypatch.setattr('app.site_feedback_routes._now_ms', lambda: next_ms)
            monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-16T00:00:00Z')
            next_day = await site_feedback(request(store, method='POST',
                                                   body={**body, 'rendered_at': next_ms - 2000},
                                                   settings=SETTINGS_LIMIT, ip='203.0.113.3'))
            assert next_day.status_code == 201
        finally:
            db.close()
    asyncio.run(scenario())


def test_rate_hash_prefers_cf_connecting_ip(monkeypatch):
    monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-15T00:00:00Z')
    base = SimpleNamespace(
        headers={'cf-connecting-ip': '1.1.1.1', 'x-forwarded-for': '2.2.2.2', 'user-agent': 'ua'},
        client=SimpleNamespace(host='3.3.3.3'))
    cf_only = SimpleNamespace(
        headers={'cf-connecting-ip': '1.1.1.1', 'user-agent': 'ua'},
        client=SimpleNamespace(host='3.3.3.3'))
    xff_only = SimpleNamespace(
        headers={'x-forwarded-for': '2.2.2.2', 'user-agent': 'ua'},
        client=SimpleNamespace(host='3.3.3.3'))
    assert _rate_hash(base, 'miraen-home') == _rate_hash(cf_only, 'miraen-home')
    assert _rate_hash(base, 'miraen-home') != _rate_hash(xff_only, 'miraen-home')