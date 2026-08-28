from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_DOCUMENT_QA_BASE_URL", "http://127.0.0.1:8767")
OUT_DIR = Path(os.environ.get("B62_DOCUMENT_QA_OUT_DIR", ".tmp/b62-document-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

DOC_NAME = "browser-notes.md"
DOC_MIME = "text/markdown"
DOC_MARKER = "B62_DOCUMENT_PRIVATE_MARKER_1021"
DOC_TEXT = f"# 브라우저 QA 메모\n{DOC_MARKER}\n핵심 일정은 금요일입니다."
QUESTION = "첨부한 메모의 핵심만 짧게 정리해줘"


async def _assert_no_horizontal_overflow(page: Page, name: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(
            f"horizontal overflow at {name}: scrollWidth={scroll_width}, innerWidth={inner_width}"
        )


async def _run_view(
    page: Page,
    *,
    name: str,
    width: int,
    height: int,
    mobile: bool,
) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})

    chat_posts: list[dict[str, Any]] = []

    def record_request(request) -> None:
        parsed = urlparse(request.url)
        if request.method == "POST" and parsed.path in {"/api/chat", "/api/chat/stream"}:
            payload: Any = None
            if request.post_data:
                try:
                    payload = json.loads(request.post_data)
                except json.JSONDecodeError:
                    payload = request.post_data
            chat_posts.append({"path": parsed.path, "payload": payload})

    page.on("request", record_request)

    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")

    health = await page.evaluate(
        "async () => { const r = await fetch('/health'); return await r.json(); }"
    )
    if health.get("runtime") != "mock":
        raise AssertionError(f"document browser QA must run in mock runtime: {health}")
    if health.get("live_enabled") is not False:
        raise AssertionError(f"live model execution must remain disabled: {health}")
    if health.get("web_tools_ready") is not False:
        raise AssertionError(f"web tools must stay off in document-only QA: {health}")

    if mobile and not await page.locator("#mobileMenu").is_visible():
        raise AssertionError("mobile menu must remain visible on mobile viewport")

    file_input = page.locator("#attachmentFileInput")
    await file_input.set_input_files(
        {
            "name": DOC_NAME,
            "mimeType": DOC_MIME,
            "buffer": DOC_TEXT.encode("utf-8"),
        }
    )

    tray = page.locator("#attachmentTray")
    await tray.wait_for(state="visible", timeout=5_000)
    attachment_name = (await page.locator("#attachmentName").inner_text()).strip()
    attachment_kind = (await page.locator("#attachmentKind").inner_text()).strip()
    attachment_size = (await page.locator("#attachmentSize").inner_text()).strip()
    note = (await page.locator("#runtimeNote").inner_text()).strip()

    if attachment_name != DOC_NAME:
        raise AssertionError(f"wrong attachment filename shown: {attachment_name!r}")
    if attachment_kind != "MD":
        raise AssertionError(f"wrong document kind shown: {attachment_kind!r}")
    if not attachment_size:
        raise AssertionError("document byte size must be visible")
    if "참고 자료" not in note or "파일 내용이 저장되지 않습니다" not in note:
        raise AssertionError(f"document privacy/reference note is unclear: {note!r}")

    await _assert_no_horizontal_overflow(page, f"{name}-attachment")
    await page.screenshot(path=str(OUT_DIR / f"{name}-document-ready.png"), full_page=True)

    await page.locator("#messageInput").fill(QUESTION)
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("send button stayed disabled after document question input")
    await page.locator("#sendButton").click()

    assistant = page.locator("#messageList .assistant-message").last
    await assistant.wait_for(state="visible", timeout=10_000)
    await page.wait_for_function(
        "() => { const items = document.querySelectorAll('#messageList .assistant-message'); if (!items.length) return false; const last = items[items.length - 1]; return !last.querySelector('.typing') && Boolean(last.querySelector('.assistant-content p')); }",
        timeout=10_000,
    )

    answer_text = (await assistant.locator(".assistant-content").inner_text()).strip()
    runtime_label = (await assistant.locator("[data-runtime-label]").inner_text()).strip()
    if not answer_text:
        raise AssertionError("mock document answer must be visible")
    if "모의 응답" not in runtime_label or "실제 모델 호출 없음" not in runtime_label:
        raise AssertionError(f"mock truth label missing: {runtime_label!r}")

    user_message = page.locator("#messageList .user-message").last
    user_text = (await user_message.inner_text()).strip()
    if QUESTION not in user_text:
        raise AssertionError("visible user message lost the question")
    if f"문서 · {DOC_NAME}" not in user_text:
        raise AssertionError(f"visible document metadata missing: {user_text!r}")
    if DOC_MARKER in user_text or DOC_MARKER in answer_text:
        raise AssertionError("raw document marker leaked into visible chat text")

    await page.wait_for_function(
        "() => document.getElementById('attachmentTray')?.hidden === true",
        timeout=5_000,
    )

    if len(chat_posts) != 1:
        raise AssertionError(f"expected exactly one chat POST, saw {chat_posts!r}")
    post = chat_posts[0]
    if post["path"] != "/api/chat":
        raise AssertionError(f"document attachment must use completed /api/chat once: {post!r}")
    payload = post["payload"]
    if not isinstance(payload, dict):
        raise AssertionError(f"chat payload must be an object: {payload!r}")
    attachments = payload.get("attachments")
    if not isinstance(attachments, list) or len(attachments) != 1:
        raise AssertionError(f"expected exactly one document attachment: {attachments!r}")
    document = attachments[0]
    expected = {
        "type": "document",
        "name": DOC_NAME,
        "media_type": DOC_MIME,
        "text": DOC_TEXT,
    }
    for key, value in expected.items():
        if document.get(key) != value:
            raise AssertionError(f"document payload mismatch for {key}: {document!r}")
    if any(key in payload for key in ("model", "provider", "route", "business14")):
        raise AssertionError(f"browser payload must not select model/provider routing: {payload!r}")

    body_text = await page.locator("body").inner_text()
    if DOC_MARKER in body_text:
        raise AssertionError("raw document body marker leaked into visible page text")
    forbidden_identity = (
        "google/gemini",
        "Gemini",
        "Agnes",
        "Poolside",
        "OpenRouter",
        "b14/auto",
        "selected_provider",
        "selected_model",
    )
    leaked = [value for value in forbidden_identity if value in body_text]
    if leaked:
        raise AssertionError(f"concrete model/provider identity leaked into product UI: {leaked}")

    await _assert_no_horizontal_overflow(page, f"{name}-result")
    await page.screenshot(path=str(OUT_DIR / f"{name}-document-result.png"), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "health": {
            "runtime": health.get("runtime"),
            "web_tools_ready": health.get("web_tools_ready"),
            "live_enabled": health.get("live_enabled"),
        },
        "attachment_tray": "PASS",
        "attachment_name": attachment_name,
        "attachment_kind": attachment_kind,
        "attachment_size_visible": True,
        "privacy_reference_note": "PASS",
        "chat_post_count": len(chat_posts),
        "chat_post_path": post["path"],
        "document_payload": "PASS",
        "visible_user_document_metadata": "PASS",
        "visible_answer": "PASS",
        "mock_truth_label": "PASS",
        "document_body_visible_leak": False,
        "attachment_cleared_after_success": True,
        "concrete_model_provider_leak": [],
        "horizontal_overflow": False,
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "runtime_expectation": "mock",
        "web_provider_expectation": "off",
        "real_web_provider_calls_expected": 0,
        "real_model_provider_calls_expected": 0,
        "document_name": DOC_NAME,
        "views": {},
    }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            desktop = await browser.new_page()
            report["views"]["desktop"] = await _run_view(
                desktop,
                name="desktop",
                width=1440,
                height=1000,
                mobile=False,
            )
            await desktop.close()

            mobile = await browser.new_page()
            report["views"]["mobile"] = await _run_view(
                mobile,
                name="mobile",
                width=390,
                height=844,
                mobile=True,
            )
            await mobile.close()
        finally:
            await browser.close()

    report["status"] = "PASS"
    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
