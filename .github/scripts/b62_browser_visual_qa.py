from __future__ import annotations

import asyncio
import hashlib
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


async def _assert_in_viewport(page: Page, selector: str) -> dict[str, float]:
    box = await page.locator(selector).bounding_box()
    if not box:
        raise AssertionError(f"{selector} has no visible bounding box")
    viewport = page.viewport_size
    assert viewport is not None
    if box["x"] < -1 or box["y"] < -1:
        raise AssertionError(f"{selector} starts outside viewport: {box}")
    if box["x"] + box["width"] > viewport["width"] + 1:
        raise AssertionError(f"{selector} overflows viewport width: {box}")
    if box["y"] + box["height"] > viewport["height"] + 1:
        raise AssertionError(f"{selector} overflows viewport height: {box}")
    return {key: round(float(value), 2) for key, value in box.items()}


async def _assert_error_clear_of_composer(page: Page, error_box) -> float:
    error_geometry = await error_box.bounding_box()
    composer_geometry = await page.locator("#composerForm").bounding_box()
    viewport = page.viewport_size
    if not error_geometry or not composer_geometry or viewport is None:
        raise AssertionError("error/composer geometry is unavailable")
    error_bottom = error_geometry["y"] + error_geometry["height"]
    if error_geometry["y"] < -1 or error_bottom > viewport["height"] + 1:
        raise AssertionError(
            f"error card is not fully visible in viewport: error={error_geometry}, viewport={viewport}"
        )
    clearance = composer_geometry["y"] - error_bottom
    if clearance < 8:
        raise AssertionError(
            f"error card is occluded by fixed composer: error={error_geometry}, composer={composer_geometry}, clearance={clearance}"
        )
    return round(float(clearance), 2)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _glass_reveal(page: Page) -> float:
    value = await page.evaluate(
        "() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--glass-reveal')) || 0"
    )
    return round(float(value), 3)


async def _glass_shell_snapshot(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """
        () => {
          const root = document.documentElement;
          const style = getComputedStyle(root);
          const portal = document.querySelector('.glass-shell-portrait');
          const field = document.querySelector('.glass-shell-field');
          const frags = [...document.querySelectorAll('.glass-shell-frag')];
          const fragmentOpacities = frags.map(el => parseFloat(getComputedStyle(el).opacity) || 0);
          const control = document.querySelector('.glass-shell-control');
          const fieldRect = field ? field.getBoundingClientRect() : null;
          return {
            mask: root.getAttribute('data-glass-mask'),
            speed: root.getAttribute('data-glass-speed'),
            progress: parseFloat(style.getPropertyValue('--glass-shell-progress')) || 0,
            dissolve: parseFloat(style.getPropertyValue('--glass-shell-dissolve')) || 0,
            pointerDriver: parseFloat(style.getPropertyValue('--glass-pointer-reveal')) || 0,
            answerDriver: parseFloat(style.getPropertyValue('--glass-answer-reveal')) || 0,
            portalOpacity: portal ? parseFloat(getComputedStyle(portal).opacity) || 0 : 0,
            fragmentCount: frags.length,
            visibleFragments: fragmentOpacities.filter(v => v > .05).length,
            maxFragmentOpacity: fragmentOpacities.length ? Math.max(...fragmentOpacities) : 0,
            fieldRect: fieldRect ? {
              x: fieldRect.x, y: fieldRect.y, width: fieldRect.width, height: fieldRect.height
            } : null,
            controls: {
              exists: Boolean(control),
              buttons: control ? [...control.querySelectorAll('[data-glass-mask-value]')].map(
                el => ({ value: el.getAttribute('data-glass-mask-value'), pressed: el.getAttribute('aria-pressed') })
              ) : [],
              speedValue: control?.querySelector('.glass-speed-value')?.textContent || '',
            },
          };
        }
        """
    )


