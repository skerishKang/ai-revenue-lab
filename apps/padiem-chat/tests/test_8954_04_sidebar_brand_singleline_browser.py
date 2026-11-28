"""#8954-4: Padiem Chat stays on one line without covering the sidebar control."""
from __future__ import annotations

import http.server
import os
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = ("light", "dark", "cinematic", "padiem-glass", "padiem-home")


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def url():
    with http.server.ThreadingHTTPServer(("127.0.0.1", int(os.getenv("CGI_8954_PORT", "0"))), _Handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
        finally:
            server.shutdown()
            worker.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("Playwright required")
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("width", [390, 1440])
def test_sidebar_brand_stays_single_line_and_clear_of_controls(browser, url, theme, width):
    page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
    try:
        page.goto(f"{url}?theme={theme}", wait_until="domcontentloaded")
        if width == 390:
            page.locator("#mobileMenu").click(timeout=5000)
        state = page.evaluate("""() => {
          const brand=document.querySelector('.brand-row .brand');
          const text=brand.querySelector('span:last-child');
          const mark=brand.querySelector('.brand-mark');
          const collapse=document.getElementById('sidebarCollapseButton');
          const row=document.querySelector('.brand-row');
          const range=document.createRange();range.selectNodeContents(text);
          const fragments=[...range.getClientRects()];
          const a=text.getBoundingClientRect(), b=collapse.getBoundingClientRect();
          return {label:text.textContent.trim(), lines:fragments.length,
            insideRow:a.right<=row.getBoundingClientRect().right+0.5,
            outsideMark:a.left>=mark.getBoundingClientRect().right,
            overlappingCollapse:getComputedStyle(collapse).display!=='none' &&
              a.left<b.right && a.right>b.left && a.top<b.bottom && a.bottom>b.top};
        }""")
        assert state["label"] == "Padiem Chat", state
        assert state["lines"] == 1, (width, theme, state)
        assert state["insideRow"] and state["outsideMark"], (width, theme, state)
        assert not state["overlappingCollapse"], (width, theme, state)
    finally:
        page.close()
