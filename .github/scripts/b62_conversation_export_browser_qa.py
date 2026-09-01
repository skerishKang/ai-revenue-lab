from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_CONVERSATION_EXPORT_QA_BASE_URL", "http://127.0.0.1:8777")
OUT_DIR = Path(os.environ.get("B62_CONVERSATION_EXPORT_QA_OUT_DIR", ".tmp/b62-conversation-export-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
FIRST_PROMPT = "부모님과 주말에 할 일을 세 가지 추천해줘"
FOLLOWUP_PROMPT = "그중 실내 활동만 다시 골라줘"


async def _install_static_font_stubs(page: Page, stubbed_hosts: set[str]) -> None:
    async def stub_stylesheet(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(status=200, content_type="text/css; charset=utf-8", body="/* deterministic QA */\n")

    async def stub_font(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", stub_stylesheet)
    await page.route("https://fonts.googleapis.com/**", stub_stylesheet)
    await page.route("https://fonts.gstatic.com/**", stub_font)


async def _wait_for_completed_answer(page: Page, minimum_count: int) -> None:
    await page.wait_for_function(
        """expected => {
          const messages = Array.from(document.querySelectorAll('.assistant-message'));
          if (messages.length < expected) return false;
          const last = messages[messages.length - 1];
          const content = last.querySelector('.assistant-content');
          return !!content && !content.querySelector('.typing') && !content.querySelector('.error-box') && content.innerText.trim().length > 0;
        }""",
        arg=minimum_count,
        timeout=10_000,
    )
    await page.wait_for_function(
        "() => { const b = document.getElementById('conversationExportButton'); return !!b && !b.hidden && !b.disabled; }",
        timeout=5_000,
    )


async def _send(page: Page, text: str, expected_answer_count: int) -> None:
    textarea = page.locator("#messageInput")
    await textarea.fill(text)
    await page.locator("#sendButton").click()
    await _wait_for_completed_answer(page, expected_answer_count)


async def _download_text(page: Page, name: str) -> tuple[str, str]:
    async with page.expect_download(timeout=5_000) as download_info:
        await page.locator("#conversationExportButton").click()
    download = await download_info.value
    suggested = download.suggested_filename
    path = await download.path()
    if path is None:
        raise AssertionError("browser did not materialize export download")
    raw = Path(path).read_bytes()
    text = raw.decode("utf-8")
    (OUT_DIR / f"{name}.txt").write_bytes(raw)
    return suggested, text


def _assert_export_text(text: str, *, expect_followup: bool) -> None:
    if not text.startswith("Padiem Chat 대화\n\n"):
        raise AssertionError(f"unexpected export header: {text[:80]!r}")
    if f"나:\n{FIRST_PROMPT}" not in text:
        raise AssertionError("first user message missing from export")
    if "Padiem Chat:\n" not in text:
        raise AssertionError("assistant label/content missing from export")
    if expect_followup and f"나:\n{FOLLOWUP_PROMPT}" not in text:
        raise AssertionError("follow-up message missing from second export")
    if not expect_followup and FOLLOWUP_PROMPT in text:
        raise AssertionError("first export unexpectedly contains future follow-up")

    first_user = text.index(FIRST_PROMPT)
    first_assistant = text.index("Padiem Chat:\n")
    if first_user >= first_assistant:
        raise AssertionError("message ordering is not user -> assistant")
    if expect_followup and first_assistant >= text.index(FOLLOWUP_PROMPT):
        raise AssertionError("follow-up ordering is incorrect")

    forbidden = ("provider_id", "request_id", "selected_provider", "selected_model", "chat_", "proj_", "data:image", "base64,")
    leaked = [token for token in forbidden if token in text]
    if leaked:
        raise AssertionError(f"private/runtime material leaked into export: {leaked!r}")


async def _assert_no_horizontal_overflow(page: Page, stage: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {stage}: {scroll_width}>{inner_width}")


async def _run_view(page: Page, *, name: str, width: int, height: int, mobile: bool) -> dict[str, object]:
    api_requests: list[str] = []
    unexpected_hosts: set[str] = set()
    stubbed_hosts: set[str] = set()

    def observe_request(request) -> None:
        parsed = urlparse(request.url)
        host = (parsed.hostname or "").lower()
        if parsed.path.startswith("/api/"):
            api_requests.append(f"{request.method} {parsed.path}")
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe_request)
    await _install_static_font_stubs(page, stubbed_hosts)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

    export_button = page.locator("#conversationExportButton")
    await export_button.wait_for(state="attached", timeout=5_000)
    if await export_button.is_visible() or not await export_button.is_disabled():
        raise AssertionError("empty conversation must not expose a usable export action")

    await _send(page, FIRST_PROMPT, 1)
    await _assert_no_horizontal_overflow(page, f"{name}-first-answer")
    if mobile:
        box = await export_button.bounding_box()
        if box is None or box["width"] < 44 or box["height"] < 44:
            raise AssertionError(f"mobile export target under 44px: {box!r}")

    await page.screenshot(path=str(OUT_DIR / f"{name}-ready.png"), full_page=True)
    if mobile:
        menu = page.locator("#mobileMenu")
        if await menu.get_attribute("aria-expanded") != "true":
            await menu.click()
        await page.locator("#sidebar").wait_for(state="visible")
        await export_button.scroll_into_view_if_needed()
    requests_before_first_export = list(api_requests)
    first_filename, first_text = await _download_text(page, f"{name}-first-export")
    if api_requests != requests_before_first_export:
        raise AssertionError(f"export triggered API request(s): before={requests_before_first_export!r} after={api_requests!r}")
    _assert_export_text(first_text, expect_followup=False)

    if FIRST_PROMPT in first_filename or "chat_" in first_filename or "proj_" in first_filename:
        raise AssertionError(f"filename includes private/conversation-derived content: {first_filename!r}")
    if not first_filename.startswith("Padiem-Chat-대화-") or not first_filename.endswith(".txt"):
        raise AssertionError(f"unexpected bounded filename: {first_filename!r}")

    if mobile:
        menu = page.locator("#mobileClose")
        if await menu.get_attribute("aria-expanded") != "false":
            await menu.click()
        await page.wait_for_function(
            "() => document.getElementById('mobileMenu')?.getAttribute('aria-expanded') === 'false'",
            timeout=5_000,
        )

    await _send(page, FOLLOWUP_PROMPT, 2)
    if mobile:
        menu = page.locator("#mobileMenu")
        if await menu.get_attribute("aria-expanded") != "true":
            await menu.click()
        await page.locator("#sidebar").wait_for(state="visible")
        await export_button.scroll_into_view_if_needed()
    requests_before_second_export = list(api_requests)
    second_filename, second_text = await _download_text(page, f"{name}-second-export")
    if api_requests != requests_before_second_export:
        raise AssertionError("second export triggered an API request")
    _assert_export_text(second_text, expect_followup=True)

    await _assert_no_horizontal_overflow(page, f"{name}-final")
    await page.screenshot(path=str(OUT_DIR / f"{name}-final.png"), full_page=True)

    if unexpected_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_hosts)!r}")

    return {
        "viewport": [width, height],
        "mobile": mobile,
        "api_requests_total": api_requests,
        "first_export_filename": first_filename,
        "second_export_filename": second_filename,
        "first_export_bytes": len(first_text.encode("utf-8")),
        "second_export_bytes": len(second_text.encode("utf-8")),
        "stubbed_font_hosts": sorted(stubbed_hosts),
        "unexpected_hosts": sorted(unexpected_hosts),
    }


async def main() -> None:
    report: dict[str, object] = {"base_url": BASE_URL, "views": {}}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for name, width, height, mobile in (
                ("desktop", 1440, 1000, False),
                ("mobile", 390, 844, True),
            ):
                context = await browser.new_context(locale="ko-KR", accept_downloads=True)
                page = await context.new_page()
                try:
                    report["views"][name] = await _run_view(page, name=name, width=width, height=height, mobile=mobile)
                finally:
                    await context.close()
        finally:
            await browser.close()

    report["status"] = "PASS"
    (OUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