async def _glass_motion_snapshot(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """
        () => {
          const root = document.documentElement;
          const rootStyle = getComputedStyle(root);
          const main = document.querySelector('.main-panel');
          const portrait = main ? getComputedStyle(main, '::before') : null;
          const bodyNoise = getComputedStyle(document.body, '::after');
          const conversation = document.querySelector('.conversation');
          const conversationStyle = conversation ? getComputedStyle(conversation) : null;
          return {
            mode: root.getAttribute('data-glass-mode'),
            reveal: parseFloat(rootStyle.getPropertyValue('--glass-reveal')) || 0,
            artX: rootStyle.getPropertyValue('--glass-art-x').trim(),
            artY: rootStyle.getPropertyValue('--glass-art-y').trim(),
            artScale: rootStyle.getPropertyValue('--glass-art-scale').trim(),
            pointerX: rootStyle.getPropertyValue('--glass-pointer-x').trim(),
            pointerY: rootStyle.getPropertyValue('--glass-pointer-y').trim(),
            maskStart: rootStyle.getPropertyValue('--glass-mask-start').trim(),
            maskFull: rootStyle.getPropertyValue('--glass-mask-full').trim(),
            portraitOpacity: portrait ? parseFloat(portrait.opacity) : 0,
            portraitTransform: portrait ? portrait.transform : '',
            bodyNoiseOpacity: parseFloat(bodyNoise.opacity) || 0,
            conversationBackground: conversationStyle ? conversationStyle.backgroundImage : '',
          };
        }
        """
    )


async def _assert_glass_portrait_image_loaded(page: Page, *, variant: str) -> dict[str, Any]:
    image = await page.locator(".main-panel").evaluate(
        """
        async (el) => {
          const style = getComputedStyle(el, '::before');
          const backgroundImage = style.backgroundImage || '';
          const match = backgroundImage.match(/url\\([\"']?(.*?)[\"']?\\)/);
          if (!match) throw new Error(`portrait background URL missing: ${backgroundImage}`);
          const url = match[1];
          const response = await fetch(url, { cache: 'no-store' });
          if (!response.ok) throw new Error(`portrait request failed: ${response.status} ${url}`);
          const blob = await response.blob();
          const objectUrl = URL.createObjectURL(blob);
          const img = new Image();
          try {
            img.src = objectUrl;
            await img.decode();
            return {
              backgroundImage,
              url,
              status: response.status,
              contentType: response.headers.get('content-type') || '',
              bytes: blob.size,
              naturalWidth: img.naturalWidth,
              naturalHeight: img.naturalHeight,
              opacity: style.opacity,
              width: style.width,
              zIndex: style.zIndex,
              maskImage: style.maskImage,
              transform: style.transform,
            };
          } finally {
            URL.revokeObjectURL(objectUrl);
          }
        }
        """
    )
    if image["naturalWidth"] <= 0 or image["naturalHeight"] <= 0 or image["bytes"] <= 1000:
        raise AssertionError(f"Padiem Glass portrait did not decode: {image}")
    expected_name = f"padiem-glass-{variant}.jpg"
    if expected_name not in image["url"]:
        raise AssertionError(f"Padiem Glass portrait URL mismatch: expected={expected_name}, actual={image['url']}")
    if image["zIndex"] != "1":
        raise AssertionError(f"Padiem Glass portrait must render above shell background: {image['zIndex']}")
    return image


async def _assert_glass_shell_image_loaded(page: Page, *, variant: str) -> dict[str, Any]:
    await page.locator(".glass-shell-portrait").wait_for(state="attached", timeout=5_000)
    image = await page.locator(".glass-shell-portrait").evaluate(
        """
        async (el) => {
          const style = getComputedStyle(el);
          const backgroundImage = style.backgroundImage || '';
          const match = backgroundImage.match(/url\\(["']?(.*?)["']?\\)/);
          if (!match) throw new Error(`shell background URL missing: ${backgroundImage}`);
          const url = match[1];
          const response = await fetch(url, { cache: 'no-store' });
          if (!response.ok) throw new Error(`shell request failed: ${response.status} ${url}`);
          const blob = await response.blob();
          const objectUrl = URL.createObjectURL(blob);
          const img = new Image();
          try {
            img.src = objectUrl;
            await img.decode();
            return {
              backgroundImage,
              url,
              status: response.status,
              contentType: response.headers.get('content-type') || '',
              bytes: blob.size,
              naturalWidth: img.naturalWidth,
              naturalHeight: img.naturalHeight,
            };
          } finally {
            URL.revokeObjectURL(objectUrl);
          }
        }
        """
    )
    expected_name = f"padiem-glass-{variant}-shell.jpg"
    if image["naturalWidth"] <= 0 or image["naturalHeight"] <= 0 or image["bytes"] <= 1000:
        raise AssertionError(f"Padiem Glass shell did not decode: {image}")
    if expected_name not in image["url"]:
        raise AssertionError(f"Padiem Glass shell URL mismatch: expected={expected_name}, actual={image['url']}")
    return image


