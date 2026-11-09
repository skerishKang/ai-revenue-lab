"""#7073 follow-up: the signed-in first screen reads each owner-scoped list once.

A production measurement (2026-11-07 journal, #7073) proved the first screen
paying for the same reads several times (inbox x4, pairings x3, runs x2,
devices x2, voice identity x2). #7086 removed those repeats. This pins the
next layer that regrew after #7086: the product's own auth re-reads
(/api/auth/status x3, /api/account/model-selection x3, /api/chat/custom/
credential x3), the quote runtime's config re-read (/api/b66/runtime-config
x4, one per capabilitychange) and the workbook source's own pairing read
(/api/pc/pairings x2 alongside the connect flow's).

The harness loads the real first screen against stubbed owner-scoped routes
and counts every /api request over the same observation the issue uses
(page load + 10s, plus the pageshow/focus surface invites the product
listeners would fire on).

/api/auth/status stays twice by design: the composer (app.js) and the tier
restore (product-capabilities.js) each read it once, in parallel, because
their projections differ (member grade, history readiness) and the tier
restore must not wait for the composer's own retry sequence (#5554). Every
other owner-scoped list is exactly once.
"""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import threading
import unittest

from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parents[1] / "static"

SIGNED_IN = {"ok": True, "ready": True, "authenticated": True,
             "user": {"name": "홍대표", "email": "rep@example.com"},
             "member_grade": "free",
             "history_ready": True, "project_files_ready": True,
             "shared_login_enabled": True, "shared_session_present": True,
             "session_state": "signed_in"}
DEPLOYMENT = {"ok": True, "projects": True, "history": True}
ADMIN_ME = {"ok": True, "state": "not_admin"}
ADMIN_SESSION = {"ok": True, "authenticated": True, "role": "member"}
SELECTION = {"ok": True, "selection": {"tier": "free"}, "restorable_tier": "free"}
CUSTOM = {"ok": True, "providers": [], "credentials": []}
RUNTIME = {"ok": True, "runtime": {}}
PAIRINGS = {"ok": True, "links": []}
EMPTY_OK = {"ok": True, "list": [], "items": []}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args) -> None:
        pass

    def _json(self, body, code=200):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        routes = {
            "/api/auth/status": SIGNED_IN,
            "/health": DEPLOYMENT,
            "/api/b66/admin/me": ADMIN_ME,
            "/api/admin/session": ADMIN_SESSION,
            "/api/account/model-selection": SELECTION,
            "/api/chat/custom/credential": CUSTOM,
            "/api/b66/runtime-config": RUNTIME,
            "/api/pc/pairings": PAIRINGS,
        }
        path = self.path.split("?", 1)[0]
        counts = self.server.counts
        if path.startswith("/api/") or path == "/health":
            counts[path] = counts.get(path, 0) + 1
        if path in routes:
            return self._json(routes[path])
        if path.startswith("/api/"):
            return self._json(EMPTY_OK)
        return super().do_GET()


class FirstScreenRequestBudget(unittest.TestCase):
    def run_page(self, run_checks):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        httpd.counts = {}
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(f"http://127.0.0.1:{port}/index.html", wait_until="load", timeout=45000)
                # observe the same window the issue uses: page load + 10s.
                # The boot read, the auth-state re-read, the capabilitychange
                # burst and the initial pageshow all fire naturally inside it
                # (production timeline: status 2.6-7.8s), so no extra event is
                # injected here.
                page.wait_for_timeout(10000)
                counts = dict(httpd.counts)
                run_checks(counts)
                browser.close()
        finally:
            httpd.shutdown()

    def test_product_auth_reads_once_per_screen_load(self):
        def checks(counts):
            self.assertEqual(counts.get("/api/account/model-selection", 0), 1,
                             f"model-selection reads: {counts}")
            self.assertEqual(counts.get("/api/chat/custom/credential", 0), 1,
                             f"custom credential reads: {counts}")
            self.assertEqual(counts.get("/api/b66/admin/me", 0), 1,
                             f"admin presence reads: {counts}")
            # composer + tier restore: one read each, in parallel (see docstring)
            self.assertEqual(counts.get("/api/auth/status", 0), 2,
                             f"auth/status reads: {counts}")
        self.run_page(checks)

    def test_quote_runtime_config_reads_once_per_screen_load(self):
        def checks(counts):
            self.assertEqual(counts.get("/api/b66/runtime-config", 0), 1,
                             f"runtime-config reads: {counts}")
        self.run_page(checks)

    def test_pairings_read_once_per_screen_load(self):
        def checks(counts):
            self.assertEqual(counts.get("/api/pc/pairings", 0), 1,
                             f"pairings reads: {counts}")
            self.assertEqual(counts.get("/api/admin/session", 0), 1,
                             f"admin/session reads: {counts}")
        self.run_page(checks)


if __name__ == "__main__":
    unittest.main()
