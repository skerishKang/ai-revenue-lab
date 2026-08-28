from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_ERROR_RETRY_QA_BASE_URL", "http://127.0.0.1:8773")
OUT_DIR = Path(os.environ.get("B62_ERROR_RETRY_QA_OUT_DIR", ".tmp/b62-error-retry-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

QUESTION = "오늘 할 일을 세 가지로 정리해줘"
PARTIAL = "먼저 가장 중요한 일 하나를 정하고,"
ERROR_MESSAGE = "연결이 잠시 불안정합니다. 다시 시도해 주세요."
RECOVERED = "가장 중요한 일 하나, 짧게 끝낼 일 하나, 휴식 하나로 나눠보세요."
FOLLOWUP = "그중 첫 번째 일부터 시작하는 방법도 알려줘"
FOLLOWUP_ANSWER = "첫 번째 일을 10분 안에 할 수 있는 가장 작은 단계로 나눠 바로 시작해 보세요."
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
FORBIDDEN_KEYS = frozenset({"model", "provider", "route", "business14"})


@dataclass
class FixtureState:
    stream_posts: list[dict[str, Any]] = field(default_factory=list)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _request_json(route: Route) -> dict[str, Any]:
    raw = route.request.post_data
    value = json.loads(raw) if raw else {}
    if not isinstance(value, dict):
        raise AssertionError(f"expected object payload, got {value!r}")
    return value


async def _reply_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=_json(payload),
        headers={"Cache-Control": "no-store"},
    )


async def _stub_fonts(page: Page, seen: set[str]) -> None:
    async def css(route: Route) -> None:
        seen.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(
            status=200,
            content_type="text/css; charset=utf-8",
            body="/* deterministic error/retry QA font stub */\n",
        )

    async def font(route: Route) -> None:
        seen.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


async def _install_api(page: Page, state: FixtureState) -> None:
    async def auth(route: Route) -> None:
        await _reply_json(route, {
            "ready": False,
            "authenticated": False,
            "history_ready": False,
            "project_files_ready": False,
            "user": None,
        })

    async def stream(route: Route) -> None:
        if route.request.method != "POST":
            await _reply_json(route, {"error": {"code": "method_not_allowed"}}, status=405)
            return
        body = _request_json(route)
        state.stream_posts.append(body)
        if any(key in body for key in FORBIDDEN_KEYS):
            raise AssertionError(f"browser selected routing internals: {body!r}")
        index = len(state.stream_posts)

        if index == 1:
            if body.get("messages") != [{"role": "user", "content": QUESTION}]:
                raise AssertionError(f"unexpected first request messages: {body!r}")
            payload = (
                "event: delta\n"
                f"data: {_json({'delta': PARTIAL})}\n\n"
                "event: error\n"
                f"data: {_json({'error': {'message': ERROR_MESSAGE}})}\n\n"
            )
        elif index == 2:
            if body != state.stream_posts[0]:
                raise AssertionError(f"retry must replay identical failed request context: first={state.stream_posts[0]!r}, retry={body!r}")
            payload = (
                "event: delta\n"
                f"data: {_json({'delta': RECOVERED})}\n\n"
                "event: done\n"
                f"data: {_json({'done': True, 'conversation_id': 'chat_retry_browser_0001'})}\n\n"
            )
        elif index == 3:
            expected_messages = [
                {"role": "user", "content": QUESTION},
                {"role": "assistant", "content": RECOVERED},
                {"role": "user", "content": FOLLOWUP},
            ]
            if body.get("messages") != expected_messages:
                raise AssertionError(f"follow-up context mismatch after recovery: {body!r}")
            if body.get("conversation_id") != "chat_retry_browser_0001":
                raise AssertionError(f"follow-up did not reuse recovered conversation id: {body!r}")
            payload = (
                "event: delta\n"
                f"data: {_json({'delta': FOLLOWUP_ANSWER})}\n\n"
                "event: done\n"
                f"data: {_json({'done': True, 'conversation_id': 'chat_retry_browser_0001'})}\n\n"
            )
        else:
            raise AssertionError(f"unexpected extra stream request #{index}: {body!r}")

        await route.fulfill(
            status=200,
            content_type="text/event-stream; charset=utf-8",
            body=payload,
            headers={"Cache-Control": "no-store"},
        )

    await page.route("**/api/auth/status", auth)
    await page.route("**/api/chat/stream", stream)


async def _wait_text(page: Page, selector: str, text: str) -> None:
    await page.wait_for_function(
        "([selector, text]) => document.querySelector(selector)?.textContent.includes(text)",
        arg=[selector, text],
        timeout=5_000,
    )


async def _no_overflow(page: Page, stage: str) -> None:
    widths = await page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    if widths[0] > widths[1] + 1:
        raise AssertionError(f"horizontal overflow at {stage}: {widths}")


async def _run(page: Page, *, label: str, width: int, height: int) -> dict[str, Any]:
    state = FixtureState()
    unexpected_hosts: set[str] = set()
    stubbed_hosts: set[str] = set()

    def observe(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe)
    await _stub_fonts(page, stubbed_hosts)
    await _install_api(page, state)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

    await page.locator("#messageInput").fill(QUESTION)
    await page.locator("#sendButton").click()
    await page.wait_for_function("() => document.querySelectorAll('#messageList .user-message').length === 1", timeout=5_000)
    await _wait_text(page, "#messageList", PARTIAL)
    await _wait_text(page, "#messageList .error-box", "답변을 불러오지 못했습니다.")
    await _wait_text(page, "#messageList .error-box", ERROR_MESSAGE)
    await page.locator("#messageList .retry-button", has_text="다시 시도").wait_for(state="visible")
    await page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#messageList [data-runtime-label]')).some(node => node.textContent.trim() === '연결 오류')",
        timeout=5_000,
    )
    if await page.locator("#messageInput").is_disabled():
        raise AssertionError("composer must be usable again after terminal stream error")
    if len(state.stream_posts) != 1:
        raise AssertionError(f"expected one failed stream request, saw {len(state.stream_posts)}")
    await _no_overflow(page, f"{label}-error")
    await page.screenshot(path=str(OUT_DIR / f"{label}-error.png"), full_page=True)

    await page.locator("#messageList .retry-button").click()
    await _wait_text(page, "#messageList", RECOVERED)
    await page.wait_for_function(
        "() => document.querySelectorAll('#messageList .error-box').length === 0 && document.querySelectorAll('#messageList .user-message').length === 1",
        timeout=5_000,
    )
    if len(state.stream_posts) != 2:
        raise AssertionError(f"retry must issue exactly one second stream request, saw {len(state.stream_posts)}")
    if PARTIAL in await page.locator("#messageList").inner_text():
        raise AssertionError("failed partial assistant shell remained after successful retry")
    await _no_overflow(page, f"{label}-recovered")
    await page.screenshot(path=str(OUT_DIR / f"{label}-recovered.png"), full_page=True)

    await page.locator("#messageInput").fill(FOLLOWUP)
    await page.locator("#sendButton").click()
    await _wait_text(page, "#messageList", FOLLOWUP_ANSWER)
    await page.wait_for_function("() => document.querySelectorAll('#messageList .user-message').length === 2", timeout=5_000)
    if len(state.stream_posts) != 3:
        raise AssertionError(f"expected one follow-up request after recovery, saw {len(state.stream_posts)} total")
    if await page.locator("#messageList .error-box").count() != 0:
        raise AssertionError("error UI remained after successful follow-up")
    await _no_overflow(page, f"{label}-followup")
    await page.screenshot(path=str(OUT_DIR / f"{label}-followup.png"), full_page=True)

    browser_text = await page.locator("body").inner_text()
    forbidden_public_terms = ("OpenRouter", "Gemini", "Poolside", "Agnes", "provider", "model id")
    leaked_terms = [term for term in forbidden_public_terms if term.lower() in browser_text.lower()]
    if leaked_terms:
        raise AssertionError(f"provider/model jargon leaked into error-retry UI: {leaked_terms}")
    if unexpected_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_hosts)}")

    return {
        "stream_requests": len(state.stream_posts),
        "user_messages": await page.locator("#messageList .user-message").count(),
        "assistant_messages": await page.locator("#messageList .assistant-message").count(),
        "unexpected_external_hosts": sorted(unexpected_hosts),
        "stubbed_static_hosts": sorted(stubbed_hosts),
        "viewport": {"width": width, "height": height},
    }


async def main() -> None:
    report: dict[str, Any] = {
        "status": "RUNNING",
        "model_selection": "DEFERRED",
        "real_provider_calls": 0,
        "core_b14_change": False,
        "production_mutation": False,
        "views": {},
    }
    report_path = OUT_DIR / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                desktop = await browser.new_page(viewport={"width": 1440, "height": 1000})
                report["views"]["desktop"] = await _run(desktop, label="desktop", width=1440, height=1000)
                await desktop.close()
                mobile = await browser.new_page(viewport={"width": 390, "height": 844})
                report["views"]["mobile"] = await _run(mobile, label="mobile", width=390, height=844)
                await mobile.close()
            finally:
                await browser.close()
        report["status"] = "PASS"
    except Exception as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
