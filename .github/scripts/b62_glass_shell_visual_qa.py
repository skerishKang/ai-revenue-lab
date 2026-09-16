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

VARIANTS = ("female", "male")


async def _shell_state(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """
        () => {
          const root = document.documentElement;
          const style = getComputedStyle(root);
          const frags = [...document.querySelectorAll('.glass-shell-frag')];
          const opacities = frags.map((f) => parseFloat(getComputedStyle(f).opacity) || 0);
          const portal = document.querySelector('.glass-shell-portrait');
          const portalStyle = portal ? getComputedStyle(portal) : null;
          const shell = window.__padiemGlassShell || {};
          return {
            theme: root.getAttribute('data-theme'),
            variant: root.getAttribute('data-glass-variant'),
            mask: root.getAttribute('data-glass-mask'),
            speed: root.getAttribute('data-glass-speed'),
            ptr: parseFloat(style.getPropertyValue('--glass-pointer-reveal')) || 0,
            ans: parseFloat(style.getPropertyValue('--glass-answer-reveal')) || 0,
            dissolve: parseFloat(style.getPropertyValue('--glass-shell-dissolve')) || 0,
            progress: shell.progress ? shell.progress() : -1,
            fragCount: frags.length,
            fragVisible: opacities.filter((o) => o > 0.08).length,
            fragMaxOpacity: opacities.length ? Math.max(...opacities) : 0,
            portalPresent: Boolean(portal),
            portalOpacity: portalStyle ? parseFloat(portalStyle.opacity) || 0 : 0,
            portalImage: portalStyle ? portalStyle.backgroundImage : '',
            portalDisplay: portalStyle ? portalStyle.display : '',
          };
        }
        """
    )


async def _wait_progress_at_least(page: Page, value: float, name: str, timeout: float = 12_000) -> None:
    try:
        await page.wait_for_function(
            "v => window.__padiemGlassShell && window.__padiemGlassShell.progress() >= v",
            arg=value,
            timeout=timeout,
            polling=200,
        )
    except Exception as exc:
        state = await _shell_state(page)
        raise AssertionError(f"{name}: progress never reached {value}: {state}") from exc


async def _wait_progress_below(page: Page, value: float, name: str, timeout: float = 15_000) -> None:
    try:
        await page.wait_for_function(
            "v => window.__padiemGlassShell && window.__padiemGlassShell.progress() <= v",
            arg=value,
            timeout=timeout,
            polling=200,
        )
    except Exception as exc:
        state = await _shell_state(page)
        raise AssertionError(f"{name}: progress never fell below {value}: {state}") from exc


