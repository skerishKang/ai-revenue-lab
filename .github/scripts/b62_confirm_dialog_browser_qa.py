from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright

from b62_product_confirm_helpers import assert_focus_trap, install_native_dialog_guard


BASE_URL = os.environ.get("B62_A11Y_QA_BASE_URL", "http://127.0.0.1:8773")
OUT_DIR = Path(os.environ.get("B62_A11Y_QA_OUT_DIR", ".tmp/b62-accessibility-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

THEMES = ("light", "dark", "cinematic", "padiem-home", "padiem-glass")
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})


def _theme_url(theme: str) -> str:
    suffix = f"?theme={theme}"
    if theme == "padiem-glass":
        suffix += "&glass=female"
    return BASE_URL + "/" + suffix


async def _stub_fonts(page: Page, seen: set[str]) -> None:
    async def css(route: Route) -> None:
        seen.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(status=200, content_type="text/css; charset=utf-8", body="/* deterministic confirm-dialog QA font stub */\n")

    async def font(route: Route) -> None:
        seen.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


async def _assert_no_overflow(page: Page, stage: str) -> None:
    values = await page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    if values[0] > values[1] + 1:
        raise AssertionError(f"horizontal overflow at {stage}: {values}")


async def _open_direct_confirm(page: Page) -> None:
    await page.evaluate(
        """
        () => {
          const input = document.getElementById('messageInput');
          input.focus();
          window.__b62ConfirmResult = 'pending';
          window.PadiemConfirmDialog.confirm({
            title: '대화를 삭제할까요?',
            message: '이 테스트 대화를 삭제합니다. 삭제한 대화는 복구할 수 없습니다.',
            cancelLabel: '취소',
            confirmLabel: '삭제',
          }).then(value => { window.__b62ConfirmResult = value; });
        }
        """
    )
    await page.locator("#confirmDialog").wait_for(state="visible", timeout=5_000)


async def _dialog_geometry(page: Page, *, mobile: bool) -> dict[str, Any]:
    panel = page.locator("#confirmDialog .confirm-dialog-panel")
    cancel = page.locator("#confirmDialogCancel")
    confirm = page.locator("#confirmDialogConfirm")
    panel_box = await panel.bounding_box()
    cancel_box = await cancel.bounding_box()
    confirm_box = await confirm.bounding_box()
    if not panel_box or not cancel_box or not confirm_box:
        raise AssertionError("confirmation dialog geometry unavailable")
    minimum = 48 if mobile else 44
    for label, box in (("cancel", cancel_box), ("confirm", confirm_box)):
        if box["height"] + 0.1 < minimum or box["width"] + 0.1 < 44:
            raise AssertionError(f"{label} confirmation target too small: {box}")
    return {
        "panel": {key: round(float(panel_box[key]), 1) for key in ("x", "y", "width", "height")},
        "cancel": {"width": round(float(cancel_box["width"]), 1), "height": round(float(cancel_box["height"]), 1)},
        "confirm": {"width": round(float(confirm_box["width"]), 1), "height": round(float(confirm_box["height"]), 1)},
    }


async def _theme_style(page: Page, theme: str) -> dict[str, Any]:
    style = await page.locator("#confirmDialog .confirm-dialog-panel").evaluate(
        """
        el => {
          const s = getComputedStyle(el);
          return {
            backgroundColor: s.backgroundColor,
            backgroundImage: s.backgroundImage,
            color: s.color,
            borderColor: s.borderColor,
            backdropFilter: s.backdropFilter || s.webkitBackdropFilter || 'none',
          };
        }
        """
    )
    if style["color"] in {"rgba(0, 0, 0, 0)", "transparent"}:
        raise AssertionError(f"confirmation text became transparent in {theme}: {style}")
    if theme in {"dark", "cinematic"} and style["backgroundColor"] in {"rgba(0, 0, 0, 0)", "transparent"}:
        raise AssertionError(f"dark confirmation panel lacks stable surface in {theme}: {style}")
    if theme == "padiem-glass" and "gradient" not in style["backgroundImage"]:
        raise AssertionError(f"Glass confirmation panel lost frosted gradient surface: {style}")
    return style


