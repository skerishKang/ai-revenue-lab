from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Route, async_playwright


BASE_URL = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

QUESTION = (
    "장문 응답 무손실 검증을 위해 구조화된 상세 답변을 끝까지 작성해줘. "
    "제목, 문단, 목록, 코드, 표를 포함하고 중간에 요약하거나 생략하지 마."
)


def _build_long_answer() -> str:
    sections: list[str] = [
        "# Padiem Chat 장문 응답 무손실 검증",
        (
            "이 답변은 브라우저가 긴 스트리밍 결과를 임의로 자르지 않고, 완료 후에도 동일한 원문을 "
            "복사와 다운로드에 사용하는지 확인하기 위한 결정론적 테스트 데이터입니다."
        ),
        "## 핵심 조건",
        "- 스트리밍 원문은 끝까지 보존되어야 합니다.\n- 완료 전에는 터미널 작업이 노출되면 안 됩니다.\n- 완료 후 Markdown, 코드, 표가 안전하게 구조화되어야 합니다.",
        "## 코드 예시",
        "```python\ndef verify_fidelity(streamed: str, completed: str) -> bool:\n    return streamed == completed and len(completed) >= 6000\n```",
        "## 표 예시",
        "| 검증 축 | 기대값 | 비고 |\n| --- | --- | --- |\n| SSE | 원문 전체 | truncation 0 |\n| DOM | 원문 전체 | rich source 보존 |\n| Copy | DOM과 동일 | 완료 후만 허용 |\n| Download | DOM과 동일 | UTF-8 텍스트 |",
    ]
    repeated = (
        "사용자가 명시적으로 긴 설명을 요구한 경우 제품 표면은 모델이 반환한 텍스트를 임의로 축약하거나 "
        "문자 수 기준으로 잘라서는 안 됩니다. 긴 문단, 한국어와 영문 토큰, 숫자 0123456789, 문장부호를 "
        "포함한 상태에서도 스트림 조립과 완료 상태 전환, 스크롤 위치, 저장 가능한 원문 경계가 동일해야 합니다. "
        "또한 구조화된 답변은 읽기 폭을 유지하면서 코드와 표 같은 넓은 콘텐츠만 작업공간 폭을 활용해야 합니다."
    )
    for index in range(1, 25):
        sections.append(f"## 상세 검증 섹션 {index:02d}")
        sections.append(f"{index:02d}. {repeated} {repeated}")
    sections.append("## 종료 표식")
    sections.append("LONG_ANSWER_END_SENTINEL_1887")
    answer = "\n\n".join(sections)
    if len(answer) < 6000:
        raise AssertionError(f"long-answer fixture unexpectedly short: {len(answer)}")
    return answer


LONG_ANSWER = _build_long_answer()


async def _reply_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
        headers={"Cache-Control": "no-store"},
    )


async def _install_api(page: Page, request_bodies: list[dict[str, Any]]) -> None:
    async def auth(route: Route) -> None:
        await _reply_json(
            route,
            {
                "ready": True,
                "authenticated": False,
                "session_state": "guest",
                "history_ready": False,
                "project_files_ready": False,
                "user": None,
            },
        )

    async def orchestration_status(route: Route) -> None:
        await _reply_json(route, {"orchestration_ready": False, "authenticated": False})

    async def stream(route: Route) -> None:
        raw = route.request.post_data or "{}"
        body = json.loads(raw)
        if not isinstance(body, dict):
            raise AssertionError(f"chat request must be an object: {body!r}")
        if body.get("mode") != "auto":
            raise AssertionError(f"browser escaped provider-neutral Auto mode: {body!r}")
        if any(key in body for key in ("provider", "model", "route", "credential", "max_tokens")):
            raise AssertionError(f"browser asserted hidden execution authority: {body!r}")
        request_bodies.append(body)

        frames: list[str] = []
        for cursor in range(0, len(LONG_ANSWER), 233):
            delta = LONG_ANSWER[cursor : cursor + 233]
            frames.append(
                "event: delta\n"
                f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
            )
        frames.append(
            "event: done\n"
            f"data: {json.dumps({'done': True, 'conversation_id': 'chat_long_fidelity_1887'})}\n\n"
        )
        await asyncio.sleep(0.15)
        await route.fulfill(
            status=200,
            content_type="text/event-stream; charset=utf-8",
            body="".join(frames),
            headers={"Cache-Control": "no-store"},
        )

    await page.route("**/api/auth/status", auth)
    await page.route("**/api/orchestration/status", orchestration_status)
    await page.route("**/api/chat/stream", stream)


async def _no_horizontal_overflow(page: Page, label: str) -> None:
    metrics = await page.evaluate(
        "() => ({scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth})"
    )
    if metrics["scrollWidth"] > metrics["innerWidth"] + 1:
        raise AssertionError(f"horizontal overflow at {label}: {metrics}")


