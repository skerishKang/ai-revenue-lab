from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, async_playwright


BASE_URL = os.environ.get("B62_WEB_QA_BASE_URL", "http://127.0.0.1:8766")
OUT_DIR = Path(os.environ.get("B62_WEB_QA_OUT_DIR", ".tmp/b62-web-search-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)


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
    await page.wait_for_function(
        "() => document.getElementById('webSearchButton') && !document.getElementById('webSearchButton').disabled",
        timeout=10_000,
    )

    health = await page.evaluate(
        "async () => { const r = await fetch('/health'); return await r.json(); }"
    )
    if health.get("runtime") != "mock":
        raise AssertionError(f"browser QA must run in mock runtime: {health}")
    if health.get("web_tools_ready") is not True:
        raise AssertionError(f"mock web search must be health-ready: {health}")
    if health.get("deep_research_ready") is not False:
        raise AssertionError(f"deep research must remain unavailable in mock runtime: {health}")
    if health.get("live_enabled") is not False:
        raise AssertionError(f"live model execution must remain disabled: {health}")

    web_button = page.locator("#webSearchButton")
    web_starter = page.locator("#webSearchStarterButton")
    deep_button = page.locator("#deepResearchButton")

    if not await web_button.is_visible() or await web_button.is_disabled():
        raise AssertionError("web-search composer control must be visible and enabled")
    if not await web_starter.is_visible() or await web_starter.is_disabled():
        raise AssertionError("web-search starter must be visible and enabled")
    if not await deep_button.is_disabled():
        raise AssertionError("deep research must remain disabled in mock runtime")

    if mobile and not await page.locator("#mobileMenu").is_visible():
        raise AssertionError("mobile menu must remain visible on mobile viewport")

    await _assert_no_horizontal_overflow(page, f"{name}-ready")
    await page.screenshot(path=str(OUT_DIR / f"{name}-web-ready.png"), full_page=True)

    await web_button.click()
    if await web_button.get_attribute("aria-pressed") != "true":
        raise AssertionError("web search must expose an active pressed state")
    note = (await page.locator("#runtimeNote").inner_text()).strip()
    if "웹에서 찾아" not in note or "출처" not in note:
        raise AssertionError(f"web-search selected-state note is unclear: {note!r}")

    question = "오늘 공개된 AI 정책을 웹에서 찾아 핵심만 알려줘"
    await page.locator("#messageInput").fill(question)
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("send button stayed disabled after entering a web-search question")
    await page.locator("#sendButton").click()

    sources = page.locator("#messageList .assistant-message .answer-sources").last
    await sources.wait_for(state="visible", timeout=15_000)
    answer = page.locator("#messageList .assistant-message .assistant-content").last
    answer_text = (await answer.inner_text()).strip()
    if not answer_text:
        raise AssertionError("web-search answer must be visibly rendered")

    links = sources.locator("a.answer-source-link")
    link_count = await links.count()
    if link_count < 1:
        raise AssertionError("web-search result must render at least one source link")

    source_rows: list[dict[str, str]] = []
    for index in range(link_count):
        link = links.nth(index)
        href = await link.get_attribute("href") or ""
        target = await link.get_attribute("target") or ""
        rel = await link.get_attribute("rel") or ""
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AssertionError(f"unsafe/non-public source href rendered: {href!r}")
        if target != "_blank":
            raise AssertionError(f"source link must open in a new tab: {target!r}")
        rel_tokens = set(rel.split())
        if not {"noopener", "noreferrer"}.issubset(rel_tokens):
            raise AssertionError(f"source link rel is incomplete: {rel!r}")
        source_rows.append({
            "href": href,
            "text": (await link.inner_text()).strip(),
        })

    # The compatibility layer converts a tool-enabled stream request into exactly
    # one completed /api/chat request. There must be no second model dispatch.
    if len(chat_posts) != 1:
        raise AssertionError(f"expected exactly one chat POST, saw {chat_posts!r}")
    post = chat_posts[0]
    if post["path"] != "/api/chat":
        raise AssertionError(f"web tool must use completed chat path once: {post!r}")
    payload = post["payload"]
    if not isinstance(payload, dict) or payload.get("tool") != "web_search":
        raise AssertionError(f"web_search tool marker missing from request: {payload!r}")
    if any(key in payload for key in ("model", "provider", "route", "business14")):
        raise AssertionError(f"browser payload must not select model/provider routing: {payload!r}")

    # Tool choice is one-request-only and must clear after completion.
    await page.wait_for_function(
        "() => document.getElementById('webSearchButton')?.getAttribute('aria-pressed') === 'false'",
        timeout=5_000,
    )

    body_text = await page.locator("body").inner_text()
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
    await page.screenshot(path=str(OUT_DIR / f"{name}-web-result.png"), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "health": {
            "runtime": health.get("runtime"),
            "web_tools_ready": health.get("web_tools_ready"),
            "deep_research_ready": health.get("deep_research_ready"),
            "live_enabled": health.get("live_enabled"),
        },
        "web_search_control": "PASS",
        "deep_research_mock_unavailable": "PASS",
        "selected_state": "PASS",
        "chat_post_count": len(chat_posts),
        "chat_post_path": post["path"],
        "request_tool": payload.get("tool"),
        "source_count": link_count,
        "source_links": source_rows,
        "visible_answer": "PASS",
        "concrete_model_provider_leak": [],
        "horizontal_overflow": False,
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "runtime_expectation": "mock",
        "web_provider_expectation": "mock",
        "real_web_provider_calls_expected": 0,
        "real_model_provider_calls_expected": 0,
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
