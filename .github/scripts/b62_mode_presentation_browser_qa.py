from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

# #4743 derives tier availability from the server-verified member grade, so an
# anonymous page exposes only `free` by design (member_grade_access.py: missing
# membership evidence never grants a paid tier). This suite certifies the tier
# picker for a signed-in member — the case its assertions describe — exactly as
# the other B62 browser QA suites stub /api/auth/status. Before this stub the
# suite ran as a guest and asserted `plus` was selectable, so it failed on every
# run after #4743 even though the page was behaving as designed.
MEMBER_GRADE = os.environ.get("B62_MODE_QA_MEMBER_GRADE", "plus")
TIER_VALUES = ("free", "plus", "pro", "max")
# PADIEM Custom is a customer-key lane, not a fifth tier. The fixture uses
# synthetic provider ids so the presentation QA stays provider-neutral.
CUSTOM_PROVIDER_FIXTURE = {
    "ok": True,
    "credentials": [],
    "providers": [
        {
            "provider": "qa-custom-provider",
            "model": "qa-custom-provider/qa-model",
            "display_name": "PADIEM Custom (QA)",
        }
    ],
}


async def _stub_member_session(page: Page) -> list[str]:
    async def auth_status(route: Route) -> None:
        await route.fulfill(
            status=200,
            content_type="application/json; charset=utf-8",
            body=json.dumps(
                {
                    "ready": True,
                    "authenticated": True,
                    "history_ready": True,
                    "project_files_ready": False,
                    "session_state": "signed_in",
                    "member_grade": MEMBER_GRADE,
                    "user": {
                        "id": "usr_mode_presentation_fixture",
                        "email": "mode-presentation@example.test",
                        "name": "Mode Presentation QA",
                        "picture": "",
                    },
                },
                ensure_ascii=False,
            ),
        )

    custom_methods: list[str] = []

    async def custom_credential(route: Route) -> None:
        custom_methods.append(route.request.method)
        await route.fulfill(
            status=200,
            content_type="application/json; charset=utf-8",
            body=json.dumps(CUSTOM_PROVIDER_FIXTURE, ensure_ascii=False),
        )

    await page.route("**/api/auth/status", auth_status)
    await page.route("**/api/chat/custom/credential", custom_credential)
    return custom_methods


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


async def _wait_custom_state(page: Page, *, name: str, expected: str) -> None:
    # Auth refresh and panel open can both request the credential status, so the
    # card briefly re-enters the loading state. Wait for the rendered state to
    # stay settled instead of sampling a single transient paint.
    deadline = asyncio.get_running_loop().time() + 8
    stable_since: float | None = None
    while asyncio.get_running_loop().time() < deadline:
        current = await page.evaluate(
            "() => document.querySelector('[data-mode-value=\"custom\"] .mode-option-state')"
            "?.textContent?.trim() || ''"
        )
        now = asyncio.get_running_loop().time()
        if current == expected:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= 0.3:
                return
        else:
            stable_since = None
        await asyncio.sleep(0.05)
    raise AssertionError(f"PADIEM Custom state did not settle to {expected!r} at {name}")


