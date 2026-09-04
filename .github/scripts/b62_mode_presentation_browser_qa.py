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
        "() => document.querySelector('.model-pill span:last-child')?.textContent === 'Auto'"
    )

    if await pill.get_attribute("role") != "button":
        raise AssertionError(f"mode pill is not keyboard-operable at {name}")
    if await pill.get_attribute("aria-haspopup") != "dialog":
        raise AssertionError(f"mode pill does not advertise dialog at {name}")

    await pill.focus()
    await page.keyboard.press("Enter")
    panel = page.locator("#modePresentationPanel")
    await panel.wait_for(state="visible")

    options = panel.locator("[data-mode-value]")
    if await options.count() != 4:
        raise AssertionError(f"expected four product mode rows at {name}")

    auto = panel.locator('[data-mode-value="auto"]')
    fast = panel.locator('[data-mode-value="fast"]')
    balanced = panel.locator('[data-mode-value="balanced"]')
    deep = panel.locator('[data-mode-value="deep"]')
    if await auto.is_disabled():
        raise AssertionError(f"Auto must be product-available at {name}")
    if await auto.get_attribute("aria-pressed") != "true":
        raise AssertionError(f"Auto must remain selected at {name}")
    for locator, mode in ((fast, "fast"), (balanced, "balanced"), (deep, "deep")):
        if not await locator.is_disabled():
            raise AssertionError(f"{mode} must remain preview-only until backend mapping is trusted at {name}")

    truth = (await panel.locator("[data-mode-truth]").inner_text()).strip()
    if "실제 모델 연결 전까지 선택할 수 없습니다" not in truth:
        raise AssertionError(f"truth boundary copy missing at {name}: {truth!r}")

    auto_box = await auto.bounding_box()
    if not auto_box or auto_box["height"] < 44:
        raise AssertionError(f"Auto mode target too small at {name}: {auto_box}")

    await page.keyboard.press("Escape")
    if not await panel.is_hidden():
        raise AssertionError(f"Escape did not close mode panel at {name}")
    focused = await page.evaluate("document.activeElement === document.querySelector('.model-pill')")
    if not focused:
        raise AssertionError(f"focus did not return to mode control at {name}")

    await _no_horizontal_overflow(page, name)
    return {
        "mode": "auto",
        "fast": "preview_only",
        "balanced": "preview_only",
        "deep": "preview_only",
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
                "() => document.querySelector('.model-pill span:last-child')?.textContent === 'Auto'"
            )
            await page.locator(".model-pill").click()
            truth = (await page.locator("[data-mode-truth]").inner_text()).strip()
            if "cannot be selected until trusted backend mappings are active" not in truth:
                raise AssertionError(f"English mode truth copy missing: {truth!r}")
            return {"locale": "en", "status": "PASS"}
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
