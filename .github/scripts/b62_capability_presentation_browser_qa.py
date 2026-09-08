from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

THEMES = (
    ("light", "theme=light"),
    ("dark", "theme=dark"),
    ("cinematic", "theme=cinematic"),
    ("padiem-home", "theme=padiem-home"),
    ("padiem-glass", "theme=padiem-glass&glass=female"),
)
EXPECTED_FIXTURES = {
    "agent",
    "memory",
    "tool-completed",
    "tool-failed",
    "approval",
    "approval-resumed",
    "evidence",
    "completed",
    "failed",
    "cancelled",
    "timed-out",
}


async def _no_horizontal_overflow(page: Page, name: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {name}: {scroll_width}>{inner_width}")


async def _exercise(page: Page, *, name: str, page_errors: list[str]) -> dict[str, Any]:
    await page.locator("#capabilityPreviewBanner").wait_for(state="visible", timeout=15_000)
    banner = (await page.locator("#capabilityPreviewBanner").inner_text()).strip()
    if "DETERMINISTIC PREVIEW" not in banner:
        raise AssertionError(f"preview truth banner missing at {name}: {banner!r}")
    if "실제" not in banner and "no live" not in banner:
        raise AssertionError(f"preview live-boundary copy missing at {name}: {banner!r}")

    articles = page.locator("[data-preview-fixture]")
    if await articles.count() != len(EXPECTED_FIXTURES):
        raise AssertionError(f"unexpected fixture count at {name}: {await articles.count()}")
    fixture_ids = set(await articles.evaluate_all("nodes => nodes.map(node => node.dataset.previewFixture)"))
    if fixture_ids != EXPECTED_FIXTURES:
        raise AssertionError(f"fixture mismatch at {name}: {sorted(fixture_ids)}")

    kits = page.locator("[data-capability-presentation]")
    if await kits.count() != len(EXPECTED_FIXTURES):
        raise AssertionError(f"presentation kit count mismatch at {name}")
    for index in range(await kits.count()):
        kit = kits.nth(index)
        if await kit.get_attribute("data-preview") != "synthetic":
            raise AssertionError(f"non-synthetic kit surfaced in preview at {name} index={index}")
        truth = (await kit.locator(".capability-preview-truth").inner_text()).strip()
        if "실제" not in truth and "does not represent a live" not in truth:
            raise AssertionError(f"kit truth boundary missing at {name} index={index}: {truth!r}")

    groups = set(await page.locator("[data-capability-group]").evaluate_all("nodes => nodes.map(node => node.dataset.capabilityGroup)"))
    expected_groups = {"agent", "context", "tool", "approval", "evidence", "terminal"}
    if not expected_groups.issubset(groups):
        raise AssertionError(f"capability groups missing at {name}: {sorted(expected_groups - groups)}")

    approval_buttons = page.locator('[data-preview-fixture="approval"] .capability-action')
    if await approval_buttons.count() != 3:
        raise AssertionError(f"approval action count mismatch at {name}")
    for index in range(3):
        if not await approval_buttons.nth(index).is_disabled():
            raise AssertionError(f"synthetic approval action enabled at {name} index={index}")
        box = await approval_buttons.nth(index).bounding_box()
        if not box or box["height"] < 44:
            raise AssertionError(f"approval target below 44px at {name}: {box}")

    terminal_fixtures = {
        "completed": "success",
        "failed": "failed",
        "cancelled": "cancelled",
        "timed-out": "timed_out",
    }
    for fixture, state in terminal_fixtures.items():
        terminal = page.locator(f'[data-preview-fixture="{fixture}"] [data-capability-terminal]')
        await terminal.wait_for(state="visible")
        if await terminal.get_attribute("data-state") != state:
            raise AssertionError(f"terminal state mismatch at {name}/{fixture}")

    if not await page.locator("#messageInput").is_disabled():
        raise AssertionError(f"composer input must be disabled in synthetic preview at {name}")

    if page_errors:
        raise AssertionError(f"page errors at {name}: {page_errors}")

    await _no_horizontal_overflow(page, name)
    return {
        "fixtures": len(EXPECTED_FIXTURES),
        "groups": sorted(groups),
        "approval_actions_disabled": True,
        "terminal_states": sorted(terminal_fixtures),
        "horizontal_overflow": False,
        "production_mutation": False,
        "status": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "preview_authority": "synthetic_only",
        "fake_live_capability_claims": 0,
        "production_mutation": False,
        "views": {},
    }
    blocked_execution_requests: list[dict[str, str]] = []
    base_host = urlparse(BASE_URL).netloc

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for theme, theme_query in THEMES:
                for viewport_name, viewport in (
                    ("desktop", {"width": 1440, "height": 1000}),
                    ("mobile", {"width": 390, "height": 844}),
                ):
                    page = await browser.new_page(viewport=viewport)
                    page_errors: list[str] = []
                    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

                    def track_request(request: Any) -> None:
                        parsed = urlparse(request.url)
                        path = parsed.path
                        if parsed.netloc == base_host and (path.startswith("/api/chat") or "orchestrat" in path or path.startswith("/api/tools")):
                            blocked_execution_requests.append({"method": request.method, "url": request.url})

                    page.on("request", track_request)
                    try:
                        name = f"{theme}-{viewport_name}"
                        query = f"?{theme_query}&capability-preview=synthetic"
                        await page.goto(f"{BASE_URL}/{query}", wait_until="domcontentloaded", timeout=30_000)
                        report["views"][name] = await _exercise(page, name=name, page_errors=page_errors)
                        if name in {"light-desktop", "padiem-glass-mobile"}:
                            await page.screenshot(path=str(OUT_DIR / f"capability-preview-{name}.png"), full_page=True)
                    finally:
                        await page.close()
        finally:
            await browser.close()

    if blocked_execution_requests:
        raise AssertionError(f"synthetic preview attempted live execution requests: {blocked_execution_requests}")
    report["live_execution_requests"] = 0
    report["status"] = "PASS"
    (OUT_DIR / "capability-presentation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
