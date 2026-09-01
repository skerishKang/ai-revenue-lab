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
    await page.wait_for_timeout(950)


async def _capture_glass_preview(page: Page, *, variant: str) -> dict[str, Any]:
    await page.set_viewport_size({"width": 1440, "height": 1000})
    await page.goto(
        f"{BASE_URL}/?theme=padiem-glass&glass={variant}",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_timeout(900)

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
    initial_reveal = await _glass_reveal(page)
    if initial_reveal > 0.15:
        raise AssertionError(f"Padiem Glass must start covered: reveal={initial_reveal}")

    home_name = f"desktop-glass-{variant}-home.png"
    await page.screenshot(path=str(OUT_DIR / home_name), full_page=True)

    peak: dict[str, Any] | None = None
    covered_again: dict[str, Any] | None = None
    reveal_samples: list[dict[str, Any]] = [{"turn": 0, "reveal": initial_reveal}]
    chat_name = f"desktop-glass-{variant}-chat.png"

    for turn in range(1, 8):
        await _send_glass_turn(page, variant=variant, turn=turn)
        await _assert_no_horizontal_overflow(page, f"glass-{variant}-turn-{turn}")
        reveal = await _glass_reveal(page)
        reveal_samples.append({"turn": turn, "reveal": reveal})
        if turn == 1:
            await page.screenshot(path=str(OUT_DIR / chat_name), full_page=True)
        if peak is None and reveal >= 0.70:
            peak_name = f"desktop-glass-{variant}-reveal-peak.png"
            await page.screenshot(path=str(OUT_DIR / peak_name), full_page=True)
            peak = {"turn": turn, "reveal": reveal, "screenshot": peak_name}
            continue
        if peak is not None and reveal <= 0.30:
            covered_name = f"desktop-glass-{variant}-covered-again.png"
            await page.screenshot(path=str(OUT_DIR / covered_name), full_page=True)
            covered_again = {"turn": turn, "reveal": reveal, "screenshot": covered_name}
            break

    if peak is None:
        raise AssertionError(f"Padiem Glass reveal peak was not reached: {reveal_samples}")
    if covered_again is None:
        raise AssertionError(f"Padiem Glass did not return to covered state after peak: {reveal_samples}")

    return {
        "variant": variant,
        "theme": theme,
        "conversation_box": conversation_box,
        "composer_box": composer_box,
        "portrait": portrait,
        "home_screenshot": home_name,
        "chat_screenshot": chat_name,
        "reveal_loop": {
            "covered": {"turn": 0, "reveal": initial_reveal, "screenshot": home_name},
            "peak": peak,
            "covered_again": covered_again,
            "samples": reveal_samples,
            "status": "PASS",
        },
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

            for variant in ("female", "male"):
                glass_page = await browser.new_page()
                report["padiem_glass_preview"][variant] = await _capture_glass_preview(
                    glass_page, variant=variant
                )
                await glass_page.close()
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
