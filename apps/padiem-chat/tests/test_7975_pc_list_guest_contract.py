"""#7975 contract: the owner-scoped PC list (/api/pc/pairings) is never read
signed-out.

The 2026-11-19 release was rolled back over exactly this: the guest first
screen fetched the pairing list, every 401 became a console error, and the
daily shared-login flow failed its console-clean contract. Since #8003 the
connect flow owns the one shared read behind its guest guard and
pc-command-ready only adopts the answer the flow publishes. No product code
changes here — these pins hold that shape for CI:

  1. guest first screen     -> zero /api/pc/* requests, zero /api/pc console
     errors (the incident's signature);
  2. signed-in first screen -> exactly one pairings read, the connect flow's
     shared one;
  3. tamper                 -> with the flow's guest guard neutralised the
     guest screen does fire, so pin 1 has teeth.
"""
from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from _support import session_login_source as sheets

STATIC = sheets.static_root()
FLOW = sheets.static_path("pc-connect-flow.js")

GUEST = {"ok": True, "authenticated": False, "ready": True, "user": None}
SIGNED_IN = {"ok": True, "authenticated": True, "ready": True,
             "user": {"name": "QA", "email": "qa@example.test"}}


class _StaticServer:
    """Read-only http.server over the static tree; /api/pc/* answers 401 like
    production does for a signed-out session."""

    def __init__(self):
        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(STATIC), **kwargs)

            def log_message(self, *args):
                pass

        self.web = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.web.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.web.server_address[1]}/index.html"

    def shutdown(self):
        self.web.shutdown()


def _stub_api(page):
    # Registration order matters: the generic answer first, then the specific
    # overrides — Playwright serves the LAST matching route.
    page.route(re.compile(r".*/api/.*$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json", body="{}"))
    page.route(re.compile(r".*/api/pc/.*$"),
               lambda route, req: route.fulfill(
                   status=401, content_type="application/json",
                   body=json.dumps({"ok": False, "error": {
                       "code": "unauthorized"}})))


def _stub_auth(page, status_body):
    page.route(re.compile(r".*/api/auth/status$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps(status_body, ensure_ascii=False)))


def _stub_pairings_ok(page):
    page.route(re.compile(r".*/api/pc/pairings$"),
               lambda route, req: route.fulfill(
                   status=200, content_type="application/json",
                   body=json.dumps({"ok": True, "links": [], "codes": []})))


def _watch_pairings(cdp) -> list[str]:
    """Initiating script URL of every /api/pc/pairings request."""
    seen: list[str] = []

    def on_request(params):
        url = params["request"]["url"]
        if not url.endswith("/api/pc/pairings"):
            return
        stack = params.get("initiator", {}).get("stack", {}).get("callFrames", [])
        script = ""
        for frame in stack:
            frame_url = frame.get("url", "")
            if frame_url.endswith(".js"):
                script = frame_url.rsplit("/", 1)[-1]
                break
        seen.append(script or "?")

    cdp.on("Network.requestWillBeSent", on_request)
    return seen


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_guest_screen_never_reads_the_pc_list():
    server = _StaticServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page)
            _stub_auth(page, GUEST)
            pc_calls: list[str] = []
            page.on("request", lambda req: pc_calls.append(req.url) if
                    "/api/pc/" in req.url else None)
            console_errors: list[tuple[str, str]] = []
            page.on("console", lambda m: console_errors.append(
                (m.location.get("url") or "", m.text[:120])) if
                m.type == "error" else None)
            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")
            attributed = _watch_pairings(cdp)
            page.goto(server.base, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(8000)
            # The Connectors card is part of the first screen's DOM even for a
            # guest; opening it must not change the answer either.
            page.evaluate("""() => {
              const d = document.getElementById('connectorsDialog');
              if (d && !d.open) d.showModal();
            }""")
            page.wait_for_timeout(2000)
            browser.close()
    finally:
        server.shutdown()
    assert pc_calls == [], pc_calls[:3]
    assert attributed == [], attributed[:3]
    # The incident's signature: console errors carrying a /api/pc/* URL.
    # Local-harness noise from missing optional files must not mask it.
    pc_console = [entry for entry in console_errors if "/api/pc/" in entry[0]]
    assert pc_console == [], pc_console[:3]


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_signed_in_screen_reads_the_pc_list_once():
    server = _StaticServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page)
            _stub_pairings_ok(page)
            _stub_auth(page, SIGNED_IN)
            cdp = context.new_cdp_session(page)
            cdp.send("Network.enable")
            attributed = _watch_pairings(cdp)
            page.goto(server.base, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(5000)
            browser.close()
    finally:
        server.shutdown()
    # One shared read per sign-in, owned by the connect flow (#7073).
    assert attributed == ["pc-connect-flow.js"], attributed


@pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
def test_flow_guest_guard_removed_fires_on_the_guest_screen():
    """변조 1회: neutralise the connect flow's guest guard and the guest first
    screen does fetch — the zero-request pin above really catches it."""
    source = sheets.source(FLOW)
    marker = "if (window.PadiemAuthGate?.authenticated() === false) {"
    assert marker in source
    tampered = source.replace(marker, "if (false) {", 1)
    assert tampered != source

    server = _StaticServer()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            _stub_api(page)
            _stub_auth(page, GUEST)
            page.route(re.compile(r".*/pc-connect-flow\.js$"),
                       lambda route, req: route.fulfill(
                           status=200, content_type="text/javascript",
                           body=tampered))
            pc_calls: list[str] = []
            page.on("request", lambda req: pc_calls.append(req.url) if
                    "/api/pc/" in req.url else None)
            page.goto(server.base, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(8000)
            browser.close()
    finally:
        server.shutdown()
    assert pc_calls, "the unguarded flow must fire on the guest screen"
