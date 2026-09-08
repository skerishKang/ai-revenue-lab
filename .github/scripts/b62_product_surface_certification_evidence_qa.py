from __future__ import annotations

import asyncio
import os
from pathlib import Path

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def _stub_fonts(page: Page) -> None:
    async def css(route: Route) -> None:
        await route.fulfill(
            status=200,
            content_type="text/css; charset=utf-8",
            body="/* deterministic settled certification evidence font stub */\n",
        )

    async def font(route: Route) -> None:
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


async def _install_auth(page: Page) -> None:
    async def auth(route: Route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json; charset=utf-8",
            body='{"ready":true,"authenticated":false,"session_state":"guest","history_ready":false,"project_files_ready":false,"user":null}',
            headers={"Cache-Control": "no-store"},
        )

    await page.route("**/api/auth/status", auth)


async def _assert_settled(page: Page, *, mobile: bool, label: str) -> None:
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_function(
        "() => document.querySelector('.sidebar-account')?.dataset.accountState === 'guest'"
    )
    await page.wait_for_function(
        "() => document.querySelector('.app-shell')?.dataset.state === 'home'"
    )
    if mobile:
        await page.wait_for_function(
            "() => !document.querySelector('.app-shell')?.classList.contains('sidebar-open')"
        )
        await page.wait_for_function(
            "() => { const node = document.querySelector('#sidebar'); if (!node) return false; const rect = node.getBoundingClientRect(); return rect.right <= 1; }",
            timeout=5_000,
        )
    scroll_width, inner_width = await page.evaluate(
        "() => [document.documentElement.scrollWidth, window.innerWidth]"
    )
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow in settled evidence {label}: {scroll_width}>{inner_width}")


async def _capture(browser, *, query: str, viewport: dict[str, int], filename: str, mobile: bool) -> None:
    page = await browser.new_page(viewport=viewport)
    try:
        await _stub_fonts(page)
        await _install_auth(page)
        await page.goto(f"{BASE_URL}/{query}", wait_until="domcontentloaded", timeout=30_000)
        await _assert_settled(page, mobile=mobile, label=filename)
        await page.screenshot(path=str(OUT_DIR / filename), full_page=True)
    finally:
        await page.close()


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            await _capture(
                browser,
                query="?theme=light",
                viewport={"width": 1440, "height": 1000},
                filename="product-surface-certification-light-desktop.png",
                mobile=False,
            )
            await _capture(
                browser,
                query="?theme=padiem-glass&glass=female",
                viewport={"width": 390, "height": 844},
                filename="product-surface-certification-padiem-glass-mobile.png",
                mobile=True,
            )
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
