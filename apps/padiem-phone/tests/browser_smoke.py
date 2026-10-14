"""Optional headless browser smoke for the mock-only phone page.

Requires installed Playwright and Chrome/chromium. Does not place a call.
Run from apps/padiem-phone: python tests/browser_smoke.py
"""
from __future__ import annotations

from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
import server
from phone_mock import MockPhoneTasks


def main():
    server.STORE = MockPhoneTasks()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.PreviewHandler)
    url = f"http://127.0.0.1:{httpd.server_address[1]}"
    runner = Thread(target=httpd.serve_forever, daemon=True)
    runner.start()
    try:
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch(channel="chrome", headless=True)
            except Exception:
                browser = pw.chromium.launch(headless=True)
            try:
                outside = []
                page_errors = []
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.on("request", lambda req: outside.append(req.url) if not req.url.startswith(url) else None)
                page.on("pageerror", lambda error: page_errors.append(str(error)))
                page.goto(url + "/", wait_until="load")
                assert page.get_by_role("heading", name="전화 업무, 한곳에서").is_visible()
                page.get_by_role("button", name="모의 전화 작업 시작").click()
                page.locator("#activeTask .task-status strong").get_by_text("모의 완료").wait_for(timeout=16000)
                page.wait_for_function("document.querySelector('#statTotal').textContent === '1'")
                page.locator('.nav-link[data-page="history"]').click()
                assert page.locator("#historyBody tr").count() >= 1
                page.locator('.nav-link[data-page="usage"]').click()
                page.wait_for_function("document.querySelector('#usageCompleted').textContent === '1'")
                page.locator('.nav-link[data-page="scripts"]').click()
                page.get_by_role("button", name="이 대본으로 시작 ↗").nth(1).click()
                assert page.locator("#destination").input_value() == "거래처 (가상)"
                assert page.locator("#dashboard").is_visible()
                print("DESKTOP_BROWSER_SMOKE=PASS")
                assert not outside, f"unexpected outbound browser requests: {outside}"
                assert not page_errors, f"browser JS errors: {page_errors}"
                mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
                mobile.goto(url + "/", wait_until="load")
                assert mobile.locator("#createButton").is_visible()
                widths = mobile.evaluate("({screen: innerWidth, doc: document.documentElement.scrollWidth})")
                assert widths["doc"] <= widths["screen"] + 2, f"mobile overflow {widths}"
                mobile.locator('.nav-link[data-page="scripts"]').click()
                assert mobile.locator("#scripts").is_visible()
                print("MOBILE_BROWSER_SMOKE=PASS")
                print("BROWSER_EXTERNAL_REQUESTS=0")
            finally:
                browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        runner.join(timeout=3)


if __name__ == "__main__":
    main()
