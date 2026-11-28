"""#8954-3: project/history scrollports must not cover help/account controls."""
from __future__ import annotations
import http.server
import json
import os
import threading
from pathlib import Path
import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
THEMES = ("light", "dark", "cinematic", "padiem-glass", "padiem-home")
MEMBER = {"ready": True, "authenticated": True, "history_ready": True,
          "user": {"email": "member@example.com", "name": "Member", "picture": ""}}

class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)
    def log_message(self, *args):
        pass

@pytest.fixture(scope="module")
def local_url():
    with http.server.ThreadingHTTPServer(("127.0.0.1", int(os.getenv("CGI_8954_PORT", "0"))), _Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
        finally:
            server.shutdown()
            thread.join(timeout=5)

@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("Playwright required")
    with sync_playwright() as pw:
        engine = pw.chromium.launch(headless=True)
        try:
            yield engine
        finally:
            engine.close()

def _populate(page):
    page.evaluate("""() => {
      const projects=document.getElementById('projectsSection');
      const history=document.getElementById('historySection');
      projects.hidden=false; history.hidden=false;
      const p=document.getElementById('projectsList'), h=document.getElementById('historyList');
      p.replaceChildren();h.replaceChildren();
      for(let i=0;i<2;i++){
        const row=document.createElement('div');row.className='project-row';
        row.innerHTML='<button class="project-item" type="button">프로젝트</button><button class="project-manage" type="button">⋯</button>';
        p.append(row);
      }
      for(let i=0;i<12;i++){
        const row=document.createElement('div');row.className='history-row';
        row.innerHTML='<button class="history-item" type="button">대화 제목</button><div class="history-actions"><button class="history-more" type="button">⋯</button></div>';
        h.append(row);
      }
    }""")

@pytest.mark.parametrize("theme", THEMES)
def test_desktop_sidebar_history_and_help_do_not_overlap(browser, local_url, theme):
    page=browser.new_page(viewport={"width":1440,"height":844})
    page.route("**/api/auth/status", lambda r:r.fulfill(
        status=200, content_type="application/json",body=json.dumps(MEMBER)))
    try:
        page.goto(local_url+"?theme="+theme,wait_until="domcontentloaded")
        page.locator(".sidebar-account[data-account-state='signed_in']").wait_for(timeout=10000)
        _populate(page)
        result=page.evaluate("""() => {
          const help=document.getElementById('helpNavLink');
          const account=document.querySelector('.sidebar-bottom');
          const list=document.getElementById('historyList');
          const h=help.getBoundingClientRect(),a=account.getBoundingClientRect();
          const s=getComputedStyle(list);
          return {helpBottom:h.bottom, accountTop:a.top, mask:s.maskImage,
            historyScroll:list.scrollHeight>list.clientHeight,
            accountPosition:getComputedStyle(account).position};
        }""")
        assert result["historyScroll"], result
        assert result["helpBottom"] <= result["accountTop"], result
        if theme == "padiem-glass":
            assert result["mask"] == "none", result
        else:
            assert result["mask"] != "none", result
        page.locator("#helpNavLink").scroll_into_view_if_needed(timeout=3000)
        assert page.locator("#helpNavLink").is_visible()
        # Pointer hit-testing must succeed; an overlay may obscure a visible link.
        page.locator("#helpNavLink").click(trial=True, timeout=3000)
    finally:
        page.close()
