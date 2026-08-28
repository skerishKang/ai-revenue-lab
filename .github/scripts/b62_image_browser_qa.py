from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_IMAGE_QA_BASE_URL", "http://127.0.0.1:8768")
OUT_DIR = Path(os.environ.get("B62_IMAGE_QA_OUT_DIR", ".tmp/b62-image-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

IMAGE_NAME = "browser-photo.png"
IMAGE_MIME = "image/png"
# Small valid 1x1 PNG used only as a deterministic browser fixture.
IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9ZQmcAAAAASUVORK5CYII="
IMAGE_BYTES = base64.b64decode(IMAGE_BASE64)
QUESTION = "첨부한 사진이 전달된 상태인지 간단히 알려줘"


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
        raise AssertionError(f"image browser QA must run in mock runtime: {health}")
    if health.get("live_enabled") is not False:
        raise AssertionError(f"live model execution must remain disabled: {health}")
    if health.get("web_tools_ready") is not False:
        raise AssertionError(f"web tools must stay off in image-only QA: {health}")

    if mobile and not await page.locator("#mobileMenu").is_visible():
        raise AssertionError("mobile menu must remain visible on mobile viewport")

    file_input = page.locator("#attachmentFileInput")
    await file_input.set_input_files(
        {
            "name": IMAGE_NAME,
            "mimeType": IMAGE_MIME,
            "buffer": IMAGE_BYTES,
        }
    )

    tray = page.locator("#attachmentTray")
    await tray.wait_for(state="visible", timeout=5_000)
    attachment_name = (await page.locator("#attachmentName").inner_text()).strip()
    attachment_size = (await page.locator("#attachmentSize").inner_text()).strip()
    note = (await page.locator("#runtimeNote").inner_text()).strip()
    thumb = page.locator("#attachmentThumb")

    if attachment_name != IMAGE_NAME:
        raise AssertionError(f"wrong attachment filename shown: {attachment_name!r}")
    if not attachment_size:
        raise AssertionError("image byte size must be visible")
    if not await thumb.is_visible():
        raise AssertionError("image thumbnail must be visible after selection")
    thumb_src = await thumb.get_attribute("src")
    if not thumb_src or not thumb_src.startswith("blob:"):
        raise AssertionError(f"thumbnail must use a local blob preview: {thumb_src!r}")
    if "한 번만 전송" not in note:
        raise AssertionError(f"image one-request note is unclear: {note!r}")

    await _assert_no_horizontal_overflow(page, f"{name}-attachment")
    await page.screenshot(path=str(OUT_DIR / f"{name}-image-ready.png"), full_page=True)

    await page.locator("#messageInput").fill(QUESTION)
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("send button stayed disabled after image question input")
    await page.locator("#sendButton").click()

    assistant = page.locator("#messageList .assistant-message").last
    await assistant.wait_for(state="visible", timeout=10_000)
    await page.wait_for_function(
        "() => { const items = document.querySelectorAll('#messageList .assistant-message'); if (!items.length) return false; const last = items[items.length - 1]; return !last.querySelector('.typing') && Boolean(last.querySelector('.assistant-content p')); }",
        timeout=10_000,
    )

    answer_text = (await assistant.locator(".assistant-content").inner_text()).strip()
    runtime_label = (await assistant.locator("[data-runtime-label]").inner_text()).strip()
    if "실제 모델 호출이나 이미지 분석은 하지 않았습니다" not in answer_text:
        raise AssertionError(f"mock image-analysis truth boundary missing: {answer_text!r}")
    if "모의 응답" not in runtime_label or "실제 모델 호출 없음" not in runtime_label:
        raise AssertionError(f"mock truth label missing: {runtime_label!r}")

    user_message = page.locator("#messageList .user-message").last
    user_text = (await user_message.inner_text()).strip()
    if QUESTION not in user_text:
        raise AssertionError("visible user message lost the question")
    if f"사진 · {IMAGE_NAME}" not in user_text:
        raise AssertionError(f"visible image metadata missing: {user_text!r}")
    if IMAGE_BASE64 in user_text or "data:image" in user_text:
        raise AssertionError("raw image payload leaked into visible user message")

    await page.wait_for_function(
        "() => document.getElementById('attachmentTray')?.hidden === true",
        timeout=5_000,
    )

    if len(chat_posts) != 1:
        raise AssertionError(f"expected exactly one chat POST, saw {chat_posts!r}")
    post = chat_posts[0]
    if post["path"] != "/api/chat":
        raise AssertionError(f"image attachment must use completed /api/chat once: {post!r}")
    payload = post["payload"]
    if not isinstance(payload, dict):
        raise AssertionError(f"chat payload must be an object: {payload!r}")
    attachments = payload.get("attachments")
    if not isinstance(attachments, list) or len(attachments) != 1:
        raise AssertionError(f"expected exactly one image attachment: {attachments!r}")
    image = attachments[0]
    expected = {
        "type": "image",
        "name": IMAGE_NAME,
        "media_type": IMAGE_MIME,
        "base64": IMAGE_BASE64,
    }
    for key, value in expected.items():
        if image.get(key) != value:
            raise AssertionError(f"image payload mismatch for {key}: {image!r}")
    if any(key in payload for key in ("model", "provider", "route", "business14")):
        raise AssertionError(f"browser payload must not select model/provider routing: {payload!r}")
    if payload.get("tool"):
        raise AssertionError(f"image-only QA must not activate a web/research tool: {payload!r}")

    body_text = await page.locator("body").inner_text()
    if IMAGE_BASE64 in body_text or "data:image" in body_text:
        raise AssertionError("raw image payload leaked into visible page text")
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
    await page.screenshot(path=str(OUT_DIR / f"{name}-image-result.png"), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "health": {
            "runtime": health.get("runtime"),
            "web_tools_ready": health.get("web_tools_ready"),
            "live_enabled": health.get("live_enabled"),
        },
        "attachment_tray": "PASS",
        "attachment_name": attachment_name,
        "thumbnail_visible": True,
        "attachment_size_visible": True,
        "one_request_note": "PASS",
        "chat_post_count": len(chat_posts),
        "chat_post_path": post["path"],
        "image_payload": "PASS",
        "visible_user_image_metadata": "PASS",
        "visible_answer": "PASS",
        "mock_no_real_image_analysis": "PASS",
        "raw_image_visible_leak": False,
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
        "real_image_analysis_expected": 0,
        "image_name": IMAGE_NAME,
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
