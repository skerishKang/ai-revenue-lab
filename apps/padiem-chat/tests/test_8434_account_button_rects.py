"""#8434 — 로그인 계정 버튼의 머리글자 원 위치·간격을 계산값으로 고정한다."""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = ["light", "dark", "cinematic", "padiem-home", "padiem-glass"]
VIEWPORTS = [(1440, 900), (768, 900), (390, 844)]
SIGNED_IN = {
    "ok": True, "ready": True, "authenticated": True, "history_ready": True,
    "project_files_ready": True,
    "user": {"name": "강철원", "email": "account@example.local", "id": "usr_8434", "picture": None},
    "session_state": "signed_in", "shared_login_enabled": True,
    "shared_session_present": True,
}
MEASURE = """() => {
  const b = document.querySelector('#accountProfileButton');
  const c = document.querySelector('.sidebar-account > .account-avatar:not([hidden])');
  const n = document.querySelector('#accountName');
  if (!b || !c || !n) return null;
  const rect = e => { const r = e.getBoundingClientRect();
    return {l: r.left, t: r.top, r: r.right, b: r.bottom}; };
  const rb = rect(b), rc = rect(c), rn = rect(n);
  return {
    leftPad: rc.l - rb.l,
    gap: rn.l - rc.r,
    vCenterDelta: ((rc.t + rc.b) / 2) - ((rn.t + rn.b) / 2),
    inside: rc.l >= rb.l && rc.r <= rb.r && rc.t >= rb.t && rc.b <= rb.b,
  };
}"""


class _Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser, f"http://127.0.0.1:{httpd.server_port}/index.html"
        finally:
            browser.close()
    httpd.shutdown()


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_account_avatar_keeps_its_rects(site, theme, width, height):
    browser, url = site
    context = browser.new_context(viewport={"width": width, "height": height}, locale="ko-KR")

    def route(request):
        if "/api/auth/status" in request.request.url:
            request.fulfill(status=200, content_type="application/json", body=json.dumps(SIGNED_IN))
        else:
            request.continue_()

    context.route("**/*", route)
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(900)
    page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
    page.wait_for_timeout(500)
    if width == 390:
        page.click("#mobileMenu")
        page.wait_for_timeout(400)
    measured = page.evaluate(MEASURE)
    context.close()

    assert measured is not None
    assert measured["inside"] is True
    assert measured["leftPad"] >= 8, measured
    assert measured["gap"] >= 8, measured
    assert abs(measured["vCenterDelta"]) <= 2, measured
