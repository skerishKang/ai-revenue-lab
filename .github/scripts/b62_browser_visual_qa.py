from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def _visible_count(page: Page, selector: str) -> int:
    return await page.locator(selector).evaluate_all(
        "els => els.filter(el => { const s = getComputedStyle(el); const r = el.getBoundingClientRect(); return s.display !== 'none' && s.visibility !== 'hidden' && r.width > 0 && r.height > 0; }).length"
    )


async def _assert_in_viewport(page: Page, selector: str) -> dict[str, float]:
    box = await page.locator(selector).bounding_box()
    if not box:
        raise AssertionError(f"{selector} has no visible bounding box")
    viewport = page.viewport_size
    assert viewport is not None
    if box["x"] < -1 or box["y"] < -1:
        raise AssertionError(f"{selector} starts outside viewport: {box}")
    if box["x"] + box["width"] > viewport["width"] + 1:
        raise AssertionError(f"{selector} overflows viewport width: {box}")
    if box["y"] + box["height"] > viewport["height"] + 1:
        raise AssertionError(f"{selector} overflows viewport height: {box}")
    return {key: round(float(value), 2) for key, value in box.items()}


async def _run_view(page: Page, *, name: str, width: int, height: int, mobile: bool) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_timeout(700)

    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {name}: scrollWidth={scroll_width}, innerWidth={inner_width}")

    composer_box = await _assert_in_viewport(page, "#composerForm")
    input_box = await _assert_in_viewport(page, "#messageInput")
    mobile_menu_visible = await page.locator("#mobileMenu").is_visible()
    if mobile and not mobile_menu_visible:
        raise AssertionError("mobile menu must be visible on mobile viewport")

    visible_starters = await _visible_count(page, ".starter")
    visible_disabled = await _visible_count(page, "button:disabled")
    model_pill_visible = await page.locator(".model-pill").is_visible()
    route_detail_visible = await page.locator(".route-details").is_visible() if await page.locator(".route-details").count() else False

    await page.screenshot(path=str(OUT_DIR / f"{name}-home.png"), full_page=True)

    first_prompt = "오늘 저녁 메뉴를 세 가지 추천해줘"
    input_box_locator = page.locator("#messageInput")
    await input_box_locator.fill(first_prompt)
    await page.locator("#sendButton").wait_for(state="visible")
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("send button stayed disabled after entering a question")
    await page.locator("#sendButton").click()

    await page.locator('.app-shell[data-state="chat"]').wait_for(state="attached")
    first_assistant = page.locator("#messageList .assistant-message").first
    await first_assistant.wait_for(state="visible", timeout=15_000)
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-content')?.textContent?.includes('모의 스트리밍 상태입니다')",
        timeout=15_000,
    )
    await page.screenshot(path=str(OUT_DIR / f"{name}-chat.png"), full_page=True)

    await page.locator("#messageInput").fill("그중 가장 간단한 것으로 하나 골라줘")
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("follow-up send button stayed disabled")
    await page.locator("#sendButton").click()
    await page.wait_for_function(
        "() => document.querySelectorAll('#messageList .assistant-message').length >= 2",
        timeout=15_000,
    )
    await page.wait_for_function(
        "() => [...document.querySelectorAll('#messageList .assistant-content')].filter(el => el.textContent?.includes('모의 스트리밍 상태입니다')).length >= 2",
        timeout=15_000,
    )

    return {
        "viewport": {"width": width, "height": height},
        "horizontal_overflow": False,
        "composer_box": composer_box,
        "input_box": input_box,
        "visible_starter_count": visible_starters,
        "visible_disabled_button_count": visible_disabled,
        "model_pill_visible": model_pill_visible,
        "route_detail_visible": route_detail_visible,
        "mobile_menu_visible": mobile_menu_visible,
        "first_question": "PASS",
        "follow_up": "PASS",
        "mock_answer_marker": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "runtime_expectation": "mock",
        "provider_calls_expected": 0,
        "views": {},
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            report["views"]["desktop"] = await _run_view(
                page, name="desktop", width=1440, height=1000, mobile=False
            )
            await page.close()

            mobile_page = await browser.new_page()
            report["views"]["mobile"] = await _run_view(
                mobile_page, name="mobile", width=390, height=844, mobile=True
            )
            await mobile_page.close()
        finally:
            await browser.close()

    report["status"] = "PASS"
    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
