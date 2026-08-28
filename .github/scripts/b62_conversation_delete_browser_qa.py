from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_CONVERSATION_DELETE_QA_BASE_URL", "http://127.0.0.1:8775")
OUT_DIR = Path(os.environ.get("B62_CONVERSATION_DELETE_QA_OUT_DIR", ".tmp/b62-conversation-delete-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

ACTIVE_ID = "chat_" + "1" * 32
OTHER_ID = "chat_" + "2" * 32
FAIL_ID = "chat_" + "3" * 32
PROJECT_ID = "proj_" + "a" * 32
USER_NAME = "삭제 검증 사용자"
PROJECT_NAME = "가족 여행"
ACTIVE_TITLE = "현재 보고 있는 대화"
OTHER_TITLE = "삭제할 다른 대화"
FAIL_TITLE = "삭제 실패 대화"
ACTIVE_USER = "제주 가족여행 준비물을 알려줘"
ACTIVE_ASSISTANT = "신분증과 충전기부터 준비해 보세요."
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})


@dataclass
class FixtureState:
    delete_requests: list[str] = field(default_factory=list)
    conversations: dict[str, dict[str, Any]] = field(default_factory=lambda: {
        ACTIVE_ID: {
            "id": ACTIVE_ID,
            "title": ACTIVE_TITLE,
            "project_id": PROJECT_ID,
            "created_at": "2026-08-28T08:00:00Z",
            "updated_at": "2026-08-28T08:03:00Z",
            "messages": [
                {"role": "user", "content": ACTIVE_USER},
                {"role": "assistant", "content": ACTIVE_ASSISTANT},
            ],
        },
        OTHER_ID: {
            "id": OTHER_ID,
            "title": OTHER_TITLE,
            "project_id": None,
            "created_at": "2026-08-28T08:01:00Z",
            "updated_at": "2026-08-28T08:02:00Z",
            "messages": [
                {"role": "user", "content": "다른 질문"},
                {"role": "assistant", "content": "다른 답변"},
            ],
        },
        FAIL_ID: {
            "id": FAIL_ID,
            "title": FAIL_TITLE,
            "project_id": None,
            "created_at": "2026-08-28T08:02:00Z",
            "updated_at": "2026-08-28T08:01:00Z",
            "messages": [
                {"role": "user", "content": "실패 fixture"},
                {"role": "assistant", "content": "행은 유지되어야 합니다."},
            ],
        },
    })

    def recent(self) -> list[dict[str, Any]]:
        rows = sorted(self.conversations.values(), key=lambda item: item["updated_at"], reverse=True)
        return [
            {
                "id": item["id"],
                "title": item["title"],
                "project_id": item.get("project_id"),
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
            for item in rows
        ]


def _json_body(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


async def _fulfill_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=_json_body(payload),
        headers={"Cache-Control": "no-store"},
    )


async def _install_static_font_stubs(page: Page, stubbed_hosts: set[str]) -> None:
    async def stub_stylesheet(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(
            status=200,
            content_type="text/css; charset=utf-8",
            body="/* deterministic QA: decorative external font suppressed */\n",
        )

    async def stub_font(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", stub_stylesheet)
    await page.route("https://fonts.googleapis.com/**", stub_stylesheet)
    await page.route("https://fonts.gstatic.com/**", stub_font)


async def _install_fixtures(page: Page, state: FixtureState) -> None:
    async def auth_status(route: Route) -> None:
        await _fulfill_json(
            route,
            {
                "ready": True,
                "authenticated": True,
                "history_ready": True,
                "project_files_ready": False,
                "user": {
                    "id": "usr_delete_browser_fixture",
                    "email": "delete@example.test",
                    "name": USER_NAME,
                    "picture": "",
                },
            },
        )

    async def projects(route: Route) -> None:
        await _fulfill_json(
            route,
            {
                "projects": [
                    {
                        "id": PROJECT_ID,
                        "name": PROJECT_NAME,
                        "instructions": "쉬운 한국어로 설명해줘.",
                        "created_at": "2026-08-28T07:00:00Z",
                        "updated_at": "2026-08-28T08:00:00Z",
                    }
                ]
            },
        )

    async def conversations(route: Route) -> None:
        await _fulfill_json(route, {"conversations": state.recent()})

    async def conversation_detail(route: Route) -> None:
        conversation_id = route.request.url.rsplit("/", 1)[-1]
        if route.request.method == "DELETE":
            state.delete_requests.append(conversation_id)
            if conversation_id == FAIL_ID:
                await _fulfill_json(
                    route,
                    {"error": {"code": "history_unavailable", "message": "대화를 삭제하지 못했습니다."}},
                    status=503,
                )
                return
            if conversation_id not in state.conversations:
                await _fulfill_json(route, {"error": {"code": "not_found", "message": "대화를 찾을 수 없습니다."}}, status=404)
                return
            del state.conversations[conversation_id]
            await _fulfill_json(route, {"deleted": True, "conversation_id": conversation_id})
            return

        conversation = state.conversations.get(conversation_id)
        if not conversation:
            await _fulfill_json(route, {"error": {"code": "not_found"}}, status=404)
            return
        await _fulfill_json(route, {"conversation": conversation})

    await page.route("**/api/auth/status", auth_status)
    await page.route("**/api/projects", projects)
    await page.route("**/api/conversations", conversations)
    await page.route("**/api/conversations/*", conversation_detail)


def _history_row(page: Page, title: str):
    return page.locator("#historyList .history-row").filter(has_text=title)


async def _open_sidebar_if_mobile(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    menu = page.locator("#mobileMenu")
    if await menu.get_attribute("aria-expanded") != "true":
        await menu.click()
    await page.wait_for_function(
        "() => document.getElementById('mobileMenu')?.getAttribute('aria-expanded') === 'true'",
        timeout=5_000,
    )


async def _wait_history_row(page: Page, title: str) -> None:
    await page.wait_for_function(
        "expected => Array.from(document.querySelectorAll('#historyList .history-row')).some(node => node.textContent.includes(expected))",
        arg=title,
        timeout=5_000,
    )


async def _assert_no_horizontal_overflow(page: Page, stage: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {stage}: {scroll_width}>{inner_width}")


async def _dismiss_next_dialog(page: Page) -> None:
    async def dismiss(dialog) -> None:
        await dialog.dismiss()

    page.once("dialog", dismiss)


async def _accept_next_dialog(page: Page) -> None:
    async def accept(dialog) -> None:
        message = dialog.message
        if "되돌릴 수 없습니다" not in message:
            raise AssertionError(f"delete confirmation lacks irreversible warning: {message!r}")
        await dialog.accept()

    page.once("dialog", accept)


async def _run_view(page: Page, *, name: str, width: int, height: int, mobile: bool) -> dict[str, Any]:
    state = FixtureState()
    unexpected_hosts: set[str] = set()
    stubbed_hosts: set[str] = set()

    def observe_request(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe_request)
    await _install_static_font_stubs(page, stubbed_hosts)
    await _install_fixtures(page, state)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

    await page.wait_for_function(
        "expected => document.getElementById('loginButton')?.textContent.trim() === '로그아웃' && document.getElementById('accountName')?.textContent.trim() === expected",
        arg=USER_NAME,
        timeout=5_000,
    )
    await _open_sidebar_if_mobile(page, mobile)
    for title in (ACTIVE_TITLE, OTHER_TITLE, FAIL_TITLE):
        await _wait_history_row(page, title)

    delete_names: dict[str, str] = {}
    for title in (ACTIVE_TITLE, OTHER_TITLE, FAIL_TITLE):
        row = _history_row(page, title)
        delete_button = row.locator(".history-delete")
        label = await delete_button.get_attribute("aria-label")
        if not label or title not in label or "삭제" not in label:
            raise AssertionError(f"delete button accessible name is not tied to title: {title!r} -> {label!r}")
        delete_names[title] = label
        if mobile:
            box = await delete_button.bounding_box()
            if box is None or box["width"] < 44 or box["height"] < 44:
                raise AssertionError(f"mobile delete target under 44px: {title!r} -> {box!r}")

    await _assert_no_horizontal_overflow(page, f"{name}-initial")
    await page.screenshot(path=str(OUT_DIR / f"{name}-initial.png"), full_page=True)

    # Open the project-bound conversation so deletion semantics can distinguish active vs other rows.
    await _history_row(page, ACTIVE_TITLE).locator(".history-item").click()
    await page.wait_for_function(
        "([userText, assistantText]) => document.getElementById('messageList')?.innerText.includes(userText) && document.getElementById('messageList')?.innerText.includes(assistantText)",
        arg=[ACTIVE_USER, ACTIVE_ASSISTANT],
        timeout=5_000,
    )
    if await page.locator("#projectBanner").is_hidden():
        raise AssertionError("project-bound restored conversation must show project banner")
    if (await page.locator("#activeProjectName").inner_text()).strip() != PROJECT_NAME:
        raise AssertionError("active project name was not restored")

    # Cancel must issue zero DELETE requests and keep the row.
    await _open_sidebar_if_mobile(page, mobile)
    await _dismiss_next_dialog(page)
    await _history_row(page, OTHER_TITLE).locator(".history-delete").click()
    await page.wait_for_timeout(100)
    if state.delete_requests:
        raise AssertionError(f"cancel issued DELETE request(s): {state.delete_requests!r}")
    if await _history_row(page, OTHER_TITLE).count() != 1:
        raise AssertionError("cancel removed the conversation row")

    # Deleting another row must not reset the currently open conversation.
    await _accept_next_dialog(page)
    await _history_row(page, OTHER_TITLE).locator(".history-delete").click()
    await page.wait_for_function(
        "expected => !Array.from(document.querySelectorAll('#historyList .history-row')).some(node => node.textContent.includes(expected))",
        arg=OTHER_TITLE,
        timeout=5_000,
    )
    if state.delete_requests != [OTHER_ID]:
        raise AssertionError(f"expected exactly one DELETE for other conversation, got {state.delete_requests!r}")
    body_text = await page.locator("#messageList").inner_text()
    if ACTIVE_USER not in body_text or ACTIVE_ASSISTANT not in body_text:
        raise AssertionError("deleting another row reset or replaced the active conversation")
    if await page.locator("#projectBanner").is_hidden():
        raise AssertionError("deleting another row lost active project context")

    # A failed deletion must leave the row and show bounded user-facing feedback.
    await _open_sidebar_if_mobile(page, mobile)
    await _accept_next_dialog(page)
    await _history_row(page, FAIL_TITLE).locator(".history-delete").click()
    await page.wait_for_function(
        "() => document.getElementById('runtimeNote')?.dataset.state === 'error'",
        timeout=5_000,
    )
    if await _history_row(page, FAIL_TITLE).count() != 1:
        raise AssertionError("failed deletion removed its conversation row")
    if state.delete_requests != [OTHER_ID, FAIL_ID]:
        raise AssertionError(f"failed deletion request accounting mismatch: {state.delete_requests!r}")
    if "삭제" not in (await page.locator("#runtimeNote").inner_text()):
        raise AssertionError("failed deletion did not show bounded Korean feedback")

    # Deleting the active conversation must reset chat state while preserving Project context.
    await _accept_next_dialog(page)
    await _history_row(page, ACTIVE_TITLE).locator(".history-delete").click()
    await page.wait_for_function(
        "expected => document.querySelector('.app-shell')?.dataset.state === 'home' && document.getElementById('messageList')?.hidden === true && !Array.from(document.querySelectorAll('#historyList .history-row')).some(node => node.textContent.includes(expected))",
        arg=ACTIVE_TITLE,
        timeout=5_000,
    )
    if state.delete_requests != [OTHER_ID, FAIL_ID, ACTIVE_ID]:
        raise AssertionError(f"active deletion request accounting mismatch: {state.delete_requests!r}")
    if await page.locator("#projectBanner").is_hidden():
        raise AssertionError("active deletion failed to preserve current Project context")
    if (await page.locator("#activeProjectName").inner_text()).strip() != PROJECT_NAME:
        raise AssertionError("active deletion changed the current Project")
    focused_id = await page.evaluate("document.activeElement && document.activeElement.id")
    if focused_id != "messageInput":
        raise AssertionError(f"active deletion should return focus to composer, got {focused_id!r}")

    await _assert_no_horizontal_overflow(page, f"{name}-final")
    await page.screenshot(path=str(OUT_DIR / f"{name}-final.png"), full_page=True)

    visible_text = await page.locator("body").inner_text()
    forbidden = [token for token in ("provider", "router", "B14", "UNASSIGNED", "LOW", "MEDIUM", "HIGH") if token in visible_text]
    if forbidden:
        raise AssertionError(f"routing jargon leaked into visible browser UI: {forbidden!r}")
    if unexpected_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_hosts)!r}")

    return {
        "name": name,
        "viewport": {"width": width, "height": height},
        "delete_accessible_names": delete_names,
        "delete_requests": list(state.delete_requests),
        "remaining_conversations": sorted(state.conversations),
        "project_preserved": True,
        "focused_after_active_delete": focused_id,
        "unexpected_external_hosts": sorted(unexpected_hosts),
        "stubbed_static_hosts": sorted(stubbed_hosts),
    }


async def main() -> None:
    report: dict[str, Any] = {"base_url": BASE_URL, "views": []}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for name, width, height, mobile in (
                ("desktop", 1440, 1000, False),
                ("mobile", 390, 844, True),
            ):
                context = await browser.new_context(locale="ko-KR")
                page = await context.new_page()
                try:
                    report["views"].append(
                        await _run_view(page, name=name, width=width, height=height, mobile=mobile)
                    )
                finally:
                    await context.close()
        finally:
            await browser.close()

    report["acceptance"] = {
        "cancel_delete_requests": 0,
        "confirmed_delete_once_per_action": True,
        "failed_delete_row_preserved": True,
        "active_delete_resets_chat": True,
        "other_delete_preserves_active_chat": True,
        "active_project_preserved": True,
        "mobile_delete_target_min_44": True,
        "provider_model_jargon": False,
    }
    (OUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