async def _send_glass_turn(page: Page, *, variant: str, turn: int) -> None:
    expected = await page.locator("#messageList .assistant-message").count() + 1
    await page.locator("#messageInput").fill(f"Padiem Glass {variant} 시각 검수 대화 {turn}")
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("Padiem Glass preview send button stayed disabled")
    await page.locator("#sendButton").click()
    await page.locator('.app-shell[data-state="chat"]').wait_for(state="attached")
    await page.wait_for_function(
        "expected => document.querySelectorAll('#messageList .assistant-message').length >= expected",
        arg=expected,
        timeout=15_000,
    )
    await page.wait_for_function(
        "expected => [...document.querySelectorAll('#messageList .assistant-content')].filter(el => el.textContent?.includes('지금은 미리보기 환경입니다')).length >= expected",
        arg=expected,
        timeout=15_000,
    )
    # Sample while the answer-activity reveal envelope is still active.
    await page.wait_for_timeout(120)


async def _capture_glass_preview(page: Page, *, variant: str) -> dict[str, Any]:
    await page.set_viewport_size({"width": 1440, "height": 1000})
    await page.goto(
        f"{BASE_URL}/?theme=padiem-glass&glass={variant}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_function(
        "() => document.documentElement.getAttribute('data-glass-mode') === 'home'",
        timeout=5_000,
    )
    await page.wait_for_timeout(700)

    theme = await page.locator("html").get_attribute("data-theme")
    glass_variant = await page.locator("html").get_attribute("data-glass-variant")
    if theme != "padiem-glass":
        raise AssertionError(f"Padiem Glass preview did not activate: {theme!r}")
    if glass_variant != variant:
        raise AssertionError(f"Padiem Glass variant mismatch: expected={variant!r}, actual={glass_variant!r}")

    await _assert_no_horizontal_overflow(page, f"glass-{variant}-home")
    conversation_box = await _assert_in_viewport(page, ".conversation")
    composer_box = await _assert_in_viewport(page, "#composerForm")
    portrait = await _assert_glass_portrait_image_loaded(page, variant=variant)
    shell_image = await _assert_glass_shell_image_loaded(page, variant=variant)
    initial_reveal = await _glass_reveal(page)
    if initial_reveal > 0.15:
        raise AssertionError(f"Padiem Glass must start covered: reveal={initial_reveal}")

    shell_initial = await _glass_shell_snapshot(page)
    if shell_initial["fragmentCount"] != 20:
        raise AssertionError(f"Glass shell must render exactly 20 source fragments: {shell_initial}")
    if shell_initial["progress"] > 0.05 or shell_initial["portalOpacity"] > 0.05:
        raise AssertionError(f"Glass shell must start covered: {shell_initial}")

    # APPEARANCE controls must expose the approved 3-mode mask and speed bar.
    await page.locator("#settingsButton").click()
    control = page.locator(".glass-shell-control")
    await control.wait_for(state="visible", timeout=5_000)
    mask_values = await control.locator("[data-glass-mask-value]").evaluate_all(
        "els => els.map(el => el.getAttribute('data-glass-mask-value'))"
    )
    if mask_values != ["auto", "on", "off"]:
        raise AssertionError(f"Glass shell mask controls mismatch: {mask_values}")
    if (await control.locator(".glass-speed-value").inner_text()).strip() != "1.0×":
        raise AssertionError("Glass shell speed control must default to 1.0×")
    await page.locator("#settingsCloseButton").click()

    # Forced On/Off verifies the actual shell portal/fragments, not only driver CSS vars.
    await page.evaluate(
        "() => { window.PadiemTheme.applyGlassSpeed(300, false); window.PadiemTheme.applyGlassMask('on', false); }"
    )
    await page.wait_for_function(
        "() => (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--glass-shell-progress')) || 0) > .94",
        timeout=4_000,
    )
    shell_on = await _glass_shell_snapshot(page)
    if shell_on["portalOpacity"] < 0.35 or shell_on["dissolve"] < 0.5:
        raise AssertionError(f"Glass mask=on did not reveal completed shell portrait: {shell_on}")
    shell_on_name = f"desktop-glass-{variant}-shell-on.png"
    await page.screenshot(path=str(OUT_DIR / shell_on_name), full_page=True)

    await page.evaluate("() => window.PadiemTheme.applyGlassMask('off', false)")
    await page.wait_for_function(
        "() => (parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--glass-shell-progress')) || 0) < .05",
        timeout=4_000,
    )
    shell_off = await _glass_shell_snapshot(page)
    if shell_off["portalOpacity"] > 0.05 or shell_off["maxFragmentOpacity"] > 0.10:
        raise AssertionError(f"Glass mask=off did not fully cover shell: {shell_off}")

    await page.evaluate(
        "() => { window.PadiemTheme.applyGlassSpeed(100, false); window.PadiemTheme.applyGlassMask('auto', false); }"
    )
    await page.wait_for_timeout(120)

    home_before_pointer = await _glass_motion_snapshot(page)
    await page.mouse.move(1180, 180)
    await page.wait_for_timeout(320)
    home_after_pointer = await _glass_motion_snapshot(page)
    home_shell_pointer = await _glass_shell_snapshot(page)
    if home_after_pointer["pointerX"] in {"", "0px", "0.0px"} and home_after_pointer["pointerY"] in {"", "0px", "0.0px"}:
        raise AssertionError(f"Padiem Glass home portrait lost cinematic pointer response: {home_after_pointer}")
    if home_shell_pointer["pointerDriver"] < 0.20 or home_shell_pointer["progress"] < 0.08 or home_shell_pointer["visibleFragments"] == 0:
        raise AssertionError(f"Glass pointer-only shell assembly is not visibly active: {home_shell_pointer}")

    home_name = f"desktop-glass-{variant}-home.png"
    await page.screenshot(path=str(OUT_DIR / home_name), full_page=True)

    # Return to the content side before testing answer-only motion.
    await page.mouse.move(70, 80)
    await page.wait_for_timeout(1100)

    chat_name = f"desktop-glass-{variant}-chat.png"
    reading_samples: list[dict[str, Any]] = []
    answer_only_reveal = 0.0
    combined_reveal = 0.0
    answer_only_shell_progress = 0.0
    combined_shell_progress = 0.0

    for turn in range(1, 6):
        # Turn 1 = answer only. Turn 2 = pointer + answer together.
        if turn == 2:
            await page.mouse.move(1180, 180)
            await page.wait_for_timeout(120)
        else:
            await page.mouse.move(70, 80)
            await page.wait_for_timeout(120)

        await _send_glass_turn(page, variant=variant, turn=turn)
        await page.wait_for_function(
            "() => document.documentElement.getAttribute('data-glass-mode') === 'reading'",
            timeout=5_000,
        )
        await _assert_no_horizontal_overflow(page, f"glass-{variant}-turn-{turn}")
        active = await _glass_motion_snapshot(page)
        active_shell = await _glass_shell_snapshot(page)
        reading_samples.append({"turn": turn, "phase": "active", "shell": active_shell, **active})

        if not 0 <= active["reveal"] <= 1:
            raise AssertionError(f"Glass reveal escaped bounded range: {active}")

        if turn == 1:
            answer_only_reveal = active["reveal"]
            answer_only_shell_progress = active_shell["progress"]
            if answer_only_reveal < 0.15:
                raise AssertionError(
                    f"Glass reading mode lost answer-driven reveal: {active}"
                )
            if active_shell["answerDriver"] <= 0 or answer_only_shell_progress < 0.05 or active_shell["visibleFragments"] == 0:
                raise AssertionError(f"Glass answer-only shell progression is not visible: {active_shell}")
            await page.screenshot(path=str(OUT_DIR / chat_name), full_page=True)

        if turn == 2:
            combined_reveal = active["reveal"]
            combined_shell_progress = active_shell["progress"]
            if combined_reveal < 0.35:
                raise AssertionError(
                    f"Glass pointer+answer reveal is too weak: {active}"
                )
            if active_shell["pointerDriver"] <= 0 or active_shell["answerDriver"] <= 0:
                raise AssertionError(f"Glass combined shell drivers are not both active: {active_shell}")
            if combined_shell_progress <= answer_only_shell_progress + 0.03:
                raise AssertionError(
                    "Glass pointer+answer shell progression must be stronger than answer-only: "
                    f"answer={answer_only_shell_progress}, combined={combined_shell_progress}"
                )

        # After answer activity and pointer proximity end, reading mode must
        # return to its calm rest posture rather than accumulating travel.
        await page.mouse.move(70, 80)
        await page.wait_for_timeout(1900)
        settled = await _glass_motion_snapshot(page)
        settled_shell = await _glass_shell_snapshot(page)
        reading_samples.append({"turn": turn, "phase": "settled", "shell": settled_shell, **settled})
        if settled["reveal"] > 0.03:
            raise AssertionError(
                f"Glass reading mode did not settle after answer activity: {settled}"
            )
        if settled["pointerX"] not in {"", "0px", "0.0px"} or settled["pointerY"] not in {"", "0px", "0.0px"}:
            raise AssertionError(f"Glass reading mode pointer failed to settle: {settled}")
        if settled["artX"] not in {"", "0px", "0.0px"} or settled["artY"] not in {"", "0px", "0.0px"}:
            raise AssertionError(f"Glass reading mode portrait failed to settle: {settled}")
        if settled["artScale"] not in {"", "1", "1.0", "1.000"}:
            raise AssertionError(f"Glass reading mode scale failed to settle: {settled}")
        if settled_shell["progress"] > max(0.12, active_shell["progress"] * 0.55):
            raise AssertionError(
                f"Glass shell did not make cinematic recovery after activity: active={active_shell}, settled={settled_shell}"
            )

    if answer_only_reveal <= 0:
        raise AssertionError("Glass answer-only reveal was never sampled")
    if combined_reveal <= 0:
        raise AssertionError("Glass pointer+answer reveal was never sampled")

    # Pointer-only reading interaction remains cinematic after the answer has
    # fully settled.
    reading_rest = await _glass_motion_snapshot(page)
    await page.mouse.move(1180, 180)
    await page.wait_for_timeout(320)
    pointer_only = await _glass_motion_snapshot(page)
    pointer_only_shell = await _glass_shell_snapshot(page)
    if pointer_only["reveal"] < 0.20:
        raise AssertionError(
            f"Glass reading mode lost pointer-driven reveal: {pointer_only}"
        )
    if pointer_only["reveal"] > 1:
        raise AssertionError(f"Glass pointer-only reveal escaped bounds: {pointer_only}")
    if pointer_only_shell["progress"] < 0.08 or pointer_only_shell["visibleFragments"] == 0:
        raise AssertionError(f"Glass reading pointer-only shell assembly is not visible: {pointer_only_shell}")

    # Moving away must re-cover, then page scrolling alone must not drive the
    # reading portrait.
    await page.mouse.move(70, 80)
    await page.wait_for_timeout(1100)
    reading_before_scroll = await _glass_motion_snapshot(page)
    if reading_before_scroll["reveal"] > 0.03:
        raise AssertionError(
            f"Glass reading mode failed to re-cover after pointer exit: {reading_before_scroll}"
        )

    await page.evaluate("window.scrollTo(0, Math.max(0, document.documentElement.scrollHeight - window.innerHeight))")
    await page.wait_for_timeout(300)
    reading_after_scroll = await _glass_motion_snapshot(page)

    stable_keys = ("reveal", "artX", "artY", "artScale", "pointerX", "pointerY", "maskStart", "maskFull")
    for key in stable_keys:
        if reading_before_scroll[key] != reading_after_scroll[key]:
            raise AssertionError(
                f"Glass reading mode changed from scroll-only travel for {key}: "
                f"before={reading_before_scroll[key]!r}, after={reading_after_scroll[key]!r}"
            )

    if reading_rest["portraitOpacity"] >= home_before_pointer["portraitOpacity"]:
        raise AssertionError(
            "Glass reading mode must reduce portrait prominence: "
            f"home={home_before_pointer['portraitOpacity']}, reading={reading_rest['portraitOpacity']}"
        )
    if reading_rest["bodyNoiseOpacity"] >= home_before_pointer["bodyNoiseOpacity"]:
        raise AssertionError(
            "Glass reading mode must reduce atmospheric grid noise: "
            f"home={home_before_pointer['bodyNoiseOpacity']}, reading={reading_rest['bodyNoiseOpacity']}"
        )

    return {
        "variant": variant,
        "theme": theme,
        "conversation_box": conversation_box,
        "composer_box": composer_box,
        "portrait": portrait,
        "shell_image": shell_image,
        "shell_contract": {
            "initial": shell_initial,
            "forced_on": shell_on,
            "forced_off": shell_off,
            "pointer_only_home": home_shell_pointer,
            "answer_only_progress": answer_only_shell_progress,
            "combined_progress": combined_shell_progress,
            "shell_on_screenshot": shell_on_name,
            "status": "PASS",
        },
        "home_screenshot": home_name,
        "chat_screenshot": chat_name,
        "home_cinematic": {
            "before_pointer": home_before_pointer,
            "after_pointer": home_after_pointer,
            "status": "PASS",
        },
        "reading_calm": {
            "samples": reading_samples,
            "answer_only_reveal": answer_only_reveal,
            "combined_reveal": combined_reveal,
            "rest": reading_rest,
            "pointer_only": pointer_only,
            "before_scroll": reading_before_scroll,
            "after_scroll": reading_after_scroll,
            "status": "PASS",
        },
        "status": "PASS",
    }


