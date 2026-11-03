from __future__ import annotations

# 대표 결정 11-03: 수동 검색 버튼 제거.
# 심층 리서치도 사용자가 버튼을 누르는 방식이 아니라 모델/서버가 스스로 판단하며,
# 브라우저는 버튼 없이 완료 응답의 evidence(자동 grounding 결과)만 렌더링한다.
# 이 시험은 (1) 세 수동 컨트롤의 부재, (2) 리서치형 질문에서 가짜 서버 응답의
# 근거가 최대 10개까지 표시되는지를 검증한다. 이전 시험의 "버튼 선택/상호배제"
# 검증은 제거된 UI에 대한 것이므로 통째로 지우지 않고 의도만 바꿔 유지한다.

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

GROUNDED_EVIDENCE = [
    {
        "id": f"source-{index}",
        "title": f"심층 자료 {index}",
        "url": f"https://example{index}.com/research/{index}",
        "snippet": f"자동 리서치 근거 {index} 요약",
        "retrieved_at": f"2026-11-03T09:{index:02d}:00Z",
    }
    for index in range(1, 13)
]

REMOVED_CONTROLS = (
    "webSearchButton",
    "deepResearchButton",
    "webSearchStarterButton",
)


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

            answer = "여러 자료를 비교한 자동 grounding 결과를 근거와 함께 정리했습니다."
            if parsed.path == "/api/chat":
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(
                        {
                            "answer": answer,
                            "answer_status": "thorough_research_answered",
                            "evidence": GROUNDED_EVIDENCE,
                            "tool": {"id": "deep_research", "title": "심층 리서치"},
                        },
                        ensure_ascii=False,
                    ),
                )
                return

            body = "".join(
                [
                    f"event: delta\ndata: {json.dumps({'delta': answer}, ensure_ascii=False)}\n\n",
                    "event: done\ndata: "
                    + json.dumps(
                        {
                            "done": True,
                            "answer_status": "thorough_research_answered",
                            "evidence": GROUNDED_EVIDENCE,
                            "tool": {"id": "deep_research", "title": "심층 리서치"},
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n",
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

    health = await page.evaluate(
        "async () => { const r = await fetch('/health'); return await r.json(); }"
    )
    if health.get("runtime") != "mock":
        raise AssertionError(f"browser QA must run in mock runtime: {health}")
    if health.get("live_enabled") is not False:
        raise AssertionError(f"live model execution must remain disabled: {health}")

    # 대표 결정 11-03: 수동 검색/리서치 컨트롤은 화면에 없다.
    present = await page.evaluate(
        """(ids) => ids.filter((id) => document.getElementById(id) !== null)""",
        list(REMOVED_CONTROLS),
    )
    if present:
        raise AssertionError(f"manual search controls must not exist: {present}")

    if mobile and not await page.locator("#mobileMenu").is_visible():
        raise AssertionError("mobile menu must remain visible on mobile viewport")

    await _assert_no_horizontal_overflow(page, f"{name}-ready")
    await page.screenshot(path=str(OUT_DIR / f"{name}-deep-ready.png"), full_page=True)

    question = "여러 자료를 비교해서 최신 AI 정책 동향을 심층 분석해줘"
    await page.locator("#messageInput").fill(question)
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError("send button stayed disabled after entering a research question")
    await page.locator("#sendButton").click()

    sources = page.locator("#messageList .assistant-message .answer-sources").last
    await sources.wait_for(state="visible", timeout=15_000)
    answer = page.locator("#messageList .assistant-message .assistant-content").last
    answer_text = (await answer.inner_text()).strip()
    if not answer_text:
        raise AssertionError("research answer must be visibly rendered")

    links = sources.locator("a.answer-source-link")
    link_count = await links.count()
    if link_count != 10:
        raise AssertionError(f"research evidence rendering must be capped at 10, saw {link_count}")

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
    post = chat_posts[0]
    if post["path"] != "/api/chat/stream":
        raise AssertionError(f"ordinary research question must use the streaming path once: {post!r}")
    payload = post["payload"]
    if not isinstance(payload, dict):
        raise AssertionError(f"browser payload must be JSON: {payload!r}")
    if payload.get("tool") is not None:
        raise AssertionError(f"the browser must not select a research tool manually: {payload!r}")
    if any(key in payload for key in ("model", "provider", "route", "business14")):
        raise AssertionError(f"browser payload must not select provider/model routing: {payload!r}")

    body_text = await page.locator("body").inner_text()
    forbidden_identity = (
        "fixture-provider-not-for-ui",
        "fixture-model-not-for-ui",
        "Gemini",
        "Agnes",
        "Poolside",
        "OpenRouter",
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
        "health": {
            "runtime": health.get("runtime"),
            "live_enabled": health.get("live_enabled"),
        },
        "manual_controls_absent": "PASS",
        "automatic_grounding_evidence": "PASS",
        "chat_post_count": len(chat_posts),
        "research_post_path": post["path"],
        "request_tool_marker": None,
        "source_count": link_count,
        "source_links": source_rows,
        "visible_answer": "PASS",
        "concrete_model_provider_leak": [],
        "horizontal_overflow": False,
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "fixture_only": True,
        "decision": "2026-11-03: manual search controls removed; server-side automatic grounding",
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