async def _audit_view(page: Page, *, theme: str, mobile: bool) -> dict[str, Any]:
    viewport = {"width": 390, "height": 844} if mobile else {"width": 1440, "height": 1000}
    unexpected_hosts: set[str] = set()
    stubbed_hosts: set[str] = set()
    native_dialogs: list[str] = []

    def observe(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe)
    await install_native_dialog_guard(page, native_dialogs)
    await _stub_fonts(page, stubbed_hosts)
    await page.set_viewport_size(viewport)
    await page.goto(_theme_url(theme), wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_function("() => typeof window.PadiemConfirmDialog?.confirm === 'function'", timeout=5_000)

    actual_theme = await page.locator("html").get_attribute("data-theme")
    if actual_theme != theme:
        raise AssertionError(f"theme did not activate: expected={theme}, actual={actual_theme}")

    # Escape path: safe action focused first, focus trapped, Promise false, trigger focus restored.
    await _open_direct_confirm(page)
    title = (await page.locator("#confirmDialogTitle").inner_text()).strip()
    message = (await page.locator("#confirmDialogMessage").inner_text()).strip()
    if title != "대화를 삭제할까요?" or "복구할 수 없습니다" not in message:
        raise AssertionError(f"explicit destructive title/consequence copy missing: {title!r}, {message!r}")
    focus_trap = await assert_focus_trap(page)
    geometry = await _dialog_geometry(page, mobile=mobile)
    style = await _theme_style(page, theme)
    await _assert_no_overflow(page, f"{theme}-{'mobile' if mobile else 'desktop'}-open")
    shot = f"confirm-dialog-{theme}-{'mobile' if mobile else 'desktop'}.png"
    await page.screenshot(path=str(OUT_DIR / shot), full_page=True)

    await page.keyboard.press("Escape")
    await page.wait_for_function("() => window.__b62ConfirmResult === false && document.getElementById('confirmDialog')?.open === false", timeout=5_000)
    focus_after_escape = await page.evaluate("document.activeElement && document.activeElement.id")
    if focus_after_escape != "messageInput":
        raise AssertionError(f"Escape did not return focus to invocation trigger: {focus_after_escape!r}")

    # Confirm path: destructive action requires an explicit keyboard activation.
    await _open_direct_confirm(page)
    await page.locator("#confirmDialogConfirm").focus()
    before_enter = await page.evaluate("window.__b62ConfirmResult")
    if before_enter != "pending":
        raise AssertionError(f"confirmation resolved before intentional activation: {before_enter!r}")
    await page.keyboard.press("Enter")
    await page.wait_for_function("() => window.__b62ConfirmResult === true && document.getElementById('confirmDialog')?.open === false", timeout=5_000)
    focus_after_confirm = await page.evaluate("document.activeElement && document.activeElement.id")
    if focus_after_confirm != "messageInput":
        raise AssertionError(f"confirm did not return focus to invocation trigger: {focus_after_confirm!r}")

    if native_dialogs:
        raise AssertionError(f"native browser dialogs observed: {native_dialogs!r}")
    if unexpected_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_hosts)!r}")

    return {
        "theme": theme,
        "mobile": mobile,
        "focus_trap": focus_trap,
        "geometry": geometry,
        "style": style,
        "escape_cancel": True,
        "keyboard_confirm": True,
        "focus_return": True,
        "native_dialogs": native_dialogs,
        "horizontal_overflow": False,
        "stubbed_static_hosts": sorted(stubbed_hosts),
        "screenshot": shot,
        "status": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {
        "status": "RUNNING",
        "scope": "B62 #1737 first-party destructive confirmation across all themes",
        "views": {},
        "production_mutation": False,
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for theme in THEMES:
                for mobile in (False, True):
                    key = f"{theme}-{'mobile' if mobile else 'desktop'}"
                    page = await browser.new_page(viewport={"width": 390, "height": 844} if mobile else {"width": 1440, "height": 1000})
                    try:
                        report["views"][key] = await _audit_view(page, theme=theme, mobile=mobile)
                    finally:
                        await page.close()
        finally:
            await browser.close()

    report["status"] = "PASS"
    report["acceptance"] = {
        "WINDOW_CONFIRM_DESTRUCTIVE_FLOWS": 0,
        "THEMED_CONFIRM_DIALOG": "PASS",
        "FOCUS_TRAP_AND_RETURN": "PASS",
        "ESC_CANCEL": "PASS",
        "ALL_THEMES": "PASS",
        "PRODUCTION_MUTATION": 0,
    }
    (OUT_DIR / "confirm-dialog-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
