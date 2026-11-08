"""#7173 — util tools open inside the app, never on another page.

Representative request (2026-11-08): pressing a util card must not leave for an
external page or jump into a Claw conversation. Each tool has its own screen in
the same util view, the header carries ← 유틸 back to the first screen, and
#util/<tool> reopens the same screen after a reload.

Browser-level because every assertion is about what the page does: which panel
is visible, which fragment is in the address bar, and whether the document was
replaced. The static sheet contracts live in test_util_inapp_screens_7173.py.
"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

SIGNED_IN_STATUS = {
    "ok": True, "authenticated": True, "ready": True,
    "user": {"name": "홍대표", "email": "rep@example.com"},
}
QUOTE_PREVIEW = {
    "ok": True,
    "preview": {
        "title": "견적서 초안",
        "result_text": "ABC건설 귀중\n배관 20개 × 30,000원 = 600,000원",
    },
}

# card data key -> (panel id, screen heading, fragment)
CARDS = {
    "speech": ("utilSpeechPanel", "축사·인사말", "#util/speech"),
    "sns": ("utilSnsPanel", "SNS 홍보", "#util/sns"),
    "meeting": ("utilMeetingPanel", "회의정리·활동집", "#util/meeting"),
    "pdfmd": ("utilPdfmdPanel", "PDF → Markdown", "#util/pdfmd"),
    "claw-quote": ("utilQuotePanel", "견적서 초안", "#util/quote"),
}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args) -> None:
        pass


def serve() -> tuple[ThreadingHTTPServer, int]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


class UtilInAppScreens(unittest.TestCase):
    def run_page(self, run_checks, path: str = "/", viewport: dict | None = None):
        httpd, port = serve()
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                context = browser.new_context(
                    viewport=viewport or {"width": 1440, "height": 900})
                page = context.new_page()
                page.on("pageerror", lambda err: self.fail(f"page error: {err}"))
                preview_calls: list[dict] = []

                def route_handler(route):
                    url = route.request.url
                    if url.endswith("/api/auth/status"):
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps(SIGNED_IN_STATUS))
                    elif "/api/claw/manual-intake/preview" in url:
                        preview_calls.append(json.loads(route.request.post_data or "{}"))
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps(QUOTE_PREVIEW))
                    elif "/api/projects" in url:
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps({"ok": True, "projects": [
                                          {"id": "p1", "name": "기본", "files": []}]}))
                    elif "/api/pc/pairings" in url:
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps({"ok": True, "links": []}))
                    elif "/api/document-conversions" in url:
                        route.fulfill(status=200, content_type="application/json",
                                      body=json.dumps({"ok": True, "jobs": [],
                                                       "new_work_enabled": False}))
                    elif "/api/" in url:
                        route.fulfill(status=200, content_type="application/json",
                                      body="{}")
                    else:
                        route.continue_()

                context.route("**/*", route_handler)
                page.goto(f"http://127.0.0.1:{port}{path}")
                page.wait_for_timeout(900)
                run_checks(page, preview_calls)
                browser.close()
        finally:
            httpd.shutdown()

    def open_util(self, page):
        page.click("#utilNavButton")
        page.wait_for_selector("#utilView:not([hidden])")
        page.wait_for_selector("#utilToolGrid:not([hidden])")

    def test_each_card_opens_its_screen_and_stays_on_the_page(self):
        def checks(page, _calls):
            self.open_util(page)
            start_navigations = page.evaluate(
                "() => performance.getEntriesByType('navigation').length")
            for key, (panel_id, heading, route) in CARDS.items():
                page.click(f'[data-util-tool="{key}"]')
                page.wait_for_selector(f"#{panel_id}:not([hidden])")
                assert page.locator(f"#{panel_id}").is_visible(), key
                assert page.locator("#utilToolGrid").is_hidden(), (
                    f"{key}: the first screen's cards give the page to the tool")
                assert page.locator("#utilBack").is_visible(), key
                assert page.locator("#utilTitle").inner_text().strip() == heading, key
                assert page.evaluate("() => location.hash") == route, key
                # The document was never replaced: same page, only the fragment
                # (and the visible screen) changed.
                assert page.evaluate("() => location.pathname") == "/", key
                assert page.evaluate(
                    "() => performance.getEntriesByType('navigation').length"
                ) == start_navigations, f"{key}: no navigation"
                page.click("#utilBack")
                page.wait_for_selector("#utilToolGrid:not([hidden])")
        self.run_page(checks)

    def test_back_returns_to_the_first_screen(self):
        def checks(page, _calls):
            self.open_util(page)
            page.click('[data-util-tool="sns"]')
            page.wait_for_selector("#utilSnsPanel:not([hidden])")
            page.click("#utilBack")
            page.wait_for_selector("#utilToolGrid:not([hidden])")
            assert page.locator("#utilSnsPanel").is_hidden()
            assert page.locator("#utilBack").is_hidden()
            assert page.locator("#utilTitle").inner_text().strip() == "유틸"
            assert page.evaluate("() => location.hash") == "#util"
        self.run_page(checks)

    def test_a_deep_link_opens_the_tool_screen(self):
        def checks(page, _calls):
            page.wait_for_selector("#utilView:not([hidden])")
            assert page.locator("#utilMeetingPanel").is_visible()
            assert page.locator("#utilToolGrid").is_hidden()
            assert page.locator("#utilTitle").inner_text().strip() == "회의정리·활동집"
            assert page.locator("#utilBack").is_visible()
        self.run_page(checks, path="/#util/meeting")

    def test_the_quote_screen_uses_the_manual_intake_preview_contract(self):
        def checks(page, calls):
            self.open_util(page)
            page.click('[data-util-tool="claw-quote"]')
            page.wait_for_selector("#utilQuotePanel:not([hidden])")
            assert page.locator("#utilQuoteResult").is_hidden(), (
                "the Claw bridge is a result action, not a before-generation one")
            page.fill("#utilQuoteForm [name=request]",
                      "ABC건설에 배관 20개, 개당 3만원으로 견적서 만들어줘")
            page.click("#utilQuoteGenerate")
            page.wait_for_selector("#utilQuoteResult:not([hidden])")
            assert "600,000" in page.input_value("#utilQuoteOutput")
            assert calls and calls[-1]["action"] == "quote", calls
            assert "ABC건설" in calls[-1]["content"]
            # The page still shows the util screen, not the Claw conversation.
            assert page.evaluate("() => location.hash") == "#util/quote"
            assert page.locator("#utilQuoteClaw").is_visible()
        self.run_page(checks)

    def test_a_phone_drawer_row_opens_the_screen_and_closes_the_drawer(self):
        def checks(page, _calls):
            page.click("#mobileMenu")
            page.wait_for_timeout(350)
            page.evaluate("() => document.getElementById('utilNavButton').click()")
            page.wait_for_selector("#utilView:not([hidden])")
            page.click('[data-util="speech"]')
            page.wait_for_selector("#utilSpeechPanel:not([hidden])")
            assert page.locator("#utilSpeechPanel").is_visible()
            assert page.locator("#utilBack").is_visible()
            assert page.evaluate(
                "() => !document.querySelector('.app-shell').classList.contains('sidebar-open')"
            ), "opening a tool from the drawer closes it"
            assert page.evaluate("() => location.hash") == "#util/speech"
            page.click("#utilBack")
            page.wait_for_selector("#utilToolGrid:not([hidden])")
        self.run_page(checks, viewport={"width": 390, "height": 844})

    def test_excel_opens_a_new_tab_and_leaves_this_page_alone(self):
        def checks(page, _calls):
            self.open_util(page)
            opened = page.evaluate("""() => {
                window.__opened = [];
                window.open = (...args) => { window.__opened.push(args); return null; };
            }""")
            del opened
            page.click('[data-util-tool="claw-excel"]')
            args = page.evaluate("() => window.__opened")
            assert args and args[0][0] == "./#padiem-claw", args
            assert args[0][2] == "noopener", args
            assert page.locator("#utilToolNotice").is_visible()
            assert "새 탭" in page.locator("#utilToolNotice").inner_text()
            assert page.locator("#utilToolGrid").is_visible(), (
                "a tool that cannot live here does not replace the first screen")
            assert page.evaluate("() => location.pathname") == "/"
        self.run_page(checks)


if __name__ == "__main__":
    unittest.main()