async def _goto_glass(page: Page, *, variant: str, extra: str = "") -> None:
    await page.goto(
        f"{BASE_URL}/?theme=padiem-glass&glass={variant}{extra}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.locator("#messageInput").wait_for(state="visible", timeout=15_000)
    await page.wait_for_timeout(700)


async def _hover_portrait(page: Page) -> None:
    viewport = page.viewport_size
    assert viewport is not None
    await page.mouse.move(viewport["width"] - 90, int(viewport["height"] * 0.42))
    await page.mouse.move(viewport["width"] - 70, int(viewport["height"] * 0.44))


async def _send_answer_turn(page: Page, tag: str) -> None:
    expected = await page.locator("#messageList .assistant-message").count() + 1
    await page.locator("#messageInput").fill(f"Glass shell QA {tag}")
    # DOM click avoids moving the pointer into the portrait proximity zone,
    # keeping the answer-only driver isolated.
    await page.evaluate("document.getElementById('sendButton').click()")
    await page.wait_for_function(
        "expected => document.querySelectorAll('#messageList .assistant-message').length >= expected",
        arg=expected,
        timeout=15_000,
    )


async def _assert_no_horizontal_overflow(page: Page, name: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(
            f"horizontal overflow at {name}: scrollWidth={scroll_width}, innerWidth={inner_width}"
        )


async def _check_variant(page: Page, variant: str) -> dict[str, Any]:
    name = f"glass-shell-{variant}"
    await _goto_glass(page, variant=variant, extra="&mask=auto")

    # idle: clean portrait only — no fragments, no shell dissolve
    idle = await _shell_state(page)
    if idle["fragCount"] != 20:
        raise AssertionError(f"{name}: expected 20 shell fragments, got {idle['fragCount']}")
    if not idle["portalPresent"]:
        raise AssertionError(f"{name}: shell portal layer missing")
    if f"padiem-glass-{variant}-shell.jpg" not in idle["portalImage"]:
        raise AssertionError(f"{name}: portal is not the {variant} shell asset: {idle['portalImage']}")
    if idle["fragVisible"] > 0 or idle["dissolve"] > 0:
        raise AssertionError(f"{name}: idle state must stay clean: {idle}")

    # pointer-only: fragment assembly becomes visible, portal not yet swapped
    await _hover_portrait(page)
    await _wait_progress_at_least(page, 0.45, f"{name}-pointer")
    pointer_only = await _shell_state(page)
    if pointer_only["ptr"] <= 0.4:
        raise AssertionError(f"{name}: pointer driver did not engage: {pointer_only}")
    if pointer_only["fragVisible"] < 8:
        raise AssertionError(f"{name}: pointer hover did not assemble shell fragments: {pointer_only}")
    await page.screenshot(path=str(OUT_DIR / f"{name}-pointer.png"), full_page=False)

    # leave portrait: recovery must be cinematic — state persists briefly,
    # then falls back to clean rather than snapping off
    peak = pointer_only["progress"]
    await page.mouse.move(70, 90)
    await page.wait_for_timeout(250)
    mid = await _shell_state(page)
    if mid["progress"] < peak * 0.35:
        raise AssertionError(
            f"{name}: recovery snapped off instead of cinematic decay: peak={peak}, mid={mid}"
        )
    await _wait_progress_below(page, 0.05, f"{name}-recover")
    recovered = await _shell_state(page)
    if recovered["fragVisible"] > 2 or recovered["dissolve"] > 0.05:
        raise AssertionError(f"{name}: shell did not recover to clean after pointer exit: {recovered}")

    # answer-only: assistant activity must drive shell progression.
    # Proof = progress rises with pointer driver at zero; fragment opacity
    # lags progress (assemble×local double easing) so assert its motion start.
    await _send_answer_turn(page, f"{variant}-answer")
    await _wait_progress_at_least(page, 0.35, f"{name}-answer")
    answer_only = await _shell_state(page)
    if answer_only["ptr"] > 0.1:
        raise AssertionError(f"{name}: answer-only phase polluted by pointer: {answer_only}")
    if answer_only["ans"] <= 0.05:
        raise AssertionError(f"{name}: answer driver did not engage: {answer_only}")
    if answer_only["fragMaxOpacity"] <= 0.02:
        raise AssertionError(f"{name}: answer activity did not move shell fragments: {answer_only}")

    # pointer + answer together: strictly stronger — dissolve portal engages.
    # The answer envelope decays (~1.8s), so send a fresh turn while hovering.
    await _hover_portrait(page)
    await _send_answer_turn(page, f"{variant}-combined")
    try:
        await page.wait_for_function(
            "parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--glass-shell-dissolve')) > 0.05",
            timeout=10_000,
            polling=100,
        )
    except Exception as exc:
        state = await _shell_state(page)
        raise AssertionError(f"{name}: pointer+answer never reached dissolve: {state}") from exc
    combined = await _shell_state(page)
    if combined["portalOpacity"] <= 0.02:
        raise AssertionError(f"{name}: completed shell portrait not visible: {combined}")
    await page.screenshot(path=str(OUT_DIR / f"{name}-combined.png"), full_page=False)

    await _assert_no_horizontal_overflow(page, name)
    return {
        "idle": idle,
        "pointer_only": pointer_only,
        "answer_only": answer_only,
        "combined": combined,
        "recovered": recovered,
    }


async def _check_mask_modes(page: Page) -> dict[str, Any]:
    # mask=on: shell portrait fully revealed without interaction
    await _goto_glass(page, variant="female", extra="&mask=on")
    await _wait_progress_at_least(page, 0.95, "mask-on", timeout=15_000)
    on_state = await _shell_state(page)
    if on_state["portalOpacity"] <= 0.5:
        raise AssertionError(f"mask=on did not reveal the shell portrait: {on_state}")
    await page.screenshot(path=str(OUT_DIR / "glass-shell-mask-on.png"), full_page=False)

    # mask=off: no fragments even under direct pointer
    await _goto_glass(page, variant="female", extra="&mask=off")
    await _hover_portrait(page)
    await page.wait_for_timeout(900)
    off_state = await _shell_state(page)
    if off_state["fragVisible"] > 0 or off_state["dissolve"] > 0 or off_state["portalOpacity"] > 0:
        raise AssertionError(f"mask=off must suppress the shell layer entirely: {off_state}")

    return {"mask_on": on_state, "mask_off": off_state}


async def _check_controls(page: Page) -> dict[str, Any]:
    await _goto_glass(page, variant="female")
    settings = page.locator("#settingsButton")
    if await settings.count() == 0:
        raise AssertionError("settings button missing")
    await settings.click()
    await page.wait_for_timeout(300)

    control = page.locator(".glass-shell-control")
    if not await control.is_visible():
        raise AssertionError("glass shell control not visible in appearance settings")
    for value in ("auto", "on", "off"):
        if await page.locator(f'[data-glass-mask-value="{value}"]').count() != 1:
            raise AssertionError(f"mask mode button missing: {value}")
    speed = page.locator(".glass-speed-range")
    if await speed.count() != 1:
        raise AssertionError("motion speed slider missing")

    await page.locator('[data-glass-mask-value="on"]').click()
    await page.wait_for_timeout(200)
    if await page.locator("html").get_attribute("data-glass-mask") != "on":
        raise AssertionError("mask mode click did not set data-glass-mask=on")
    url = page.url
    if "mask=on" not in url:
        raise AssertionError(f"mask mode is not URL-authoritative: {url}")

    await speed.evaluate("(el) => { el.value = '220'; el.dispatchEvent(new Event('input', {bubbles: true})); }")
    await page.wait_for_timeout(200)
    if await page.locator("html").get_attribute("data-glass-speed") != "220":
        raise AssertionError("speed slider did not set data-glass-speed=220")
    label = await page.locator(".glass-speed-value").text_content()
    if not label or "2.2" not in label:
        raise AssertionError(f"speed value label did not update: {label!r}")

    await page.locator('[data-glass-mask-value="auto"]').click()
    await page.wait_for_timeout(200)
    if await page.locator("html").get_attribute("data-glass-mask") != "auto":
        raise AssertionError("mask mode did not return to auto")
    await page.keyboard.press("Escape")
    await page.evaluate("document.querySelector('.settings-dialog')?.close?.()")
    return {"controls": "ok", "mask_url": url, "speed_label": label}


async def _check_reduced_motion(browser: Any) -> dict[str, Any]:
    ctx = await browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = await ctx.new_page()
    await _goto_glass(page, variant="female", extra="&mask=on")
    await page.wait_for_timeout(900)
    state = await _shell_state(page)
    await ctx.close()
    if state["portalOpacity"] <= 0.3:
        raise AssertionError(f"reduced-motion mask=on must show a static shell portrait: {state}")
    if state["fragVisible"] > 2:
        raise AssertionError(f"reduced-motion must not animate fragments: {state}")
    return {"reduced_motion": state}


async def _check_touch(browser: Any) -> dict[str, Any]:
    ctx = await browser.new_context(
        viewport={"width": 390, "height": 844},
        has_touch=True,
        is_mobile=True,
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    )
    page = await ctx.new_page()
    await _goto_glass(page, variant="female")
    await page.touchscreen.tap(300, 300)
    await page.wait_for_timeout(700)
    state = await _shell_state(page)
    await ctx.close()
    # Touch must never synthesize a hover driver. Answer-activity progression
    # is genuine product behavior (not synthetic hover) and stays allowed.
    if state["ptr"] != 0:
        raise AssertionError(f"touch synthesized pointer hover: {state}")
    return {"touch": state}


async def main() -> None:
    report: dict[str, Any] = {"base_url": BASE_URL, "views": {}}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 1600, "height": 1000})
        for variant in VARIANTS:
            report["views"][f"variant-{variant}"] = await _check_variant(page, variant)
        report["views"]["mask-modes"] = await _check_mask_modes(page)
        report["views"]["controls"] = await _check_controls(page)
        await page.close()
        report["views"]["reduced-motion"] = await _check_reduced_motion(browser)
        report["views"]["touch"] = await _check_touch(browser)
        await browser.close()

    out = OUT_DIR / "glass-shell-report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"B62 Glass shell visual QA: PASS -> {out}")


if __name__ == "__main__":
    asyncio.run(main())
