"""Shared fixtures for the #8035 ops-center member/audit contracts.

Lives under tests/_support so the test-to-test import and raw-source assertion
ratchets do not grow when the ops-center lane is carried forward.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

from starlette.requests import Request

from app.config import Settings
from app.d1_sqlite import SqliteD1
from app.feedback_store import D1FeedbackStore
from app.local_cpython import apply_migrations
from sid_session_helper import sid_session_token

CHAT_DIR = Path(__file__).resolve().parents[2]
OWNER = 'usr_' + 'a' * 32
OTHER = 'usr_' + 'b' * 32
BODY = 'fixture-private-feedback-body'
DISABLED_ARIA = 'disabled aria-disabled'
MEMBERS_TAB_ID = 'id="opsTabMembers"'
AUDIT_BODY_ID = 'id="opsAuditBody"'
MEMBER_SEARCH_ID = 'id="opsMemberSearch"'
BASE = 'https://chat.example.test'
SETTINGS = Settings(auth_mode='password', public_base_url=BASE,
                    session_secret='fixture-feedback-session-signing-only',
                    feedback_daily_limit=2)


class AdminAuthority:
    async def is_global_model_admin(self, *, user_id):
        return user_id == OTHER


def database(path=':memory:', *, full=False):
    db = sqlite3.connect(str(path), isolation_level=None, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=OFF')
    if full:
        apply_migrations(db)
        db.execute('PRAGMA foreign_keys=OFF')
    else:
        db.execute(
            "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, "
            "display_name TEXT NOT NULL DEFAULT '', email TEXT NOT NULL DEFAULT '')")
        for name in ('115_feedback.sql', '117_feedback_replies_ai_tester.sql',
                     '119_chat_news.sql', '123_product_news_version.sql',
                     '126_ai_tester_intro.sql'):
            db.executescript((CHAT_DIR / 'migrations' / name).read_text(encoding='utf-8'))
    for uid in (OWNER, OTHER):
        if full:
            db.execute(
                "INSERT INTO users (id,auth_provider,provider_subject,email,"
                "display_name,picture_url,created_at,updated_at) "
                "VALUES (?,'google',?,'fixture@example.test','','','','')", (uid, uid))
        else:
            db.execute('INSERT OR IGNORE INTO users (id) VALUES (?)', (uid,))
    return db, D1FeedbackStore(SqliteD1(db))


def payload(response):
    return json.loads(response.body)


def request(store, *, method='GET', user=OWNER, body=None,
            path='/api/chat/feedback', feedback_id='', query='', origin=BASE):
    from app.auth import SESSION_COOKIE

    state = SimpleNamespace(
        settings=SETTINGS, history_store=object(), feedback_store=store,
        central_model_admin_authorizer=AdminAuthority())
    headers = [(b'content-type', b'application/json')]
    if user:
        token = sid_session_token(SETTINGS, user)
        headers.append((b'cookie', (SESSION_COOKIE + '=' + token).encode()))
    if origin is not None:
        headers.append((b'origin', origin.encode()))
    data = json.dumps(body or {}, ensure_ascii=True).encode()

    async def receive():
        return {'type': 'http.request', 'body': data, 'more_body': False}

    return Request({
        'type': 'http', 'method': method, 'path': path,
        'query_string': query.encode(), 'headers': headers,
        'app': SimpleNamespace(state=state),
        'path_params': {'feedback_id': feedback_id},
    }, receive)
