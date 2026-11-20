"""#8105 — 게스트가 /admin 을 열면 알림 API 호출이 0건이다.

게이트만 보고 있는 게스트가 알림 단추를 강제로 눌러도 ops API는 부르지 않는다.
화면은 실제 정적 파일을 띄우고, 서버 응답은 대역으로 고정한다.
다른 시험 파일을 import하지 않는다.
"""
from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

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
def test_a_guest_on_admin_never_calls_the_alert_api():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(_served_dir()), **kwargs)

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    calls: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            ctx = browser.new_context(viewport={'width': 1440, 'height': 950})
            page = ctx.new_page()
            page.route(re.compile(r'.*/api/admin/session$'),
                       lambda route, req: route.fulfill(
                           status=200, content_type='application/json',
                           body=json.dumps({'ok': True, 'authenticated': False,
                                            'role': None, 'capabilities': {}})))
            page.route(re.compile(r'.*/api/.*$'),
                       lambda route, req: route.fulfill(
                           status=200, content_type='application/json', body='{}'))
            page.on('request', lambda req: calls.append(req.url)
                    if ('/api/admin/' in req.url
                        and '/api/admin/session' not in req.url) else None)
            page.goto(f'http://127.0.0.1:{server.server_port}/' + _admin_page(),
                      wait_until='domcontentloaded', timeout=30000)
            page.wait_for_selector('#gatePanel:not([hidden])', timeout=15000)
            page.wait_for_timeout(1200)
            page.evaluate("() => { document.getElementById('opsAlertReload').click();"
                          " document.getElementById('opsAlertDispatch').click(); }")
            page.wait_for_timeout(800)
            ctx.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    assert calls == [], calls[:3]