async def _open_context(browser: Browser, viewport: dict[str, int]) -> BrowserContext:
    context = await browser.new_context(viewport=viewport)
    await context.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE_URL)
    return context


async def _submit_long_answer(page: Page, requests: list[dict[str, Any]]) -> None:
    await _install_api(page, requests)
    await page.goto(
        f"{BASE_URL}/?theme=padiem-glass&glass=female",
        wait_until="domcontentloaded",
        timeout=30_000,
    )
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_function("() => Boolean(window.PadiemChatInteractionPresentation)")
    await page.locator("#messageInput").fill(QUESTION)
    await page.locator("#sendButton").click()
    await page.wait_for_function(
        "() => ['preparing', 'streaming'].includes(document.querySelector('#composerForm')?.dataset.interactionPhase)",
        timeout=5_000,
    )
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-message:last-child')?.dataset.lifecycle === 'completed'",
        timeout=15_000,
    )
    await page.locator("#messageList .assistant-message:last-child .rich-response").wait_for(
        state="visible", timeout=5_000
    )
    if len(requests) != 1:
        raise AssertionError(f"expected one deterministic stream request, got {len(requests)}")


async def _desktop_long_answer_probe(browser: Browser) -> dict[str, Any]:
    context = await _open_context(browser, {"width": 1920, "height": 1080})
    page = await context.new_page()
    requests: list[dict[str, Any]] = []
    try:
        await _submit_long_answer(page, requests)
        assistant = page.locator("#messageList .assistant-message:last-child")
        source = assistant.locator(".assistant-content > p.rich-response-source")
        raw_dom = await source.text_content()
        if raw_dom != LONG_ANSWER:
            raise AssertionError(
                f"completed DOM source lost streamed bytes: {len(raw_dom or '')} != {len(LONG_ANSWER)}"
            )
        if "LONG_ANSWER_END_SENTINEL_1887" not in raw_dom:
            raise AssertionError("long-answer terminal sentinel missing")

        rich = assistant.locator(".rich-response")
        if await rich.locator(".rich-code-block").count() < 1:
            raise AssertionError("long-answer code block did not finalize")
        if await rich.locator("table").count() < 1:
            raise AssertionError("long-answer table did not finalize")
        if await rich.locator(".rich-response-heading").count() < 8:
            raise AssertionError("long-answer headings did not finalize")
        if await assistant.get_attribute("data-terminal-actions-safe") != "true":
            raise AssertionError("completed long answer is not terminal-action safe")

        copy_button = assistant.locator(".answer-copy")
        await copy_button.wait_for(state="visible")
        await copy_button.click()
        copied = await page.evaluate("navigator.clipboard.readText()")
        if copied != LONG_ANSWER:
            raise AssertionError(f"copy source fidelity failed: {len(copied)} != {len(LONG_ANSWER)}")

        download_target = OUT_DIR / "long-answer-fidelity-download.txt"
        async with page.expect_download() as download_info:
            await assistant.locator(".answer-download").click()
        download = await download_info.value
        await download.save_as(str(download_target))
        downloaded = download_target.read_text(encoding="utf-8")
        if downloaded != LONG_ANSWER:
            raise AssertionError(
                f"download source fidelity failed: {len(downloaded)} != {len(LONG_ANSWER)}"
            )

        conversation_box = await page.locator(".conversation").bounding_box()
        composer_box = await page.locator(".composer-wrap").bounding_box()
        prose_box = await rich.locator(".rich-response-paragraph").first.bounding_box()
        rich_box = await rich.bounding_box()
        if not conversation_box or not composer_box or not prose_box or not rich_box:
            raise AssertionError("desktop geometry unavailable")
        if conversation_box["width"] < 1000 or conversation_box["width"] > 1100:
            raise AssertionError(f"large desktop active-chat lane out of target: {conversation_box}")
        if abs(conversation_box["width"] - composer_box["width"]) > 1.5:
            raise AssertionError(
                f"conversation/composer width drift: {conversation_box['width']} vs {composer_box['width']}"
            )
        if abs(conversation_box["x"] - composer_box["x"]) > 1.5:
            raise AssertionError(
                f"conversation/composer left gutter drift: {conversation_box['x']} vs {composer_box['x']}"
            )
        if rich_box["width"] <= prose_box["width"] + 30:
            raise AssertionError(
                f"wide rich surface did not exceed prose measure: {rich_box['width']} vs {prose_box['width']}"
            )

        await _no_horizontal_overflow(page, "desktop-long-answer")
        await page.screenshot(
            path=str(OUT_DIR / "post-certification-desktop-long-answer.png"),
            full_page=True,
        )
        return {
            "status": "PASS",
            "stream_chars": len(LONG_ANSWER),
            "dom_source_chars": len(raw_dom),
            "copy_chars": len(copied),
            "download_chars": len(downloaded),
            "terminal_sentinel": True,
            "rich_headings": await rich.locator(".rich-response-heading").count(),
            "code_blocks": await rich.locator(".rich-code-block").count(),
            "tables": await rich.locator("table").count(),
            "conversation_width": round(float(conversation_box["width"]), 2),
            "composer_width": round(float(composer_box["width"]), 2),
            "prose_width": round(float(prose_box["width"]), 2),
            "rich_width": round(float(rich_box["width"]), 2),
            "horizontal_overflow": 0,
        }
    finally:
        await context.close()


