# -*- coding: utf-8 -*-
"""#8740 — text-size toggle: one token change, remembered before first paint."""
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

pytestmark_browser = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

ROOT = Path(__file__).resolve().parents[1]
CHROME = next(
    (c for c in (os.environ.get("B61_CHROME_PATH"),
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe")
     if c and Path(c).is_file()),
    None,
)
PAGES = ["index.html", "about.html", "activity.html", "policy.html", "media.html", "news.html", "404.html"]
sys.path.insert(0, str(ROOT / "scripts"))
import assemble  # noqa: E402
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
    out = tmp_path_factory.mktemp("councillor-8740-dist")
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


def test_every_page_has_the_text_size_button_and_early_script():
    for page in PAGES:
        html = assemble.render(page)
        assert 'id="textSizeToggle"' in html, page
        assert 'aria-pressed="false"' in html, page
        assert "글씨 크게" in html and "글씨 보통" in html, page
        assert 'localStorage.getItem("textSize")' in html, page
    css = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    assert 'html[data-text-size="large"]' in css
    assert "--fs-body: 20px" in css and "--fs-label: 17px" in css
    assert ".lightbox-source" in css and "font-size: var(--fs-body)" in css
    assert any("'글씨 크게'로 글자를 크게 볼 수 있습니다." in line
               for n in DATA["news"] if n["date"] == "2026-11-25" for line in n["changes"])


@pytestmark_browser
def test_toggle_changes_computed_size_and_survives_reload(browser, base_url):
    ctx = browser.new_context(viewport={"width": 820, "height": 1180})
    page = ctx.new_page()
    try:
        page.goto(base_url + "activity.html", wait_until="load")
        assert page.evaluate("() => getComputedStyle(document.body).fontSize") == "16px"
        button = page.locator("#textSizeToggle")
        assert button.get_attribute("aria-pressed") == "false"
        assert button.inner_text().strip() == "글씨 크게"
        button.click()
        assert page.evaluate("() => document.documentElement.getAttribute('data-text-size')") == "large"
        assert page.evaluate("() => getComputedStyle(document.body).fontSize") == "20px"
        assert button.get_attribute("aria-pressed") == "true"
        assert button.inner_text().strip() == "글씨 보통"
        page.reload(wait_until="load")
        assert page.evaluate("() => document.documentElement.getAttribute('data-text-size')") == "large"
        assert page.evaluate("() => getComputedStyle(document.body).fontSize") == "20px"
        assert page.locator("#textSizeToggle").get_attribute("aria-pressed") == "true"
        page.locator("#textSizeToggle").click()
        assert page.evaluate("() => document.documentElement.getAttribute('data-text-size')") is None
        assert page.evaluate("() => getComputedStyle(document.body).fontSize") == "16px"
    finally:
        ctx.close()


@pytestmark_browser
def test_matrix_has_no_overflow_shift_or_header_break(browser, base_url):
    CLS = ("window.__cls=0; new PerformanceObserver(l=>{for(const e of l.getEntries()) "
           "if(!e.hadRecentInput) window.__cls+=e.value;}).observe({type:'layout-shift',buffered:true});")
    for size in ("normal", "large"):
        for theme in ("light", "dark"):
            for width, height in ((390, 844), (820, 1180), (1440, 900)):
                ctx = browser.new_context(viewport={"width": width, "height": height})
                if theme == "dark":
                    ctx.add_init_script("try{localStorage.setItem('theme','dark')}catch(e){}")
                if size == "large":
                    ctx.add_init_script("try{localStorage.setItem('textSize','large')}catch(e){}")
                page = ctx.new_page()
                page.add_init_script(CLS)
                errors = []
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e: errors.append(str(e)))
                try:
                    for name in PAGES:
                        page.goto(base_url + name, wait_until="load")
                        page.wait_for_timeout(200)
                        assert page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 1, (size, theme, width, name)
                        assert page.evaluate("() => window.__cls") < 0.1, (size, theme, width, name)
                        boxes = page.evaluate("""() => ['themeToggle','textSizeToggle']
                          .map(id => { const r = document.getElementById(id).getBoundingClientRect();
                            return {l:r.left,r:r.right,t:r.top,b:r.bottom}; })""")
                        assert len(boxes) == 2 and all(b["r"] <= width + 1 and b["l"] >= -1 for b in boxes), (size, theme, width, boxes)
                        assert boxes[0]["b"] <= boxes[1]["t"] + 1 or boxes[0]["r"] <= boxes[1]["l"] + 1 or boxes[1]["r"] <= boxes[0]["l"] + 1, (size, theme, width, boxes)
                    # lightbox still clears the fixed tab bar on the phone
                    if width == 390:
                        page.goto(base_url + "media.html", wait_until="load")
                        page.locator('a[aria-label="제1차 산업건설위원회 크게 보기"]').click()
                        page.wait_for_timeout(200)
                        overlap = page.evaluate("""() => { const t = document.querySelector('.mobile-tabbar').getBoundingClientRect();
                          const s = document.getElementById('lightboxSource').getBoundingClientRect();
                          const l = document.getElementById('lightboxLink').getBoundingClientRect();
                          const area = (r) => Math.max(0,Math.min(r.bottom,t.bottom)-Math.max(r.top,t.top)) * Math.max(0,Math.min(r.right,t.right)-Math.max(r.left,t.left));
                          return {source:area(s), link:area(l)}; }""")
                        assert overlap == {"source": 0, "link": 0}, (size, theme, overlap)
                    assert not errors, errors
                finally:
                    ctx.close()
