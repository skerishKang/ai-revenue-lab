from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_AUTH_HISTORY_QA_BASE_URL", "http://127.0.0.1:8769")
OUT_DIR = Path(os.environ.get("B62_AUTH_HISTORY_QA_OUT_DIR", ".tmp/b62-auth-history-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

FIRST_QUESTION = "저장된 대화 다시 열기 테스트 질문"
FIRST_ANSWER = "저장된 첫 답변입니다."
FOLLOWUP_QUESTION = "이어서 묻는 질문"
FOLLOWUP_ANSWER = "이어진 답변입니다."
NEW_QUESTION = "새 대화 질문"
NEW_ANSWER = "새 대화 답변입니다."
CONVERSATION_ID = "conv_browser_history_fixture"
PROJECT_ID = "proj_browser_history_fixture"
USER_ID = "usr_browser_history_fixture"
USER_NAME = "브라우저 QA 사용자"


@dataclass
class FixtureState:
    authenticated: bool = True
    logout_posts: int = 0
    stream_posts: list[dict[str, Any]] = field(default_factory=list)
    history_calls: int = 0
    unexpected_external_requests: list[str] = field(default_factory=list)
    stubbed_static_hosts: set[str] = field(default_factory=set)


async def _fulfill_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload, ensure_ascii=False),
        headers={"Cache-Control": "no-store"},
    )


async def _install_routes(page: Page, state: FixtureState) -> None:
    async def auth_status(route: Route) -> None:
        await _fulfill_json(
            route,
            {
                "ready": True,
                "authenticated": state.authenticated,
                "history_ready": state.authenticated,
                "project_files_ready": False,
                "session_state": "signed_in" if state.authenticated else "guest",
                "user": (
                    {
                        "id": USER_ID,
                        "email": "browser-history@example.test",
                        "name": USER_NAME,
                        "picture": "",
                    }
                    if state.authenticated
                    else None
                ),
            },
        )

    async def logout(route: Route) -> None:
        if route.request.method != "POST":
            await _fulfill_json(route, {"error": {"code": "method_not_allowed"}}, 405)
            return
        state.logout_posts += 1
        state.authenticated = False
        await _fulfill_json(route, {"ok": True})

    async def conversations(route: Route) -> None:
        state.history_calls += 1
        if not state.authenticated:
            await _fulfill_json(route, {"conversations": []})
            return
        await _fulfill_json(
            route,
            {
                "conversations": [
                    {
                        "id": CONVERSATION_ID,
                        "title": FIRST_QUESTION,
                        "created_at": "2026-09-04T00:00:00Z",
                        "updated_at": "2026-09-04T00:00:00Z",
                    }
                ]
            },
        )

    async def conversation_detail(route: Route) -> None:
        await _fulfill_json(
            route,
            {
                "conversation": {
                    "id": CONVERSATION_ID,
                    "title": FIRST_QUESTION,
                    "project_id": PROJECT_ID,
                    "messages": [
                        {"role": "user", "content": FIRST_QUESTION},
                        {"role": "assistant", "content": FIRST_ANSWER},
                    ],
                }
            },
        )

    async def projects(route: Route) -> None:
        if not state.authenticated:
            await _fulfill_json(route, {"projects": []})
            return
        await _fulfill_json(
            route,
            {
                "projects": [
                    {
                        "id": PROJECT_ID,
                        "name": "브라우저 QA 프로젝트",
                        "instructions": "브라우저 QA용 프로젝트",
                        "created_at": "2026-09-04T00:00:00Z",
                        "updated_at": "2026-09-04T00:00:00Z",
                    }
                ]
            },
        )

    async def project_files(route: Route) -> None:
        await _fulfill_json(route, {"files": []})

    async def stream(route: Route) -> None:
        try:
            body = await route.request.post_data_json
        except Exception:
            body = json.loads(route.request.post_data or "{}")
        state.stream_posts.append(body)
        question = ""
        messages = body.get("messages") if isinstance(body, dict) else None
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict) and isinstance(last.get("content"), str):
                question = last["content"]
        answer = NEW_ANSWER if question == NEW_QUESTION else FOLLOWUP_ANSWER
        conversation_id = CONVERSATION_ID if body.get("conversation_id") == CONVERSATION_ID else "conv_browser_history_new"
        frames = [
            f"event: delta\ndata: {json.dumps({'delta': answer}, ensure_ascii=False)}\n\n",
            f"event: done\ndata: {json.dumps({'done': True, 'conversation_id': conversation_id}, ensure_ascii=False)}\n\n",
        ]
        await route.fulfill(
            status=200,
            content_type="text/event-stream; charset=utf-8",
            body="".join(frames),
            headers={"Cache-Control": "no-store"},
        )

    async def health(route: Route) -> None:
        await _fulfill_json(
            route,
            {
                "status": "ok",
                "web_tools_ready": False,
                "deep_research_ready": False,
                "auth_configured": True,
                "history_store_bound": True,
                "projects_code_ready": True,
                "project_files_code_ready": True,
                "project_file_store_bound": False,
                "saved_outputs_code_ready": False,
                "saved_output_store_bound": False,
            },
        )

    await page.route("**/api/auth/status", auth_status)
    await page.route("**/api/auth/logout", logout)
    await page.route("**/api/conversations", conversations)
    await page.route(f"**/api/conversations/{CONVERSATION_ID}", conversation_detail)
    await page.route("**/api/projects", projects)
    await page.route(f"**/api/projects/{PROJECT_ID}/files", project_files)
    await page.route("**/api/chat/stream", stream)
    await page.route("**/health", health)

    async def external(route: Route) -> None:
        parsed = urlparse(route.request.url)
        host = parsed.hostname or ""
        if host in {"fonts.googleapis.com", "cdn.jsdelivr.net"}:
            state.stubbed_static_hosts.add(host)
            await route.fulfill(status=200, body="", content_type="text/css")
            return
        state.unexpected_external_requests.append(route.request.url)
        await route.abort()

    await page.route("https://**/*", external)


