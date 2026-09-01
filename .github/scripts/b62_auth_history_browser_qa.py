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

SEED_ID = "chat_seed_000000000000000000000001"
NEW_ID = "chat_new_0000000000000000000000002"
USER_NAME = "브라우저 테스트 사용자"
SEED_TITLE = "제주 여행 준비"
SEED_USER = "제주 여행 준비물을 알려줘"
SEED_ASSISTANT = "가벼운 옷, 신분증, 충전기부터 준비해 보세요."
FOLLOWUP = "그중 꼭 필요한 세 가지만 골라줘"
FOLLOWUP_ANSWER = "신분증, 충전기, 날씨에 맞는 옷 세 가지를 먼저 챙겨보세요."
NEW_QUESTION = "오늘 할 일을 세 가지로 정리해줘"
NEW_ANSWER = "가장 중요한 일 하나, 짧은 정리 하나, 휴식 하나로 나눠보세요."
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})


@dataclass
class FixtureState:
    authenticated: bool = True
    logout_posts: int = 0
    stream_posts: list[dict[str, Any]] = field(default_factory=list)
    conversations: dict[str, dict[str, Any]] = field(default_factory=lambda: {
        SEED_ID: {
            "id": SEED_ID,
            "title": SEED_TITLE,
            "created_at": "2026-08-28T04:00:00Z",
            "updated_at": "2026-08-28T04:00:00Z",
            "messages": [
                {"role": "user", "content": SEED_USER},
                {"role": "assistant", "content": SEED_ASSISTANT},
            ],
        }
    })

    def recent(self) -> list[dict[str, str]]:
        items = sorted(self.conversations.values(), key=lambda item: item["updated_at"], reverse=True)
        return [
            {
                "id": item["id"],
                "title": item["title"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
            for item in items
        ]


def _json_body(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def _fulfill_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=_json_body(payload),
        headers={"Cache-Control": "no-store"},
    )


def _parse_post_data(route: Route) -> dict[str, Any]:
    raw = route.request.post_data
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise AssertionError(f"expected object request payload, got {value!r}")
    return value


async def _install_static_font_stubs(page: Page, stubbed_hosts: set[str]) -> None:
    async def stub_stylesheet(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(
            status=200,
            content_type="text/css; charset=utf-8",
            body="/* deterministic browser QA: external decorative font fetch suppressed */\n",
            headers={"Cache-Control": "no-store"},
        )

    async def stub_font_binary(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", stub_stylesheet)
    await page.route("https://fonts.googleapis.com/**", stub_stylesheet)
    await page.route("https://fonts.gstatic.com/**", stub_font_binary)


async def _install_fixtures(page: Page, state: FixtureState) -> None:
    async def auth_status(route: Route) -> None:
        await _fulfill_json(
            route,
            {
                "ready": True,
                "authenticated": state.authenticated,
                "history_ready": state.authenticated,
                "project_files_ready": False,
                "user": (
                    {
                        "id": "usr_browser_fixture",
                        "email": "browser@example.test",
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
            await _fulfill_json(route, {"error": {"code": "method_not_allowed"}}, status=405)
            return
        state.logout_posts += 1
        state.authenticated = False
        await _fulfill_json(route, {"ok": True})

    async def projects(route: Route) -> None:
        await _fulfill_json(route, {"projects": []})

    async def conversations(route: Route) -> None:
        await _fulfill_json(route, {"conversations": state.recent()})

    async def conversation_detail(route: Route) -> None:
        conversation_id = route.request.url.rsplit("/", 1)[-1]
        conversation = state.conversations.get(conversation_id)
        if not conversation:
            await _fulfill_json(route, {"error": {"code": "not_found"}}, status=404)
            return
        await _fulfill_json(route, {"conversation": conversation})

    async def stream(route: Route) -> None:
        if route.request.method != "POST":
            await _fulfill_json(route, {"error": {"code": "method_not_allowed"}}, status=405)
            return
        payload = _parse_post_data(route)
        state.stream_posts.append(payload)

        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            raise AssertionError(f"stream request missing messages: {payload!r}")
        latest = messages[-1]
        if not isinstance(latest, dict) or latest.get("role") != "user" or not isinstance(latest.get("content"), str):
            raise AssertionError(f"stream request missing latest user message: {payload!r}")
        question = latest["content"]

        incoming_id = payload.get("conversation_id")
        if incoming_id is None:
            conversation_id = NEW_ID
            answer = NEW_ANSWER
            state.conversations[conversation_id] = {
                "id": conversation_id,
                "title": question[:80],
                "created_at": "2026-08-28T04:02:00Z",
                "updated_at": "2026-08-28T04:02:00Z",
                "messages": [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ],
            }
        else:
            if incoming_id != SEED_ID:
                raise AssertionError(f"unexpected restored conversation id: {incoming_id!r}")
            conversation_id = incoming_id
            answer = FOLLOWUP_ANSWER
            state.conversations[conversation_id]["messages"].extend(
                [
                    {"role": "user", "content": question},
                    {"role": "assistant", "content": answer},
                ]
            )
            state.conversations[conversation_id]["updated_at"] = "2026-08-28T04:01:00Z"

        body = (
            "event: delta\n"
            f"data: {_json_body({'delta': answer})}\n\n"
            "event: done\n"
            f"data: {_json_body({'done': True, 'conversation_id': conversation_id})}\n\n"
        )
        await route.fulfill(
            status=200,
            content_type="text/event-stream; charset=utf-8",
            body=body,
            headers={"Cache-Control": "no-store"},
        )

    await page.route("**/api/auth/status", auth_status)
    await page.route("**/api/auth/logout", logout)
    await page.route("**/api/projects", projects)
    await page.route("**/api/conversations", conversations)
    await page.route("**/api/conversations/*", conversation_detail)
    await page.route("**/api/chat/stream", stream)


async def _assert_no_horizontal_overflow(page: Page, stage: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(
            f"horizontal overflow at {stage}: scrollWidth={scroll_width}, innerWidth={inner_width}"
        )


async def _open_sidebar_if_mobile(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    menu = page.locator("#mobileMenu")
    await menu.wait_for(state="visible")
    if await menu.get_attribute("aria-expanded") != "true":
        await menu.click()
    await page.locator("#sidebar").wait_for(state="visible")


async def _close_sidebar_if_mobile(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    menu = page.locator("#mobileMenu")
    if await menu.get_attribute("aria-expanded") == "true":
        await page.locator("#mobileClose").click()
        await page.wait_for_function(
            "() => document.getElementById('mobileMenu')?.getAttribute('aria-expanded') === 'false'",
            timeout=5_000,
        )


async def _wait_history_title(page: Page, title: str) -> None:
    await page.wait_for_function(
        "expected => Array.from(document.querySelectorAll('#historyList .history-item')).some(node => node.textContent.trim() === expected)",
        arg=title,
        timeout=5_000,
    )


async def _run_view(page: Page, *, name: str, width: int, height: int, mobile: bool) -> dict[str, Any]:
    state = FixtureState()
    unexpected_external_hosts: set[str] = set()
    stubbed_static_hosts: set[str] = set()

    def observe_request(request) -> None:
        parsed = urlparse(request.url)
        host = (parsed.hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_external_hosts.add(host)

    page.on("request", observe_request)
    await _install_static_font_stubs(page, stubbed_static_hosts)
    await _install_fixtures(page, state)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

    await page.wait_for_function(
        "expected => document.getElementById('loginButton')?.textContent.trim() === '로그아웃' && document.getElementById('accountName')?.textContent.trim() === expected",
        arg=USER_NAME,
        timeout=5_000,
    )
    if await page.locator("#accountName").is_hidden():
        raise AssertionError("authenticated user name must be visible")

    await _open_sidebar_if_mobile(page, mobile)
    await _wait_history_title(page, SEED_TITLE)
    history_section = page.locator("#historySection")
    if await history_section.is_hidden():
        raise AssertionError("recent history section must be visible for authenticated fixture")
    await _assert_no_horizontal_overflow(page, f"{name}-history-list")
    await page.screenshot(path=str(OUT_DIR / f"{name}-history-list.png"), full_page=True)

    seed_button = page.locator("#historyList .history-item", has_text=SEED_TITLE)
    await seed_button.click()
    await page.wait_for_function(
        "([userText, assistantText]) => document.getElementById('messageList')?.innerText.includes(userText) && document.getElementById('messageList')?.innerText.includes(assistantText)",
        arg=[SEED_USER, SEED_ASSISTANT],
        timeout=5_000,
    )
    if await page.locator("#messageList").is_hidden():
        raise AssertionError("saved conversation must open in the conversation surface")
    await page.screenshot(path=str(OUT_DIR / f"{name}-history-restored.png"), full_page=True)

    await page.locator("#messageInput").fill(FOLLOWUP)
    await page.locator("#sendButton").click()
    await page.wait_for_function(
        "expected => document.getElementById('messageList')?.innerText.includes(expected)",
        arg=FOLLOWUP_ANSWER,
        timeout=5_000,
    )
    if not state.stream_posts:
        raise AssertionError("follow-up did not issue a stream request")
    followup_payload = state.stream_posts[0]
    if followup_payload.get("conversation_id") != SEED_ID:
        raise AssertionError(f"follow-up did not reuse restored conversation id: {followup_payload!r}")
    if any(key in followup_payload for key in ("model", "provider", "route", "business14")):
        raise AssertionError(f"browser follow-up selected routing internals: {followup_payload!r}")
    await _wait_history_title(page, SEED_TITLE)
    await page.screenshot(path=str(OUT_DIR / f"{name}-history-followup.png"), full_page=True)

    await _open_sidebar_if_mobile(page, mobile)
    await page.locator("#newChatButton").click()
    await page.wait_for_function(
        "() => document.querySelector('.app-shell')?.dataset.state === 'home' && document.getElementById('messageList')?.hidden === true",
        timeout=5_000,
    )
    await page.locator("#messageInput").fill(NEW_QUESTION)
    await page.locator("#sendButton").click()
    await page.wait_for_function(
        "expected => document.getElementById('messageList')?.innerText.includes(expected)",
        arg=NEW_ANSWER,
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
        "() => document.getElementById('loginButton')?.textContent.trim() === '로그인' && document.getElementById('historySection')?.hidden === true",
        timeout=5_000,
    )
    if state.logout_posts != 1:
        raise AssertionError(f"logout must POST exactly once, saw {state.logout_posts}")
    if not await page.locator("#accountName").is_hidden():
        raise AssertionError("account name must be hidden after logout")
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
    leaked = [value for value in forbidden_identity if value in body_text]
    if leaked:
        raise AssertionError(f"concrete model/provider identity leaked into product UI: {leaked}")
    if unexpected_external_hosts:
        raise AssertionError(
            f"browser QA attempted unexpected external requests: {sorted(unexpected_external_hosts)}"
        )

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
        "stream_post_count": len(state.stream_posts),
        "explicit_routing_selector": False,
        "stubbed_decorative_font_hosts": sorted(stubbed_static_hosts),
        "unexpected_external_requests": [],
        "horizontal_overflow": False,
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "fixture_boundary": "browser-route-fixtures-only",
        "decorative_font_network": "stubbed-before-network",
        "real_google_oauth": 0,
        "real_d1": 0,
        "real_model_provider_calls": 0,
        "production_mutation": False,
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
