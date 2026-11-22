"""#8340 1차 — light·padiem-home 테마 아바타 캡 제거 후 계산값 고정.

정적 원문을 읽지 않고, 로컬 정적 서버와 모의 API 응답으로 채팅 상태를 만든 뒤
Chromium getComputedStyle 값을 확인한다. 값 리터럴은 시트가 아니라 계산 결과다.
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
  if (!shell) return { ready: false };
  shell.dataset.state = 'chat';
  const list = document.getElementById('messageList');
  if (!list) return { ready: false };
  list.hidden = false;
  const msg = document.createElement('div');
  msg.className = 'assistant-message';
  const avatar = document.createElement('span');
  avatar.className = 'assistant-avatar';
  avatar.textContent = 'A';
  msg.appendChild(avatar);
  list.appendChild(msg);
  return { ready: true };
}"""

READ = """() => {
  const el = document.querySelector('.assistant-avatar');
  if (!el) return null;
  const cs = getComputedStyle(el);
  const out = {};
  for (const prop of ['background-image', 'background-color', 'border-top-width',
                      'border-top-color', 'color', 'box-shadow']) {
    out[prop] = cs.getPropertyValue(prop);
  }
  return out;
}"""

EXPECTED = {
    "light": {
        "background-image": "linear-gradient(135deg, rgb(119, 104, 238), rgb(79, 64, 206))",
        "background-color": "rgba(0, 0, 0, 0)",
        "border-top-width": "0px",
        "border-top-color": "rgb(255, 255, 255)",
        "color": "rgb(255, 255, 255)",
        "box-shadow": "rgba(85, 70, 214, 0.12) 0px 6px 18px 0px",
    },
    "padiem-home": {
        "background-image": "none",
        "background-color": "rgba(255, 255, 255, 0.72)",
        "border-top-width": "1px",
        "border-top-color": "rgba(26, 34, 48, 0.12)",
        "color": "rgb(26, 34, 48)",
        "box-shadow": "rgba(26, 34, 48, 0.08) 0px 6px 18px 0px",
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
            page.wait_for_timeout(1200)
            marker = page.evaluate(FILL)
            assert marker.get("ready") is True, marker
            page.wait_for_timeout(300)
            return page.evaluate(READ)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize("theme", sorted(EXPECTED))
def test_theme_avatar_keeps_its_computed_values_without_importance(site, theme, width, height):
    observed = _read(site, theme, width, height)
    for prop, want in EXPECTED[theme].items():
        got = observed[prop]
        assert got == want, (theme, width, height, prop, want, got)
