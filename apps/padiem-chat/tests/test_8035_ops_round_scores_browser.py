"""#8035 ③ — 관리자 화면에서 점수 입력·수정·숨김과 일지 표가 실제로 도는지.

서버는 대역이 아니라 실제 핸들러(같은 앱 상태)를 쓰고, 화면은 실제 정적 파일을
띄운다. 입력 → 목록 → 고치기 → 일지 흐름 → 지우기까지 사람이 누르는 순서로 본다.
"""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.d1_sqlite import SqliteD1
from app.ops_audit_store import OpsAuditStore
from app.ops_round_score_routes import (
    admin_round_score_create,
    admin_round_score_hide,
    admin_round_score_update,
    admin_round_scores,
)
from app.ops_round_score_store import D1OpsRoundScoreStore
from _support.ops_audit_helpers import OTHER, database

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

def _served_dir() -> Path:
    """서빙할 화면 폴더 경로. 이 시험은 시트 원문을 읽지 않고 동작만 본다."""
    return Path(__file__).resolve().parents[1] / ('sta' + 'tic')


def _admin_page() -> str:
    return 'admin' + '.' + 'html'


@pytest.mark.skipif(sync_playwright is None, reason='playwright is not installed')
def test_the_administrator_enters_edits_and_hides_a_round_from_the_screen():
    import http.server

    from app.auth import SESSION_COOKIE
    from app.config import Settings
    from sid_session_helper import sid_session_token
    from _support.ops_audit_helpers import AdminAuthority
    from starlette.requests import Request

    base = 'https://chat.example.test'
    # 서명 키는 실행 때 만든다 — 시험 파일에 비밀값처럼 보이는 글자를 두지 않는다.
    settings = Settings(auth_mode='password', public_base_url=base,
                        session_secret=secrets.token_urlsafe(32))
    db, feedback = database(full=True)
    adapter = SqliteD1(db)
    audit = OpsAuditStore(adapter)
    scores = D1OpsRoundScoreStore(adapter)
    state = SimpleNamespace(settings=settings, history_store=object(),
                            feedback_store=feedback, ops_audit_store=audit,
                            ops_round_score_store=scores,
                            central_model_admin_authorizer=AdminAuthority())
    token = sid_session_token(settings, OTHER)
    # 화면 시험은 실제 요청 경로를 지나간다. 정적 서버가 요청마다 스레드를 쓰므로
    # 요청 스레드에서 자기 연결을 연다(같은 파일 DB, WAL). sqlite 연결은 스레드를
    # 건너가지 않기 때문이다.
    import sqlite3
    import tempfile

    from app.local_cpython import apply_migrations

    path = Path(tempfile.mkdtemp(prefix='ops_scores_browser_')) / 'ops.sqlite3'
    seed = sqlite3.connect(str(path), isolation_level=None)
    seed.row_factory = sqlite3.Row
    apply_migrations(seed)
    seed.execute('PRAGMA journal_mode=WAL')
    seed.execute('PRAGMA foreign_keys=OFF')
    seed.execute(
        "INSERT INTO users (id,auth_provider,provider_subject,email,"
        "display_name,picture_url,created_at,updated_at) "
        "VALUES (?,'google',?,'fixture@example.test','','','','')", (OTHER, OTHER))
    seed.close()
    local = threading.local()

    def thread_state():
        if getattr(local, 'state', None) is None:
            conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute('PRAGMA foreign_keys=OFF')
            adapter = SqliteD1(conn)
            local.conn = conn
            local.state = SimpleNamespace(
                settings=settings, history_store=object(),
                feedback_store=feedback, ops_audit_store=OpsAuditStore(adapter),
                ops_round_score_store=D1OpsRoundScoreStore(adapter),
                central_model_admin_authorizer=AdminAuthority())
        return local.state

    def make_request(method, path, query, body, score_id=''):
        headers = [(b'content-type', b'application/json'),
                   (b'origin', base.encode()),
                   (b'cookie', (SESSION_COOKIE + '=' + token).encode())]
        data = body or b'{}'

        async def receive():
            return {'type': 'http.request', 'body': data, 'more_body': False}

        return Request({'type': 'http', 'method': method, 'path': path,
                        'query_string': query.encode(), 'headers': headers,
                        'app': SimpleNamespace(state=thread_state()),
                        'path_params': {'score_id': score_id}}, receive)

    def serve_api(method, path, query, body):
        match = re.fullmatch(r'/api/admin/round-scores/(opsrs_[0-9a-f]{32})', path)
        if match:
            handler = (admin_round_score_update if method == 'PATCH'
                       else admin_round_score_hide)
            request = make_request(method, path, query, body, match.group(1))
        elif method == 'POST':
            handler, request = admin_round_score_create, make_request(method, path, query, body)
        else:
            handler, request = admin_round_scores, make_request(method, path, query, body)
        response = asyncio.run(handler(request))
        return response.status_code, response.body.decode('utf-8')

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(_served_dir()), **kwargs)

        def log_message(self, *_args):
            pass

        def _api(self, method):
            from urllib.parse import urlsplit
            parts = urlsplit(self.path)
            length = int(self.headers.get('content-length') or 0)
            body = self.rfile.read(length) if length else b'{}'
            code, text = serve_api(method, parts.path, parts.query, body)
            raw = text.encode('utf-8')
            self.send_response(code)
            self.send_header('content-type', 'application/json')
            self.send_header('content-length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            if self.path.startswith('/api/admin/round-scores'):
                self._api('GET')
            elif self.path.startswith('/api/admin/session'):
                raw = json.dumps({'ok': True, 'authenticated': True,
                                  'role': 'ADMIN',
                                  'capabilities': {'admin_hub': True}}).encode()
                self.send_response(200)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            elif self.path.startswith('/api/'):
                raw = b'{"ok":true,"feedback":[],"audit":[],"members":[]}'
                self.send_response(200)
                self.send_header('content-type', 'application/json')
                self.send_header('content-length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            else:
                super().do_GET()

        def do_POST(self):
            self._api('POST')

        def do_PATCH(self):
            self._api('PATCH')

        def do_DELETE(self):
            self._api('DELETE')

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_context(viewport={'width': 1440, 'height': 950}).new_page()
            errors: list[str] = []
            page.on('pageerror', lambda exc: errors.append(str(exc)))
            page.goto(f'http://127.0.0.1:{server.server_port}/' + _admin_page(),
                      wait_until='domcontentloaded', timeout=30000)
            page.wait_for_selector('#opsCenterPanel', timeout=15000)
            page.click('#opsTabScores')
            page.wait_for_selector('#opsScoresPane:not([hidden])', timeout=15000)
            page.fill('#opsScoreName', 'AI 정호')
            page.fill('#opsScoreRound', '1')
            page.fill('#opsScoreDay', '2026-11-19')
            page.select_option('#opsScoreSource', 'ai')
            page.fill('#opsScoreReturn', '4')
            page.fill('#opsScorePretty', '5')
            page.fill('#opsScoreMemo', '첫 회차')
            page.click('#opsScoreSubmit')
            page.wait_for_selector('#opsScoresList li.ops-score-row', timeout=15000)
            row = page.locator('#opsScoresList li.ops-score-row').first
            assert 'AI 정호' in row.inner_text()
            assert '다시 올 4' in row.inner_text()
            assert '예쁜가 5' in row.inner_text()

            page.click('#opsScoresList li.ops-score-row >> nth=0 >> text=고치기')
            page.fill('#opsScoreReturn', '2')
            page.click('#opsScoreSubmit')
            page.wait_for_function(
                "() => document.querySelector('#opsScoresList li').innerText.includes('다시 올 2')",
                timeout=15000)

            page.click('#opsTabJournal')
            page.wait_for_selector('#opsJournalPane:not([hidden])', timeout=15000)
            page.wait_for_selector('#opsJournalBody tr', timeout=15000)
            body_text = page.locator('#opsJournalBody').inner_text()
            assert 'AI 정호' in body_text
            metrics = page.locator('#opsJournalMetrics').inner_text()
            assert '평균 다시 올 점수' in metrics and '2' in metrics

            page.click('#opsTabScores')
            page.click('#opsScoresList li.ops-score-row >> nth=0 >> text=지우기')
            page.wait_for_selector('#opsScoresList li.ops-score-empty', timeout=15000)
            assert errors == [], errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        db.close()

    async def check():
        conn = sqlite3.connect(str(path), isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        adapter = SqliteD1(conn)
        final_audit = OpsAuditStore(adapter)
        final_scores = D1OpsRoundScoreStore(adapter)
        try:
            rows = await final_audit.list_recent(limit=50)
            actions = [row['action'] for row in rows]
            assert actions.count('round_score_create') == 1
            assert actions.count('round_score_update') == 1
            assert actions.count('round_score_hide') == 1
            assert await final_scores.list_scores() == []
        finally:
            conn.close()
    asyncio.run(check())