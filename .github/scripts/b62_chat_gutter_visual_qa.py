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

VIEWPORTS = (
    ("desktop-1920", 1920, 1080),
    ("compact-1280", 1280, 720),
    ("tablet-landscape-960", 960, 768),
    ("tablet-portrait-768", 768, 1024),
    ("mobile-390", 390, 844),
)


async def _box(page: Page, selector: str) -> dict[str, float]:
    box = await page.locator(selector).bounding_box()
    if not box:
        raise AssertionError(f"{selector} has no visible bounding box")
    return {key: round(float(value), 2) for key, value in box.items()}


def _right(box: dict[str, float]) -> float:
    return box["x"] + box["width"]


def _assert_close(a: float, b: float, *, name: str, tolerance: float = 1.5) -> None:
    if abs(a - b) > tolerance:
        raise AssertionError(f"{name} mismatch: {a} vs {b}")


async def _capture(page: Page, *, name: str, width: int, height: int) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(
        f"{BASE_URL}/?theme=padiem-glass&glass=female",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.locator("#messageInput").wait_for(state="visible")
    await page.locator("#messageInput").fill("공유 대화폭 반응형 검증")
    await page.locator("#sendButton").click()
    await page.locator('.app-shell[data-state="chat"]').wait_for(state="attached")
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-content')?.textContent?.includes('지금은 미리보기 환경입니다')",
        timeout=15_000,
    )
    await page.wait_for_timeout(450)

    conversation = await _box(page, ".conversation")
    composer = await _box(page, ".composer-wrap")
    message_list = await _box(page, "#messageList")
    user_message = await _box(page, ".user-message")
    user_bubble = await _box(page, ".user-message .message-bubble")
    assistant_message = await _box(page, ".assistant-message")
    assistant_avatar = await _box(page, ".assistant-avatar")
    assistant_body = await _box(page, ".assistant-body")

    _assert_close(conversation["x"], composer["x"], name=f"{name} left gutter")
    _assert_close(_right(conversation), _right(composer), name=f"{name} right gutter")
    _assert_close(conversation["width"], composer["width"], name=f"{name} lane width")
    _assert_close(message_list["x"], conversation["x"], name=f"{name} message-list left")
    _assert_close(_right(message_list), _right(conversation), name=f"{name} message-list right")
    _assert_close(user_message["x"], conversation["x"], name=f"{name} user outer left")
    _assert_close(_right(user_message), _right(conversation), name=f"{name} user outer right")
    _assert_close(_right(user_bubble), _right(conversation), name=f"{name} user bubble right")

    assistant_gap = round(assistant_body["x"] - _right(assistant_avatar), 2)
    if assistant_gap < 8 or assistant_gap > 12.5:
        raise AssertionError(f"{name} assistant meta/content gap out of range: {assistant_gap}")

    html_metrics = await page.evaluate(
        """
        () => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
        })
        """
    )
    if html_metrics["scrollWidth"] > html_metrics["innerWidth"] + 1:
        raise AssertionError(f"{name} horizontal overflow: {html_metrics}")

    prose = page.locator(".assistant-content .rich-response-paragraph").first
    if await prose.count():
        prose_box = await prose.bounding_box()
        if prose_box and width >= 1024 and prose_box["width"] > 760:
            raise AssertionError(f"{name} prose measure too wide: {prose_box['width']}")

    screenshot = f"{name}-shared-gutter.png"
    await page.screenshot(path=str(OUT_DIR / screenshot), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "conversation": conversation,
        "composer": composer,
        "message_list": message_list,
        "user_message": user_message,
        "user_bubble": user_bubble,
        "assistant_message": assistant_message,
        "assistant_avatar": assistant_avatar,
        "assistant_body": assistant_body,
        "assistant_gap_px": assistant_gap,
        "horizontal_overflow": False,
        "shared_left_gutter": True,
        "shared_right_gutter": True,
        "user_bubble_right_aligned": True,
        "screenshot": screenshot,
        "status": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "purpose": "B62 shared conversation/composer gutter, user edge, and assistant meta rhythm",
        "views": {},
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for name, width, height in VIEWPORTS:
                page = await browser.new_page()
                try:
                    report["views"][name] = await _capture(
                        page, name=name, width=width, height=height
                    )
                finally:
                    await page.close()
        finally:
            await browser.close()

    report["status"] = "PASS"
    report_path = OUT_DIR / "shared-gutter-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
