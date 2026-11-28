"""#8954-5: long Chat/Claw input keeps its first line above the scroll top."""
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
LONG_TEXT = "\n".join("첫 줄과 위 여백 검사 {} — 긴 문장을 반복해 입력칸 높이를 확인합니다.".format(i + 1)
                      for i in range(18))


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
def test_long_input_scrolls_inside_without_cutting_first_line(browser, url, theme, width):
    page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
    try:
        page.goto(f"{url}?theme={theme}", wait_until="domcontentloaded")
        field = page.locator("#messageInput")
        field.fill(LONG_TEXT)
        field.press("Control+End")
        field.press("Control+Home")
        state = field.evaluate("""e => {const s=getComputedStyle(e),f=e.closest('.composer');
          const er=e.getBoundingClientRect(),fr=f.getBoundingClientRect();
          return {scrollTop:e.scrollTop,scrollHeight:e.scrollHeight,clientHeight:e.clientHeight,
            height:er.height, overflowY:s.overflowY, paddingTop:parseFloat(s.paddingTop),
            scrollPaddingTop:parseFloat(s.scrollPaddingTop), topInside:er.top-fr.top};
        }""")
        assert state["scrollHeight"] > state["clientHeight"] + 100, state
        assert state["height"] <= 180.5 and state["overflowY"] == "auto", state
        assert state["paddingTop"] >= 7 and state["topInside"] >= 8, state
        assert state["scrollTop"] <= 1, (theme, width, state)
    finally:
        page.close()
