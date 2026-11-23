"""#7718 usage log API — admin-only, aggregate counts, no personal data."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from starlette.requests import Request

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings
from app.usage_log_routes import admin_usage_log
from test_7680_feedback_routes import AdminAuthority, SETTINGS, payload
from _support.feedback_store import BODY, OWNER, OTHER, database

BASE = 'https://chat.example.test'


class SiteOnlyAuthority:
    async def is_global_model_admin(self, *, user_id):
        return False


def request(store, *, user=OWNER, authority=None):
    auth = authority or AdminAuthority()
    state = SimpleNamespace(settings=SETTINGS, feedback_store=store, history_store=object(),
                            central_model_admin_authorizer=auth)
    headers = [(b'origin', BASE.encode())]
    if user:
        headers.append((b'cookie', (SESSION_COOKIE + '=' + create_session_token(SETTINGS, user, canonical_session_id="session_test_a")).encode()))
    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    return Request({'type': 'http', 'method': 'GET', 'path': '/api/admin/usage-log',
                    'query_string': b'', 'headers': headers,
                    'app': SimpleNamespace(state=state)}, receive)


def test_admin_only_guard():
    async def scenario():
        db, store = database()
        try:
            assert (await admin_usage_log(request(store, user=None))).status_code == 401
            assert (await admin_usage_log(request(store, user=OWNER))).status_code == 403
            assert (await admin_usage_log(request(store, user=OWNER,
                    authority=SiteOnlyAuthority()))).status_code == 403
            ok = await admin_usage_log(request(store, user=OTHER))
            assert ok.status_code == 200 and payload(ok)['ok'] is True
            assert 'no-store' in ok.headers['cache-control']
        finally:
            db.close()
    asyncio.run(scenario())


def test_empty_db_returns_empty_state_and_null_return_score():
    async def scenario():
        db, store = database()
        try:
            result = payload(await admin_usage_log(request(store, user=OTHER)))
            assert result['rows'] == []
            values = {row['key']: row['value'] for row in result['metrics']}
            assert values == {'active': 0, 'left': 0, 'new': 0, 'resolved': 0, 'return': None}
        finally:
            db.close()
    asyncio.run(scenario())


def test_counts_only_ai_testers_and_no_personal_data():
    async def scenario():
        db, store = database()
        try:
            db.execute('UPDATE users SET ai_tester=1 WHERE id=?', (OWNER,))
            row = await store.submit(OWNER, BODY)
            await store.submit(OTHER, 'a real user opinion that must not leak')
            await store.set_status(row.id, 'fixed')
            result = payload(await admin_usage_log(request(store, user=OTHER)))
            values = {row['key']: row['value'] for row in result['metrics']}
            assert values == {'active': 1, 'left': 0, 'new': 1, 'resolved': 1, 'return': None}
            assert result['rows'] == []
            text = json.dumps(result, ensure_ascii=False)
            assert BODY not in text and 'a real user opinion that must not leak' not in text
            assert '@' not in text and OWNER not in text
        finally:
            db.close()
    asyncio.run(scenario())


def test_activity_window_derives_active_and_left():
    async def scenario():
        db, store = database()
        try:
            db.execute('UPDATE users SET ai_tester=1 WHERE id=?', (OWNER,))
            recent = await store.submit(OWNER, BODY)
            old = await store.submit(OWNER, BODY)
            now = datetime.now(timezone.utc)
            db.execute('UPDATE product_feedback SET created_at=? WHERE id=?',
                       ((now - timedelta(days=40)).isoformat(), old.id))
            counts = await store.usage_log_counts(now=now)
            assert counts['active'] == 1
            assert counts['left'] == 0
            assert counts['new'] == 2
            db.execute('UPDATE product_feedback SET created_at=? WHERE id=?',
                       ((now - timedelta(days=40)).isoformat(), recent.id))
            counts = await store.usage_log_counts(now=now)
            assert counts['active'] == 0 and counts['left'] == 1
        finally:
            db.close()
    asyncio.run(scenario())