async def _run_claw_intermediate(page: Page) -> dict[str, Any]:
    name = "claw-tablet-820"
    await page.set_viewport_size({"width": 820, "height": 900})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_timeout(500)

    if not await page.locator("#mobileMenu").is_visible():
        raise AssertionError("shared shell must expose the mobile menu at 820px")
    await page.locator("#mobileMenu").click()
    await page.locator("#clawNavButton").wait_for(state="visible")
    await page.locator("#clawNavButton").click()

    await page.locator('.app-shell[data-state="claw"]').wait_for(state="attached")
    workspace = page.locator("#clawWorkspace")
    if await workspace.get_attribute("data-view") != "manual":
        raise AssertionError("Claw navigation must enter the manual shared-conversation view")
    if await workspace.is_visible():
        raise AssertionError("manual Claw workspace header canvas must stay hidden under #2532 continuity")
    for selector in (".conversation", "#clawManualForm", "#composerForm", "#messageInput"):
        if not await page.locator(selector).is_visible():
            raise AssertionError(f"{selector} must stay visible in manual Claw at 820px")

    await _assert_no_horizontal_overflow(page, name)
    conversation_box = await _assert_in_viewport(page, ".conversation")
    composer_box = await _assert_in_viewport(page, "#composerForm")

    direction = await page.locator(".claw-mode-bar-row").evaluate(
        "el => getComputedStyle(el).flexDirection"
    )
    if direction != "column":
        raise AssertionError(f"Claw mode bar must stack at shared mobile breakpoint: {direction!r}")

    target_heights: dict[str, float] = {}
    for selector in ("#clawGenerateBtn", "#clawExecuteButton"):
        box = await page.locator(selector).bounding_box()
        if not box or box["height"] < 44:
            raise AssertionError(f"Claw touch target too small at 820px: {selector}={box}")
        target_heights[selector] = box["height"]

    input_font_px = await page.locator("#messageInput").evaluate(
        "el => parseFloat(getComputedStyle(el).fontSize)"
    )
    if input_font_px < 16:
        raise AssertionError(f"Claw shared composer input must remain iOS-zoom safe: {input_font_px}")

    await page.screenshot(path=str(OUT_DIR / f"{name}.png"), full_page=True)
    return {
        "viewport": {"width": 820, "height": 900},
        "shared_shell_mobile_menu": True,
        "manual_workspace_header_hidden": True,
        "shared_conversation_visible": True,
        "shared_composer_visible": True,
        "mode_bar_direction": direction,
        "touch_target_heights": target_heights,
        "input_font_px": input_font_px,
        "conversation_box": conversation_box,
        "composer_box": composer_box,
        "horizontal_overflow": False,
        "status": "PASS",
    }


