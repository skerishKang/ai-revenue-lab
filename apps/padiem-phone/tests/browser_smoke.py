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
from phone_scripts import ScriptStore


def main():
    server.STORE = MockPhoneTasks()
    server.SCRIPTS = ScriptStore()  # no user-local writes during browser smoke
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
                assert page.get_by_role("heading", name="어떤 전화를 맡겨드릴까요?").is_visible()
                page.locator("#createButton").click()
                page.locator("#activeTask .task-status strong").wait_for(timeout=4000)
                page.reload(wait_until="load")
                page.locator("#activeTask .task-status strong").wait_for(timeout=5000)
                assert page.locator("#createButton").is_disabled(), "in-progress mock task must resume"
                page.locator("#activeTask .task-status strong").get_by_text("모의 완료").wait_for(timeout=16000)
                page.wait_for_function("document.querySelector('#statTotal').textContent === '1'")
                page.locator('.nav-link[data-page="history"]').click()
                assert page.locator("#historyBody tr").count() >= 1
                page.locator('.nav-link[data-page="usage"]').click()
                page.wait_for_function("document.querySelector('#usageCompleted').textContent === '1'")
                page.locator("#usageStageBreakdown .usage-stage-row").first.wait_for(timeout=4000)
                assert page.locator("#usageStageBreakdown .usage-stage-row").count() == 4
                page.locator('.nav-link[data-page="scripts"]').click()
                page.get_by_role("button", name="이 대본으로 시작 ↗").nth(1).click()
                assert page.locator("#destination").input_value() == "거래처 (가상)"
                assert page.locator("#dashboard").is_visible()

                # Custom script creation, editing, reuse, deletion and history snapshot.
                page.locator('.nav-link[data-page="scripts"]').click()
                page.locator("#newScriptButton").click()
                page.locator("#scriptTitle").fill("나만의 확인 대본")
                page.locator("#scriptDestination").fill("가상 거래처")
                page.locator("#scriptGoal").fill("입고 예정일을 확인해 줘")
                page.locator("#scriptQuestions").fill("입고 날짜가 언제인가요?")
                page.locator("#scriptNotes").fill("결제를 진행하지 마세요")
                page.locator("#saveScriptButton").click()
                page.get_by_role("heading", name="나만의 확인 대본").wait_for(timeout=8000)
                card = page.locator(".template-card").filter(has_text="나만의 확인 대본")
                card.get_by_role("button", name="편집").click()
                page.locator("#scriptTitle").fill("수정한 확인 대본")
                page.locator("#saveScriptButton").click()
                page.get_by_role("heading", name="수정한 확인 대본").wait_for(timeout=8000)
                card = page.locator(".template-card").filter(has_text="수정한 확인 대본")
                card.get_by_role("button", name="이 대본으로 시작").click()
                assert page.locator("#dashboard").is_visible()
                assert page.locator("#goal").input_value() == "입고 예정일을 확인해 줘"
                page.locator("#createButton").click()
                page.locator("#activeTask .task-status strong").get_by_text("모의 완료").wait_for(timeout=16000)
                page.locator('.nav-link[data-page="scripts"]').click()
                card = page.locator(".template-card").filter(has_text="수정한 확인 대본")
                card.get_by_role("button", name="편집").click()
                page.once("dialog", lambda dialog: dialog.accept())
                page.locator("#deleteScriptButton").click()
                page.get_by_role("heading", name="수정한 확인 대본").wait_for(state="detached", timeout=8000)
                assert page.locator(".template-card").count() == 3
                page.locator('.nav-link[data-page="history"]').click()
                page.locator("#historyBody .detail-link").first.click()
                page.locator("#historyDetails").wait_for(state="visible", timeout=8000)
                assert page.locator("#historyDetailsContent").get_by_text("결제를 진행하지 마세요").is_visible()
                assert page.locator("#historyDetailsContent").get_by_text("입고 날짜가 언제인가요?").is_visible()
                assert page.locator(".phone-stage-timeline .phone-stage").count() >= 2
                with page.expect_download() as download_result:
                    page.get_by_role("button", name="모의 업무 보고서(.txt) 저장").click()
                download = download_result.value
                assert download.suggested_filename.startswith("padiem-phone-mock-")
                report = Path(download.path()).read_text(encoding="utf-8-sig")
                assert "결제를 진행하지 마세요" in report
                assert "실제 전화 발신: 0건" in report
                print("TASK_REPORT_DOWNLOAD=PASS")
                page.locator("#closeHistoryDetails").click()
                assert page.locator("#historyDetails").is_hidden()
                print("SCRIPT_UI_CRUD_AND_TASK_SNAPSHOT=PASS")
                print("DESKTOP_BROWSER_SMOKE=PASS")
                assert not outside, f"unexpected outbound browser requests: {outside}"
                assert not page_errors, f"browser JS errors: {page_errors}"
                mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
                mobile.goto(url + "/", wait_until="load")
                assert mobile.locator("#createButton").is_visible()
                assert mobile.get_by_role("heading", name="어떤 전화를 맡겨드릴까요?").is_visible()
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
