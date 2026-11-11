"""#7476 본문 2: the basic settings dialog's account section.

Signed in, the section shows the full session email and the secondary logout
button; signed out, the whole section is hidden. The value comes from the
existing /api/auth/status projection (no new request).
"""

from __future__ import annotations

import http.server
import json
import secrets
import threading
from pathlib import Path

import pytest

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

STATIC = Path(__file__).resolve().parents[1] / "static"
MEMBER = {
    "ready": True,
    "authenticated": True,
    "history_ready": True,
    "user": {"email": "member@example.com", "name": "Member", "picture": ""},
}
GUEST = {"ready": True, "authenticated": False, "history_ready": True, "user": None}


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC))

    def log_message(self, *args):
        pass


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    web = None
    for _ in range(64):
        port = 49152 + secrets.randbelow(16384)
        try:
            web = _Server(("127.0.0.1", port), _Handler)
            break
        except OSError:
            continue
    if web is None:
        raise OSError("no safe ephemeral test port was available")
    with web:
        threading.Thread(target=web.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed in this environment")
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        yield instance
        instance.close()


def _open_settings(browser, server_url: str, status: dict, viewport: dict) -> tuple:
    page = browser.new_page(viewport=viewport)
    page.route(
        "**/api/auth/status",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(status)
        ),
    )
    page.goto(server_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1400)
    page.evaluate(
        """() => {
          const dialog = document.getElementById('settingsDialog');
          if (dialog && !dialog.open && typeof dialog.showModal === 'function') dialog.showModal();
        }"""
    )
    page.wait_for_timeout(200)
    return page


@requires_browser
def test_signed_in_shows_the_full_email_and_the_logout_button(browser, server) -> None:
    page = _open_settings(browser, server, MEMBER, {"width": 1280, "height": 800})
    try:
        state = page.evaluate(
            """() => {
              const section = document.getElementById('accountSettingsSection');
              const email = document.getElementById('settingsAccountEmail');
              const logout = document.getElementById('settingsLogoutButton');
              return {
                sectionHidden: section.hidden,
                sectionVisible: section.getBoundingClientRect().height > 0,
                emailHidden: email.hidden,
                emailText: email.textContent,
                logoutVisible: logout.getBoundingClientRect().height >= 44,
                heading: document.getElementById('accountSettingsTitle').textContent.trim(),
              };
            }"""
        )
        assert state["sectionHidden"] is False, state
        assert state["sectionVisible"] is True, state
        assert state["heading"] == "계정", state
        assert state["emailHidden"] is False, state
        assert state["emailText"] == "member@example.com", state
        assert state["logoutVisible"] is True, state
    finally:
        page.close()


@requires_browser
def test_signed_out_hides_the_whole_account_section(browser, server) -> None:
    page = _open_settings(browser, server, GUEST, {"width": 390, "height": 844})
    try:
        state = page.evaluate(
            """() => {
              const section = document.getElementById('accountSettingsSection');
              const email = document.getElementById('settingsAccountEmail');
              return {hidden: section.hidden, height: section.getBoundingClientRect().height,
                      emailText: email.textContent, emailHidden: email.hidden};
            }"""
        )
        assert state["hidden"] is True, state
        assert state["height"] == 0, state
        assert state["emailText"] == "", state
        assert state["emailHidden"] is True, state
    finally:
        page.close()
