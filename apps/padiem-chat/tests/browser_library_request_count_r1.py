"""R1: real static scripts must settle while the Library stays open for 30s.

Only loopback assets and synthetic API fixtures are used. The counted window
starts when Library opens; bootstrap requests are reported separately.
"""
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

STATIC = Path(os.environ.get("R1_STATIC_ROOT", Path(__file__).resolve().parents[1] / "static"))
AUTH = {"ok": True, "ready": True, "authenticated": True,
        "user": {"name": "Fixture owner", "email": "owner@example.test"},
        "history_ready": True, "project_files_ready": True,
        "shared_login_enabled": True, "shared_session_present": True}


def test_library_open_request_count_stays_bounded_for_30_seconds():
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(STATIC), **kwargs)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    counts, errors = Counter(), []

    def respond(route):
        url = urlsplit(route.request.url)
        if url.hostname != "127.0.0.1":
            route.fulfill(status=200, body="", content_type="text/css")
            return
        if not url.path.startswith("/api/"):
            route.continue_()
            return
        counts[url.path] += 1
        if url.path == "/api/auth/status":
            data = AUTH
        elif url.path == "/api/projects":
            data = {"ok": True, "projects": [], "has_more": False}
        elif url.path == "/api/conversations":
            data = {"ok": True, "conversations": [], "has_more": False}
        elif url.path == "/api/project-files":
            data = {"ok": True, "files": [], "has_more": False}
        elif url.path == "/api/b66/admin/me":
            data = {"ok": True, "admin": False}
        elif url.path == "/api/outputs":
            data = {"ok": True, "outputs": [], "has_more": False}
        else:
            data = {"ok": True}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 950})
            page.route("**/*", respond)
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{httpd.server_address[1]}/")
            page.wait_for_function("document.getElementById('accountName').textContent === 'Fixture owner'")
            page.wait_for_timeout(1500)
            bootstrap = counts.copy()
            counts.clear()
            page.locator("#filesNavButton").click()
            page.wait_for_function("window.PadiemChatLibrary && window.PadiemChatLibrary.isOpen()")
            page.wait_for_timeout(30000)
            assert page.evaluate("window.PadiemChatLibrary.isOpen()"), "Library must stay open"
            assert not errors, errors
            print(json.dumps({"bootstrap": dict(bootstrap), "library_30s": dict(counts),
                              "library_total": counts.total(), "all_total": (counts + bootstrap).total()}, sort_keys=True))
            assert counts.total() <= 15, dict(counts)
            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()