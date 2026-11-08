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


def _measure_requests_for_30_seconds(view):
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
            if view == "library":
                page.locator("#filesNavButton").click()
                page.wait_for_function("window.PadiemChatLibrary && window.PadiemChatLibrary.isOpen()")
            page.wait_for_timeout(30000)
            if view == "library":
                assert page.evaluate("window.PadiemChatLibrary.isOpen()"), "Library must stay open"
            else:
                assert page.evaluate("document.querySelector('.app-shell').dataset.state === 'home'")
            assert not errors, errors
            report = {"view": view, "bootstrap": dict(bootstrap), "window_30s": dict(counts),
                      "window_total": counts.total(), "all_total": (counts + bootstrap).total()}
            print(json.dumps(report, sort_keys=True))
            browser.close()
            return report
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_library_open_request_count_stays_bounded_for_30_seconds():
    report = _measure_requests_for_30_seconds("library")
    assert report["window_total"] <= 15, report
    assert report["window_total"] <= 1, report  # Step 1 settled Library baseline.
    assert report["all_total"] <= 26, report


def test_first_screen_requests_do_not_exceed_step1_baseline():
    report = _measure_requests_for_30_seconds("home")
    # Step 1 (7599d3c78), same API fixtures: boot 25, settled home 0.
    assert report["window_total"] == 0, report
    assert report["all_total"] <= 25, report
