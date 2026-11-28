"""#8954-7 PC connected notice does not overlap the live microphone/composer."""
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


@pytest.mark.parametrize("width", [390, 1440])
@pytest.mark.parametrize("theme", THEMES)
def test_connected_notice_is_above_composer_and_mics(browser, url, width, theme):
    page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
    try:
        page.goto(f"{url}?theme={theme}", wait_until="domcontentloaded")
        page.evaluate("""() => {
          const el=document.createElement('p');
          el.className='pc-connect-note';el.setAttribute('role','status');
          el.textContent='내 컴퓨터 연결됨 ✓';document.body.append(el);
        }""")
        state = page.evaluate("""() => {
          const box=sel=>document.querySelector(sel).getBoundingClientRect();
          const note=box('.pc-connect-note'), composer=box('.composer-wrap');
          const mic=box('#voiceMicButton'),wave=box('#voiceWaveformButton');
          const overlap=(a,b)=>Math.max(0,Math.min(a.right,b.right)-Math.max(a.left,b.left)) *
            Math.max(0,Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top));
          return {noteBottom:note.bottom, noteTop:note.top, composerTop:composer.top,
            microphoneOverlap:overlap(note,mic), waveformOverlap:overlap(note,wave),
            inViewport:note.top>=0 && note.bottom<=innerHeight,
            text:document.querySelector('.pc-connect-note').textContent};
        }""")
        assert state["text"] == "내 컴퓨터 연결됨 ✓"
        assert state["inViewport"], (width, theme, state)
        assert state["noteBottom"] <= state["composerTop"], (width, theme, state)
        assert state["microphoneOverlap"] == 0, (width, theme, state)
        assert state["waveformOverlap"] == 0, (width, theme, state)
    finally:
        page.close()
