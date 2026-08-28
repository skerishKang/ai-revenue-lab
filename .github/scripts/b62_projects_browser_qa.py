from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_PROJECTS_QA_BASE_URL", "http://127.0.0.1:8770")
OUT_DIR = Path(os.environ.get("B62_PROJECTS_QA_OUT_DIR", ".tmp/b62-projects-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

USER_NAME = "프로젝트 브라우저 사용자"
PROJECT_ID = "proj_00000000000000000000000000000001"
PROJECT_NAME = "제주 가족여행"
PROJECT_NAME_EDITED = "제주 부모님 여행"
PROJECT_INSTRUCTIONS = "부모님과 함께 보는 내용이라 쉬운 한국어로 답해줘."
PROJECT_INSTRUCTIONS_EDITED = "부모님이 읽기 쉽게 핵심부터 짧게 설명해줘."
FIRST_QUESTION = "제주 여행 준비물을 세 가지 알려줘"
FIRST_ANSWER = "신분증, 충전기, 날씨에 맞는 옷을 먼저 챙겨보세요."
SECOND_QUESTION = "첫날 일정도 간단히 짜줘"
SECOND_ANSWER = "도착 후 점심, 해안 산책, 이른 저녁 순서로 여유 있게 잡아보세요."
CHAT_ONE = "chat_project_000000000000000000000001"
CHAT_TWO = "chat_project_000000000000000000000002"
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
FORBIDDEN_ROUTING_KEYS = frozenset({"model", "provider", "route", "business14"})


@dataclass
class FixtureState:
    projects: dict[str, dict[str, Any]] = field(default_factory=dict)
    conversations: dict[str, dict[str, Any]] = field(default_factory=dict)
    project_posts: list[dict[str, Any]] = field(default_factory=list)
    project_patches: list[dict[str, Any]] = field(default_factory=list)
    stream_posts: list[dict[str, Any]] = field(default_factory=list)
    clock: int = 0

    def now(self) -> str:
        self.clock += 1
        return f"2026-08-28T04:54:{self.clock:02d}Z"

    def project_list(self) -> list[dict[str, Any]]:
        return list(self.projects.values())

    def recent(self) -> list[dict[str, Any]]:
        items = sorted(self.conversations.values(), key=lambda item: item["updated_at"], reverse=True)
        return [
            {
                "id": item["id"],
                "title": item["title"],
                "project_id": item["project_id"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
            for item in items
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


def _payload(route: Route) -> dict[str, Any]:
    raw = route.request.post_data
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise AssertionError(f"expected object payload, got {value!r}")
    return value


async def _install_static_font_stubs(page: Page, stubbed_hosts: set[str]) -> None:
    async def css(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(
            status=200,
            content_type="text/css; charset=utf-8",
            body="/* deterministic Projects browser QA: external decorative font suppressed */\n",
            headers={"Cache-Control": "no-store"},
        )

    async def font(route: Route) -> None:
        host = (urlparse(route.request.url).hostname or "").lower()
        stubbed_hosts.add(host)
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


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
                    "id": "usr_projects_browser_fixture",
                    "email": "projects@example.test",
                    "name": USER_NAME,
                    "picture": "",
                },
            },
        )

    async def projects_root(route: Route) -> None:
        method = route.request.method
        if method == "GET":
            await _fulfill_json(route, {"projects": state.project_list()})
            return
        if method == "POST":
            body = _payload(route)
            state.project_posts.append(body)
            if set(body) != {"name", "instructions"}:
                raise AssertionError(f"unexpected project create fields: {body!r}")
            if body["name"] != PROJECT_NAME or body["instructions"] != PROJECT_INSTRUCTIONS:
                raise AssertionError(f"unexpected project create payload: {body!r}")
            now = state.now()
            project = {
                "id": PROJECT_ID,
                "name": body["name"],
                "instructions": body["instructions"],
                "created_at": now,
                "updated_at": now,
            }
            state.projects[PROJECT_ID] = project
            await _fulfill_json(route, {"project": project}, status=201)
            return
        await _fulfill_json(route, {"error": {"code": "method_not_allowed"}}, status=405)

    async def project_detail(route: Route) -> None:
        project_id = route.request.url.split("/api/projects/", 1)[-1].split("?", 1)[0]
        project = state.projects.get(project_id)
        if not project:
            await _fulfill_json(route, {"error": {"code": "not_found"}}, status=404)
            return
        if route.request.method == "GET":
            await _fulfill_json(route, {"project": project})
            return
        if route.request.method == "PATCH":
            body = _payload(route)
            state.project_patches.append(body)
            if set(body) != {"name", "instructions"}:
                raise AssertionError(f"unexpected project patch fields: {body!r}")
            if body["name"] != PROJECT_NAME_EDITED or body["instructions"] != PROJECT_INSTRUCTIONS_EDITED:
                raise AssertionError(f"unexpected project patch payload: {body!r}")
            updated = dict(project)
            updated.update(name=body["name"], instructions=body["instructions"], updated_at=state.now())
            state.projects[project_id] = updated
            await _fulfill_json(route, {"project": updated})
            return
        await _fulfill_json(route, {"error": {"code": "method_not_allowed"}}, status=405)

    async def conversations(route: Route) -> None:
        await _fulfill_json(route, {"conversations": state.recent()})

    async def conversation_detail(route: Route) -> None:
        conversation_id = route.request.url.rsplit("/", 1)[-1].split("?", 1)[0]
        conversation = state.conversations.get(conversation_id)
        if not conversation:
            await _fulfill_json(route, {"error": {"code": "not_found"}}, status=404)
            return
        await _fulfill_json(route, {"conversation": conversation})

    async def stream(route: Route) -> None:
        if route.request.method != "POST":
            await _fulfill_json(route, {"error": {"code": "method_not_allowed"}}, status=405)
            return
        body = _payload(route)
        state.stream_posts.append(body)
        if any(key in body for key in FORBIDDEN_ROUTING_KEYS):
            raise AssertionError(f"browser selected routing internals: {body!r}")
        if body.get("project_id") != PROJECT_ID:
            raise AssertionError(f"project_id not bound to chat request: {body!r}")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            raise AssertionError(f"chat request missing messages: {body!r}")
        latest = messages[-1]
        if not isinstance(latest, dict) or latest.get("role") != "user" or not isinstance(latest.get("content"), str):
            raise AssertionError(f"chat request missing latest user message: {body!r}")
        question = latest["content"]
        incoming = body.get("conversation_id")

        if question == FIRST_QUESTION:
            if incoming is not None:
                raise AssertionError(f"first project chat unexpectedly reused conversation id: {body!r}")
            conversation_id = CHAT_ONE
            answer = FIRST_ANSWER
        elif question == SECOND_QUESTION:
            if incoming is not None:
                raise AssertionError(f"new project chat unexpectedly reused conversation id: {body!r}")
            conversation_id = CHAT_TWO
            answer = SECOND_ANSWER
        else:
            raise AssertionError(f"unexpected chat question: {question!r}")

        now = state.now()
        state.conversations[conversation_id] = {
            "id": conversation_id,
            "title": question,
            "project_id": PROJECT_ID,
            "created_at": now,
            "updated_at": now,
            "messages": [
                {"role": "user", "content": question},
                {"role": "assistant", "content": answer},
            ],
        }
        project = state.projects[PROJECT_ID]
        sse = (
            "event: delta\n"
            f"data: {_json({'delta': answer})}\n\n"
            "event: done\n"
            f"data: {_json({'done': True, 'conversation_id': conversation_id, 'project_id': PROJECT_ID, 'project': {'id': PROJECT_ID, 'name': project['name']}})}\n\n"
        )
        await route.fulfill(
            status=200,
            content_type="text/event-stream; charset=utf-8",
            body=sse,
            headers={"Cache-Control": "no-store"},
        )

    await page.route("**/api/auth/status", auth_status)
    await page.route("**/api/projects", projects_root)
    await page.route("**/api/projects/*", project_detail)
    await page.route("**/api/conversations", conversations)
    await page.route("**/api/conversations/*", conversation_detail)
    await page.route("**/api/chat/stream", stream)


async def _open_sidebar_if_mobile(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    menu = page.locator("#mobileMenu")
    await menu.wait_for(state="visible")
    if await menu.get_attribute("aria-expanded") != "true":
        await menu.click()
    await page.wait_for_function("() => document.querySelector('.app-shell')?.classList.contains('sidebar-open')")


async def _assert_no_overflow(page: Page, stage: str) -> None:
    scroll_width = await page.evaluate("document.documentElement.scrollWidth")
    inner_width = await page.evaluate("window.innerWidth")
    if scroll_width > inner_width + 1:
        raise AssertionError(f"horizontal overflow at {stage}: scrollWidth={scroll_width}, innerWidth={inner_width}")


async def _wait_text(page: Page, selector: str, expected: str) -> None:
    await page.wait_for_function(
        "([selector, expected]) => document.querySelector(selector)?.textContent.includes(expected)",
        arg=[selector, expected],
        timeout=5_000,
    )


async def _wait_history(page: Page, title: str) -> None:
    await page.wait_for_function(
        "expected => Array.from(document.querySelectorAll('#historyList .history-item')).some(node => node.textContent.trim() === expected)",
        arg=title,
        timeout=5_000,
    )


async def _run_view(page: Page, *, name: str, width: int, height: int, mobile: bool) -> dict[str, Any]:
    state = FixtureState()
    unexpected_external_hosts: set[str] = set()
    stubbed_static_hosts: set[str] = set()

    def observe(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_external_hosts.add(host)

    page.on("request", observe)
    await _install_static_font_stubs(page, stubbed_static_hosts)
    await _install_fixtures(page, state)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

    await page.wait_for_function(
        "expected => document.getElementById('loginButton')?.textContent.trim() === '로그아웃' && document.getElementById('accountName')?.textContent.trim() === expected && document.getElementById('projectsNavButton')?.disabled === false",
        arg=USER_NAME,
        timeout=5_000,
    )
    await _open_sidebar_if_mobile(page, mobile)
    await _wait_text(page, "#projectsBadge", "새로 만들기")
    await _assert_no_overflow(page, f"{name}-empty-projects")
    await page.screenshot(path=str(OUT_DIR / f"{name}-projects-empty.png"), full_page=True)

    await page.locator("#projectsNavButton").click()
    await page.locator("#projectDialog").wait_for(state="visible")
    await page.locator("#projectNameInput").fill(PROJECT_NAME)
    await page.locator("#projectInstructionsInput").fill(PROJECT_INSTRUCTIONS)
    await page.locator("#projectSaveButton").click()
    await page.wait_for_function("() => document.getElementById('projectDialog')?.open === false", timeout=5_000)
    await page.wait_for_function(
        "expected => document.getElementById('projectBanner')?.hidden === false && document.getElementById('activeProjectName')?.textContent.trim() === expected",
        arg=PROJECT_NAME,
        timeout=5_000,
    )
    if len(state.project_posts) != 1:
        raise AssertionError(f"expected exactly one project create request, saw {len(state.project_posts)}")
    await _assert_no_overflow(page, f"{name}-project-active")
    await page.screenshot(path=str(OUT_DIR / f"{name}-project-active.png"), full_page=True)

    await page.locator("#messageInput").fill(FIRST_QUESTION)
    await page.locator("#sendButton").click()
    await _wait_text(page, "#messageList", FIRST_ANSWER)
    await _wait_history(page, FIRST_QUESTION)
    if len(state.stream_posts) != 1:
        raise AssertionError(f"expected one stream request after first question, saw {len(state.stream_posts)}")
    first_payload = state.stream_posts[0]
    if first_payload.get("project_id") != PROJECT_ID or "conversation_id" in first_payload:
        raise AssertionError(f"first project chat contract mismatch: {first_payload!r}")
    await page.screenshot(path=str(OUT_DIR / f"{name}-project-first-chat.png"), full_page=True)

    await _open_sidebar_if_mobile(page, mobile)
    await page.locator("#newChatButton").click()
    await page.wait_for_function(
        "expected => document.querySelector('.app-shell')?.dataset.state === 'home' && document.getElementById('projectBanner')?.hidden === false && document.getElementById('activeProjectName')?.textContent.trim() === expected",
        arg=PROJECT_NAME,
        timeout=5_000,
    )
    await page.locator("#messageInput").fill(SECOND_QUESTION)
    await page.locator("#sendButton").click()
    await _wait_text(page, "#messageList", SECOND_ANSWER)
    await _wait_history(page, SECOND_QUESTION)
    if len(state.stream_posts) != 2:
        raise AssertionError(f"expected two total stream requests, saw {len(state.stream_posts)}")
    second_payload = state.stream_posts[1]
    if second_payload.get("project_id") != PROJECT_ID or "conversation_id" in second_payload:
        raise AssertionError(f"new project chat did not preserve only project context: {second_payload!r}")
    await page.screenshot(path=str(OUT_DIR / f"{name}-project-new-chat.png"), full_page=True)

    await page.locator("#exitProjectButton").click()
    await page.wait_for_function("() => document.getElementById('projectBanner')?.hidden === true", timeout=5_000)

    await _open_sidebar_if_mobile(page, mobile)
    project_button = page.locator("#projectsList .project-item", has_text=PROJECT_NAME)
    await project_button.click()
    await page.wait_for_function(
        "expected => document.getElementById('projectBanner')?.hidden === false && document.getElementById('activeProjectName')?.textContent.trim() === expected",
        arg=PROJECT_NAME,
        timeout=5_000,
    )

    await _open_sidebar_if_mobile(page, mobile)
    history_button = page.locator("#historyList .history-item", has_text=FIRST_QUESTION)
    await history_button.click()
    await page.wait_for_function(
        "([question, answer, project]) => document.getElementById('messageList')?.innerText.includes(question) && document.getElementById('messageList')?.innerText.includes(answer) && document.getElementById('activeProjectName')?.textContent.trim() === project",
        arg=[FIRST_QUESTION, FIRST_ANSWER, PROJECT_NAME],
        timeout=5_000,
    )
    await page.screenshot(path=str(OUT_DIR / f"{name}-project-reopened.png"), full_page=True)

    await page.locator("#editProjectButton").click()
    await page.locator("#projectDialog").wait_for(state="visible")
    await page.locator("#projectNameInput").fill(PROJECT_NAME_EDITED)
    await page.locator("#projectInstructionsInput").fill(PROJECT_INSTRUCTIONS_EDITED)
    await page.locator("#projectSaveButton").click()
    await page.wait_for_function("() => document.getElementById('projectDialog')?.open === false", timeout=5_000)
    await page.wait_for_function(
        "expected => document.getElementById('activeProjectName')?.textContent.trim() === expected",
        arg=PROJECT_NAME_EDITED,
        timeout=5_000,
    )
    if len(state.project_patches) != 1:
        raise AssertionError(f"expected exactly one project PATCH, saw {len(state.project_patches)}")
    await _open_sidebar_if_mobile(page, mobile)
    await _wait_text(page, "#projectsList", PROJECT_NAME_EDITED)
    await _assert_no_overflow(page, f"{name}-project-edited")
    await page.screenshot(path=str(OUT_DIR / f"{name}-project-edited.png"), full_page=True)

    if unexpected_external_hosts:
        raise AssertionError(f"browser QA made unexpected external requests: {sorted(unexpected_external_hosts)}")

    return {
        "project_create_requests": len(state.project_posts),
        "project_patch_requests": len(state.project_patches),
        "stream_requests": len(state.stream_posts),
        "conversation_ids": sorted(state.conversations),
        "final_project_name": state.projects[PROJECT_ID]["name"],
        "stubbed_static_hosts": sorted(stubbed_static_hosts),
        "unexpected_external_hosts": sorted(unexpected_external_hosts),
        "viewport": {"width": width, "height": height},
    }


async def main() -> None:
    report: dict[str, Any] = {
        "status": "RUNNING",
        "base_url": BASE_URL,
        "model_selection": "DEFERRED",
        "real_provider_calls": 0,
        "real_google_oauth": 0,
        "real_d1": 0,
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
                report["views"]["desktop"] = await _run_view(
                    desktop, name="desktop", width=1440, height=1000, mobile=False
                )
                await desktop.close()

                mobile = await browser.new_page(viewport={"width": 390, "height": 844})
                report["views"]["mobile"] = await _run_view(
                    mobile, name="mobile", width=390, height=844, mobile=True
                )
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
