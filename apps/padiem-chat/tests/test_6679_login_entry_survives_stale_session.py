"""#6679 - a stale shared-session cookie must not wedge the login entry.

**The defect this pins.** A browser holding an old shared-session cookie gets
``/api/auth/status`` -> ``guest`` + ``shared_session_present: true``. The page
then calls ``/auth/shared/refresh``; when the authority has already killed that
token the refresh answers 503 (or, after the server fix, 401 with the cookie
cleared). ``loadAuthStatus`` treated the failed renewal as ``unreachable``
(``ready: false``), and the login button's dead-state branch retried the status
forever instead of opening the sign-in dialog: the user could not log in until
they cleared the site cookies by hand.

**The contract.**

1. the first status answer is definitive: guest stays guest even when the
   refresh that tried to renew the stale cookie fails,
2. with a refresh answering 503, clicking 로그인 opens the sign-in dialog,
3. with the server fix deployed (refresh 401 + cleared cookie), the same flow
   still lands on an openable sign-in dialog.

The QA runs the shipped ``static/index.html`` against a stub that reproduces
the stale-cookie state.
"""
from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "static"
STATUS_ENDPOINT = "/api/auth/status"
REFRESH_ENDPOINT = "/auth/shared/refresh"


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        status = 503 if self.server.refresh_status == 503 else 401
        body = json.dumps({"error": "authentication_unavailable" if status == 503
                           else "authentication_expired"}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if status == 401:
            # The server fix: clear the dead shared cookies on a rejection.
            self.send_header(
                "Set-Cookie",
                "padiem_shared_access=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=lax")
            self.send_header(
                "Set-Cookie",
                "padiem_shared_refresh=; Path=/auth/shared; Max-Age=0; Secure; HttpOnly; SameSite=lax")
        self.end_headers()
        self.wfile.write(body)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    refresh_status = 503


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        thread = threading.Thread(target=web.serve_forever, daemon=True)
        thread.start()
        yield web
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        yield b
        b.close()


STALE_GUEST = {
    "ready": True,
    "authenticated": False,
    "history_ready": True,
    "project_files_ready": True,
    "user": None,
    "session_state": "guest",
    "methods": {"google": True, "password": True},
    "shared_login_enabled": True,
    "shared_session_present": True,
}


def open_chat(browser, server, refresh_status):
    server.refresh_status = refresh_status
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    page.route("**" + STATUS_ENDPOINT, lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(STALE_GUEST)))
    page.goto("http://127.0.0.1:%d/index.html" % server.server_address[1],
              wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    return page


def test_refresh_503_still_lands_on_an_open_login_dialog(browser, server):
    page = open_chat(browser, server, refresh_status=503)
    account = page.locator(".sidebar-account")
    account.wait_for(state="visible", timeout=5000)
    state = account.get_attribute("data-account-state")
    assert state == "guest", state
    login = page.locator("#loginButton")
    assert login.is_visible()
    assert login.is_enabled(), "the login button must not sit in its dead retry branch"
    login.click()
    dialog = page.locator("#authDialog")
    assert dialog.is_visible(), "the sign-in dialog must open despite the failed refresh"
    page.close()


def test_refresh_401_with_cleared_cookie_also_opens_the_dialog(browser, server):
    # The server-side half of #6679: the refresh answers 401 and clears the
    # shared cookies. The client still presents the definitive guest status —
    # never an unreachable dead end.
    page = open_chat(browser, server, refresh_status=401)
    account = page.locator(".sidebar-account")
    account.wait_for(state="visible", timeout=5000)
    assert account.get_attribute("data-account-state") == "guest"
    login = page.locator("#loginButton")
    assert login.is_visible()
    login.click()
    assert page.locator("#authDialog").is_visible()
    page.close()
