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

VIEWPORTS = (
    ("desktop-1920", 1920, 1080),
    ("compact-1280", 1280, 720),
    ("tablet-landscape-960", 960, 768),
    ("tablet-portrait-768", 768, 1024),
    ("mobile-390", 390, 844),
)


async def _box(page: Page, selector: str) -> dict[str, float]:
    box = await page.locator(selector).bounding_box()
    if not box:
        raise AssertionError(f"{selector} has no visible bounding box")
    return {key: round(float(value), 2) for key, value in box.items()}


def _right(box: dict[str, float]) -> float:
    return box["x"] + box["width"]


def _assert_close(a: float, b: float, *, name: str, tolerance: float = 1.5) -> None:
    if abs(a - b) > tolerance:
        raise AssertionError(f"{name} mismatch: {a} vs {b}")


async def _capture(page: Page, *, name: str, width: int, height: int) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(
        f"{BASE_URL}/?theme=padiem-glass&glass=female",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.locator("#messageInput").wait_for(state="visible")
    await page.locator("#messageInput").fill("공유 대화폭 반응형 검증")
    await page.locator("#sendButton").click()
    await page.locator('.app-shell[data-state="chat"]').wait_for(state="attached")
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-content')?.textContent?.includes('지금은 미리보기 환경입니다')",
        timeout=15_000,
    )
    await page.wait_for_timeout(450)

    # Deterministic layout fixtures: verify wide answer/error surfaces and
    # readable prose measure without requiring another runtime/provider path.
    await page.evaluate(
        """
        () => {
          const content = document.querySelector('#messageList .assistant-content');
          if (!content) throw new Error('assistant content missing');

          const rich = document.createElement('div');
          rich.id = 'shared-gutter-rich-fixture';
          rich.className = 'rich-response';
          const paragraph = document.createElement('p');
          paragraph.className = 'rich-response-paragraph';
          paragraph.textContent = '긴 답변 읽기 폭 검증 문장입니다. '.repeat(36);
          rich.appendChild(paragraph);
          content.appendChild(rich);

          const error = document.createElement('div');
          error.id = 'shared-gutter-error-fixture';
          error.className = 'error-box';
          const copy = document.createElement('p');
          copy.textContent = '오류 카드 반응형 폭 검증';
          const retry = document.createElement('button');
          retry.type = 'button';
          retry.className = 'retry-button';
          retry.textContent = '다시 시도';
          error.append(copy, retry);
          content.appendChild(error);
        }
        """
    )
    await page.wait_for_timeout(80)

    conversation = await _box(page, ".conversation")
    composer = await _box(page, ".composer-wrap")
    message_list = await _box(page, "#messageList")
    user_message = await _box(page, ".user-message")
    user_bubble = await _box(page, ".user-message .message-bubble")
    assistant_message = await _box(page, ".assistant-message")
    assistant_avatar = await _box(page, ".assistant-avatar")
    assistant_body = await _box(page, ".assistant-body")
    rich_surface = await _box(page, "#shared-gutter-rich-fixture")
    prose = await _box(page, "#shared-gutter-rich-fixture .rich-response-paragraph")
    error_surface = await _box(page, "#shared-gutter-error-fixture")
    retry_control = await _box(page, "#shared-gutter-error-fixture .retry-button")

    # Resolve the actual used padding rather than parsing the raw custom-property
    # token. The token uses clamp(), so parseFloat('--padiem-chat-inner-gutter')
    # is NaN even when the browser has correctly resolved it to a pixel value.
    conversation_padding = await page.locator(".conversation").evaluate(
        """
        (el) => {
          const style = getComputedStyle(el);
          return {
            left: Number.parseFloat(style.paddingLeft) || 0,
            right: Number.parseFloat(style.paddingRight) || 0,
          };
        }
        """
    )
    inner_gutter_left = round(float(conversation_padding["left"]), 2)
    inner_gutter_right = round(float(conversation_padding["right"]), 2)

    # Resolve the declared reading-measure token using the paragraph's actual
    # font metrics. A ch unit is font-dependent, so an arbitrary pixel ceiling
    # would reject a correctly applied 76ch measure on some platforms/fonts.
    prose_measure = await page.locator(
        "#shared-gutter-rich-fixture .rich-response-paragraph"
    ).evaluate(
        """
        (el) => {
          const shell = el.closest('.app-shell');
          if (!shell) throw new Error('app shell missing');
          const token = getComputedStyle(shell)
            .getPropertyValue('--padiem-chat-reading-measure')
            .trim();
          if (!token) throw new Error('reading measure token missing');

          const style = getComputedStyle(el);
          const probe = document.createElement('div');
          probe.style.position = 'absolute';
          probe.style.visibility = 'hidden';
          probe.style.pointerEvents = 'none';
          probe.style.inlineSize = token;
          probe.style.font = style.font;
          probe.style.letterSpacing = style.letterSpacing;
          document.body.appendChild(probe);
          const px = probe.getBoundingClientRect().width;
          probe.remove();
          return { token, px };
        }
        """
    )
    prose_measure_token = str(prose_measure["token"])
    prose_measure_px = round(float(prose_measure["px"]), 2)
    if prose_measure_px <= 0:
        raise AssertionError(f"{name} reading measure did not resolve: {prose_measure}")

    # Outer shell contract: conversation and composer are exactly one lane.
    _assert_close(conversation["x"], composer["x"], name=f"{name} outer left gutter")
    _assert_close(_right(conversation), _right(composer), name=f"{name} outer right gutter")
    _assert_close(conversation["width"], composer["width"], name=f"{name} outer lane width")

    # Internal identity rail contract: message content starts inside the actual
    # bounded, symmetric conversation padding instead of flattening avatar/meta.
    _assert_close(
        message_list["x"] - conversation["x"],
        inner_gutter_left,
        name=f"{name} message-list left inner gutter",
    )
    _assert_close(
        _right(conversation) - _right(message_list),
        inner_gutter_right,
        name=f"{name} message-list right inner gutter",
    )
    _assert_close(
        inner_gutter_left,
        inner_gutter_right,
        name=f"{name} symmetric conversation inner gutter",
    )
    _assert_close(assistant_avatar["x"], message_list["x"], name=f"{name} avatar rail start")

    # User and wide assistant/error surfaces recover the right-side inner
    # gutter and terminate at the same composer/conversation outer boundary.
    _assert_close(_right(user_message), _right(conversation), name=f"{name} user outer right")
    _assert_close(_right(user_bubble), _right(conversation), name=f"{name} user bubble right")
    _assert_close(_right(rich_surface), _right(conversation), name=f"{name} rich answer right")
    _assert_close(_right(error_surface), _right(conversation), name=f"{name} error card right")

    assistant_gap = round(assistant_body["x"] - _right(assistant_avatar), 2)
    if assistant_gap < 8 or assistant_gap > 12.5:
        raise AssertionError(f"{name} assistant meta/content gap out of range: {assistant_gap}")

    if prose["width"] > prose_measure_px + 1.5:
        raise AssertionError(
            f"{name} prose exceeds {prose_measure_token} measure: "
            f"{prose['width']} vs {prose_measure_px}"
        )
    if rich_surface["width"] > prose_measure_px + 8 and prose["width"] >= rich_surface["width"] - 1.5:
        raise AssertionError(
            f"{name} prose failed to stay narrower than wide answer surface: "
            f"{prose['width']} vs {rich_surface['width']}"
        )
    if retry_control["width"] <= 0 or retry_control["height"] <= 0:
        raise AssertionError(f"{name} retry control disappeared: {retry_control}")

    html_metrics = await page.evaluate(
        """
        () => ({
          scrollWidth: document.documentElement.scrollWidth,
          innerWidth: window.innerWidth,
        })
        """
    )
    if html_metrics["scrollWidth"] > html_metrics["innerWidth"] + 1:
        raise AssertionError(f"{name} horizontal overflow: {html_metrics}")

    screenshot = f"{name}-shared-gutter.png"
    await page.screenshot(path=str(OUT_DIR / screenshot), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "conversation": conversation,
        "composer": composer,
        "inner_gutter_left_px": inner_gutter_left,
        "inner_gutter_right_px": inner_gutter_right,
        "message_list": message_list,
        "user_message": user_message,
        "user_bubble": user_bubble,
        "assistant_message": assistant_message,
        "assistant_avatar": assistant_avatar,
        "assistant_body": assistant_body,
        "assistant_gap_px": assistant_gap,
        "rich_surface": rich_surface,
        "prose": prose,
        "prose_measure_token": prose_measure_token,
        "prose_measure_px": prose_measure_px,
        "error_surface": error_surface,
        "retry_control": retry_control,
        "horizontal_overflow": False,
        "outer_gutter_parity": True,
        "meta_subgrid_preserved": True,
        "user_bubble_right_aligned": True,
        "rich_answer_right_aligned": True,
        "error_card_right_aligned": True,
        "screenshot": screenshot,
        "status": "PASS",
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "purpose": "B62 shared outer gutter plus preserved internal meta rail and responsive answer surfaces",
        "views": {},
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for name, width, height in VIEWPORTS:
                page = await browser.new_page()
                try:
                    report["views"][name] = await _capture(
                        page, name=name, width=width, height=height
                    )
                finally:
                    await page.close()
        finally:
            await browser.close()

    report["status"] = "PASS"
    report_path = OUT_DIR / "shared-gutter-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
