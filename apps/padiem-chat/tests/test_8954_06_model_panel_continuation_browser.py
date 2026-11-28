"""#8954-6: tier chooser advertises scrolling and glass background is opaque."""
from __future__ import annotations

import http.server
import json
import os
import re
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
def test_tier_panel_signals_scroll_and_last_action_can_be_reached(browser, url, width, theme):
    page = browser.new_page(viewport={"width": width, "height": 844}, reduced_motion="reduce")
    try:
        member = {"ready": True, "authenticated": True, "history_ready": True,
                  "user": {"email": "member@example.com", "name": "Member", "picture": ""}}
        page.route("**/api/auth/status", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(member)))
        page.goto(f"{url}?theme={theme}", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        trigger = page.locator(".model-pill")
        trigger.click(timeout=5000)
        panel = page.locator(".mode-presentation-panel:visible")
        assert panel.count() == 1
        state = panel.evaluate("""el => {const s=getComputedStyle(el), r=el.getBoundingClientRect();
          const actions=[...el.querySelectorAll('button')].filter(b => b.getBoundingClientRect().height>0);
          const last=actions[actions.length-1];
          return {top:r.top,bottom:r.bottom,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,
            boxShadow:s.boxShadow,scrollbarWidth:s.scrollbarWidth,background:s.backgroundColor,
            backgroundImage:s.backgroundImage,lastText:last?.textContent?.trim(),lastTop:last?.getBoundingClientRect().top};
        }""")
        assert state["top"] >= 0 and state["bottom"] <= 844, (width, theme, state)
        assert state["scrollHeight"] > state["clientHeight"] + 100, state
        assert "inset" in state["boxShadow"], (width, theme, state)
        if theme == "padiem-glass":
            assert re.fullmatch(r"rgb\([^)]*\)|rgba\([^)]*, 1\)", state["background"]), state
            # A translucent frosted gradient over an opaque color still fully masks the page.
            assert "linear-gradient" in state["backgroundImage"], state
        assert state["lastTop"] > state["bottom"], state
        # Reach the bottom action with native scrolling, never dispatch a synthetic click.
        panel.evaluate("el => { el.scrollTop = el.scrollHeight; }")
        after = panel.evaluate("""el => {const r=el.getBoundingClientRect();
          const actions=[...el.querySelectorAll('button')].filter(b => b.getBoundingClientRect().height>0);
          const last=actions[actions.length-1].getBoundingClientRect();
          return {scrollTop:el.scrollTop,bottom:r.bottom,lastBottom:last.bottom,lastTop:last.top};
        }""")
        assert after["scrollTop"] > 0, after
        assert after["lastTop"] >= 0 and after["lastBottom"] <= after["bottom"] + 1, after
    finally:
        page.close()
