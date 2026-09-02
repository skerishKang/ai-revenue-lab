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
    ("glass-zoom75-equivalent", 2560, 1440),
    ("glass-zoom100-equivalent", 1920, 1080),
    ("glass-zoom150-equivalent", 1280, 720),
)


async def _box(page: Page, selector: str) -> dict[str, float]:
    box = await page.locator(selector).bounding_box()
    if not box:
        raise AssertionError(f"{selector} has no visible bounding box")
    return {key: round(float(value), 2) for key, value in box.items()}


async def _assert_no_horizontal_overflow(page: Page, name: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(
            f"horizontal overflow at {name}: scrollWidth={scroll_width}, innerWidth={inner_width}"
        )


async def _assert_horizontally_in_viewport(page: Page, selector: str) -> dict[str, float]:
    box = await _box(page, selector)
    viewport = page.viewport_size
    assert viewport is not None
    if box["x"] < -1:
        raise AssertionError(f"{selector} starts outside viewport width: {box}")
    if box["x"] + box["width"] > viewport["width"] + 1:
        raise AssertionError(f"{selector} overflows viewport width: {box}")
    return box


async def _assert_in_viewport(page: Page, selector: str) -> dict[str, float]:
    box = await _assert_horizontally_in_viewport(page, selector)
    viewport = page.viewport_size
    assert viewport is not None
    if box["y"] < -1:
        raise AssertionError(f"{selector} starts outside viewport height: {box}")
    if box["y"] + box["height"] > viewport["height"] + 1:
        raise AssertionError(f"{selector} overflows viewport height: {box}")
    return box


async def _portrait_style(page: Page) -> dict[str, Any]:
    return await page.locator(".main-panel").evaluate(
        """
        (el) => {
          const style = getComputedStyle(el, '::before');
          return {
            backgroundImage: style.backgroundImage,
            opacity: Number.parseFloat(style.opacity || '0'),
            width: Number.parseFloat(style.width || '0'),
            right: style.right,
            maskImage: style.maskImage,
          };
        }
        """
    )


async def _capture(page: Page, *, name: str, width: int, height: int) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(
        f"{BASE_URL}/?theme=padiem-glass&glass=female",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_timeout(700)

    theme = await page.locator("html").get_attribute("data-theme")
    variant = await page.locator("html").get_attribute("data-glass-variant")
    if theme != "padiem-glass" or variant != "female":
        raise AssertionError(f"Glass female did not activate: theme={theme!r}, variant={variant!r}")

    await _assert_no_horizontal_overflow(page, f"{name}-home")
    conversation_home = await _assert_horizontally_in_viewport(page, ".conversation")
    composer_home = await _assert_in_viewport(page, "#composerForm")
    portrait_home = await _portrait_style(page)
    if "padiem-glass-female.jpg" not in portrait_home["backgroundImage"]:
        raise AssertionError(f"female portrait missing at {name}: {portrait_home}")
    if portrait_home["opacity"] < 0.15 or portrait_home["width"] < 250:
        raise AssertionError(f"female portrait is not materially visible at {name}: {portrait_home}")

    home_screenshot = f"{name}-female-home.png"
    await page.screenshot(path=str(OUT_DIR / home_screenshot), full_page=True)

    await page.locator("#messageInput").fill("브라우저 배율 대응 시각 검수")
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError(f"send button stayed disabled at {name}")
    await page.locator("#sendButton").click()
    await page.locator('.app-shell[data-state="chat"]').wait_for(state="attached")
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-content')?.textContent?.includes('지금은 미리보기 환경입니다')",
        timeout=15_000,
    )
    await page.wait_for_timeout(350)

    await _assert_no_horizontal_overflow(page, f"{name}-chat")
    conversation_chat = await _assert_horizontally_in_viewport(page, ".conversation")
    composer_chat = await _assert_in_viewport(page, "#composerForm")
    input_chat = await _assert_in_viewport(page, "#messageInput")
    assistant_avatar = await _assert_horizontally_in_viewport(page, ".assistant-avatar")

    assistant_name = (await page.locator(".assistant-meta span").first.inner_text()).strip()
    if assistant_name != "Padiem Chat":
        raise AssertionError(f"assistant brand casing drift at {name}: {assistant_name!r}")

    input_style = await page.locator("#messageInput").evaluate(
        """
        (el) => {
          const s = getComputedStyle(el);
          return { color: s.color, backgroundColor: s.backgroundColor };
        }
        """
    )
    if input_style["color"] not in {"rgb(255, 255, 255)", "rgba(255, 255, 255, 1)"}:
        raise AssertionError(f"chat input text is not white at {name}: {input_style}")
    if input_style["backgroundColor"] in {"rgba(0, 0, 0, 0)", "transparent"}:
        raise AssertionError(f"chat input lacks readable field surface at {name}: {input_style}")

    portrait_chat = await _portrait_style(page)
    if portrait_chat["opacity"] < 0.15 or portrait_chat["width"] < 250:
        raise AssertionError(f"female portrait disappeared in chat at {name}: {portrait_chat}")

    chat_screenshot = f"{name}-female-chat.png"
    await page.screenshot(path=str(OUT_DIR / chat_screenshot), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "conversation_home": conversation_home,
        "composer_home": composer_home,
        "conversation_chat": conversation_chat,
        "composer_chat": composer_chat,
        "input_chat": input_chat,
        "assistant_avatar": assistant_avatar,
        "assistant_name": assistant_name,
        "input_style": input_style,
        "portrait_home": portrait_home,
        "portrait_chat": portrait_chat,
        "home_screenshot": home_screenshot,
        "chat_screenshot": chat_screenshot,
        "vertical_scroll_allowed": True,
        "horizontal_overflow": False,
        "status": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "purpose": "Padiem Glass 1920x1080 browser zoom-equivalent desktop visual contract",
        "browser_zoom_forced": False,
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
    report_path = OUT_DIR / "glass-zoom-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
