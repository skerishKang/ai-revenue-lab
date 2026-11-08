"""#7171: the moment the session is gone (sign-out, expiry, status 401),
every signed-in surface leaves with it — sidebar projects, recent
conversations, the open conversation screen, library rows — and a re-login
shows only the new session's own data. One funnel: applyAuthState's
authenticated → guest transition.
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
             "history_ready": True, "project_files_ready": True,
             "shared_login_enabled": True, "shared_session_present": True}
GUEST_EXPIRED = {"ok": True, "ready": True, "authenticated": False, "user": None,
                 "history_ready": False, "project_files_ready": False,
                 "session_state": "expired",
                 "shared_login_enabled": True, "shared_session_present": False}
PROJECTS = {"ok": True, "projects": [
    {"id": "proj_b67", "name": "B67 법률 테스트", "file_count": 3}], "has_more": False}
CONVERSATIONS = {"ok": True, "conversations": [
    {"id": "conv_secret", "title": "기밀 대화", "updated_at": "2026-11-08"}],
    "has_more": False}
CONVERSATION = {"ok": True, "conversation": {
    "id": "conv_secret", "title": "기밀 대화", "project_id": None,
    "messages": [
        {"role": "user", "content": "기밀 내용 질문"},
        {"role": "assistant", "content": "기밀 내용 답변"}]}}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args) -> None:
        pass


class AuthLossClearsSurfaces(unittest.TestCase):
    def run_page(self, run_checks):
        state = {"guest": False}
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

        def route_handler(route):
            url = route.request.url
            state.setdefault("project_reads", 0)
            if "/api/projects" in url:
                state["project_reads"] += 1
            if url.endswith("/api/auth/status"):
                if state["guest"]:
                    body = GUEST_EXPIRED
                elif state.get("second"):
                    body = state["second"]
                else:
                    body = SIGNED_IN
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(body))
            elif "/api/projects" in url:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(PROJECTS))
            elif url.endswith("/api/conversations"):
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(CONVERSATIONS))
            elif "/api/conversations/conv_secret" in url:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps(CONVERSATION))
            elif "/api/" in url:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"ok": True}))
            else:
                route.continue_()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                context = browser.new_context(viewport={"width": 1440, "height": 950})
                page = context.new_page()
                page.on("pageerror", lambda err: self.fail(f"page error: {err}"))
                context.route("**/*", route_handler)
                page.goto(f"http://127.0.0.1:{port}/")
                page.wait_for_timeout(1500)
                run_checks(page, state)
                browser.close()
        finally:
            httpd.shutdown()

    def expire_session(self, page, state):
        """The server-side session dies; the next status read names this
        browser a guest (the shared refresh fails — an outage, not a relogin)."""
        state["guest"] = True
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_timeout(1500)

    def test_expiry_clears_lists_and_the_open_conversation(self):
        def checks(page, state):
            page.wait_for_selector("#projectsList .project-item")
            page.wait_for_selector("#historyList .recent-item.history-item")
            # Open the previous account's conversation.
            page.evaluate("""() => {
              document.getElementById("historyList")
                .querySelector(".recent-item.history-item")?.click();
            }""")
            page.wait_for_timeout(900)
            assert page.locator("#messageList *").count() > 0, "conversation opened"
            self.expire_session(page, state)
            assert page.locator("#accountName").inner_text() != "홍대표"
            assert page.locator("#projectsList *").count() == 0, \
                "projects leave with the session"
            assert page.locator("#historyList *").count() == 0, \
                "recent conversations leave with the session"
            assert page.locator("#messageList *").count() == 0, \
                "the open conversation screen is the guest screen now"
        self.run_page(checks)

    def test_relogin_shows_only_the_new_sessions_lists(self):
        def checks(page, state):
            page.wait_for_selector("#projectsList .project-item")
            self.expire_session(page, state)
            assert page.locator("#projectsList *").count() == 0
            # A different account signs in; only its own rows may appear.
            reads_before = state["project_reads"]
            SIGNED_IN_SECOND = dict(SIGNED_IN)
            SIGNED_IN_SECOND["user"] = {"name": "다른사용자", "email": "other@example.com"}
            state["guest"] = False
            state["second"] = SIGNED_IN_SECOND
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_timeout(1500)
            assert page.locator("#accountName").inner_text() == "다른사용자"
            # The re-login re-FETCHES the list from the server (fresh rows for
            # the new session) instead of replaying the wiped DOM.
            assert state["project_reads"] > reads_before, "re-login re-fetches"
            assert page.locator("#projectsList .project-item").count() == 1
        self.run_page(checks)


if __name__ == "__main__":
    unittest.main()
