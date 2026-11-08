"""브라우저 가드: 음성 Live 엔진이 같은 출처 중계만 알고 프로바이더를 노출하지 않음 (#6828).

실제 브라우저에서 정적 페이지를 열어 엔진의 URL 계약을 확인한다.
연결→말하기→응답→끊기 흐름은 가짜 프로바이더 Node 하네스가 담당한다.
"""
from __future__ import annotations

import http.server
import threading
from pathlib import Path

import pytest

try:  # pragma: no cover
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

requires_browser = pytest.mark.skipif(sync_playwright is None, reason="playwright not installed")

STATIC = Path(__file__).resolve().parents[1] / "static"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC), **kw)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def server():
    with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as web:
        threading.Thread(target=web.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@requires_browser
def test_browser_live_engine_only_knows_the_same_origin_relay(server):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(server, wait_until="domcontentloaded")
        page.wait_for_function("() => !!window.PadiemVoiceLiveSession", timeout=15000)
        info = page.evaluate("""() => {
          const e = window.PadiemVoiceLiveSession;
          const url = e.buildLiveUrl();
          return { url: url, host: location.host, path: e.LIVE_WS_PATH };
        }""")
        assert info["path"] == "/api/voice/relay"
        assert info["url"].endswith("/api/voice/relay")
        assert info["host"] in info["url"]
        assert "access_token" not in info["url"]
        browser.close()
