from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright

from b62_visual_timing import (
    TimingOvershoot,
    check_settle_window,
    wait_state_settled,
    with_timing_retries,
)

BASE_URL = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

TIMING_EVIDENCE: list[dict[str, Any]] = []

VIEWPORTS = (
    ("glass-zoom75-equivalent", 2560, 1440),
    ("glass-zoom100-equivalent", 1920, 1080),
    ("glass-zoom150-equivalent", 1280, 720),
)

_FOLLOW_STATE_EXPR = """
() => ({
  following: window.__padiemConversationMotion.isFollowingLatest(),
  y: window.scrollY,
})
"""


async def _box(page: Page, selector: str) -> dict[str, float]:
    box = await page.locator(selector).bounding_box()
    if not box:
        raise AssertionError(f"{selector} has no visible bounding box")
    return {key: round(float(value), 2) for key, value in box.items()}


async def _assert_no_horizontal_overflow(page: Page, name: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(
            f"horizontal overflow at {name}: scrollWidth={scroll_width}, innerWidth={inner_width}"
        )


async def _assert_horizontally_in_viewport(page: Page, selector: str) -> dict[str, float]:
    box = await _box(page, selector)
    viewport = page.viewport_size
    assert viewport is not None
    if box["x"] < -1:
        raise AssertionError(f"{selector} starts outside viewport width: {box}")
    if box["x"] + box["width"] > viewport["width"] + 1:
        raise AssertionError(f"{selector} overflows viewport width: {box}")
    return box


async def _assert_in_viewport(page: Page, selector: str) -> dict[str, float]:
    box = await _assert_horizontally_in_viewport(page, selector)
    viewport = page.viewport_size
    assert viewport is not None
    if box["y"] < -1:
        raise AssertionError(f"{selector} starts outside viewport height: {box}")
    if box["y"] + box["height"] > viewport["height"] + 1:
        raise AssertionError(f"{selector} overflows viewport height: {box}")
    return box


async def _portrait_style(page: Page) -> dict[str, Any]:
    return await page.locator(".main-panel").evaluate(
        """
        (el) => {
          const style = getComputedStyle(el, '::before');
          return {
            backgroundImage: style.backgroundImage,
            opacity: Number.parseFloat(style.opacity || '0'),
            width: Number.parseFloat(style.width || '0'),
            right: style.right,
            maskImage: style.maskImage,
          };
        }
        """
    )


async def _assert_conversation_motion(page: Page, name: str) -> dict[str, Any]:
    loaded = await page.evaluate(
        "Boolean(window.__padiemConversationMotion && window.__padiemConversationMotion.isFollowingLatest)"
    )
    if not loaded:
        raise AssertionError(f"conversation motion helper did not load at {name}")

    recommendation_count = await page.locator("#sidebar [data-prompt]").count()
    if recommendation_count != 0:
        raise AssertionError(
            f"generic sidebar recommendations must be removed at {name}: count={recommendation_count}"
        )

    clearance = await page.evaluate(
        "Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--padiem-composer-clearance')) || 0"
    )
    composer_wrap_height = await page.locator(".composer-wrap").evaluate(
        "el => el.getBoundingClientRect().height"
    )
    if clearance < max(220, composer_wrap_height + 60):
        raise AssertionError(
            f"composer clearance is too small at {name}: clearance={clearance}, composer={composer_wrap_height}"
        )

    # Grow the current assistant answer deterministically. Conversation follow
    # still tracks the newest tokens, while the Glass portrait may now perform
    # the bounded answer-driven reveal requested for active reading.
    await page.evaluate(
        """
        () => {
          const content = document.querySelector('#messageList .assistant-content');
          if (!content) throw new Error('assistant content missing');
          const tail = document.createElement('div');
          tail.id = 'conversation-motion-test-tail';
          for (let i = 0; i < 48; i += 1) {
            const line = document.createElement('span');
            line.style.display = 'block';
            line.textContent = `대화 진행 자동 추적 검증 ${i + 1}`;
            tail.appendChild(line);
          }
          content.appendChild(tail);
        }
        """
    )
    await page.wait_for_timeout(350)

    followed = await page.evaluate(
        """
        () => ({
          following: window.__padiemConversationMotion.isFollowingLatest(),
          remaining: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)
            - (window.scrollY + window.innerHeight),
          composerTop: document.querySelector('.composer-wrap').getBoundingClientRect().top,
          latestBottom: document.querySelector('#conversation-motion-test-tail').getBoundingClientRect().bottom,
          reveal: Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--glass-reveal')) || 0,
        })
        """
    )
    if not followed["following"]:
        raise AssertionError(f"latest-answer follow unexpectedly paused at {name}: {followed}")
    if followed["remaining"] > 4:
        raise AssertionError(f"latest-answer growth was not followed at {name}: {followed}")
    if followed["latestBottom"] > followed["composerTop"] - 12:
        raise AssertionError(f"latest answer is covered by the fixed composer at {name}: {followed}")
    if not 0.15 <= float(followed["reveal"]) <= 1.0:
        raise AssertionError(
            f"Glass answer-driven reveal must be visible and bounded during active reading at {name}: {followed}"
        )

    # An intentional upward wheel is a user signal: auto-follow must pause.
    await page.wait_for_timeout(600)
    await page.mouse.wheel(0, -520)
    # Detect the pause on the page clock instead of sampling a fixed host
    # sleep: on a loaded CI runner the old 180ms sleep + read round-trip could
    # land either before the wheel was processed (false "did not pause") or
    # at an uncontrolled time.  The pause must still arrive within the
    # original ~180ms budget (200ms ceiling absorbs only the deterministic
    # ~one-tick in-page detection granularity, not the former host slack).
    wheel_observed = await page.evaluate("performance.now()")
    pause_wait = await wait_state_settled(
        page,
        started_ms=wheel_observed,
        done_expr="() => !window.__padiemConversationMotion.isFollowingLatest()",
        timeout_ms=900,
        read_expr=_FOLLOW_STATE_EXPR,
        fallback_ms=8.0,
    )
    paused_before = pause_wait["state"]
    check_settle_window(
        f"user scroll-up did not pause auto-follow at {name}: {paused_before}",
        pause_wait,
        lo_ms=0,
        hi_ms=200,
        evidence_log=TIMING_EVIDENCE,
        label=f"{name}-scroll-pause",
    )
    # Record the paused viewport only once any in-flight wheel scrolling has
    # settled, so the later ±8px comparison measures product behavior and not
    # where in the scroll the detection tick happened to land.
    await page.wait_for_timeout(120)
    paused_before = await page.evaluate(_FOLLOW_STATE_EXPR)
    if paused_before["following"]:
        raise AssertionError(f"user scroll-up did not pause auto-follow at {name}: {paused_before}")

    await page.evaluate(
        """
        () => {
          const tail = document.querySelector('#conversation-motion-test-tail');
          for (let i = 0; i < 12; i += 1) {
            const line = document.createElement('span');
            line.style.display = 'block';
            line.textContent = `사용자 과거 읽기 중 추가 토큰 ${i + 1}`;
            tail.appendChild(line);
          }
        }
        """
    )
    await page.wait_for_timeout(220)
    paused_after = await page.evaluate(
        """
        () => ({
          following: window.__padiemConversationMotion.isFollowingLatest(),
          y: window.scrollY,
        })
        """
    )
    if paused_after["following"]:
        raise AssertionError(f"DOM growth resumed follow while user was reading history at {name}: {paused_after}")
    if abs(float(paused_after["y"]) - float(paused_before["y"])) > 8:
        raise AssertionError(
            f"viewport moved while auto-follow was paused at {name}: before={paused_before}, after={paused_after}"
        )

    # Returning to the end restores normal progressive-follow behavior.
    await page.evaluate(
        "window.scrollTo(0, Math.max(document.documentElement.scrollHeight, document.body.scrollHeight))"
    )
    try:
        await page.wait_for_function(
            "() => window.__padiemConversationMotion && window.__padiemConversationMotion.isFollowingLatest()",
            timeout=2_500,
            polling=50,
        )
    except Exception as exc:
        resumed_state = await page.evaluate(
            """
            () => ({
              following: window.__padiemConversationMotion?.isFollowingLatest?.() || false,
              y: window.scrollY,
              remaining: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)
                - (window.scrollY + window.innerHeight),
            })
            """
        )
        raise AssertionError(
            f"returning to conversation end did not resume follow at {name}: {resumed_state}"
        ) from exc

    await page.evaluate(
        """
        () => {
          const tail = document.querySelector('#conversation-motion-test-tail');
          const line = document.createElement('span');
          line.style.display = 'block';
          line.textContent = '최신 답변 추적 재개 검증';
          tail.appendChild(line);
        }
        """
    )
    await page.wait_for_timeout(220)
    resumed_state = await page.evaluate(
        """
        () => ({
          following: window.__padiemConversationMotion.isFollowingLatest(),
          remaining: Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)
            - (window.scrollY + window.innerHeight),
          reveal: Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--glass-reveal')) || 0,
        })
        """
    )
    if not resumed_state["following"] or resumed_state["remaining"] > 4:
        raise AssertionError(f"progressive follow did not resume at {name}: {resumed_state}")
    if not 0.15 <= float(resumed_state["reveal"]) <= 1.0:
        raise AssertionError(
            f"Glass answer-driven reveal must remain visible and bounded after follow resumes at {name}: {resumed_state}"
        )

    # After token activity stops, the portrait must settle back to the calm
    # reading posture. Move the pointer out of the portrait zone first so this
    # assertion isolates answer activity from the independent pointer driver.
    await page.mouse.move(70, 80)
    await page.wait_for_timeout(1900)
    settled_reveal = await page.evaluate(
        "() => Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--glass-reveal')) || 0"
    )
    if float(settled_reveal) > 0.03:
        raise AssertionError(
            f"Glass answer-driven reveal did not settle after inactivity at {name}: {settled_reveal}"
        )

    return {
        "helper_loaded": True,
        "composer_clearance_px": round(float(clearance), 2),
        "composer_wrap_height_px": round(float(composer_wrap_height), 2),
        "latest_growth_followed": True,
        "latest_answer_clears_composer": True,
        "user_scroll_up_pauses": True,
        "growth_while_paused_keeps_viewport": True,
        "return_to_end_resumes": True,
        "glass_reveal_after_growth": followed["reveal"],
        "glass_reveal_after_resume": resumed_state["reveal"],
        "glass_reveal_after_settle": settled_reveal,
        "sidebar_generic_recommendations_removed": True,
        "status": "PASS",
    }


async def _capture(page: Page, *, name: str, width: int, height: int) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(
        f"{BASE_URL}/?theme=padiem-glass&glass=female",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_timeout(700)

    theme = await page.locator("html").get_attribute("data-theme")
    variant = await page.locator("html").get_attribute("data-glass-variant")
    mode_home = await page.locator("html").get_attribute("data-glass-mode")
    if theme != "padiem-glass" or variant != "female":
        raise AssertionError(f"Glass female did not activate: theme={theme!r}, variant={variant!r}")
    if mode_home != "home":
        raise AssertionError(f"Glass home must stay cinematic at {name}: mode={mode_home!r}")

    await _assert_no_horizontal_overflow(page, f"{name}-home")
    conversation_home = await _assert_horizontally_in_viewport(page, ".conversation")
    composer_home = await _assert_in_viewport(page, "#composerForm")
    portrait_home = await _portrait_style(page)
    if "padiem-glass-female.jpg" not in portrait_home["backgroundImage"]:
        raise AssertionError(f"female portrait missing at {name}: {portrait_home}")
    if portrait_home["opacity"] < 0.15 or portrait_home["width"] < 250:
        raise AssertionError(f"female portrait is not materially visible at {name}: {portrait_home}")

    home_screenshot = f"{name}-female-home.png"
    await page.screenshot(path=str(OUT_DIR / home_screenshot), full_page=True)

    await page.locator("#messageInput").fill("브라우저 배율 대응 시각 검수")
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError(f"send button stayed disabled at {name}")
    await page.locator("#sendButton").click()
    await page.locator('.app-shell[data-state="chat"]').wait_for(state="attached")
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-content')?.textContent?.includes('지금은 미리보기 환경입니다')",
        timeout=15_000,
    )
    await page.wait_for_function(
        "() => document.documentElement.getAttribute('data-glass-mode') === 'reading'",
        timeout=5_000,
    )
    await page.wait_for_timeout(350)

    await _assert_no_horizontal_overflow(page, f"{name}-chat")
    conversation_chat = await _assert_horizontally_in_viewport(page, ".conversation")
    composer_chat = await _assert_in_viewport(page, "#composerForm")
    input_chat = await _assert_in_viewport(page, "#messageInput")
    assistant_avatar = await _assert_horizontally_in_viewport(page, ".assistant-avatar")

    assistant_name = (await page.locator(".assistant-meta span").first.inner_text()).strip()
    if assistant_name != "Padiem Chat":
        raise AssertionError(f"assistant brand casing drift at {name}: {assistant_name!r}")

    input_style = await page.locator("#messageInput").evaluate(
        """
        (el) => {
          const s = getComputedStyle(el);
          return { color: s.color, backgroundColor: s.backgroundColor, boxShadow: s.boxShadow };
        }
        """
    )
    composer_style = await page.locator("#composerForm").evaluate(
        """
        (el) => {
          const s = getComputedStyle(el);
          return { backgroundColor: s.backgroundColor, backgroundImage: s.backgroundImage };
        }
        """
    )
    if input_style["color"] not in {"rgb(23, 32, 42)", "rgba(23, 32, 42, 1)"}:
        raise AssertionError(f"chat input text does not match bright Glass foreground at {name}: {input_style}")
    if input_style["backgroundColor"] not in {"rgba(0, 0, 0, 0)", "transparent"}:
        raise AssertionError(f"nested Glass textarea surface returned at {name}: {input_style}")
    if input_style["boxShadow"] not in {"none", "rgba(0, 0, 0, 0) 0px 0px 0px 0px"}:
        raise AssertionError(f"nested Glass textarea shadow returned at {name}: {input_style}")
    if (
        composer_style["backgroundColor"] in {"rgba(0, 0, 0, 0)", "transparent"}
        and composer_style["backgroundImage"] == "none"
    ):
        raise AssertionError(f"outer composer lost its readable surface at {name}: {composer_style}")

    portrait_chat = await _portrait_style(page)
    if "padiem-glass-female.jpg" not in portrait_chat["backgroundImage"]:
        raise AssertionError(f"female portrait asset disappeared in chat at {name}: {portrait_chat}")
    if portrait_chat["opacity"] < 0.04 or portrait_chat["width"] < 250:
        raise AssertionError(f"female portrait became imperceptible in chat at {name}: {portrait_chat}")
    if portrait_chat["opacity"] >= portrait_home["opacity"]:
        raise AssertionError(
            f"female portrait must step back during reading at {name}: home={portrait_home}, chat={portrait_chat}"
        )

    chat_screenshot = f"{name}-female-chat.png"
    await page.screenshot(path=str(OUT_DIR / chat_screenshot), full_page=True)

    motion = await _assert_conversation_motion(page, name)

    return {
        "viewport": {"width": width, "height": height},
        "glass_mode_home": mode_home,
        "glass_mode_chat": "reading",
        "conversation_home": conversation_home,
        "composer_home": composer_home,
        "conversation_chat": conversation_chat,
        "composer_chat": composer_chat,
        "input_chat": input_chat,
        "assistant_avatar": assistant_avatar,
        "assistant_name": assistant_name,
        "input_style": input_style,
        "composer_style": composer_style,
        "portrait_home": portrait_home,
        "portrait_chat": portrait_chat,
        "portrait_prominence_reduced": True,
        "conversation_motion": motion,
        "home_screenshot": home_screenshot,
        "chat_screenshot": chat_screenshot,
        "vertical_scroll_allowed": True,
        "horizontal_overflow": False,
        "status": "PASS",
    }


async def _run_checks(report: dict[str, Any]) -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for name, width, height in VIEWPORTS:
                async def _viewport_cycle(
                    name: str = name, width: int = width, height: int = height
                ) -> dict[str, Any]:
                    page = await browser.new_page()
                    try:
                        return await _capture(page, name=name, width=width, height=height)
                    finally:
                        await page.close()

                # Overshoot retries re-sample the identical thresholds in a
                # fresh page+viewport once the in-page measurement has proven
                # the runner, not the product, missed the requested window.
                report["views"][name] = await with_timing_retries(
                    _viewport_cycle,
                    label=name,
                    evidence_log=TIMING_EVIDENCE,
                )
        finally:
            await browser.close()


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "purpose": "Padiem Glass zoom-responsive composition with cinematic home and calm active reading",
        "browser_zoom_forced": False,
        "views": {},
    }
    report_path = OUT_DIR / "glass-zoom-report.json"
    try:
        await _run_checks(report)
    except Exception as exc:
        report["status"] = (
            "OVERSHOOT-EXHAUSTED" if isinstance(exc, TimingOvershoot) else "FAIL"
        )
        report["error"] = str(exc)[:2000]
        if TIMING_EVIDENCE:
            report["timing_evidence"] = TIMING_EVIDENCE
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        raise

    report["status"] = "PASS"
    if TIMING_EVIDENCE:
        report["timing_evidence"] = TIMING_EVIDENCE
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
