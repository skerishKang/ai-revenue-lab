"""#8954-1: mobile Settings > Advanced remains usable after real pointer/Tab input.

The synthetic auth response is display-only; no production account is used.
"""
from __future__ import annotations

import http.server
import json
import os
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

STATIC = Path(__file__).resolve().parents[1] / "static"
MEMBER = {"ready": True, "authenticated": True, "history_ready": True,
          "user": {"email": "member@example.com", "name": "Member", "picture": ""}}


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def url():
    # Local manual QA may set 9434; CI uses an assigned available port.
    with http.server.ThreadingHTTPServer(("127.0.0.1", int(os.getenv("CGI_8954_PORT", "0"))), _Handler) as web:
        thread = threading.Thread(target=web.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        finally:
            web.shutdown()
            thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is required for browser QA")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.mark.parametrize("width", [390, 1440])
def test_settings_advanced_back_is_real_clickable_and_keyboard_reachable(browser, url, width):
    page = browser.new_page(viewport={"width": width, "height": 844})
    page.route("**/api/auth/status", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(MEMBER)))
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.locator(".sidebar-account[data-account-state='signed_in']").wait_for(timeout=10000)
        if width == 390:
            page.locator("#mobileMenu").click()
        page.locator("#accountProfileButton").click()
        page.locator("#settingsButton").click()
        assert page.locator("#settingsDialog").evaluate("el => el.matches(':modal')")
        page.locator("#settingsAdvancedOpen").click()
        assert not page.locator("#settingsDialog").evaluate("el => el.open")
        assert not page.locator("#advancedSettingsView").evaluate("el => el.hidden")
        assert page.locator("#sidebarScrim").evaluate("el => el.hidden"), "mobile scrim blocks Advanced"
        assert not page.locator(".app-shell").evaluate("el => el.classList.contains('sidebar-open')")
        # A real Tab must enter the standalone page, not the closed modal or scrim.
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement?.closest('#advancedSettingsView') !== null")
        page.locator("#advancedSettingsBack").click(timeout=3000)
        assert page.locator("#advancedSettingsView").evaluate("el => el.hidden")
    finally:
        page.close()
