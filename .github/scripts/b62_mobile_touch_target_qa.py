from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_TOUCH_QA_BASE_URL", "http://127.0.0.1:8784")
OUT_DIR = Path(os.environ.get("B62_TOUCH_QA_OUT_DIR", ".tmp/b62-mobile-touch-target-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
TARGET_FLOOR = 44.0


async def stub_fonts(page: Page, seen_hosts: set[str]) -> None:
    async def stylesheet(route) -> None:
        seen_hosts.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(status=200, content_type="text/css; charset=utf-8", body="/* deterministic touch-target QA font stub */\n")

    async def font(route) -> None:
        seen_hosts.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", stylesheet)
    await page.route("https://fonts.googleapis.com/**", stylesheet)
    await page.route("https://fonts.gstatic.com/**", font)


async def measure_element(page: Page, selector: str, label: str) -> dict:
    result = await page.locator(selector).first.evaluate(
        """(el) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return {
            width: Math.round(rect.width * 10) / 10,
            height: Math.round(rect.height * 10) / 10,
            display: style.display,
            visibility: style.visibility,
            hidden: Boolean(el.closest('[hidden]')),
          };
        }"""
    )
    visible = (
        not result["hidden"]
        and result["display"] != "none"
        and result["visibility"] != "hidden"
        and result["width"] > 0
        and result["height"] > 0
    )
    return {"control": label, **result, "visible": visible}


async def measure_many(page: Page, selector: str, label_prefix: str) -> list[dict]:
    return await page.locator(selector).evaluate_all(
        """(elements, prefix) => elements.map((el, index) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          const hidden = Boolean(el.closest('[hidden]'));
          return {
            control: `${prefix}[${index}]`,
            width: Math.round(rect.width * 10) / 10,
            height: Math.round(rect.height * 10) / 10,
            display: style.display,
            visibility: style.visibility,
            hidden,
            visible: !hidden && style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0,
          };
        })""",
        label_prefix,
    )


def assert_floor(items: list[dict], stage: str) -> None:
    failures = [
        item
        for item in items
        if item["visible"] and (item["width"] < TARGET_FLOOR or item["height"] < TARGET_FLOOR)
    ]
    if failures:
        raise AssertionError(f"visible mobile targets below {TARGET_FLOOR:g}px at {stage}: {failures}")


async def assert_no_overflow(page: Page, stage: str) -> None:
    widths = await page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    if widths[0] > widths[1] + 1:
        raise AssertionError(f"horizontal overflow at {stage}: {widths}")


async def run_mobile(page: Page) -> dict:
    seen_hosts: set[str] = set()
    unexpected_hosts: set[str] = set()

    def observe(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe)
    await stub_fonts(page, seen_hosts)
    await page.set_viewport_size({"width": 390, "height": 844})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("h1").wait_for(state="visible")

    first_view = [
        await measure_element(page, "#mobileMenu", "mobileMenu"),
        await measure_element(page, "#loginButton", "loginButton"),
        await measure_element(page, "#attachmentButton", "attachmentButton"),
        await measure_element(page, "#sendButton", "sendButton"),
    ]
    assert_floor(first_view, "first-view")
    await assert_no_overflow(page, "first-view")
    await page.screenshot(path=str(OUT_DIR / "mobile-first-390x844.png"), full_page=True)

    await page.locator("#mobileMenu").click()
    await page.wait_for_function("() => document.querySelector('.app-shell')?.classList.contains('sidebar-open')")
    drawer = [
        await measure_element(page, "#mobileClose", "mobileClose"),
        await measure_element(page, "#newChatButton", "newChatButton"),
        await measure_element(page, "a.brand", "brandHome"),
    ]
    drawer.extend(await measure_many(page, ".recent-item", "recentItem"))
    assert_floor(drawer, "open-drawer")
    await assert_no_overflow(page, "open-drawer")
    await page.screenshot(path=str(OUT_DIR / "mobile-drawer-390x844.png"), full_page=True)

    if unexpected_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_hosts)}")

    return {
        "viewport": {"width": 390, "height": 844},
        "target_floor_px": TARGET_FLOOR,
        "first_view": first_view,
        "drawer": drawer,
        "under_44_count": 0,
        "stubbed_static_hosts": sorted(seen_hosts),
        "unexpected_external_hosts": sorted(unexpected_hosts),
    }


async def main() -> None:
    report = {
        "status": "RUNNING",
        "scope": "B62 parent-generation mobile touch targets",
        "model_selection": "DEFERRED",
        "low_medium_high": "UNASSIGNED",
        "real_provider_calls": 0,
        "core_b14_change": 0,
        "production_mutation": False,
    }
    report_path = OUT_DIR / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 390, "height": 844})
                report["mobile"] = await run_mobile(page)
                await page.close()
            finally:
                await browser.close()
        report["status"] = "PASS"
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
