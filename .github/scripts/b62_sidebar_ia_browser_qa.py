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


async def _assert_no_horizontal_overflow(page: Page, name: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {name}: scrollWidth={scroll_width}, innerWidth={inner_width}")


async def _assert_focus(page: Page, selector: str, label: str) -> None:
    matches = await page.evaluate(
        "selector => document.activeElement === document.querySelector(selector)",
        selector,
    )
    if not matches:
        active = await page.evaluate(
            "() => ({ tag: document.activeElement?.tagName || '', id: document.activeElement?.id || '', className: document.activeElement?.className || '', text: (document.activeElement?.textContent || '').trim() })"
        )
        raise AssertionError(f"keyboard order mismatch for {label}: active={active}")


async def _assert_sidebar_contract(page: Page, *, mobile: bool) -> dict[str, Any]:
    if await page.locator("#recentTitle").count() != 0:
        raise AssertionError("sidebar suggested-question heading must be removed")
    if await page.locator("#sidebar [data-prompt]").count() != 0:
        raise AssertionError("sidebar must not own prompt-discovery controls")

    visible_starters = await _visible_count(page, "#emptyState .starter-grid .starter")
    if visible_starters < 3:
        raise AssertionError(f"central empty-state starters were not preserved: visible={visible_starters}")

    home = page.locator("#sidebar .sidebar-bottom .home-link")
    settings = page.locator("#sidebar .sidebar-bottom #settingsButton")
    account = page.locator("#sidebar .sidebar-bottom .sidebar-account")
    if await home.count() != 1 or await settings.count() != 1 or await account.count() != 1:
        raise AssertionError("bottom utility group must contain Padiem Home, settings and account exactly once")
    if await home.get_attribute("href") != "https://padiem.net/":
        raise AssertionError("Padiem Home destination changed")

    order = await page.evaluate(
        """
        () => {
          const sidebar = document.querySelector('#sidebar');
          const nodes = [
            sidebar.querySelector('#newChatButton'),
            sidebar.querySelector('.side-nav'),
            sidebar.querySelector('#projectsSection'),
            sidebar.querySelector('#historySection'),
            sidebar.querySelector('#outputsSection'),
            sidebar.querySelector('.sidebar-footer'),
            sidebar.querySelector('.sidebar-bottom'),
          ];
          return nodes.map(node => node ? [...sidebar.children].indexOf(node) : -1);
        }
        """
    )
    if order != sorted(order) or min(order) < 0:
        raise AssertionError(f"sidebar DOM hierarchy is not navigation/history then utilities: {order}")

    if mobile:
        await page.locator("#mobileMenu").click()
        await page.locator("#sidebar").wait_for(state="visible")
        await _assert_focus(page, "#mobileClose", "mobile close")
        await page.keyboard.press("Tab")
        await _assert_focus(page, ".brand", "mobile brand")
        await page.keyboard.press("Tab")
        await _assert_focus(page, "#newChatButton", "mobile new chat")
        await page.keyboard.press("Tab")
        await _assert_focus(page, ".sidebar-bottom .home-link", "mobile Padiem Home")
        await page.keyboard.press("Tab")
        await _assert_focus(page, "#settingsButton", "mobile settings")
        await page.screenshot(path=str(OUT_DIR / "sidebar-ia-mobile.png"), full_page=True)
    else:
        await page.locator(".brand").focus()
        await page.keyboard.press("Tab")
        await _assert_focus(page, "#newChatButton", "desktop new chat")
        await page.keyboard.press("Tab")
        await _assert_focus(page, ".sidebar-bottom .home-link", "desktop Padiem Home")
        await page.keyboard.press("Tab")
        await _assert_focus(page, "#settingsButton", "desktop settings")
        await page.screenshot(path=str(OUT_DIR / "sidebar-ia-desktop.png"), full_page=True)

    await _assert_no_horizontal_overflow(page, "sidebar-ia-mobile" if mobile else "sidebar-ia-desktop")
    return {
        "mobile": mobile,
        "duplicate_sidebar_prompt_surface": 0,
        "visible_empty_state_starters": visible_starters,
        "utility_order": ["padiem-home", "settings", "account"],
        "keyboard_navigation": "PASS",
        "horizontal_overflow": False,
        "status": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {"base_url": BASE_URL, "views": {}}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            desktop = await browser.new_page(viewport={"width": 1440, "height": 1000})
            await desktop.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
            await desktop.locator("#messageInput").wait_for(state="visible")
            report["views"]["desktop"] = await _assert_sidebar_contract(desktop, mobile=False)
            await desktop.close()

            mobile = await browser.new_page(viewport={"width": 390, "height": 844})
            await mobile.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
            await mobile.locator("#messageInput").wait_for(state="visible")
            report["views"]["mobile"] = await _assert_sidebar_contract(mobile, mobile=True)
            await mobile.close()
        finally:
            await browser.close()

    report["status"] = "PASS"
    (OUT_DIR / "sidebar-ia-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
