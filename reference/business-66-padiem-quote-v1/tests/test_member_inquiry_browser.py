"""Local-only B66 inquiry dialog smoke; API mocked, no production writes."""
from __future__ import annotations

import http.server
import json
import socketserver
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        return


class Server(socketserver.TCPServer):
    allow_reuse_address = True


def main() -> None:
    received = []
    with Server(("127.0.0.1", 0), Handler) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width, height in [(320, 640), (390, 844), (768, 900), (873, 1008), (1009, 1008), (1100, 900), (1199, 900), (1280, 850)]:
                    context = browser.new_context(viewport={"width": width, "height": height})
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    result = {"status": 401}
                    def route_inquiry(route):
                        if route.request.method != "POST":
                            route.fulfill(status=405, content_type="application/json",
                                          body='{"ok":false}')
                            return
                        received.append(json.loads(route.request.post_data))
                        if result["status"] == 401:
                            route.fulfill(status=401, content_type="application/json",
                                          body='{"ok":false,"error":{"code":"auth_required"}}')
                        else:
                            route.fulfill(status=201, content_type="application/json",
                                          body='{"ok":true,"inquiry_id":"b66inq_' + 'a'*32 + '"}')
                    page.route("**/api/padiem/b66/inquiries", route_inquiry)
                    page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html",
                              wait_until="domcontentloaded")
                    page.wait_for_function("Boolean(window.B66ShellLayout)")
                    before = len(received)
                    page.locator("#b66OpenInquiry").click()
                    assert page.locator("#b66InquiryDialog").evaluate("(el) => el.open") is True
                    page.locator("#b66InquiryCategory").select_option("bug")
                    page.locator("#b66InquirySubject").fill("Print preview issue")
                    page.locator("#b66InquiryBody").fill("The PDF alignment looks wrong.")
                    page.locator("#b66InquiryForm button[type=submit]").click()
                    page.locator("#b66InquiryStatus").get_by_text(
                        "로그인 후 문의할 수 있습니다.").wait_for()
                    assert len(received) == before + 1
                    assert received[-1] == {
                        "category": "bug",
                        "subject": "Print preview issue",
                        "body": "The PDF alignment looks wrong.",
                    }
                    result["status"] = 201
                    page.locator("#b66InquiryForm button[type=submit]").click()
                    page.locator("#b66InquiryStatus").get_by_text("문의가 접수되었습니다.", exact=False).wait_for()
                    assert len(received) == before + 2
                    assert page.locator("#b66InquirySubject").input_value() == ""
                    assert page.locator("#b66InquiryBody").input_value() == ""
                    page.locator("#b66CloseInquiry").click()
                    assert page.locator("#b66InquiryDialog").evaluate("(el) => el.open") is False
                    assert not errors, (width, errors)
                    print(f"B66_MEMBER_INQUIRY_BROWSER_PASS={width}x{height}", flush=True)
                    context.close()
            finally:
                browser.close()
        server.shutdown()


if __name__ == "__main__":
    main()
