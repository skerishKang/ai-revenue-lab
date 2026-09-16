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

THEMES = (
    ("light", "?theme=light"),
    ("dark", "?theme=dark"),
    ("cinematic", "?theme=cinematic"),
    ("padiem-home", "?theme=padiem-home"),
    ("padiem-glass", "?theme=padiem-glass&glass=female"),
)


async def _no_horizontal_overflow(page: Page, name: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {name}: {scroll_width}>{inner_width}")


async def _exercise(page: Page, *, name: str) -> dict[str, Any]:
    pill = page.locator(".model-pill")
    await pill.wait_for(state="visible")
    await page.wait_for_function(
        "() => document.querySelector('.model-pill span:last-child')?.textContent === 'Padiem Plus'"
    )

    if await pill.get_attribute("role") != "button":
        raise AssertionError(f"tier pill is not keyboard-operable at {name}")
    if await pill.get_attribute("aria-haspopup") != "dialog":
        raise AssertionError(f"tier pill does not advertise dialog at {name}")

    await pill.focus()
    await page.keyboard.press("Enter")
    panel = page.locator("#modePresentationPanel")
    await panel.wait_for(state="visible")

    options = panel.locator("[data-mode-value]")
    if await options.count() != 1:
        raise AssertionError(f"expected exactly one product tier row at {name}")

    plus = panel.locator('[data-mode-value="plus"]')
    if await plus.is_disabled():
        raise AssertionError(f"Plus must be selectable at {name}")
    if await plus.get_attribute("aria-pressed") != "true":
        raise AssertionError(f"Plus must be the default selected tier at {name}")
    if await panel.locator('[data-mode-value="pro"]').count() != 0:
        raise AssertionError(f"Pro must remain browser-hidden at {name}")
    if await panel.locator('[data-mode-value="max"]').count() != 0:
        raise AssertionError(f"Max must remain browser-hidden at {name}")

    truth = (await panel.locator("[data-mode-truth]").inner_text()).strip()
    if "모델·제공자 선택은 파디엠 서버가 관리" not in truth:
        raise AssertionError(f"server-authority truth copy missing at {name}: {truth!r}")

    plus_box = await plus.bounding_box()
    if not plus_box or plus_box["height"] < 44:
        raise AssertionError(f"Plus tier target too small at {name}: {plus_box}")

    await plus.click()
    if not await panel.is_hidden():
        raise AssertionError(f"tier selection must close panel at {name}")

    await pill.focus()
    await page.keyboard.press("Enter")
    await panel.wait_for(state="visible")
    plus = panel.locator('[data-mode-value="plus"]')
    if await plus.get_attribute("aria-pressed") != "true":
        raise AssertionError(f"Plus selection did not remain active at {name}")

    await page.keyboard.press("Escape")
    if not await panel.is_hidden():
        raise AssertionError(f"Escape did not close tier panel at {name}")
    focused = await page.evaluate("document.activeElement === document.querySelector('.model-pill')")
    if not focused:
        raise AssertionError(f"focus did not return to tier control at {name}")

    await _no_horizontal_overflow(page, name)
    return {
        "default_tier": "plus",
        "selected_tier": "plus",
        "plus": "available",
        "pro": "browser_hidden",
        "max": "browser_hidden",
        "server_authority_copy": True,
        "escape_focus_return": True,
        "horizontal_overflow": False,
        "status": "PASS",
    }

async def main() -> None:
    report: dict[str, Any] = {"base_url": BASE_URL, "views": {}}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for theme, query in THEMES:
                for viewport_name, viewport in (
                    ("desktop", {"width": 1440, "height": 1000}),
                    ("mobile", {"width": 390, "height": 844}),
                ):
                    page = await browser.new_page(viewport=viewport)
                    try:
                        name = f"{theme}-{viewport_name}"
                        await page.goto(f"{BASE_URL}/{query}", wait_until="domcontentloaded", timeout=30_000)
                        await page.locator("#messageInput").wait_for(state="visible")
                        report["views"][name] = await _exercise(page, name=name)
                        if name in {"light-desktop", "padiem-glass-mobile"}:
                            await page.locator(".model-pill").click()
                            await page.locator("#modePresentationPanel").wait_for(state="visible")
                            await page.screenshot(path=str(OUT_DIR / f"mode-{name}.png"), full_page=True)
                    finally:
                        await page.close()
        finally:
            await browser.close()

    english = await _english_probe()
    report["english"] = english
    report["status"] = "PASS"
    (OUT_DIR / "mode-presentation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


async def _english_probe() -> dict[str, Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page(viewport={"width": 900, "height": 720})
            await page.goto(f"{BASE_URL}/?theme=light&lang=en", wait_until="domcontentloaded", timeout=30_000)
            await page.locator("#messageInput").wait_for(state="visible")
            await page.wait_for_function(
                "() => document.querySelector('.model-pill span:last-child')?.textContent === 'Padiem Plus'"
            )
            await page.locator(".model-pill").click()
            panel = page.locator("#modePresentationPanel")
            await panel.wait_for(state="visible")
            if await panel.locator("[data-mode-value]").count() != 1:
                raise AssertionError("English tier panel must expose exactly Plus")
            if await panel.locator('[data-mode-value="pro"]').count() != 0:
                raise AssertionError("English tier panel must keep Pro browser-hidden")
            truth = (await panel.locator("[data-mode-truth]").inner_text()).strip()
            if "Provider and model routing stays server-managed" not in truth:
                raise AssertionError(f"English tier truth copy missing: {truth!r}")
            return {"locale": "en", "default_tier": "plus", "status": "PASS"}
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
