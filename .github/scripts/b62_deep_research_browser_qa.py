from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_DEEP_RESEARCH_QA_BASE_URL", "http://127.0.0.1:8773")
OUT_DIR = Path(os.environ.get("B62_DEEP_RESEARCH_QA_OUT_DIR", ".tmp/b62-deep-research-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)


async def _assert_no_horizontal_overflow(page: Page, name: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(
            f"horizontal overflow at {name}: scrollWidth={scroll_width}, innerWidth={inner_width}"
        )


def _research_payload(status: str) -> dict[str, Any]:
    evidence = [
        {
            "id": f"source-{index}",
            "title": f"공개 자료 {index}",
            "url": f"https://example{index}.com/research/{index}",
            "snippet": f"검증용 공개 자료 {index} 요약",
        }
        for index in range(1, 12)
    ]
    return {
        "answer": "여러 공개 자료를 비교해 핵심 차이와 공통점을 정리했습니다.",
        "answer_status": "deep_research_answered",
        "tool": {"id": "deep_research", "title": "심층 리서치"},
        "evidence": evidence,
        "research": {
            "status": status,
            "searches_completed": 3,
            "source_count": 10,
        },
        # Deliberately include internal-looking fixture fields. The product UI must
        # ignore them rather than expose route/model/provider identity.
        "selected_provider": "fixture-provider-not-for-ui",
        "selected_model": "fixture-model-not-for-ui",
    }


async def _run_view(
    page: Page,
    *,
    name: str,
    width: int,
    height: int,
    research_status: str,
) -> dict[str, Any]:
    await page.set_viewport_size({"width": width, "height": height})

    chat_posts: list[dict[str, Any]] = []

    async def route_handler(route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)

        if parsed.path == "/health":
            await route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "runtime": "mock",
                        "live_enabled": False,
                        "web_tools_ready": True,
                        "deep_research_ready": True,
                    }
                ),
            )
            return

        if request.method == "POST" and parsed.path in {"/api/chat", "/api/chat/stream"}:
            payload: Any = None
            if request.post_data:
                try:
                    payload = json.loads(request.post_data)
                except json.JSONDecodeError:
                    payload = request.post_data
            chat_posts.append({"path": parsed.path, "payload": payload})

            if parsed.path == "/api/chat":
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(_research_payload(research_status), ensure_ascii=False),
                )
                return

            body = "".join(
                [
                    f"event: delta\ndata: {json.dumps({'delta': '일반 대화로 돌아왔습니다.'}, ensure_ascii=False)}\n\n",
                    f"event: done\ndata: {json.dumps({'done': True}, ensure_ascii=False)}\n\n",
                ]
            )
            await route.fulfill(
                status=200,
                headers={
                    "Content-Type": "text/event-stream; charset=utf-8",
                    "Cache-Control": "no-cache, no-store",
                },
                body=body,
            )
            return

        await route.continue_()

    await page.route("**/*", route_handler)
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_function(
        "() => document.getElementById('deepResearchButton') && !document.getElementById('deepResearchButton').disabled",
        timeout=10_000,
    )

    deep_button = page.locator("#deepResearchButton")
    web_button = page.locator("#webSearchButton")

    if not await deep_button.is_visible() or await deep_button.is_disabled():
        raise AssertionError("deep-research control must be visible and health-enabled")
    if not await web_button.is_visible() or await web_button.is_disabled():
        raise AssertionError("web-search control must remain available when health-ready")

    await _assert_no_horizontal_overflow(page, f"{name}-ready")
    await page.screenshot(path=str(OUT_DIR / f"{name}-deep-ready.png"), full_page=True)

    # Prove mutual exclusion before submitting the research request.
    await web_button.click()
    if await web_button.get_attribute("aria-pressed") != "true":
        raise AssertionError("web search did not enter selected state")
    await deep_button.click()
    if await deep_button.get_attribute("aria-pressed") != "true":
        raise AssertionError("deep research did not enter selected state")
    if await web_button.get_attribute("aria-pressed") != "false":
        raise AssertionError("web search and deep research must be mutually exclusive")

    note = (await page.locator("#runtimeNote").inner_text()).strip()
    if "심층 리서치" not in note or "여러 웹 자료" not in note:
        raise AssertionError(f"deep-research selected-state note is unclear: {note!r}")

    await page.screenshot(path=str(OUT_DIR / f"{name}-deep-selected.png"), full_page=True)

    question = "여러 공개 자료를 비교해서 핵심 차이를 정리해줘"
    await page.locator("#messageInput").fill(question)
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("send button stayed disabled after entering a research question")
    await page.locator("#sendButton").click()

    summary = page.locator("#messageList .assistant-message .research-summary").last
    await summary.wait_for(state="visible", timeout=15_000)
    summary_text = (await summary.inner_text()).strip()
    if "심층 리서치" not in summary_text or "검색 3회" not in summary_text or "출처 10개" not in summary_text:
        raise AssertionError(f"research summary is incomplete: {summary_text!r}")
    partial_copy = "일부 자료는 가져오지 못했습니다"
    if research_status == "partial" and partial_copy not in summary_text:
        raise AssertionError(f"partial research state is not truthfully rendered: {summary_text!r}")
    if research_status == "complete" and partial_copy in summary_text:
        raise AssertionError(f"complete research result must not claim partial failure: {summary_text!r}")

    sources = page.locator("#messageList .assistant-message .answer-sources").last
    await sources.wait_for(state="visible", timeout=10_000)
    links = sources.locator("a.answer-source-link")
    link_count = await links.count()
    if link_count != 10:
        raise AssertionError(f"deep-research source rendering must be capped at 10, saw {link_count}")

    source_rows: list[dict[str, str]] = []
    for index in range(link_count):
        link = links.nth(index)
        href = await link.get_attribute("href") or ""
        target = await link.get_attribute("target") or ""
        rel = await link.get_attribute("rel") or ""
        parsed = urlparse(href)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AssertionError(f"unsafe source href rendered: {href!r}")
        if target != "_blank":
            raise AssertionError(f"source link must open in a new tab: {target!r}")
        rel_tokens = set(rel.split())
        if not {"noopener", "noreferrer"}.issubset(rel_tokens):
            raise AssertionError(f"source link rel is incomplete: {rel!r}")
        source_rows.append({"href": href, "text": (await link.inner_text()).strip()})

    if len(chat_posts) != 1:
        raise AssertionError(f"expected one research chat POST, saw {chat_posts!r}")
    research_post = chat_posts[0]
    if research_post["path"] != "/api/chat":
        raise AssertionError(f"deep research must use completed /api/chat transport: {research_post!r}")
    research_payload = research_post["payload"]
    if not isinstance(research_payload, dict) or research_payload.get("tool") != "deep_research":
        raise AssertionError(f"deep_research tool marker missing: {research_payload!r}")
    if any(key in research_payload for key in ("model", "provider", "route", "business14")):
        raise AssertionError(f"browser payload must not select provider/model routing: {research_payload!r}")

    await page.wait_for_function(
        "() => document.getElementById('deepResearchButton')?.getAttribute('aria-pressed') === 'false'",
        timeout=5_000,
    )

    # A subsequent ordinary question must go back to streaming with no tool marker.
    await page.locator("#messageInput").fill("이제 일반 대화로 한 문장만 답해줘")
    await page.locator("#sendButton").click()
    await page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#messageList .assistant-message .assistant-content')).some((el) => el.textContent.includes('일반 대화로 돌아왔습니다.'))",
        timeout=10_000,
    )

    if len(chat_posts) != 2:
        raise AssertionError(f"expected research + one ordinary request, saw {chat_posts!r}")
    ordinary_post = chat_posts[1]
    if ordinary_post["path"] != "/api/chat/stream":
        raise AssertionError(f"ordinary request must return to stream transport: {ordinary_post!r}")
    ordinary_payload = ordinary_post["payload"]
    if isinstance(ordinary_payload, dict) and ordinary_payload.get("tool") is not None:
        raise AssertionError(f"one-request Deep Research state leaked into next request: {ordinary_payload!r}")

    body_text = await page.locator("body").inner_text()
    forbidden_identity = (
        "fixture-provider-not-for-ui",
        "fixture-model-not-for-ui",
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
        raise AssertionError(f"provider/model identity leaked into product UI: {leaked}")

    await _assert_no_horizontal_overflow(page, f"{name}-result")
    await page.screenshot(path=str(OUT_DIR / f"{name}-deep-result.png"), full_page=True)

    return {
        "viewport": {"width": width, "height": height},
        "research_status": research_status,
        "mutual_exclusion": "PASS",
        "selected_state": "PASS",
        "research_post_path": research_post["path"],
        "research_tool": research_payload.get("tool"),
        "summary": summary_text,
        "source_count": link_count,
        "source_links": source_rows,
        "one_request_reset": "PASS",
        "next_request_path": ordinary_post["path"],
        "next_request_tool": ordinary_payload.get("tool") if isinstance(ordinary_payload, dict) else None,
        "concrete_model_provider_leak": [],
        "horizontal_overflow": False,
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "fixture_only": True,
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
                research_status="complete",
            )
            await desktop.close()

            mobile = await browser.new_page()
            report["views"]["mobile"] = await _run_view(
                mobile,
                name="mobile",
                width=390,
                height=844,
                research_status="partial",
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
