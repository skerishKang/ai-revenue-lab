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

#8090: /api/admin/session went back to one read. admin-entry.js and chat-
feedback-module.js now join the shared read in admin-session-shared.js (one
request per auth epoch, #8003's shared-read shape) instead of each fetching
its own projection. The scenario tests below pin what both consumers show
for an admin, a member and a guest on that single shared answer.
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
GUEST = {"ok": True, "ready": True, "authenticated": False,
         "member_grade": "free", "history_ready": False,
         "project_files_ready": False, "shared_login_enabled": True,
         "shared_session_present": False, "session_state": "guest"}
DEPLOYMENT = {"ok": True, "projects": True, "history": True}
ADMIN_ME = {"ok": True, "state": "not_admin"}
ADMIN_SESSION = {"ok": True, "authenticated": True, "role": None,
                 "site_feedback_sites": [],
                 "capabilities": {"chat_admin": False, "site_feedback_admin": False}}
ADMIN_SESSION_ADMIN = {"ok": True, "authenticated": True,
                       "role": "global_model_admin", "site_feedback_sites": [],
                       "capabilities": {"chat_admin": True,
                                        "site_feedback_admin": False}}
ADMIN_SESSION_GUEST = {"ok": True, "authenticated": False, "role": None,
                       "site_feedback_sites": [], "capabilities": {}}
SELECTION = {"ok": True, "selection": {"tier": "free"}, "restorable_tier": "free"}
CUSTOM = {"ok": True, "providers": [], "credentials": []}
RUNTIME = {"ok": True, "runtime": {}}
PAIRINGS = {"ok": True, "links": []}
EMPTY_OK = {"ok": True, "list": [], "items": []}

BASE_ROUTES = {
    "/api/auth/status": SIGNED_IN,
    "/health": DEPLOYMENT,
    "/api/b66/admin/me": ADMIN_ME,
    "/api/admin/session": ADMIN_SESSION,
    "/api/account/model-selection": SELECTION,
    "/api/chat/custom/credential": CUSTOM,
    "/api/b66/runtime-config": RUNTIME,
    "/api/pc/pairings": PAIRINGS,
}


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
        routes = dict(BASE_ROUTES)
        routes.update(getattr(self.server, "route_overrides", {}) or {})
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
    def run_page(self, run_checks, route_overrides=None):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        httpd.counts = {}
        httpd.route_overrides = dict(route_overrides or {})
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
                run_checks(counts, page)
                browser.close()
        finally:
            httpd.shutdown()

    def test_product_auth_reads_once_per_screen_load(self):
        def checks(counts, page):
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
        def checks(counts, page):
            self.assertEqual(counts.get("/api/b66/runtime-config", 0), 1,
                             f"runtime-config reads: {counts}")
        self.run_page(checks)

    def test_pairings_read_once_per_screen_load(self):
        def checks(counts, page):
            self.assertEqual(counts.get("/api/pc/pairings", 0), 1,
                             f"pairings reads: {counts}")
            # #8090: admin-entry.js와 chat-feedback-module.js는 admin-session-
            # shared.js의 공용 읽기 하나를 함께 읽는다 — 첫 화면에서
            # /api/admin/session은 정확히 1회(구 2회, #8035).
            self.assertEqual(counts.get("/api/admin/session", 0), 1,
                             f"admin/session reads: {counts}")
        self.run_page(checks)

    def test_admin_role_shows_the_hub_entry_and_feedback_admin_tab(self):
        def checks(counts, page):
            self.assertEqual(counts.get("/api/admin/session", 0), 1,
                             f"admin/session reads: {counts}")
            self.assertIsNone(page.get_attribute("#adminHubLink", "hidden"),
                              "the admin hub entry must be visible for an admin")
            self.assertEqual(page.get_attribute("#adminHubLink", "data-role"),
                             "global_model_admin")
            # chat-feedback-module.js painted from the same shared answer:
            # the admin inbox tab is offered without opening the dialog.
            self.assertIsNone(page.get_attribute("#feedbackAdminTab", "hidden"),
                              "the feedback admin tab must be visible for an admin")
        self.run_page(checks, route_overrides={"/api/admin/session": ADMIN_SESSION_ADMIN})

    def test_member_role_hides_the_hub_entry_and_feedback_admin(self):
        def checks(counts, page):
            self.assertEqual(counts.get("/api/admin/session", 0), 1,
                             f"admin/session reads: {counts}")
            self.assertEqual(page.get_attribute("#adminHubLink", "hidden"), "",
                              "the admin hub entry must stay hidden for a member")
            self.assertIsNone(page.get_attribute("#adminHubLink", "data-role"))
            self.assertEqual(page.get_attribute("#feedbackAdminTab", "hidden"), "",
                             "the feedback admin tab must stay hidden for a member")
        self.run_page(checks)

    def test_guest_first_screen_answers_once_and_stays_unauthorized(self):
        def checks(counts, page):
            # #8011 stays intact: no /api/pc/* on the guest screen, and the
            # admin probe is the same single shared read it was before #8090.
            self.assertEqual(counts.get("/api/pc/pairings", 0), 0,
                             f"guest pc reads: {counts}")
            self.assertEqual(counts.get("/api/admin/session", 0), 1,
                             f"admin/session reads: {counts}")
            self.assertEqual(page.get_attribute("#adminHubLink", "hidden"), "",
                             "the admin hub entry must stay hidden for a guest")
            self.assertEqual(page.get_attribute("#feedbackAdminTab", "hidden"), "",
                             "the feedback admin tab must stay hidden for a guest")
            # a guest answer answered its caller once; it never became the
            # shared session answer, so a later sign-in reads fresh.
            self.assertIsNone(page.evaluate("window.PadiemAdminSession.current()"))
        self.run_page(checks, route_overrides={
            "/api/auth/status": GUEST,
            "/api/admin/session": ADMIN_SESSION_GUEST,
        })


if __name__ == "__main__":
    unittest.main()
