# -*- coding: utf-8 -*-
"""#8740 follow-up — the first-screen intro paragraph must follow the large-text token at every width."""
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
WIDTHS = (390, 820, 1440)


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
    out = tmp_path_factory.mktemp("councillor-8740c-dist")
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


def test_hero_lead_follows_text_size_at_every_width(browser, base_url):
    measured = {}
    for width in WIDTHS:
        for size, expected in (("normal", "16px"), ("large", "20px")):
            ctx = browser.new_context(viewport={"width": width, "height": 900})
            if size == "large":
                ctx.add_init_script("try{localStorage.setItem('textSize','large')}catch(e){}")
            page = ctx.new_page()
            try:
                page.goto(base_url + "index.html", wait_until="load")
                page.wait_for_timeout(150)
                got = page.evaluate("() => getComputedStyle(document.querySelector('.hero-lead')).fontSize")
                measured[f"{width}/{size}"] = got
                assert got == expected, (width, size, got)
                overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                assert overflow <= 1, (width, size, overflow)
            finally:
                ctx.close()
    assert measured


def test_large_text_hero_does_not_overlap_portrait(browser, base_url):
    for width in WIDTHS:
        ctx = browser.new_context(viewport={"width": width, "height": 900})
        ctx.add_init_script("try{localStorage.setItem('textSize','large')}catch(e){}")
        page = ctx.new_page()
        try:
            page.goto(base_url + "index.html", wait_until="load")
            page.wait_for_timeout(150)
            overlap = page.evaluate("""() => {
              const a = document.querySelector('.hero-lead').getBoundingClientRect();
              const b = document.querySelector('.hero-portrait').getBoundingClientRect();
              return Math.max(0, Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)) *
                     Math.max(0, Math.min(a.right,b.right)-Math.max(a.left,b.left));
            }""")
            assert overlap == 0, (width, overlap)
        finally:
            ctx.close()