async def _exercise(page: Page, *, name: str, custom_methods: list[str]) -> dict[str, Any]:
    pill = page.locator(".model-pill")
    await pill.wait_for(state="visible")
    await page.wait_for_function(
        "() => document.querySelector('.model-pill span:last-child')?.textContent === 'Padiem Free'"
    )

    if await pill.get_attribute("role") != "button":
        raise AssertionError(f"tier pill is not keyboard-operable at {name}")
    if await pill.get_attribute("aria-haspopup") != "dialog":
        raise AssertionError(f"tier pill does not advertise dialog at {name}")

    await pill.focus()
    await page.keyboard.press("Enter")
    panel = page.locator("#modePresentationPanel")
    await panel.wait_for(state="visible")

    tiers = panel.locator(".mode-option-list [data-mode-value]")
    if await tiers.count() != 4:
        raise AssertionError(f"expected four tier rows (free/plus/pro/max) at {name}")
    tier_values = await tiers.evaluate_all("els => els.map(el => el.dataset.modeValue)")
    if tier_values != list(TIER_VALUES):
        raise AssertionError(f"PADIEM tier rows changed at {name}: {tier_values!r}")

    custom_section = panel.locator("section.mode-custom-section")
    if await custom_section.count() != 1:
        raise AssertionError(f"PADIEM Custom must be one independent section at {name}")
    custom_option = custom_section.locator('[data-mode-value="custom"]')
    if await custom_option.count() != 1:
        raise AssertionError(f"PADIEM Custom must expose exactly one option at {name}")
    if await panel.locator('.mode-option-list [data-mode-value="custom"]').count() != 0:
        raise AssertionError(f"PADIEM Custom must not join the PADIEM tier list at {name}")
    option_values = await panel.locator("[data-mode-value]").evaluate_all(
        "els => els.map(el => el.dataset.modeValue)"
    )
    if sorted(option_values) != sorted(tuple(TIER_VALUES) + ("custom",)):
        raise AssertionError(f"unexpected model-card rows at {name}: {option_values!r}")

    await _wait_custom_state(page, name=name, expected="키 필요")
    custom_title = (await custom_option.locator("strong").inner_text()).strip()
    if "PADIEM Custom" not in custom_title:
        raise AssertionError(f"PADIEM Custom label missing at {name}: {custom_title!r}")
    custom_state = (await custom_option.locator(".mode-option-state").inner_text()).strip()
    if custom_state != "키 필요":
        raise AssertionError(f"PADIEM Custom key-required state missing at {name}: {custom_state!r}")
    if await custom_option.is_disabled():
        raise AssertionError(f"PADIEM Custom must be selectable for a signed-in member at {name}")
    custom_form = custom_section.locator(".mode-custom-credential")
    if not await custom_form.is_visible():
        raise AssertionError(f"PADIEM Custom key form hidden at {name}")
    custom_input = custom_form.locator("#modeCustomApiKey")
    if await custom_input.get_attribute("type") != "password":
        raise AssertionError(f"PADIEM Custom key input must be masked at {name}")
    if await custom_input.input_value() != "":
        raise AssertionError(f"PADIEM Custom key input must stay empty at {name}")
    custom_status = (await custom_form.locator(".mode-custom-status").inner_text()).strip()
    if "등록된 키가 없습니다." not in custom_status:
        raise AssertionError(f"PADIEM Custom credential truth missing at {name}: {custom_status!r}")
    if await custom_form.locator(".mode-custom-delete").is_visible():
        raise AssertionError(f"PADIEM Custom delete must stay hidden without a key at {name}")

    free = panel.locator('[data-mode-value="free"]')
    if await free.is_disabled():
        raise AssertionError(f"Free must be selectable at {name}")
    if await free.get_attribute("aria-pressed") != "true":
        raise AssertionError(f"Free must be the default selected tier at {name}")
    plus = panel.locator('[data-mode-value="plus"]')
    if await plus.is_disabled():
        raise AssertionError(f"Plus must be selectable at {name}")

    for locked in ("pro", "max"):
        row = panel.locator(f'[data-mode-value="{locked}"]')
        if await row.is_disabled():
            raise AssertionError(f"{locked} must be clickable (업그레이드) at {name}")
        state_text = (await row.locator(".mode-option-state").inner_text()).strip()
        if "업그레이드" not in state_text:
            raise AssertionError(f"{locked} must show 업그레이드 at {name}: {state_text!r}")

    truth = (await panel.locator("[data-mode-truth]").inner_text()).strip()
    if "더 높은 등급의 모델을 사용하려면 업그레이드가 필요합니다." not in truth:
        raise AssertionError(f"server-authority truth copy missing at {name}: {truth!r}")

    plus_box = await plus.bounding_box()
    if not plus_box or plus_box["height"] < 44:
        raise AssertionError(f"Plus tier target too small at {name}: {plus_box}")

    await custom_option.click()
    if not await panel.is_visible():
        raise AssertionError(f"key-required PADIEM Custom must keep the panel open at {name}")
    await page.wait_for_function("() => document.activeElement?.id === 'modeCustomApiKey'")
    pill_text = (await page.locator(".model-pill span:last-child").inner_text()).strip()
    if pill_text != "PADIEM Custom":
        raise AssertionError(f"PADIEM Custom selection not reflected on the pill at {name}: {pill_text!r}")

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
    if not custom_methods or any(method != "GET" for method in custom_methods):
        raise AssertionError(f"PADIEM Custom QA saw non-read credential traffic at {name}: {custom_methods!r}")
    return {
        "default_tier": "free",
        "selected_tier": "plus",
        "plus": "available",
        "pro": "upgrade",
        "max": "upgrade",
        "tier_rows": list(TIER_VALUES),
        "custom_section": "separate",
        "custom_state": "key_required",
        "custom_credential_methods": sorted(set(custom_methods)),
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
                        custom_methods = await _stub_member_session(page)
                        await page.goto(f"{BASE_URL}/{query}", wait_until="domcontentloaded", timeout=30_000)
                        await page.locator("#messageInput").wait_for(state="visible")
                        report["views"][name] = await _exercise(
                            page, name=name, custom_methods=custom_methods
                        )
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
            await _stub_member_session(page)
            await page.goto(f"{BASE_URL}/?theme=light&lang=en", wait_until="domcontentloaded", timeout=30_000)
            await page.locator("#messageInput").wait_for(state="visible")
            await page.wait_for_function(
                "() => document.querySelector('.model-pill span:last-child')?.textContent === 'Padiem Free'"
            )
            await page.locator(".model-pill").click()
            panel = page.locator("#modePresentationPanel")
            await panel.wait_for(state="visible")
            tiers = panel.locator(".mode-option-list [data-mode-value]")
            if await tiers.count() != 4:
                raise AssertionError("English tier panel must expose four tier rows")
            tier_values = await tiers.evaluate_all("els => els.map(el => el.dataset.modeValue)")
            if tier_values != list(TIER_VALUES):
                raise AssertionError(f"English tier rows changed: {tier_values!r}")
            custom_section = panel.locator("section.mode-custom-section")
            custom_option = custom_section.locator('[data-mode-value="custom"]')
            if await custom_section.count() != 1 or await custom_option.count() != 1:
                raise AssertionError("English panel must keep PADIEM Custom in one separate section")
            await _wait_custom_state(page, name="english", expected="Key required")
            custom_state = (await custom_option.locator(".mode-option-state").inner_text()).strip()
            if custom_state != "Key required":
                raise AssertionError(f"English PADIEM Custom state missing: {custom_state!r}")
            custom_heading = (await panel.locator("#modeCustomTitle").inner_text()).strip()
            if custom_heading != "My API key (PADIEM Custom)":
                raise AssertionError(f"English PADIEM Custom heading missing: {custom_heading!r}")
            if await panel.locator('[data-mode-value="pro"]').is_disabled():
                raise AssertionError("English tier panel must keep Pro disabled")
            pro_state = (await panel.locator('[data-mode-value="pro"] .mode-option-state').inner_text()).strip()
            if "Upgrade" not in pro_state:
                raise AssertionError(f"English tier panel must show Upgrade for Pro: {pro_state!r}")
            truth = (await panel.locator("[data-mode-truth]").inner_text()).strip()
            if "Upgrade is required to use higher-tier models." not in truth:
                raise AssertionError(f"English tier truth copy missing: {truth!r}")
            return {"locale": "en", "default_tier": "free", "status": "PASS"}
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
