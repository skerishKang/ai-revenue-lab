# -*- coding: utf-8 -*-
"""#8732 — activity share button and the clean canonical share URL."""
from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

ROOT = Path(__file__).resolve().parents[1]
CHROME = next(
    (c for c in (os.environ.get("B61_CHROME_PATH"),
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe")
     if c and Path(c).is_file()),
    None,
)
DATA = json.loads((ROOT / "static" / "miraen.json").read_text(encoding="utf-8"))


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BUILD_DIR), **kwargs)

    def guess_type(self, path):
        value = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else value

    def log_message(self, *_args):
        pass


class StaticServer(http.server.ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


BUILD_DIR = None


@pytest.fixture(scope="module")
def build_dir(tmp_path_factory):
    global BUILD_DIR
    out = tmp_path_factory.mktemp("councillor-8732-dist")
    result = subprocess.run(
        [sys.executable, "scripts/build-dist", "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    BUILD_DIR = out
    return out


@pytest.fixture(scope="module")
def base_url(build_dir):
    server = StaticServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None or not CHROME:
        pytest.skip("playwright or Chrome is not installed")
    with sync_playwright() as playwright:
        launched = playwright.chromium.launch(headless=True, executable_path=CHROME)
        yield launched
        launched.close()


def test_share_button_is_prerendered_but_hidden_without_scripts(build_dir):
    html = (build_dir / "activity.html").read_text(encoding="utf-8")
    assert 'id="activityShare"' in html and "공유하기" in html
    assert 'id="activityShare" type="button" hidden' in html
    assert 'id="shareStatus" role="status" aria-live="polite" hidden' in html
    assert '<meta name="site-base" content="https://councillor-prototype-v2.pages.dev" />' in html
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert "navigator.share(" in app_js and "navigator.clipboard.writeText" in app_js
    assert "주소를 복사했습니다" in app_js
    assert "kakao" not in app_js.lower()


def test_share_url_has_no_query_and_ends_with_activity_id(browser, base_url):
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    ctx.add_init_script("""(() => {
      Object.defineProperty(navigator, 'share', { value: undefined, configurable: true });
      window.__copied = [];
      Object.defineProperty(navigator, 'clipboard', {
        value: { writeText: (text) => { window.__copied.push(text); return Promise.resolve(); } },
        configurable: true,
      });
    })();""")
    page = ctx.new_page()
    try:
        # Arrive from the home search, so the address bar carries ?q=…&scope=all.
        page.goto(base_url + "activity.html?q=%EC%A3%BC%EA%B1%B0&scope=all#a-2026-11-04-01", wait_until="load")
        page.wait_for_selector("#activityShare:not([hidden])")
        button = page.locator("#activityShare")
        assert button.is_visible()
        assert button.evaluate("(e) => e.getBoundingClientRect().height") >= 44
        button.click()
        page.wait_for_timeout(300)
        copied = page.evaluate("() => window.__copied")
        assert len(copied) == 1, copied
        assert copied[0] == "https://councillor-prototype-v2.pages.dev/activity#a-2026-11-04-01", copied
        assert "?q=" not in copied[0]
        assert copied[0].endswith("#a-2026-11-04-01")
        status = page.locator("#shareStatus")
        assert status.is_visible() and status.inner_text() == "주소를 복사했습니다"
    finally:
        ctx.close()


def test_share_button_works_in_all_viewports_and_themes(browser, base_url):
    for theme in ("light", "dark"):
        for width, height in ((390, 844), (820, 1180), (1440, 900)):
            ctx = browser.new_context(viewport={"width": width, "height": height})
            if theme == "dark":
                ctx.add_init_script("try{localStorage.setItem('theme','dark')}catch(e){}")
            ctx.add_init_script("""(() => {
              Object.defineProperty(navigator, 'share', { value: undefined, configurable: true });
              window.__copied = [];
              Object.defineProperty(navigator, 'clipboard', {
                value: { writeText: (t) => { window.__copied.push(t); return Promise.resolve(); } },
                configurable: true,
              });
            })();""")
            page = ctx.new_page()
            errors = []
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errors.append(str(e)))
            try:
                page.goto(base_url + "activity.html#a-2026-11-04-01", wait_until="load")
                page.wait_for_selector("#activityShare:not([hidden])")
                page.locator("#activityShare").click()
                page.wait_for_timeout(200)
                assert page.evaluate("() => window.__copied.length") == 1
                assert page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1
                assert not errors, errors
            finally:
                ctx.close()
