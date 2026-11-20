"""#8001 2차 — 팝업·패널 칸 배경/호버 계산 값 계약.

원문 글자 단언 없이 실제 Chromium 계산 값으로 확인한다. 계정·장치·DB는 건드리지 않고
정적 서버와 모의 API만 쓴다.
"""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None,
                                reason="playwright is not installed in this lane")

STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
SIGNED_IN = {"ok": True, "ready": True, "authenticated": True,
             "user": {"name": "QA", "email": "qa@example.test"},
             "member_grade": "free", "history_ready": True,
             "project_files_ready": True, "shared_login_enabled": True,
             "shared_session_present": True, "session_state": "signed_in"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/"):
            raw = json.dumps(SIGNED_IN if path == "/api/auth/status" else {"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        return super().do_GET()


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()


PROBE = """([sel, token]) => {
  const cells = [...document.querySelectorAll(sel)]
    .filter(e => !e.closest('[hidden]'));
  if (!cells.length) return null;
  const probe = document.createElement('span');
  probe.style.cssText = 'display:block;width:10px;height:10px;background:var(' + token + ')';
  cells[0].parentElement.appendChild(probe);
  const tokenBg = getComputedStyle(probe).backgroundColor;
  probe.remove();
  return { cellBg: getComputedStyle(cells[0]).backgroundColor, tokenBg };
}"""

CELLS = (
    ("calendar", "#calendarNavButton", ".calendar-visual-day"),
    ("claw", "#clawNavButton", ".claw-task-option:not(.claw-task-option-primary)"),
    ("news", "#newsButton", ".news-item"),
    ("feedback", "#feedbackButton", ".feedback-button"),
)


def _open(page, opener, panel):
    page.evaluate("() => document.querySelectorAll('dialog[open]').forEach(d => d.close())")
    page.click(opener, timeout=4000)
    page.wait_for_timeout(600)
    if panel == "news":
        page.evaluate("() => window.PadiemNews && window.PadiemNews.open()")
    if panel == "feedback":
        page.evaluate("() => document.getElementById('feedbackDialog').showModal()")
    if panel == "claw":
        page.evaluate("() => document.querySelector('.app-shell').dataset.state = 'claw'")
        page.evaluate("""() => {
          const ws = document.getElementById('clawWorkspace');
          if (ws) ws.dataset.view = 'general';
          for (const id of ['clawWorkspace', 'clawTaskHub']) {
            const el = document.getElementById(id);
            if (el) { el.hidden = false; el.style.setProperty('display', 'block', 'important'); }
          }
          document.querySelectorAll('.claw-task-option')
            .forEach(e => { e.hidden = false; e.style.setProperty('display', 'block', 'important'); });
        }""")
    page.wait_for_timeout(400)


@pytest.mark.parametrize("theme", THEMES)
def test_panel_cells_use_the_panel_card_token(site, theme):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            page.goto(f"{site}?theme={theme}", wait_until="load")
            page.wait_for_timeout(1600)
            for _panel, opener, sel in CELLS:
                _open(page, opener, _panel)
                got = page.evaluate(PROBE, [sel, "--card-bg"])
                assert got is not None, (_panel, theme)
                assert got["cellBg"] == got["tokenBg"], (_panel, theme, got)
        finally:
            browser.close()


@pytest.mark.parametrize("theme", THEMES)
def test_hovered_cells_use_the_one_control_wash_token(site, theme):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            page.goto(f"{site}?theme={theme}", wait_until="load")
            page.wait_for_timeout(1600)
            for _panel, opener, sel in CELLS:
                _open(page, opener, _panel)
                cells = page.query_selector_all(sel)
                target = next((c for c in cells if c.is_visible()), None)
                assert target is not None, (_panel, theme)
                target.hover(timeout=4000)
                page.wait_for_timeout(350)
                got = page.evaluate(PROBE, [sel, "--control-wash-hover"])
                assert got is not None, (_panel, theme)
                assert got["cellBg"] == got["tokenBg"], (_panel, theme, got)
        finally:
            browser.close()


def test_tampering_card_bg_moves_the_cells_but_not_the_control(site):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            page.goto(f"{site}?theme=light", wait_until="load")
            page.wait_for_timeout(1600)
            page.click("#calendarNavButton", timeout=4000)
            page.wait_for_timeout(600)
            before = page.evaluate(PROBE, [".calendar-visual-day", "--card-bg"])
            page.evaluate("() => document.documentElement.style.setProperty('--card-bg', 'rgb(255, 0, 0)')")
            page.wait_for_timeout(200)
            after = page.evaluate("() => getComputedStyle(document.querySelector('.calendar-visual-day')).backgroundColor")
            control = page.evaluate("() => getComputedStyle(document.querySelector('.calendar-view')).backgroundColor")
            assert before["cellBg"] == before["tokenBg"]
            assert after == "rgb(255, 0, 0)", after
            assert control != after, control
        finally:
            browser.close()
