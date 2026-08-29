from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765").rstrip("/")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

THEMES = ("light", "dark", "cinematic", "padiem-home")
BRIGHT_THEMES = {"light", "padiem-home"}


async def _assert_no_horizontal_overflow(page: Page, label: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(
            f"horizontal overflow at {label}: scrollWidth={scroll_width}, innerWidth={inner_width}"
        )


async def _style(page: Page, selector: str) -> dict[str, str] | None:
    locator = page.locator(selector).first
    if await locator.count() == 0 or not await locator.is_visible():
        return None
    return await locator.evaluate(
        "el => { const s = getComputedStyle(el); return { color: s.color, backgroundColor: s.backgroundColor, backgroundImage: s.backgroundImage, boxShadow: s.boxShadow, fontSize: s.fontSize, opacity: s.opacity }; }"
    )


async def _visible_theme_option_count(page: Page) -> int:
    return await page.locator(".theme-picker .theme-option:visible").count()


async def _headline_line_boxes(page: Page) -> int:
    locator = page.locator("#emptyState h1")
    return await locator.evaluate(
        """el => {
          const range = document.createRange();
          range.selectNodeContents(el);
          const rects = Array.from(range.getClientRects()).filter(r => r.width > 1 && r.height > 1);
          const tops = [];
          for (const rect of rects) {
            if (!tops.some(top => Math.abs(top - rect.top) < 2)) tops.push(rect.top);
          }
          return tops.length;
        }"""
    )


async def _open_theme(page: Page, theme: str) -> None:
    await page.goto(f"{BASE_URL}/?theme={theme}", wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_timeout(500)
    actual = await page.evaluate("document.documentElement.dataset.theme")
    if actual != theme:
        raise AssertionError(f"theme URL state mismatch: expected={theme}, actual={actual}")
    option = page.locator(f'[data-theme-value="{theme}"]')
    if await option.get_attribute("aria-pressed") != "true":
        raise AssertionError(f"theme control is not selected for {theme}")


async def _capture_surface(
    page: Page,
    *,
    theme: str,
    surface: str,
    width: int,
    height: int,
    mobile: bool,
) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})
    await _open_theme(page, theme)
    prefix = f"theme-{theme}-{surface}"

    await _assert_no_horizontal_overflow(page, f"{prefix}-home")
    active_tool = await _style(page, "#attachmentButton")
    if theme in BRIGHT_THEMES:
        if active_tool is None:
            raise AssertionError(f"active File tool is not visible for bright theme {theme}/{surface}")
        inherited_dark_foregrounds = {
            "rgb(255, 255, 255)",
            "rgba(255, 255, 255, 0.58)",
        }
        if active_tool["color"] in inherited_dark_foregrounds:
            raise AssertionError(
                f"active File tool retained dark-theme foreground for {theme}/{surface}: {active_tool}"
            )

    sidebar_heading = await _style(page, "#recentTitle")
    composer_note = await _style(page, ".composer-note")
    if sidebar_heading is None or sidebar_heading["fontSize"] != "12px":
        raise AssertionError(
            f"sidebar heading readability floor failed for {theme}/{surface}: {sidebar_heading}"
        )
    if composer_note is None or composer_note["fontSize"] != "12px":
        raise AssertionError(
            f"composer-note readability floor failed for {theme}/{surface}: {composer_note}"
        )

    headline_lines = await _headline_line_boxes(page)
    if mobile and theme == "light" and headline_lines != 2:
        raise AssertionError(
            f"Light mobile home headline should render as 2 lines, got {headline_lines}"
        )

    home_metrics = {
        "sidebar_heading": sidebar_heading,
        "sidebar_item": await _style(page, ".recent-item"),
        "active_file_tool": active_tool,
        "composer_note": composer_note,
        "headline_line_boxes": headline_lines,
        "body": await _style(page, "body"),
        "composer": await _style(page, ".composer"),
    }
    await page.screenshot(path=str(OUT_DIR / f"{prefix}-home.png"), full_page=True)

    drawer = None
    if mobile:
        menu = page.locator("#mobileMenu")
        await menu.click()
        await page.wait_for_timeout(250)
        if await menu.get_attribute("aria-expanded") != "true":
            raise AssertionError(f"mobile drawer did not open for {theme}")
        sidebar_box = await page.locator("#sidebar").bounding_box()
        if not sidebar_box or sidebar_box["x"] < -1:
            raise AssertionError(f"mobile drawer is off-screen for {theme}: {sidebar_box}")
        await _assert_no_horizontal_overflow(page, f"{prefix}-drawer")
        drawer = {key: round(float(value), 2) for key, value in sidebar_box.items()}
        await page.screenshot(path=str(OUT_DIR / f"{prefix}-drawer.png"), full_page=True)
        await page.locator("#mobileClose").click()
        await page.wait_for_timeout(200)
        if await menu.get_attribute("aria-expanded") != "false":
            raise AssertionError(f"mobile drawer did not close for {theme}")

    prompt = "오늘 저녁 메뉴를 세 가지 추천해줘"
    await page.locator("#messageInput").fill(prompt)
    send = page.locator("#sendButton")
    if await send.is_disabled():
        raise AssertionError(f"send button stayed disabled for {theme}/{surface}")
    await send.click()
    await page.locator('.app-shell[data-state="chat"]').wait_for(state="attached")
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-content')?.textContent?.includes('지금은 미리보기 환경입니다')",
        timeout=15_000,
    )
    # Let message-entry animation and layout settle before visual evidence.
    await page.wait_for_timeout(700)
    await _assert_no_horizontal_overflow(page, f"{prefix}-chat")

    compact_theme_options = None
    expanded_theme_options = None
    if mobile:
        # Chat chrome should collapse to the current theme only.
        await page.locator("#messageInput").focus()
        await page.wait_for_timeout(50)
        compact_theme_options = await _visible_theme_option_count(page)
        if compact_theme_options != 1:
            raise AssertionError(
                f"mobile chat theme picker should show 1 compact option for {theme}, got {compact_theme_options}"
            )

        # Focusing/tapping the current option must expand the existing four-way picker.
        selected_option = page.locator(f'[data-theme-value="{theme}"]')
        await selected_option.focus()
        await page.wait_for_timeout(50)
        expanded_theme_options = await _visible_theme_option_count(page)
        if expanded_theme_options != len(THEMES):
            raise AssertionError(
                f"mobile chat theme picker should expand to {len(THEMES)} options for {theme}, got {expanded_theme_options}"
            )
        await _assert_no_horizontal_overflow(page, f"{prefix}-chat-theme-expanded")

        # Restore compact state before the canonical chat screenshot.
        await page.locator("#messageInput").focus()
        await page.wait_for_timeout(50)
        if await _visible_theme_option_count(page) != 1:
            raise AssertionError(f"mobile chat theme picker did not collapse again for {theme}")

    chat_composer_note = await _style(page, ".composer-note")
    if chat_composer_note is None or chat_composer_note["fontSize"] != "12px":
        raise AssertionError(
            f"chat composer-note readability floor failed for {theme}/{surface}: {chat_composer_note}"
        )

    chat_metrics = {
        "assistant_text": await _style(page, ".assistant-content"),
        "assistant_meta": await _style(page, ".assistant-meta"),
        "active_file_tool": await _style(page, "#attachmentButton"),
        "composer_note": chat_composer_note,
        "user_bubble": await _style(page, ".message-bubble"),
        "body": await _style(page, "body"),
        "composer": await _style(page, ".composer"),
        "compact_theme_options": compact_theme_options,
        "expanded_theme_options": expanded_theme_options,
    }
    await page.screenshot(path=str(OUT_DIR / f"{prefix}-chat.png"), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "url_theme": theme,
        "horizontal_overflow": False,
        "drawer_box": drawer,
        "home_metrics": home_metrics,
        "chat_metrics": chat_metrics,
        "home_screenshot": f"{prefix}-home.png",
        "drawer_screenshot": f"{prefix}-drawer.png" if mobile else None,
        "chat_screenshot": f"{prefix}-chat.png",
        "status": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "runtime_expectation": "mock",
        "provider_calls_expected": 0,
        "themes": {},
    }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for theme in THEMES:
                report["themes"][theme] = {}

                desktop = await browser.new_page()
                report["themes"][theme]["desktop"] = await _capture_surface(
                    desktop,
                    theme=theme,
                    surface="desktop",
                    width=1440,
                    height=1000,
                    mobile=False,
                )
                await desktop.close()

                mobile = await browser.new_page()
                report["themes"][theme]["mobile"] = await _capture_surface(
                    mobile,
                    theme=theme,
                    surface="mobile",
                    width=390,
                    height=844,
                    mobile=True,
                )
                await mobile.close()
        finally:
            await browser.close()

    dark_home = report["themes"]["dark"]["desktop"]["home_metrics"]
    cinematic_home = report["themes"]["cinematic"]["desktop"]["home_metrics"]
    if dark_home["body"]["backgroundImage"] == cinematic_home["body"]["backgroundImage"]:
        raise AssertionError("Cinematic body atmosphere is not distinct from neutral Dark")
    if dark_home["composer"]["backgroundImage"] == cinematic_home["composer"]["backgroundImage"]:
        raise AssertionError("Cinematic composer surface is not distinct from neutral Dark")

    report["cinematic_distinct_from_dark"] = True
    report["status"] = "PASS"
    (OUT_DIR / "theme-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