async def _open_sidebar_if_mobile(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    menu = page.locator("#mobileMenu")
    if await menu.get_attribute("aria-expanded") != "true":
        await menu.click()
    await page.locator("#sidebar").wait_for(state="visible")


async def _wait_history_title(page: Page, title: str) -> None:
    await page.wait_for_function(
        "expected => Array.from(document.querySelectorAll('#historyList .history-item')).some(el => el.textContent.trim() === expected)",
        arg=title,
        timeout=5_000,
    )


async def _assert_no_horizontal_overflow(page: Page, label: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {label}: {scroll_width}>{inner_width}")


async def _run_view(page: Page, *, name: str, width: int, height: int, mobile: bool) -> dict[str, Any]:
    state = FixtureState()
    await _install_routes(page, state)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.locator("#messageInput").wait_for(state="visible")
    await page.wait_for_function(
        f"() => document.getElementById('accountName')?.textContent.trim() === {json.dumps(USER_NAME)}",
        timeout=5_000,
    )
    await _open_sidebar_if_mobile(page, mobile)

    if await page.locator("#accountName").is_hidden():
        raise AssertionError("authenticated account name is hidden")
    if (await page.locator("#accountName").inner_text()).strip() != USER_NAME:
        raise AssertionError("authenticated identity did not render")
    await _wait_history_title(page, FIRST_QUESTION)
    await _assert_no_horizontal_overflow(page, f"{name}-initial")
    await page.screenshot(path=str(OUT_DIR / f"{name}-history-initial.png"), full_page=True)

    await page.locator("#historyList .history-item").first.click()
    await page.wait_for_function(
        f"() => document.getElementById('messageList')?.innerText.includes({json.dumps(FIRST_ANSWER)})",
        timeout=5_000,
    )
    if await page.locator("#messageList").is_hidden():
        raise AssertionError("saved conversation did not open")
    await page.locator("#messageInput").fill(FOLLOWUP_QUESTION)
    await page.locator("#sendButton").click()
    await page.wait_for_function(
        f"() => document.getElementById('messageList')?.innerText.includes({json.dumps(FOLLOWUP_ANSWER)})",
        timeout=5_000,
    )
    if len(state.stream_posts) != 1:
        raise AssertionError(f"expected one follow-up stream request, saw {len(state.stream_posts)}")
    followup_payload = state.stream_posts[0]
    if followup_payload.get("conversation_id") != CONVERSATION_ID:
        raise AssertionError(f"follow-up did not reuse conversation id: {followup_payload!r}")
    if any(key in followup_payload for key in ("model", "provider", "route", "business14")):
        raise AssertionError(f"browser selected routing internals: {followup_payload!r}")
    await _assert_no_horizontal_overflow(page, f"{name}-reopened")
    await page.screenshot(path=str(OUT_DIR / f"{name}-history-reopened.png"), full_page=True)

    await page.locator("#newChatButton").click()
    await page.wait_for_function(
        "() => document.querySelector('.app-shell')?.dataset.state === 'home' && document.getElementById('messageList')?.hidden === true",
        timeout=5_000,
    )
    await page.locator("#messageInput").fill(NEW_QUESTION)
    await page.locator("#sendButton").click()
    await page.wait_for_function(
        f"() => document.getElementById('messageList')?.innerText.includes({json.dumps(NEW_ANSWER)})",
        timeout=5_000,
    )
    if len(state.stream_posts) != 2:
        raise AssertionError(f"expected two stream requests total, saw {len(state.stream_posts)}")
    new_payload = state.stream_posts[1]
    if "conversation_id" in new_payload:
        raise AssertionError(f"new chat reused an old conversation id: {new_payload!r}")
    if any(key in new_payload for key in ("model", "provider", "route", "business14")):
        raise AssertionError(f"new chat selected routing internals: {new_payload!r}")
    await _wait_history_title(page, NEW_QUESTION)
    await _open_sidebar_if_mobile(page, mobile)
    await page.screenshot(path=str(OUT_DIR / f"{name}-history-new-chat.png"), full_page=True)

    await _open_sidebar_if_mobile(page, mobile)
    await page.locator("#loginButton").click()
    await page.wait_for_function(
        """() => {
          const button = document.getElementById('loginButton');
          const account = document.getElementById('accountName');
          const container = document.querySelector('.sidebar-account');
          const history = document.getElementById('historySection');
          return button?.textContent.trim() === '로그인'
            && account?.hidden === false
            && account?.textContent.trim() === '게스트'
            && container?.dataset.accountState === 'guest'
            && history?.hidden === true;
        }""",
        timeout=5_000,
    )
    if state.logout_posts != 1:
        raise AssertionError(f"logout must POST exactly once, saw {state.logout_posts}")
    if await page.locator("#accountName").is_hidden():
        raise AssertionError("guest account label must remain visible after logout")
    if (await page.locator("#accountName").inner_text()).strip() != "게스트":
        raise AssertionError("logout must return account presentation to guest")
    if await page.locator(".sidebar-account").get_attribute("data-account-state") != "guest":
        raise AssertionError("logout must project guest account state")
    if not await page.locator("#historySection").is_hidden():
        raise AssertionError("history must be hidden after logout")
    await _assert_no_horizontal_overflow(page, f"{name}-logout")
    await page.screenshot(path=str(OUT_DIR / f"{name}-history-logout.png"), full_page=True)

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
    leaked = [token for token in forbidden_identity if token in body_text]
    if leaked:
        raise AssertionError(f"browser exposed routing internals: {leaked}")
    if state.unexpected_external_requests:
        raise AssertionError(f"unexpected external requests: {state.unexpected_external_requests}")

    return {
        "viewport": {"width": width, "height": height},
        "authenticated_identity": "PASS",
        "recent_history": "PASS",
        "reopen_conversation": "PASS",
        "followup_reuses_conversation_id": "PASS",
        "new_chat_drops_old_conversation_id": "PASS",
        "new_history_entry": "PASS",
        "logout_posts": state.logout_posts,
        "logout_clears_history_ui": "PASS",
        "logout_guest_presentation": "PASS",
        "stream_post_count": len(state.stream_posts),
        "explicit_routing_selector": False,
        "stubbed_decorative_font_hosts": sorted(state.stubbed_static_hosts),
        "unexpected_external_requests": state.unexpected_external_requests,
        "horizontal_overflow": False,
    }


async def main() -> None:
    report = {
        "base_url": BASE_URL,
        "fixture_boundary": "browser-route-fixtures-only",
        "decorative_font_network": "stubbed-before-network",
        "real_google_oauth": 0,
        "real_d1": 0,
        "real_model_provider_calls": 0,
        "production_mutation": False,
        "views": {},
        "status": "PASS",
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            try:
                report["views"]["desktop"] = await _run_view(
                    page, name="desktop", width=1440, height=1000, mobile=False
                )
            finally:
                await page.close()

            page = await browser.new_page()
            try:
                report["views"]["mobile"] = await _run_view(
                    page, name="mobile", width=390, height=844, mobile=True
                )
            finally:
                await page.close()
        finally:
            await browser.close()

    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
