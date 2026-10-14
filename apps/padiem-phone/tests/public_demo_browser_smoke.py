"""Browser acceptance for public static demo: no backend and no network call.
Requires Playwright + installed Chrome; runs an ephemeral loopback static server.
"""
from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from playwright.sync_api import sync_playwright

PUBLIC = Path(__file__).resolve().parents[1] / "public-demo"


class SilentStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    web = ThreadingHTTPServer(("127.0.0.1", 0), partial(SilentStaticHandler, directory=str(PUBLIC)))
    host = f"http://127.0.0.1:{web.server_address[1]}"
    worker = Thread(target=web.serve_forever, daemon=True)
    worker.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="chrome", headless=True)
            try:
                desktop = browser.new_page(viewport={"width": 1470, "height": 920}, accept_downloads=True)
                requests = []
                errors = []
                desktop.on("request", lambda req: requests.append(req.url))
                desktop.on("pageerror", lambda error: errors.append(str(error)))
                desktop.goto(host + "/", wait_until="load", timeout=13000)
                assert desktop.get_by_text("PUBLIC DEMO").count() >= 1
                assert desktop.get_by_role("heading", name="어떤 전화를 맡겨드릴까요?").is_visible()
                assert desktop.locator("#quickTemplates .script-row").count() == 3

                desktop.locator("#createButton").click()
                desktop.locator("#activeTask .task-status strong").get_by_text("모의 완료").wait_for(timeout=17000)
                assert desktop.locator("#statTotal").inner_text() == "1"
                desktop.locator('.nav-link[data-page="usage"]').click()
                desktop.locator("#usageStageBreakdown .usage-stage-row").first.wait_for(timeout=6000)
                assert desktop.locator("#usageStageBreakdown .usage-stage-row").count() == 4
                desktop.locator('.nav-link[data-page="history"]').click()
                desktop.locator("#historyBody .detail-link").first.click()
                desktop.locator("#historyDetails").wait_for(state="visible")
                assert desktop.locator(".phone-stage-timeline li").count() == 5
                with desktop.expect_download() as download:
                    desktop.get_by_role("button", name="모의 업무 보고서(.txt) 저장").click()
                saved = Path(download.value.path()).read_text(encoding="utf-8-sig")
                assert "실제 전화 발신: 0건" in saved
                assert "실제 요금: 0원" in saved
                print("PUBLIC_DEMO_REPORT_DOWNLOAD=PASS")

                desktop.locator('.nav-link[data-page="scripts"]').click()
                desktop.locator("#newScriptButton").click()
                desktop.locator("#scriptTitle").fill("가상 시연 대본")
                desktop.locator("#scriptDestination").fill("가상 거래처")
                desktop.locator("#scriptGoal").fill("물품 출고일 확인해 줘")
                desktop.locator("#scriptNotes").fill("실제 업무 변경 금지")
                desktop.locator("#saveScriptButton").click()
                desktop.get_by_role("heading", name="가상 시연 대본").wait_for(timeout=5000)
                assert desktop.locator(".template-card").count() == 4
                # Nothing is persisted: reload resets the entire in-memory mock.
                desktop.reload(wait_until="load")
                assert desktop.locator(".template-card").count() == 3 if desktop.locator("#scripts").is_visible() else True
                desktop.locator('.nav-link[data-page="usage"]').click()
                assert desktop.locator("#usageTotal").inner_text() == "0"
                print("PUBLIC_DEMO_MEMORY_RESET=PASS")

                assert all(link.startswith(host) for link in requests), requests
                assert not any("/api/" in link for link in requests), requests
                assert not errors, errors
                print("PUBLIC_DEMO_NO_EXTERNAL_OR_API_REQUESTS=PASS")
                mobile = browser.new_page(viewport={"width": 390, "height": 844})
                mobile.goto(host + "/", wait_until="load")
                assert mobile.locator("#createButton").is_visible()
                dimensions = mobile.evaluate("({window: innerWidth, doc: document.documentElement.scrollWidth})")
                assert dimensions["doc"] <= dimensions["window"] + 2, dimensions
                mobile.locator('.nav-link[data-page="scripts"]').click()
                assert mobile.locator("#scripts").is_visible()
                print("PUBLIC_DEMO_DESKTOP_MOBILE=PASS")
            finally:
                browser.close()
    finally:
        web.shutdown()
        web.server_close()
        worker.join(timeout=3)


if __name__ == "__main__":
    main()