async def _run_view(page: Page, *, name: str, width: int, height: int, mobile: bool) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_timeout(700)

    await _assert_no_horizontal_overflow(page, f"{name}-home")
    composer_box = await _assert_in_viewport(page, "#composerForm")
    input_box = await _assert_in_viewport(page, "#messageInput")
    mobile_menu_visible = await page.locator("#mobileMenu").is_visible()
    if mobile and not mobile_menu_visible:
        raise AssertionError("mobile menu must be visible on mobile viewport")

    visible_starters = await _visible_count(page, ".starter")
    visible_disabled = await _visible_count(page, "button:disabled")
    model_pill_visible = await page.locator(".model-pill").is_visible()
    route_detail_visible = await page.locator(".route-details").is_visible() if await page.locator(".route-details").count() else False

    await page.screenshot(path=str(OUT_DIR / f"{name}-home.png"), full_page=True)

    # Test-only transport control. The product still talks only to the local mock
    # server. We delay the first stream long enough to capture the real typing UI,
    # and later fail exactly one stream request to exercise the existing retry UI.
    stream_control = {"delay_next": True, "fail_next": False}

    async def handle_stream(route) -> None:
        if stream_control["fail_next"]:
            stream_control["fail_next"] = False
            await route.fulfill(
                status=502,
                content_type="application/json",
                body=json.dumps(
                    {
                        "error": {
                            "code": "qa_forced_stream_failure",
                            "message": "QA에서 재시도 화면을 확인하기 위한 일시적 연결 오류입니다.",
                        }
                    },
                    ensure_ascii=False,
                ),
            )
            return
        if stream_control["delay_next"]:
            stream_control["delay_next"] = False
            await asyncio.sleep(1.0)
        await route.continue_()

    await page.route("**/api/chat/stream", handle_stream)

    first_prompt = "오늘 저녁 메뉴를 세 가지 추천해줘"
    input_box_locator = page.locator("#messageInput")
    await input_box_locator.fill(first_prompt)
    await page.locator("#sendButton").wait_for(state="visible")
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("send button stayed disabled after entering a question")
    await page.locator("#sendButton").click()

    await page.locator('.app-shell[data-state="chat"]').wait_for(state="attached")
    typing = page.locator("#messageList .assistant-message .typing").last
    await typing.wait_for(state="visible", timeout=3_000)
    if await typing.get_attribute("aria-label") != "답변 준비 중":
        raise AssertionError("typing state must expose the visible '답변 준비 중' label")
    await _assert_no_horizontal_overflow(page, f"{name}-loading")
    await page.screenshot(path=str(OUT_DIR / f"{name}-loading.png"), full_page=True)

    first_assistant = page.locator("#messageList .assistant-message").first
    await first_assistant.wait_for(state="visible", timeout=15_000)
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-content')?.textContent?.includes('지금은 미리보기 환경입니다')",
        timeout=15_000,
    )
    await page.screenshot(path=str(OUT_DIR / f"{name}-chat.png"), full_page=True)

    await page.locator("#messageInput").fill("그중 가장 간단한 것으로 하나 골라줘")
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("follow-up send button stayed disabled")
    await page.locator("#sendButton").click()
    await page.wait_for_function(
        "() => document.querySelectorAll('#messageList .assistant-message').length >= 2",
        timeout=15_000,
    )
    await page.wait_for_function(
        "() => [...document.querySelectorAll('#messageList .assistant-content')].filter(el => el.textContent?.includes('지금은 미리보기 환경입니다')).length >= 2",
        timeout=15_000,
    )

    stream_control["fail_next"] = True
    await page.locator("#messageInput").fill("연결 오류가 나면 다시 시도할 수 있는지 확인해줘")
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("error-path send button stayed disabled")
    await page.locator("#sendButton").click()

    error_box = page.locator("#messageList .assistant-message .error-box").last
    await error_box.wait_for(state="visible", timeout=5_000)
    retry_button = error_box.locator(".retry-button")
    await retry_button.wait_for(state="visible")
    if await retry_button.is_disabled():
        raise AssertionError("retry button must be usable after a stream error")
    error_text = (await error_box.inner_text()).strip()
    if "답변을 불러오지 못했습니다" not in error_text or "다시 시도" not in error_text:
        raise AssertionError(f"error state is not understandable: {error_text!r}")
    error_clearance_px = await _assert_error_clear_of_composer(page, error_box)
    await _assert_no_horizontal_overflow(page, f"{name}-error")
    await page.screenshot(path=str(OUT_DIR / f"{name}-error.png"), full_page=True)

    await retry_button.click()
    await page.wait_for_function(
        "() => { const els = [...document.querySelectorAll('#messageList .assistant-content')]; return Boolean(els.at(-1)?.textContent?.includes('지금은 미리보기 환경입니다')); }",
        timeout=15_000,
    )
    await _assert_no_horizontal_overflow(page, f"{name}-recovered")
    await page.screenshot(path=str(OUT_DIR / f"{name}-recovered.png"), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "horizontal_overflow": False,
        "composer_box": composer_box,
        "input_box": input_box,
        "visible_starter_count": visible_starters,
        "visible_disabled_button_count": visible_disabled,
        "model_pill_visible": model_pill_visible,
        "route_detail_visible": route_detail_visible,
        "mobile_menu_visible": mobile_menu_visible,
        "loading_state": "PASS",
        "first_question": "PASS",
        "progressive_stream_path": "PASS",
        "follow_up": "PASS",
        "mock_answer_marker": "PASS",
        "error_retry": "PASS",
        "error_composer_clearance_px": error_clearance_px,
        "retry_recovery": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "runtime_expectation": "mock",
        "provider_calls_expected": 0,
        "views": {},
        "padiem_glass_preview": {},
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            report["views"]["desktop"] = await _run_view(
                page, name="desktop", width=1440, height=1000, mobile=False
            )
            await page.close()

            mobile_page = await browser.new_page()
            report["views"]["mobile"] = await _run_view(
                mobile_page, name="mobile", width=390, height=844, mobile=True
            )
            await mobile_page.close()

            claw_tablet_page = await browser.new_page()
            report["views"]["claw-tablet-820"] = await _run_claw_intermediate(claw_tablet_page)
            await claw_tablet_page.close()

            for variant in ("female", "male"):
                glass_page = await browser.new_page()
                report["padiem_glass_preview"][variant] = await _capture_glass_preview(
                    glass_page, variant=variant
                )
                await glass_page.close()

            # Reduced-motion: Auto/touch-style motion stays static, while an
            # explicit On state resolves immediately without animation.
            reduced_page = await browser.new_page()
            await reduced_page.emulate_media(reduced_motion="reduce")
            await reduced_page.goto(
                f"{BASE_URL}/?theme=padiem-glass&glass=female",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            await reduced_page.locator(".glass-shell-portrait").wait_for(state="attached")
            await reduced_page.mouse.move(1180, 180)
            await reduced_page.wait_for_timeout(160)
            reduced_auto = await _glass_shell_snapshot(reduced_page)
            if reduced_auto["progress"] > 0.01 or reduced_auto["pointerDriver"] > 0.01:
                raise AssertionError(f"reduced-motion Auto shell must remain static: {reduced_auto}")
            await reduced_page.evaluate("() => window.PadiemTheme.applyGlassMask('on', false)")
            await reduced_page.wait_for_timeout(80)
            reduced_on = await _glass_shell_snapshot(reduced_page)
            if reduced_on["progress"] < 0.99 or reduced_on["portalOpacity"] < 0.35:
                raise AssertionError(f"reduced-motion explicit On must resolve statically: {reduced_on}")
            report["padiem_glass_reduced_motion"] = {
                "auto": reduced_auto,
                "on": reduced_on,
                "status": "PASS",
            }
            await reduced_page.close()

            # Touch/mobile must not synthesize the desktop hover driver.
            touch_context = await browser.new_context(
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
            )
            touch_page = await touch_context.new_page()
            await touch_page.goto(
                f"{BASE_URL}/?theme=padiem-glass&glass=female&mask=auto",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            await touch_page.locator(".glass-shell-portrait").wait_for(state="attached")
            hover_capable = await touch_page.evaluate(
                "() => matchMedia('(hover: hover) and (pointer: fine)').matches"
            )
            if hover_capable:
                raise AssertionError("touch/mobile QA unexpectedly advertises fine hover")
            await touch_page.touchscreen.tap(330, 180)
            await touch_page.wait_for_timeout(320)
            touch_shell = await _glass_shell_snapshot(touch_page)
            if touch_shell["pointerDriver"] > 0.01 or touch_shell["progress"] > 0.05:
                raise AssertionError(f"touch input synthesized forbidden shell hover: {touch_shell}")
            await _assert_no_horizontal_overflow(touch_page, "glass-touch-mobile")
            report["padiem_glass_touch"] = {
                "hover_capable": hover_capable,
                "shell": touch_shell,
                "horizontal_overflow": False,
                "status": "PASS",
            }
            await touch_context.close()
        finally:
            await browser.close()

    female_home = OUT_DIR / report["padiem_glass_preview"]["female"]["home_screenshot"]
    male_home = OUT_DIR / report["padiem_glass_preview"]["male"]["home_screenshot"]
    female_hash = _sha256_file(female_home)
    male_hash = _sha256_file(male_home)
    if female_hash == male_hash:
        raise AssertionError(
            "Padiem Glass Female/Male variants rendered pixel-identical home screenshots; portrait layer is not visibly contributing"
        )
    report["padiem_glass_visual_distinction"] = {
        "female_home_sha256": female_hash,
        "male_home_sha256": male_hash,
        "different": True,
        "status": "PASS",
    }

    report["status"] = "PASS"
    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
