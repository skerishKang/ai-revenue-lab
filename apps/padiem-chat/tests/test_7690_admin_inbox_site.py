"""#7690 후속: 새 사이트 의견 알림 1건, 사이트별 개수, 권한 밖 거절."""
import asyncio
import hashlib
import hmac
import json
import secrets
from types import SimpleNamespace

from starlette.requests import Request

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.ops_alert_store import D1OpsAlertStore
from app.site_feedback_admin_identity import D1SiteFeedbackAdminAuthorizer
from app.site_feedback_routes import admin_site_feedback, site_feedback_ingest
from app.site_feedback_store import D1SiteFeedbackStore
from _support.feedback_store import database

BASE = 'https://chat.example.test'
_SESSION_SECRET = secrets.token_urlsafe(32)
_SECRET = secrets.token_urlsafe(32)
SETTINGS = Settings(auth_mode='password', public_base_url=BASE,
                    session_secret=_SESSION_SECRET,
                    site_feedback_secret_lovetree=_SECRET)
CENTRAL = 'usr_' + 'b' * 32
NOW_MS = 1_700_000_000_000


class AdminAuthority:
    async def is_global_model_admin(self, *, user_id):
        return user_id == CENTRAL


def _payload(feedback_id=101, event='new', **over):
    value = {'event': event, 'feedbackId': feedback_id, 'body': 'lovetree-body',
             'status': 'reviewing' if event != 'new' else 'received',
             'append': 'append-body' if event == 'append' else None,
             'isAiCustomer': True, 'accountSubjectId': 'subj-1',
             'category': 'bug' if event == 'new' else '', 'title': 't',
             'createdAt': '2026-11-22T10:00:00.000Z'}
    value.update(over)
    return value


def _signed(site_store, alert_store, payload_value, *, timestamp_ms=NOW_MS):
    raw = json.dumps(payload_value, ensure_ascii=False, separators=(',', ':')).encode()
    message = str(timestamp_ms).encode() + b'\nlovetree\n' + raw
    signature = 'sha256=' + hmac.new(_SECRET.encode(), message, hashlib.sha256).hexdigest()
    headers = [(b'content-type', b'application/json'),
               (b'x-lt-site', b'lovetree'),
               (b'x-lt-timestamp', str(timestamp_ms).encode()),
               (b'x-lt-signature', signature.encode())]

    async def receive():
        return {'type': 'http.request', 'body': raw, 'more_body': False}

    state = SimpleNamespace(settings=SETTINGS, site_feedback_store=site_store,
                            ops_alert_store=alert_store,
                            ops_alert_notifier=None, ops_alert_tasks=set())
    return Request({'type': 'http', 'method': 'POST', 'path': '/api/site-feedback/ingest',
                    'query_string': b'', 'headers': headers,
                    'app': SimpleNamespace(state=state), 'path_params': {},
                    'client': ('203.0.113.9', 12345)}, receive)


def _admin_request(store, authorizer, *, user=None, query='site=lovetree'):
    state = SimpleNamespace(settings=SETTINGS, history_store=object(), site_feedback_store=store,
                            platform_admin_role_store=None, b66_member_admin_store=None,
                            central_model_admin_authorizer=AdminAuthority(),
                            site_feedback_admin_authorizer=authorizer)
    headers = [(b'content-type', b'application/json')]
    if user:
        token = create_session_token(SETTINGS, user, canonical_session_id="session_test_a")
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    data = b'{}'

    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}

    return Request({'type': 'http', 'method': 'GET', 'path': '/api/admin/session',
                    'query_string': query.encode(), 'headers': headers,
                    'app': SimpleNamespace(state=state), 'path_params': {'feedback_id': ''},
                    'client': ('203.0.113.9', 12345)}, receive)


def _body(response):
    return json.loads(response.body)


def test_ingest_new_alerts_once_and_admin_list_shows_site(monkeypatch):
    async def scenario():
        db, _ = database(full=True)
        try:
            site_store = D1SiteFeedbackStore(SqliteD1(db))
            alert_store = D1OpsAlertStore(SqliteD1(db))
            monkeypatch.setattr('app.site_feedback_routes._now_ms', lambda: NOW_MS)
            monkeypatch.setattr('app.site_feedback_routes._now_iso', lambda: '2026-11-22T13:00:00Z')

            created = await site_feedback_ingest(
                _signed(site_store, alert_store, _payload()))
            assert created.status_code == 201
            site_id = _body(created)['feedback']['id']
            rows = db.execute('SELECT kind, target_id, label FROM ops_alert_outbox').fetchall()
            assert len(rows) == 1
            assert rows[0]['kind'] == 'site_feedback' and rows[0]['label'] == 'lovetree'
            assert rows[0]['target_id'] == site_id
            status = await alert_store.status()
            assert status['pending_by_site']['lovetree'] == 1
            assert status['pending_by_site']['chat'] == 0

            duplicate = await site_feedback_ingest(
                _signed(site_store, alert_store, _payload(), timestamp_ms=NOW_MS + 1000))
            assert duplicate.status_code == 200
            appended = await site_feedback_ingest(
                _signed(site_store, alert_store, _payload(event='append'),
                        timestamp_ms=NOW_MS + 2000))
            assert appended.status_code == 200
            changed = await site_feedback_ingest(
                _signed(site_store, alert_store, _payload(event='status'),
                        timestamp_ms=NOW_MS + 3000))
            assert changed.status_code == 200
            assert len(db.execute('SELECT 1 FROM ops_alert_outbox').fetchall()) == 1

            authorizer = D1SiteFeedbackAdminAuthorizer(SqliteD1(db))
            listed = await admin_site_feedback(
                _admin_request(site_store, authorizer, user=CENTRAL))
            assert listed.status_code == 200
            items = _body(listed)['feedback']
            assert [item['id'] for item in items] == [site_id]
            assert items[0]['site'] == 'lovetree'
            assert items[0]['external_feedback_id'] == '101'
        finally:
            db.close()
    asyncio.run(scenario())


def test_pending_by_site_counts_site_feedback_by_label():
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1OpsAlertStore(SqliteD1(db))
            await store.enqueue(kind='site_feedback', target_id='sf_' + '1' * 32, label='lovetree')
            await store.enqueue(kind='site_feedback', target_id='sf_' + '2' * 32, label='miraen-home')
            await store.enqueue(kind='product_feedback', target_id='fb_' + '3' * 32, label='chat')
            status = await store.status()
            assert status['pending'] == 3
            assert status['pending_by_site']['lovetree'] == 1
            assert status['pending_by_site']['miraen-home'] == 1
            assert status['pending_by_site']['chat'] == 1
        finally:
            db.close()
    asyncio.run(scenario())


def test_admin_site_endpoint_refuses_without_grant():
    async def scenario():
        db, _ = database(full=True)
        try:
            store = D1SiteFeedbackStore(SqliteD1(db))
            authorizer = D1SiteFeedbackAdminAuthorizer(SqliteD1(db))
            guest = await admin_site_feedback(_admin_request(store, authorizer))
            assert guest.status_code == 401
            member = await admin_site_feedback(
                _admin_request(store, authorizer, user='usr_' + 'd' * 32))
            assert member.status_code == 403
        finally:
            db.close()
    asyncio.run(scenario())
