from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_PROJECT_DELETE_QA_BASE_URL", "http://127.0.0.1:8773")
OUT_DIR = Path(os.environ.get("B62_PROJECT_DELETE_QA_OUT_DIR", ".tmp/b62-project-delete-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

USER_NAME = "프로젝트 삭제 QA 사용자"
ACTIVE_ID = "proj_" + "1" * 32
OTHER_ID = "proj_" + "2" * 32
BLOCKED_ID = "proj_" + "3" * 32
CHAT_ID = "chat_" + "a" * 32
ACTIVE_NAME = "가족여행"
OTHER_NAME = "주말 계획"
BLOCKED_NAME = "자료 프로젝트"
QUESTION = "부모님과 갈 여행 일정을 정리해줘"
ANSWER = "첫날은 이동을 줄이고 쉬는 시간을 넉넉히 두는 일정이 좋습니다."
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
FORBIDDEN_VISIBLE_TERMS = ("provider", "router", "business14", "unassigned")


@dataclass
class FixtureState:
    projects: dict[str, dict[str, Any]] = field(default_factory=dict)
    conversations: dict[str, dict[str, Any]] = field(default_factory=dict)
    files: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    delete_requests: list[str] = field(default_factory=list)

    @classmethod
    def seeded(cls) -> "FixtureState":
        now = "2026-08-28T09:20:00Z"
        projects = {
            ACTIVE_ID: {"id": ACTIVE_ID, "name": ACTIVE_NAME, "instructions": "쉬운 한국어로 설명", "created_at": now, "updated_at": now},
            OTHER_ID: {"id": OTHER_ID, "name": OTHER_NAME, "instructions": "", "created_at": now, "updated_at": now},
            BLOCKED_ID: {"id": BLOCKED_ID, "name": BLOCKED_NAME, "instructions": "", "created_at": now, "updated_at": now},
        }
        conversations = {
            CHAT_ID: {
                "id": CHAT_ID,
                "title": QUESTION,
                "project_id": ACTIVE_ID,
                "created_at": now,
                "updated_at": now,
                "messages": [
                    {"role": "user", "content": QUESTION},
                    {"role": "assistant", "content": ANSWER},
                ],
            }
        }
        files = {
            BLOCKED_ID: [{
                "id": "file_" + "b" * 32,
                "project_id": BLOCKED_ID,
                "name": "자료.md",
                "media_type": "text/markdown",
                "content_chars": 12,
                "created_at": now,
                "updated_at": now,
            }]
        }
        return cls(projects=projects, conversations=conversations, files=files)

    def project_list(self) -> list[dict[str, Any]]:
        return list(self.projects.values())

    def recent(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item["id"],
                "title": item["title"],
                "project_id": item["project_id"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
            for item in self.conversations.values()
        ]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def _fulfill_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=_json(payload),
        headers={"Cache-Control": "no-store"},
    )


async def _install_font_stubs(page: Page, stubbed_hosts: set[str]) -> None:
    async def css(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(status=200, content_type="text/css; charset=utf-8", body="/* deterministic font stub */\n")

    async def font(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


async def _install_api_fixtures(page: Page, state: FixtureState) -> None:
    async def api(route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        method = request.method

        if path == "/api/auth/status":
            await _fulfill_json(route, {
                "ready": True,
                "authenticated": True,
                "history_ready": True,
                "project_files_ready": True,
                "user": {"id": "usr_project_delete_fixture", "email": "qa@example.test", "name": USER_NAME, "picture": ""},
            })
            return

        if path == "/api/projects" and method == "GET":
            await _fulfill_json(route, {"projects": state.project_list()})
            return

        if path.startswith("/api/projects/") and path.endswith("/files") and method == "GET":
            project_id = path.split("/")[3]
            if project_id not in state.projects:
                await _fulfill_json(route, {"error": {"code": "project_not_found"}}, status=404)
                return
            await _fulfill_json(route, {"files": state.files.get(project_id, [])})
            return

        if path.startswith("/api/projects/") and "/files/" not in path:
            project_id = path.split("/")[3]
            project = state.projects.get(project_id)
            if method == "GET":
                if not project:
                    await _fulfill_json(route, {"error": {"code": "project_not_found"}}, status=404)
                    return
                conversations = [item for item in state.recent() if item.get("project_id") == project_id]
                await _fulfill_json(route, {"project": project, "conversations": conversations})
                return
            if method == "DELETE":
                state.delete_requests.append(project_id)
                if not project:
                    await _fulfill_json(route, {"error": {"code": "project_not_found", "message": "프로젝트를 찾을 수 없습니다."}}, status=404)
                    return
                if state.files.get(project_id):
                    await _fulfill_json(route, {"error": {"code": "project_has_files", "message": "프로젝트 파일을 먼저 삭제해 주세요."}}, status=409)
                    return
                del state.projects[project_id]
                for conversation in state.conversations.values():
                    if conversation.get("project_id") == project_id:
                        conversation["project_id"] = None
                await _fulfill_json(route, {"deleted": True, "project_id": project_id})
                return

        if path == "/api/conversations" and method == "GET":
            await _fulfill_json(route, {"conversations": state.recent()})
            return

        if path.startswith("/api/conversations/") and method == "GET":
            conversation_id = path.rsplit("/", 1)[-1]
            conversation = state.conversations.get(conversation_id)
            if not conversation:
                await _fulfill_json(route, {"error": {"code": "conversation_not_found"}}, status=404)
                return
            await _fulfill_json(route, {"conversation": conversation})
            return

        if path == "/api/outputs" and method == "GET":
            await _fulfill_json(route, {"outputs": []})
            return

        await _fulfill_json(route, {"error": {"code": "fixture_unhandled", "message": path}}, status=404)

    await page.route("**/api/**", api)


async def _open_sidebar(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    menu = page.locator("#mobileMenu")
    if await menu.get_attribute("aria-expanded") != "true":
        await menu.click()
    await page.wait_for_function("() => document.querySelector('.app-shell')?.classList.contains('sidebar-open')")


async def _close_sidebar(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    if await page.locator("#mobileMenu").get_attribute("aria-expanded") == "true":
        await page.locator("#mobileClose").click()
    await page.wait_for_function("() => !document.querySelector('.app-shell')?.classList.contains('sidebar-open')")


async def _assert_no_overflow(page: Page, stage: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {stage}: {scroll_width}>{inner_width}")


async def _wait_signed_in(page: Page) -> None:
    await page.wait_for_function(
        "expected => document.getElementById('loginButton')?.textContent.trim() === '로그아웃' && document.getElementById('accountName')?.textContent.trim() === expected && document.getElementById('projectsNavButton')?.disabled === false",
        arg=USER_NAME,
        timeout=7_000,
    )


async def _open_manage(page: Page, mobile: bool, name: str) -> None:
    await _open_sidebar(page, mobile)
    button = page.get_by_role("button", name=f"‘{name}’ 프로젝트 관리")
    await button.wait_for(state="visible")
    await button.click()
    await page.locator("#projectDialog").wait_for(state="visible")
    await page.locator("#projectDeleteButton").wait_for(state="visible")


async def _run_view(page: Page, *, name: str, width: int, height: int, mobile: bool) -> dict[str, Any]:
    state = FixtureState.seeded()
    unexpected_external_hosts: set[str] = set()
    stubbed_hosts: set[str] = set()

    def observe(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_external_hosts.add(host)

    page.on("request", observe)
    await _install_font_stubs(page, stubbed_hosts)
    await _install_api_fixtures(page, state)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    await _wait_signed_in(page)

    # New Project creation must not expose destructive Project deletion.
    await _open_sidebar(page, mobile)
    await page.locator("#projectCreateButton").click()
    await page.locator("#projectDialog").wait_for(state="visible")
    if await page.locator("#projectDeleteButton").is_visible():
        raise AssertionError("new Project dialog exposed delete action")
    await page.locator("#projectDialogCancel").click()

    # Reopen the saved active-project conversation without changing its content.
    await _open_sidebar(page, mobile)
    await page.get_by_role("button", name=QUESTION, exact=True).click()
    await page.wait_for_function(
        "([projectName, answer]) => document.getElementById('projectBanner')?.hidden === false && document.getElementById('activeProjectName')?.textContent.trim() === projectName && document.getElementById('messageList')?.textContent.includes(answer)",
        arg=[ACTIVE_NAME, ANSWER],
        timeout=7_000,
    )
    await _close_sidebar(page, mobile)
    baseline_messages = await page.locator("#messageList").inner_text()

    # Cancel path: zero DELETE requests.
    await _open_manage(page, mobile, BLOCKED_NAME)
    delete_button = page.locator("#projectDeleteButton")
    box = await delete_button.bounding_box()
    if not box or box["width"] < 44 or box["height"] < 44:
        raise AssertionError(f"delete target below 44px: {box}")
    await page.evaluate("window.confirm = () => false")
    before_cancel = len(state.delete_requests)
    await delete_button.click()
    if len(state.delete_requests) != before_cancel:
        raise AssertionError("cancel unexpectedly sent DELETE")

    # File-bearing Project must fail closed with 409 and remain visible/editable.
    await page.evaluate("window.confirm = () => true")
    await delete_button.click()
    await page.wait_for_function(
        "() => document.getElementById('projectFormError')?.hidden === false && document.getElementById('projectFormError')?.textContent.includes('프로젝트 파일을 먼저 삭제해 주세요')",
        timeout=5_000,
    )
    if state.delete_requests.count(BLOCKED_ID) != 1 or BLOCKED_ID not in state.projects:
        raise AssertionError(f"file-blocked delete contract failed: {state.delete_requests!r}")
    await page.screenshot(path=str(OUT_DIR / f"{name}-blocked.png"), full_page=True)
    await page.locator("#projectDialogClose").click()

    # Delete OTHER through its Manage action without selecting it: active Project/chat stay intact.
    await _open_manage(page, mobile, OTHER_NAME)
    await page.evaluate("window.confirm = () => true")
    await page.locator("#projectDeleteButton").click()
    await page.wait_for_function("() => document.getElementById('projectDialog')?.open === false", timeout=5_000)
    if state.delete_requests.count(OTHER_ID) != 1 or OTHER_ID in state.projects:
        raise AssertionError(f"other Project deletion failed: {state.delete_requests!r}")
    await _close_sidebar(page, mobile)
    if await page.locator("#activeProjectName").inner_text() != ACTIVE_NAME:
        raise AssertionError("deleting another Project changed active Project")
    if await page.locator("#messageList").inner_text() != baseline_messages:
        raise AssertionError("deleting another Project changed current conversation content")

    # Delete ACTIVE: preserve visible conversation, detach Project UI, retain composer focus.
    await page.locator("#editProjectButton").click()
    await page.locator("#projectDialog").wait_for(state="visible")
    await page.evaluate("window.confirm = () => true")
    await page.locator("#projectDeleteButton").click()
    await page.wait_for_function(
        "() => document.getElementById('projectDialog')?.open === false && document.getElementById('projectBanner')?.hidden === true",
        timeout=5_000,
    )
    if state.delete_requests.count(ACTIVE_ID) != 1 or ACTIVE_ID in state.projects:
        raise AssertionError(f"active Project deletion failed: {state.delete_requests!r}")
    if state.conversations[CHAT_ID]["project_id"] is not None:
        raise AssertionError("fixture conversation was not detached from deleted Project")
    if await page.locator("#messageList").inner_text() != baseline_messages:
        raise AssertionError("active Project deletion erased current conversation content")
    focused = await page.evaluate("document.activeElement && document.activeElement.id")
    if focused != "messageInput":
        raise AssertionError(f"composer focus not restored after active Project delete: {focused!r}")

    await _open_sidebar(page, mobile)
    if await page.get_by_role("button", name=f"‘{ACTIVE_NAME}’ 프로젝트 관리").count() != 0:
        raise AssertionError("deleted active Project remained in Project list")
    if await page.get_by_role("button", name=f"‘{OTHER_NAME}’ 프로젝트 관리").count() != 0:
        raise AssertionError("deleted other Project remained in Project list")
    if await page.get_by_role("button", name=f"‘{BLOCKED_NAME}’ 프로젝트 관리").count() != 1:
        raise AssertionError("blocked Project unexpectedly disappeared")
    manage_box = await page.get_by_role("button", name=f"‘{BLOCKED_NAME}’ 프로젝트 관리").bounding_box()
    if not manage_box or manage_box["width"] < 44 or manage_box["height"] < 44:
        raise AssertionError(f"Project manage target below 44px: {manage_box}")
    await _assert_no_overflow(page, f"{name}-final")
    await page.screenshot(path=str(OUT_DIR / f"{name}-final.png"), full_page=True)

    visible = (await page.locator("body").inner_text()).lower()
    leaked = [term for term in FORBIDDEN_VISIBLE_TERMS if term in visible]
    if leaked:
        raise AssertionError(f"routing jargon visible in Project deletion flow: {leaked!r}")
    if unexpected_external_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_external_hosts)}")

    return {
        "viewport": {"width": width, "height": height},
        "delete_requests": state.delete_requests,
        "remaining_projects": sorted(state.projects),
        "conversation_project_id_after_active_delete": state.conversations[CHAT_ID]["project_id"],
        "messages_preserved": True,
        "composer_focus": focused,
        "delete_button_box": box,
        "manage_button_box": manage_box,
        "unexpected_external_hosts": sorted(unexpected_external_hosts),
        "stubbed_font_hosts": sorted(stubbed_hosts),
    }


async def main() -> None:
    report: dict[str, Any] = {"status": "PASS", "views": {}}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            for name, width, height, mobile in (
                ("desktop", 1440, 1000, False),
                ("mobile", 390, 844, True),
            ):
                context = await browser.new_context(locale="ko-KR")
                page = await context.new_page()
                try:
                    report["views"][name] = await _run_view(page, name=name, width=width, height=height, mobile=mobile)
                finally:
                    await context.close()
        finally:
            await browser.close()

    (OUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
