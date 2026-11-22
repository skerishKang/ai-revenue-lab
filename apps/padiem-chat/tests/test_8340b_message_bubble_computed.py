"""#8340 2차 — light·padiem-home 테마 메시지 버블 캡 제거 후 계산값 고정.

원문을 읽지 않고 로컬 정적 서버와 모의 API 응답으로 채팅 상태를 만든 뒤
Chromium getComputedStyle 값을 확인한다.
"""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright  # noqa: E402
except ImportError:
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None,
                                reason="playwright is not installed in this lane")

STATIC = Path(__file__).resolve().parents[1] / "static"

STATUS = {
    "ready": True, "authenticated": False, "user": None,
    "session_state": "guest", "shared_login_enabled": False,
    "shared_session_present": False, "status_reachable": True,
    "history_ready": False, "project_files_ready": False,
    "model_requires_session": False,
}

FETCH_STUB = """
(() => {
  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  const headers = { 'content-type': 'application/json' };
  const answer = (body) => Promise.resolve(new Response(JSON.stringify(body), {
    status: 200, statusText: 'OK', headers,
  }));
  const offline = () => Promise.resolve(new Response('{"ok":false}', {
    status: 404, statusText: 'Not Found', headers,
  }));
  window.fetch = (input, init) => {
    const url = String(typeof input === 'string' ? input : (input && input.url) || '');
    if (!url.includes('/api/')) return realFetch ? realFetch(input, init) : offline();
    if (url.includes('/api/auth/status')) return answer(__STATUS__);
    return offline();
  };
})();
""".replace("__STATUS__", json.dumps(STATUS))

FILL = """() => {
  const shell = document.querySelector('.app-shell');
  const list = document.getElementById('messageList');
  const tpl = document.getElementById('userMessageTemplate');
  if (!shell || !list || !tpl) return { ready: false };
  shell.dataset.state = 'chat';
  const node = tpl.content.firstElementChild.cloneNode(true);
  list.appendChild(node);
  return { ready: true };
}"""

READ = """() => {
  const el = document.querySelector('.message-bubble');
  if (!el) return null;
  const cs = getComputedStyle(el);
  const out = {};
  for (const prop of ['background-image', 'background-color', 'color', 'border-top-width',
                      'border-top-color', 'box-shadow', 'backdrop-filter']) {
    out[prop] = cs.getPropertyValue(prop);
  }
  return out;
}"""

EXPECTED = {
    "light": {
        "background-image": "none",
        "background-color": "rgb(101, 87, 232)",
        "color": "rgb(255, 255, 255)",
        "border-top-width": "1px",
        "border-top-color": "rgba(0, 0, 0, 0)",
        "box-shadow": "rgba(101, 87, 232, 0.06) 0px 2px 10px 0px",
        "backdrop-filter": "none",
    },
    "padiem-home": {
        "background-image": "none",
        "background-color": "rgb(26, 34, 48)",
        "color": "rgb(255, 255, 255)",
        "border-top-width": "1px",
        "border-top-color": "rgba(0, 0, 0, 0)",
        "box-shadow": "rgba(26, 34, 48, 0.1) 0px 4px 16px 0px",
        "backdrop-filter": "blur(18px)",
    },
}

VIEWPORTS = [(1440, 950), (1100, 900), (390, 844)]


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d/index.html" % server.server_port
    finally:
        server.shutdown()
        thread.join(timeout=5)


def _read(url, theme, width, height):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": width, "height": height},
                                    reduced_motion="reduce")
            page.route("**/*", lambda route: route.continue_()
                       if "127.0.0.1" in route.request.url else route.abort())
            page.add_init_script(FETCH_STUB)
            page.goto(url + "?theme=" + theme, wait_until="load")
            page.wait_for_timeout(1000)
            marker = page.evaluate(FILL)
            assert marker.get("ready") is True, marker
            page.wait_for_timeout(300)
            return page.evaluate(READ)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize("theme", sorted(EXPECTED))
def test_theme_bubble_keeps_its_computed_values_without_importance(site, theme, width, height):
    observed = _read(site, theme, width, height)
    for prop, want in EXPECTED[theme].items():
        got = observed[prop]
        assert got == want, (theme, width, height, prop, want, got)