async def _mobile_keyboard_probe(browser: Browser) -> dict[str, Any]:
    context = await _open_context(browser, {"width": 390, "height": 844})
    page = await context.new_page()
    requests: list[dict[str, Any]] = []
    try:
        await _submit_long_answer(page, requests)
        await page.set_viewport_size({"width": 390, "height": 540})
        await page.evaluate("window.dispatchEvent(new Event('resize'))")
        await page.wait_for_timeout(80)

        multiline = "첫째 줄\n둘째 줄\n셋째 줄\n넷째 줄\n다섯째 줄\n여섯째 줄"
        await page.locator("#messageInput").fill(multiline)
        await page.wait_for_timeout(60)
        textarea_box = await page.locator("#messageInput").bounding_box()
        composer_box = await page.locator(".composer-wrap").bounding_box()
        if not textarea_box or not composer_box:
            raise AssertionError("mobile composer geometry unavailable")
        if textarea_box["height"] <= 70 or textarea_box["height"] > 181:
            raise AssertionError(f"multiline composer did not auto-grow within bounds: {textarea_box}")
        if composer_box["y"] + composer_box["height"] > 541:
            raise AssertionError(f"composer left resized mobile viewport: {composer_box}")
        if not await page.locator("#sendButton").is_visible() or await page.locator("#sendButton").is_disabled():
            raise AssertionError("send control unavailable with multiline mobile composer")

        # Software keyboards can overlay rather than resize the layout viewport.
        # Exercise the CSS contract deterministically without claiming a physical
        # iOS/Android keyboard run.
        await page.evaluate(
            "document.documentElement.style.setProperty('--padiem-visual-keyboard-inset', '180px')"
        )
        await page.wait_for_timeout(50)
        overlay_box = await page.locator(".composer-wrap").bounding_box()
        if not overlay_box or overlay_box["y"] + overlay_box["height"] > 361:
            raise AssertionError(f"overlay keyboard inset did not lift composer: {overlay_box}")

        await page.evaluate(
            "document.documentElement.style.setProperty('--padiem-visual-keyboard-inset', '0px')"
        )
        await page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        await page.wait_for_timeout(80)
        assistant_box = await page.locator("#messageList .assistant-message:last-child").bounding_box()
        settled_composer_box = await page.locator(".composer-wrap").bounding_box()
        if not assistant_box or not settled_composer_box:
            raise AssertionError("mobile latest-answer geometry unavailable")
        if assistant_box["y"] + assistant_box["height"] > settled_composer_box["y"] + 3:
            raise AssertionError(
                f"latest answer is covered by composer: {assistant_box} vs {settled_composer_box}"
            )

        await _no_horizontal_overflow(page, "mobile-keyboard")
        await page.screenshot(
            path=str(OUT_DIR / "post-certification-mobile-keyboard.png"),
            full_page=True,
        )
        return {
            "status": "PASS",
            "viewport": {"width": 390, "height": 540},
            "textarea_height": round(float(textarea_box["height"]), 2),
            "composer_bottom": round(float(composer_box["y"] + composer_box["height"]), 2),
            "overlay_keyboard_inset": 180,
            "overlay_composer_bottom": round(float(overlay_box["y"] + overlay_box["height"]), 2),
            "latest_answer_clears_composer": True,
            "horizontal_overflow": 0,
            "physical_device_claim": False,
        }
    finally:
        await context.close()


async def main() -> None:
    report: dict[str, Any] = {
        "status": "RUNNING",
        "issue": 1887,
        "long_stream_payload_chars": len(LONG_ANSWER),
        "client_side_length_limit_added": False,
        "production_mutation": False,
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            report["desktop"] = await _desktop_long_answer_probe(browser)
            report["mobile"] = await _mobile_keyboard_probe(browser)
        finally:
            await browser.close()

    if report["long_stream_payload_chars"] < 6000:
        raise AssertionError("long stream fixture must be at least 6000 characters")
    report["long_stream_dom_fidelity"] = "PASS"
    report["copy_download_source_fidelity"] = "PASS"
    report["rich_response_long_content"] = "PASS"
    report["large_desktop_active_chat_width"] = "PASS"
    report["mobile_keyboard_approximation"] = "PASS"
    report["multiline_composer"] = "PASS"
    report["latest_answer_clears_composer"] = "PASS"
    report["client_side_truncation"] = 0
    report["horizontal_overflow"] = 0
    report["status"] = "PASS"

    report_path = OUT_DIR / "post-certification-hardening-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
