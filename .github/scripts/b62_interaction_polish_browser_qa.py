from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_QA_BASE_URL", "http://127.0.0.1:8765")
OUT_DIR = Path(os.environ.get("B62_QA_OUT_DIR", ".tmp/b62-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})

SUCCESS_QUESTION = "오늘 우선순위를 정리해줘"
SUCCESS_ANSWER = "가장 중요한 일 하나부터 정하고 작은 단계로 시작해 보세요."
CANCEL_QUESTION = "길게 설명해줘"
TIMEOUT_QUESTION = "시간이 오래 걸리는 요청을 해줘"


async def _reply_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
        headers={"Cache-Control": "no-store"},
    )


async def _stub_fonts(page: Page) -> None:
    async def css(route: Route) -> None:
        await route.fulfill(status=200, content_type="text/css; charset=utf-8", body="/* deterministic interaction QA */")

    async def font(route: Route) -> None:
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


async def _install_api(page: Page, requests: list[dict[str, Any]]) -> None:
    async def auth(route: Route) -> None:
        await _reply_json(route, {
            "ready": False,
            "authenticated": False,
            "history_ready": False,
            "project_files_ready": False,
            "user": None,
        })

    async def orchestration_status(route: Route) -> None:
        await _reply_json(route, {"orchestration_ready": False, "authenticated": False})

    async def stream(route: Route) -> None:
        body = json.loads(route.request.post_data or "{}")
        requests.append(body)
        index = len(requests)
        if index == 1:
            await asyncio.sleep(0.35)
            payload = (
                "event: delta\n"
                f"data: {json.dumps({'delta': SUCCESS_ANSWER}, ensure_ascii=False)}\n\n"
                "event: done\n"
                f"data: {json.dumps({'done': True, 'conversation_id': 'chat_interaction_0001'})}\n\n"
            )
            await route.fulfill(
                status=200,
                content_type="text/event-stream; charset=utf-8",
                body=payload,
                headers={"Cache-Control": "no-store"},
            )
            return
        if index == 2:
            await asyncio.sleep(1.2)
            payload = (
                "event: delta\n"
                f"data: {json.dumps({'delta': '취소되기 전 임시 응답'}, ensure_ascii=False)}\n\n"
                "event: done\n"
                f"data: {json.dumps({'done': True})}\n\n"
            )
            try:
                await route.fulfill(status=200, content_type="text/event-stream; charset=utf-8", body=payload)
            except Exception:
                # The page intentionally aborts this request before fulfillment.
                pass
            return
        if index == 3:
            await _reply_json(route, {
                "error": {
                    "code": "upstream_timeout",
                    "message": "upstream timeout",
                }
            }, status=504)
            return
        raise AssertionError(f"unexpected stream request #{index}: {body!r}")

    await page.route("**/api/auth/status", auth)
    await page.route("**/api/orchestration/status", orchestration_status)
    await page.route("**/api/chat/stream", stream)


async def _wait_phase(page: Page, phase: str) -> None:
    await page.wait_for_function(
        "phase => document.querySelector('#composerForm')?.dataset.interactionPhase === phase",
        arg=phase,
        timeout=5_000,
    )


async def _focus_id(page: Page) -> str:
    return await page.evaluate("document.activeElement && document.activeElement.id || ''")


async def _no_overflow(page: Page, label: str) -> None:
    widths = await page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
    if widths[0] > widths[1] + 1:
        raise AssertionError(f"horizontal overflow at {label}: {widths}")


async def _run(page: Page, *, label: str) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    unexpected_hosts: set[str] = set()

    def observe_request(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe_request)
    await _stub_fonts(page)
    await _install_api(page, requests)
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_function("() => Boolean(window.PadiemChatInteractionPresentation)", timeout=5_000)
    await page.evaluate("""
      () => {
        window.__b62InteractionPhases = [];
        document.addEventListener('padiem:interaction-phase', (event) => {
          window.__b62InteractionPhases.push(event.detail.phase);
        });
      }
    """)

    # Success: preparing -> streaming -> safe completed actions.
    await page.locator("#messageInput").fill(SUCCESS_QUESTION)
    await page.locator("#sendButton").click()
    await _wait_phase(page, "preparing")
    if await page.locator(".answer-actions").count() != 0:
        raise AssertionError(f"terminal actions appeared while preparing at {label}")
    if not await page.locator("#composerForm").get_attribute("aria-busy") == "true":
        raise AssertionError(f"composer aria-busy missing while preparing at {label}")
    await page.wait_for_function(
        "answer => document.querySelector('#messageList')?.textContent.includes(answer)",
        arg=SUCCESS_ANSWER,
        timeout=5_000,
    )
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-message:last-child')?.dataset.lifecycle === 'completed'",
        timeout=5_000,
    )
    await _wait_phase(page, "idle")
    await page.locator("#messageList .assistant-message:last-child .answer-actions").wait_for(state="visible", timeout=5_000)
    if await page.locator("#messageList .assistant-message:last-child").get_attribute("data-terminal-actions-safe") != "true":
        raise AssertionError(f"completed answer not marked terminal-action safe at {label}")
    await page.wait_for_function("() => document.activeElement?.id === 'messageInput'", timeout=5_000)
    export_button = page.locator("#conversationExportButton")
    await export_button.wait_for(state="visible", timeout=5_000)
    if await export_button.is_disabled():
        raise AssertionError(f"completed conversation export should be enabled at {label}")

    # Cancel: cancellation is distinct and incomplete actions stay blocked.
    await page.locator("#messageInput").fill(CANCEL_QUESTION)
    await page.locator("#sendButton").click()
    await _wait_phase(page, "preparing")
    await page.locator("#cancelStreamButton").wait_for(state="visible", timeout=5_000)
    await page.locator("#cancelStreamButton").click()
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-message:last-child')?.dataset.lifecycle === 'cancelled'",
        timeout=5_000,
    )
    await _wait_phase(page, "idle")
    cancelled = page.locator("#messageList .assistant-message:last-child")
    if await cancelled.get_attribute("data-terminal-actions-safe") != "false":
        raise AssertionError(f"cancelled answer incorrectly marked safe at {label}")
    if "생성 취소됨" not in await cancelled.inner_text():
        raise AssertionError(f"cancelled copy missing at {label}")
    await cancelled.locator(".retry-button", has_text="다시 생성").wait_for(state="visible")
    if not await export_button.is_disabled():
        raise AssertionError(f"export must stay disabled with cancelled incomplete answer at {label}")
    await page.wait_for_function("() => document.activeElement?.id === 'messageInput'", timeout=5_000)

    # Timeout: distinct copy, retry available, still not terminal-action safe.
    await page.locator("#messageInput").fill(TIMEOUT_QUESTION)
    await page.locator("#sendButton").click()
    await page.wait_for_function(
        "() => document.querySelector('#messageList .assistant-message:last-child')?.dataset.lifecycle === 'timed_out'",
        timeout=5_000,
    )
    timed_out = page.locator("#messageList .assistant-message:last-child")
    if await timed_out.get_attribute("data-terminal-actions-safe") != "false":
        raise AssertionError(f"timed-out answer incorrectly marked safe at {label}")
    if "응답 시간이 지났습니다." not in await timed_out.inner_text():
        raise AssertionError(f"timeout heading not normalized at {label}")
    if "정해진 시간 안에 응답이 완료되지 않았습니다." not in await timed_out.inner_text():
        raise AssertionError(f"timeout body not distinct at {label}")
    await timed_out.locator(".retry-button", has_text="다시 시도").wait_for(state="visible")
    await page.wait_for_function("() => document.activeElement?.id === 'messageInput'", timeout=5_000)

    # Attachment error and success both expose bounded attachment-loading state.
    await page.locator("#attachmentFileInput").set_input_files({
        "name": "unsupported.exe",
        "mimeType": "application/octet-stream",
        "buffer": b"not-a-supported-document",
    })
    await page.wait_for_function(
        "() => document.querySelector('#runtimeNote')?.dataset.state === 'error'",
        timeout=5_000,
    )
    await _wait_phase(page, "idle")
    if await _focus_id(page) != "attachmentButton":
        raise AssertionError(f"attachment error focus did not recover to attachment button at {label}")

    await page.locator("#messageInput").fill("첨부 후 보낼 문장")
    await page.locator("#attachmentFileInput").set_input_files({
        "name": "notes.txt",
        "mimeType": "text/plain",
        "buffer": "간단한 참고 문서".encode("utf-8"),
    })
    await page.locator("#attachmentTray").wait_for(state="visible", timeout=5_000)
    await _wait_phase(page, "idle")
    if await _focus_id(page) != "messageInput":
        raise AssertionError(f"attachment success focus did not recover to composer at {label}")
    if await page.locator("#sendButton").is_disabled():
        raise AssertionError(f"send should recover after successful attachment load at {label}")

    phases = await page.evaluate("window.__b62InteractionPhases")
    required_phases = {"attachment_loading", "preparing", "streaming", "cancelling", "idle"}
    if not required_phases.issubset(set(phases)):
        raise AssertionError(f"missing interaction phases at {label}: {sorted(required_phases - set(phases))}; got={phases}")
    if unexpected_hosts:
        raise AssertionError(f"unexpected external hosts at {label}: {sorted(unexpected_hosts)}")
    if len(requests) != 3:
        raise AssertionError(f"expected exactly three chat requests at {label}, saw {len(requests)}")

    await _no_overflow(page, label)
    await page.screenshot(path=str(OUT_DIR / f"interaction-polish-{label}.png"), full_page=True)
    return {
        "status": "PASS",
        "phases": phases,
        "chat_requests": len(requests),
        "completed_actions_safe": True,
        "cancelled_actions_safe": False,
        "timed_out_actions_safe": False,
        "focus_recovery": True,
        "attachment_error_focus": "attachmentButton",
        "attachment_success_focus": "messageInput",
        "production_mutation": False,
    }


async def main() -> None:
    report: dict[str, Any] = {
        "status": "RUNNING",
        "hidden_reasoning_exposure": 0,
        "provider_retry_fallback_policy_in_b62": False,
        "p01_recovery_state_machine_in_b62": False,
        "production_mutation": False,
        "views": {},
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for label, viewport in (
                ("desktop", {"width": 1440, "height": 1000}),
                ("mobile", {"width": 390, "height": 844}),
            ):
                page = await browser.new_page(viewport=viewport)
                try:
                    report["views"][label] = await _run(page, label=label)
                finally:
                    await page.close()
        finally:
            await browser.close()
    report["status"] = "PASS"
    (OUT_DIR / "interaction-polish-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
