"""Exercise the actual news panel and handlers without a live account or server."""
from __future__ import annotations

import asyncio
import http.server
import json
import sqlite3
import threading
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from app.d1_sqlite import SqliteD1
from app.feedback_store import D1FeedbackStore
from app.news_store import D1NewsStore
from app.ops_audit_store import OpsAuditStore
from app.ops_news_routes import admin_news_create, admin_news_list, admin_news_update
from _support.ops_audit_helpers import OTHER, OWNER, database, request

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

NOW = '2026-11-20T00:00:00.000Z'
FB = 'fb_' + 'd' * 32


@pytest.mark.skipif(sync_playwright is None, reason='playwright is not installed')
def test_admin_news_works_and_guest_news_calls_are_zero(tmp_path, monkeypatch):
    path = tmp_path / 'news.sqlite3'
    db, _ = database(path, full=True)
    db.execute('INSERT INTO product_feedback '
               '(id,user_id,body,created_day,created_at,updated_at) VALUES (?,?,?,?,?,?)',
               (FB, OWNER, '검증 의견', NOW[:10], NOW, NOW))
    db.close()
    monkeypatch.setattr('app.ops_audit_store._now', lambda: NOW)
    directory = Path(__file__).resolve().parents[1] / ('sta' + 'tic')
    news_calls = []

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def log_message(self, *_args):
            pass

        def respond(self, status, raw):
            self.send_response(status)
            self.send_header('content-type', 'application/json')
            self.send_header('content-length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def api(self, method):
            parts = urlsplit(self.path)
            if parts.path == '/api/admin/session':
                body = {'ok': True, 'authenticated': self.server.admin,
                        'role': 'ADMIN' if self.server.admin else None,
                        'capabilities': {'admin_hub': True, 'chat_admin': True}
                        if self.server.admin else {}}
                self.respond(200, json.dumps(body).encode())
                return
            if not parts.path.startswith('/api/admin/news'):
                self.respond(200, b'{"ok":true,"feedback":[],"audit":[],"members":[]}')
                return
            news_calls.append((method, parts.path))
            length = int(self.headers.get('content-length') or 0)
            data = json.loads(self.rfile.read(length)) if length else None
            conn = sqlite3.connect(str(path), isolation_level=None)
            conn.row_factory = sqlite3.Row
            try:
                adapter = SqliteD1(conn)
                req = request(D1FeedbackStore(adapter), method=method,
                              user=OTHER if self.server.admin else None,
                              path=parts.path, body=data)
                req.app.state.news_store = D1NewsStore(adapter, now=lambda: NOW)
                req.app.state.ops_audit_store = OpsAuditStore(adapter)
                handler = {'GET': admin_news_list, 'POST': admin_news_create,
                           'PATCH': admin_news_update}[method]
                if method == 'PATCH':
                    req.scope['path_params'] = {'number': int(parts.path.rsplit('/', 1)[1])}
                res = asyncio.run(handler(req))
                self.respond(res.status_code, res.body)
            finally:
                conn.close()

        def do_GET(self):
            if self.path.startswith('/api/'):
                self.api('GET')
            else:
                super().do_GET()

        def do_POST(self):
            self.api('POST')

        def do_PATCH(self):
            self.api('PATCH')

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.admin = False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}/admin' + '.html#ops-news'
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            guest = browser.new_page()
            guest.goto(url, wait_until='domcontentloaded')
            guest.wait_for_selector('#gatePanel:not([hidden])')
            guest.evaluate("() => document.getElementById('opsTabNews').click()")
            guest.wait_for_load_state('networkidle')
            assert news_calls == []
            guest.close()
            server.admin = True
            page = browser.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(url, wait_until='domcontentloaded')
            page.wait_for_selector('#opsNewsPane:not([hidden])')
            page.fill('#opsNewsVersion', '2026.11.20')
            page.fill('#opsNewsTitle', '새 소식')
            page.fill('#opsNewsDetail', '설명')
            page.select_option('#opsNewsSource', 'ai_tester')
            page.fill('#opsNewsFeedback', FB)
            page.click('#opsNewsSubmit')
            page.wait_for_selector('#opsNewsList .ops-news-row')
            row = page.locator('#opsNewsList .ops-news-row')
            assert '새 소식' in row.inner_text() and FB in row.inner_text()
            row.get_by_text('고치기', exact=True).click()
            page.fill('#opsNewsTitle', '고친 새 소식')
            page.select_option('#opsNewsSource', 'user')
            page.click('#opsNewsSubmit')
            page.wait_for_function("() => document.getElementById('opsNewsList').innerText.includes('고친 새 소식')")
            assert '사용자 의견' in row.inner_text() and FB in row.inner_text()
            assert errors == []
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute('SELECT number,title,source,published_at FROM product_news').fetchall() == [
            (1, '고친 새 소식', 'user', NOW)]
        assert conn.execute('SELECT news_number FROM product_feedback WHERE id=?', (FB,)).fetchone() == (1,)
        audit = conn.execute("SELECT action FROM ops_audit_log WHERE action IN ('news_create','news_update')").fetchall()
        assert sorted(audit) == [('news_create',), ('news_update',)]
    finally:
        conn.close()
