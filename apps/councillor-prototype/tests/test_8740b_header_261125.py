# -*- coding: utf-8 -*-
"""#8740 follow-up — header labels must never break mid-word on narrow screens."""
from __future__ import annotations

import http.server
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
WIDTHS = (320, 360, 390, 430, 480, 820, 1440)
SIZES = ("normal", "large")
THEMES = ("light", "dark")


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
    out = tmp_path_factory.mktemp("councillor-8740b-dist")
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


LINES_JS = """() => {
  const lines = (el) => {
    if (!el) return 0;
    const range = document.createRange();
    range.selectNodeContents(el);
    const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
    return rects.length ? new Set(rects.map(r => Math.round(r.top))).size : 1;
  };
  const visibleLabel = (el) => [...el.querySelectorAll('span')]
    .find(s => getComputedStyle(s).display !== 'none') || el;
  const themeBtn = document.getElementById('themeToggle');
  const textBtn = document.getElementById('textSizeToggle');
  const a = themeBtn.getBoundingClientRect();
  const b = textBtn.getBoundingClientRect();
  return {
    nameLines: lines(document.querySelector('.brand-name')),
    themeLines: lines(visibleLabel(themeBtn)),
    textLines: lines(visibleLabel(textBtn)),
    theme: {w: Math.round(a.width), h: Math.round(a.height)},
    text: {w: Math.round(b.width), h: Math.round(b.height)},
    gap: Math.round(b.left - a.right),
    headerHeight: Math.round(document.querySelector('.topbar').getBoundingClientRect().height),
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
  };
}"""


def test_header_has_no_broken_words_in_any_condition(browser, base_url):
    broken = []
    for width in WIDTHS:
        for size in SIZES:
            for theme in THEMES:
                ctx = browser.new_context(viewport={"width": width, "height": 900})
                if theme == "dark":
                    ctx.add_init_script("try{localStorage.setItem('theme','dark')}catch(e){}")
                if size == "large":
                    ctx.add_init_script("try{localStorage.setItem('textSize','large')}catch(e){}")
                page = ctx.new_page()
                try:
                    page.goto(base_url + "index.html", wait_until="load")
                    m = page.evaluate(LINES_JS)
                    key = f"{width}/{size}/{theme}"
                    if m["nameLines"] > 1 or m["themeLines"] > 1 or m["textLines"] > 1:
                        broken.append((key, "lines", m))
                    if m["theme"]["w"] < 44 or m["theme"]["h"] < 44:
                        broken.append((key, "theme size", m))
                    if m["text"]["w"] < 44 or m["text"]["h"] < 44:
                        broken.append((key, "text size", m))
                    if m["gap"] < 8:
                        broken.append((key, "gap", m))
                    if m["overflow"] > 1:
                        broken.append((key, "overflow", m))
                finally:
                    ctx.close()
    assert not broken, f"broken header conditions: {broken}"


def test_large_text_does_not_grow_the_header(browser, base_url):
    heights = {}
    for size in SIZES:
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        if size == "large":
            ctx.add_init_script("try{localStorage.setItem('textSize','large')}catch(e){}")
        page = ctx.new_page()
        try:
            page.goto(base_url + "index.html", wait_until="load")
            heights[size] = page.evaluate(LINES_JS)["headerHeight"]
        finally:
            ctx.close()
    assert heights["normal"] == heights["large"], heights
