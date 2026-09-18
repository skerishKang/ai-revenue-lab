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
          const imageRect = shell.imageRect ? shell.imageRect() : null;
          const fragRects = frags.map((f) => f.getBoundingClientRect());
          const visibleRects = fragRects.filter((_, i) => opacities[i] > 0.08);
          const imageArea = imageRect ? imageRect.width * imageRect.height : 0;
          return {
            theme: root.getAttribute('data-theme'),
            variant: root.getAttribute('data-glass-variant'),
            mask: root.getAttribute('data-glass-mask'),
            speed: root.getAttribute('data-glass-speed'),
            ptr: parseFloat(style.getPropertyValue('--glass-pointer-reveal')) || 0,
            ans: parseFloat(style.getPropertyValue('--glass-answer-reveal')) || 0,
            pointerX: style.getPropertyValue('--glass-pointer-x').trim(),
            pointerY: style.getPropertyValue('--glass-pointer-y').trim(),
            dissolve: parseFloat(style.getPropertyValue('--glass-shell-dissolve')) || 0,
            progress: shell.progress ? shell.progress() : -1,
            target: shell.target ? shell.target() : -1,
            fragCount: frags.length,
            fragVisible: opacities.filter((o) => o > 0.08).length,
            fragMaxOpacity: opacities.length ? Math.max(...opacities) : 0,
            fragMaxHeightRatio: imageRect && visibleRects.length
              ? Math.max(...visibleRects.map((r) => r.height / imageRect.height))
              : 0,
            fragMaxAreaRatio: imageArea > 0 && visibleRects.length
              ? Math.max(...visibleRects.map((r) => (r.width * r.height) / imageArea))
              : 0,
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


async def _wait_completed_shell(
    page: Page,
    name: str,
    *,
    min_portal_opacity: float = 0.80,
    timeout: float = 12_000,
) -> None:
    """Wait for the reverse shell to finish visually, not just numerically.

    Progress reaches .95 before the fragment dissolve has completed.  The
    product contract is the completed portal with no fragment plates left
    hanging over the portrait, so certify that rendered state directly.
    """
    try:
        await page.wait_for_function(
            """minPortal => {
              const shell = window.__padiemGlassShell;
              if (!shell || shell.progress() < .99) return false;
              const frags = [...document.querySelectorAll('.glass-shell-frag')];
              const maxOpacity = frags.length
                ? Math.max(...frags.map((el) => parseFloat(getComputedStyle(el).opacity) || 0))
                : 0;
              const portal = document.querySelector('.glass-shell-portrait');
              const portalOpacity = portal ? (parseFloat(getComputedStyle(portal).opacity) || 0) : 0;
              return maxOpacity <= .05 && portalOpacity >= minPortal;
            }""",
            arg=min_portal_opacity,
            timeout=timeout,
            polling=100,
        )
    except Exception as exc:
        state = await _shell_state(page)
        raise AssertionError(f"{name}: completed shell visual state never settled: {state}") from exc


async def _goto_glass(page: Page, *, variant: str, extra: str = "") -> None:
    await page.goto(
        f"{BASE_URL}/?theme=padiem-glass&glass={variant}{extra}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.locator("#messageInput").wait_for(state="visible", timeout=15_000)
    await page.wait_for_timeout(700)


async def _hover_portrait(page: Page) -> None:
    field = page.locator(".glass-shell-field")
    await field.wait_for(state="attached", timeout=5_000)
    box = await field.bounding_box()
    if not box:
        raise AssertionError("Glass shell field has no live bounding box")
    # Enter the actual portrait field, not a viewport approximation.
    await page.mouse.move(box["x"] + box["width"] * 0.55, box["y"] + box["height"] * 0.42)
    await page.mouse.move(box["x"] + box["width"] * 0.82, box["y"] + box["height"] * 0.44)


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

    # Reverse contract: Auto rests on the completed shell portrait.
    await _wait_completed_shell(page, f"{name}-idle")
    idle = await _shell_state(page)
    if idle["fragCount"] != 20:
        raise AssertionError(f"{name}: expected 20 shell fragments, got {idle['fragCount']}")
    if not idle["portalPresent"]:
        raise AssertionError(f"{name}: shell portal layer missing")
    if f"padiem-glass-{variant}-shell.jpg" not in idle["portalImage"]:
        raise AssertionError(f"{name}: portal is not the {variant} shell asset: {idle['portalImage']}")
    if idle["portalOpacity"] < 0.80 or idle["fragVisible"] > 0:
        raise AssertionError(f"{name}: reverse idle must show the completed shell: {idle}")

    # Pointer-only: hover is a binary state transition, not an X-axis scrub.
    # Enter near the LEFT side of the actual image, sample the slow transition,
    # then move to the RIGHT side and require the same target with monotonic
    # time-driven progress.
    shell_rect = await page.evaluate(
        "() => window.__padiemGlassShell && window.__padiemGlassShell.imageRect && window.__padiemGlassShell.imageRect()"
    )
    if not shell_rect:
        raise AssertionError(f"{name}: missing live portrait image rect")
    y = shell_rect["top"] + shell_rect["height"] * 0.44
    peel_started = await page.evaluate("performance.now()")
    await page.mouse.move(shell_rect["left"] + shell_rect["width"] * 0.18, y)
    await page.wait_for_timeout(260)
    left_transition = await _shell_state(page)
    if left_transition["ptr"] < 0.99 or left_transition["target"] > 0.01:
        raise AssertionError(f"{name}: left-edge hover did not latch binary peel target: {left_transition}")
    if left_transition["progress"] < 0.78:
        raise AssertionError(f"{name}: shell teardown is too fast at 260ms: {left_transition}")
    if left_transition["portalOpacity"] < 0.55:
        raise AssertionError(f"{name}: shell portal faded too early at 260ms: {left_transition}")
    if left_transition["fragMaxHeightRatio"] > 0.075 or left_transition["fragMaxAreaRatio"] > 0.075:
        raise AssertionError(f"{name}: transition contains oversized mosaic fragments: {left_transition}")
    if left_transition["pointerX"] not in {"", "0px", "0.0px"} or left_transition["pointerY"] not in {"", "0px", "0.0px"}:
        raise AssertionError(f"{name}: hover must not parallax the portrait: {left_transition}")

    await page.screenshot(path=str(OUT_DIR / f"{name}-pointer-transition.png"), full_page=False)
    await page.mouse.move(shell_rect["left"] + shell_rect["width"] * 0.82, y)
    await page.wait_for_timeout(650)
    right_transition = await _shell_state(page)
    if right_transition["ptr"] < 0.99 or right_transition["target"] > 0.01:
        raise AssertionError(f"{name}: right-edge hover changed the binary peel target: {right_transition}")
    if right_transition["progress"] > left_transition["progress"] + 0.02:
        raise AssertionError(
            f"{name}: horizontal motion scrubbed/reversed time progress: left={left_transition}, right={right_transition}"
        )
    if right_transition["progress"] >= left_transition["progress"] - 0.10:
        raise AssertionError(
            f"{name}: timed peel did not continue while moving horizontally: left={left_transition}, right={right_transition}"
        )
    if not 0.45 <= right_transition["progress"] <= 0.80:
        raise AssertionError(f"{name}: ~900ms sample is not a visible mid-transition state: {right_transition}")
    if right_transition["fragMaxHeightRatio"] > 0.075 or right_transition["fragMaxAreaRatio"] > 0.075:
        raise AssertionError(f"{name}: mid transition contains oversized mosaic fragments: {right_transition}")
    await page.screenshot(path=str(OUT_DIR / f"{name}-pointer-transition-mid.png"), full_page=False)

    await _wait_progress_below(page, 0.05, f"{name}-pointer")
    peel_elapsed_ms = await page.evaluate("started => performance.now() - started", peel_started)
    if not 1_800 <= peel_elapsed_ms <= 3_600:
        raise AssertionError(f"{name}: 1x peel must settle in about 2–3s, got {peel_elapsed_ms:.0f}ms")
    pointer_only = await _shell_state(page)
    if pointer_only["ptr"] <= 0.8:
        raise AssertionError(f"{name}: pointer driver did not fully engage: {pointer_only}")
    if pointer_only["progress"] > 0.08:
        raise AssertionError(f"{name}: portrait hover did not reach clean end-state: {pointer_only}")
    if pointer_only["fragVisible"] > 0 or pointer_only["fragMaxOpacity"] > 0.05:
        raise AssertionError(f"{name}: hover left mosaic fragments over the clean portrait: {pointer_only}")
    if pointer_only["portalOpacity"] > 0.05:
        raise AssertionError(f"{name}: completed shell portal remained visible during clean hover: {pointer_only}")
    await page.screenshot(path=str(OUT_DIR / f"{name}-pointer.png"), full_page=False)

    # Pointer exit reassembles rather than snapping: it must travel back to the
    # completed portal and leave no fragment plates hanging over the face.
    peeled = pointer_only["progress"]
    recover_started = await page.evaluate("performance.now()")
    await page.mouse.move(70, 90)
    await page.wait_for_timeout(250)
    mid = await _shell_state(page)
    if mid["progress"] <= peeled:
        raise AssertionError(
            f"{name}: reverse recovery did not begin after pointer exit: peeled={peeled}, mid={mid}"
        )
    await _wait_completed_shell(page, f"{name}-recover")
    recover_elapsed_ms = await page.evaluate("started => performance.now() - started", recover_started)
    if not 1_600 <= recover_elapsed_ms <= 3_600:
        raise AssertionError(f"{name}: 1x reassembly must settle slowly, got {recover_elapsed_ms:.0f}ms")
    recovered = await _shell_state(page)
    if recovered["portalOpacity"] < 0.80 or recovered["fragVisible"] > 0:
        raise AssertionError(f"{name}: shell did not reassemble after pointer exit: {recovered}")
    await page.screenshot(path=str(OUT_DIR / f"{name}-recovered.png"), full_page=False)

    # Repeat the same contract RIGHT -> LEFT. Pointer X may change where the
    # cursor is, but must never scrub, reverse, or retarget the timed peel.
    await page.mouse.move(shell_rect["left"] + shell_rect["width"] * 0.82, y)
    await page.wait_for_timeout(260)
    reverse_right = await _shell_state(page)
    if reverse_right["ptr"] < 0.99 or reverse_right["target"] > 0.01:
        raise AssertionError(f"{name}: right-edge reverse sweep did not latch binary peel target: {reverse_right}")
    if reverse_right["progress"] < 0.40:
        raise AssertionError(f"{name}: reverse-direction teardown is too fast at 1x: {reverse_right}")
    if reverse_right["portalOpacity"] < 0.55:
        raise AssertionError(f"{name}: reverse-direction shell portal faded too early at 260ms: {reverse_right}")
    if reverse_right["fragMaxHeightRatio"] > 0.075 or reverse_right["fragMaxAreaRatio"] > 0.075:
        raise AssertionError(f"{name}: reverse transition contains oversized mosaic fragments: {reverse_right}")
    await page.screenshot(path=str(OUT_DIR / f"{name}-pointer-transition-reverse.png"), full_page=False)

    await page.mouse.move(shell_rect["left"] + shell_rect["width"] * 0.18, y)
    await page.wait_for_timeout(260)
    reverse_left = await _shell_state(page)
    if reverse_left["ptr"] < 0.99 or reverse_left["target"] > 0.01:
        raise AssertionError(f"{name}: left-edge reverse sweep changed the binary peel target: {reverse_left}")
    if reverse_left["progress"] > reverse_right["progress"] + 0.02:
        raise AssertionError(
            f"{name}: right-to-left motion scrubbed/reversed time progress: right={reverse_right}, left={reverse_left}"
        )
    if reverse_left["pointerX"] not in {"", "0px", "0.0px"} or reverse_left["pointerY"] not in {"", "0px", "0.0px"}:
        raise AssertionError(f"{name}: reverse sweep must not parallax the portrait: {reverse_left}")

    await _wait_progress_below(page, 0.05, f"{name}-pointer-reverse")
    reverse_clean = await _shell_state(page)
    if reverse_clean["fragVisible"] > 0 or reverse_clean["portalOpacity"] > 0.05:
        raise AssertionError(f"{name}: reverse sweep did not settle on the clean portrait: {reverse_clean}")
    await page.mouse.move(70, 90)
    await _wait_completed_shell(page, f"{name}-reverse-recover")
    reverse_recovered = await _shell_state(page)

    # Answer-only remains visually stable: answer activity may drive the
    # atmospheric portrait motion, but it must not peel the shell by itself.
    await page.mouse.move(70, 90)
    await _send_answer_turn(page, f"{variant}-answer")
    await page.wait_for_function(
        "() => (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--glass-answer-reveal')) || 0) > .05",
        timeout=5_000,
    )
    answer_only = await _shell_state(page)
    if answer_only["ptr"] > 0.1:
        raise AssertionError(f"{name}: answer-only phase polluted by pointer: {answer_only}")
    if answer_only["ans"] <= 0.05:
        raise AssertionError(f"{name}: answer driver did not engage: {answer_only}")
    if answer_only["progress"] < 0.90:
        raise AssertionError(f"{name}: answer activity peeled the shell without portrait hover: {answer_only}")
    if answer_only["portalOpacity"] < 0.35:
        raise AssertionError(f"{name}: reading shell lost its reduced-prominence portal: {answer_only}")

    # Pointer + answer: the answer pulse is shorter than the deliberate
    # 2–3 s peel. Prove the drivers overlap first, then prove pointer hover
    # alone carries the shell all the way to the clean end-state.
    await _hover_portrait(page)
    await _send_answer_turn(page, f"{variant}-combined")
    await page.wait_for_function(
        """() => {
          const style = getComputedStyle(document.documentElement);
          const pointer = parseFloat(style.getPropertyValue('--glass-pointer-reveal')) || 0;
          const answer = parseFloat(style.getPropertyValue('--glass-answer-reveal')) || 0;
          return pointer > .8 && answer > .05;
        }""",
        timeout=5_000,
    )
    combined_overlap = await _shell_state(page)
    if combined_overlap["ptr"] <= 0.8 or combined_overlap["ans"] <= 0.05:
        raise AssertionError(f"{name}: combined drivers never overlapped: {combined_overlap}")

    await _wait_progress_below(page, 0.05, f"{name}-combined")
    combined = await _shell_state(page)
    if combined["ptr"] <= 0.8:
        raise AssertionError(f"{name}: pointer did not remain authoritative through clean settle: {combined}")
    if combined["progress"] > 0.08:
        raise AssertionError(f"{name}: pointer did not fully peel shell during answer activity: {combined}")
    if combined["fragVisible"] > 0 or combined["fragMaxOpacity"] > 0.05 or combined["portalOpacity"] > 0.05:
        raise AssertionError(f"{name}: combined hover did not settle on clean portrait: {combined}")
    await page.screenshot(path=str(OUT_DIR / f"{name}-combined.png"), full_page=False)

    await page.mouse.move(70, 90)
    await _wait_completed_shell(
        page,
        f"{name}-final-recover",
        min_portal_opacity=0.35,
    )
    final_recovered = await _shell_state(page)
    if final_recovered["fragVisible"] > 0:
        raise AssertionError(f"{name}: final shell recovery left fragment plates visible: {final_recovered}")

    await _assert_no_horizontal_overflow(page, name)
    return {
        "idle": idle,
        "pointer_only": pointer_only,
        "peel_elapsed_ms": peel_elapsed_ms,
        "recover_elapsed_ms": recover_elapsed_ms,
        "answer_only": answer_only,
        "combined_overlap": combined_overlap,
        "combined": combined,
        "recovered": recovered,
        "reverse_right": reverse_right,
        "reverse_left": reverse_left,
        "reverse_clean": reverse_clean,
        "reverse_recovered": reverse_recovered,
        "final_recovered": final_recovered,
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
    # Touch must never synthesize a hover driver. Auto therefore remains in
    # its completed-shell resting state unless the explicit mask mode changes.
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
