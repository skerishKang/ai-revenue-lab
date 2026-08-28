from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright


BASE_URL = os.environ.get("B62_OUTPUTS_QA_BASE_URL", "http://127.0.0.1:8771")
OUT_DIR = Path(os.environ.get("B62_OUTPUTS_QA_OUT_DIR", ".tmp/b62-saved-outputs-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

USER_NAME = "저장 답변 브라우저 사용자"
QUESTION = "제주 가족여행 준비를 한 문장으로 정리해줘"
ANSWER = "신분증과 충전기, 날씨에 맞는 옷을 먼저 챙기고 일정은 여유 있게 잡아보세요."
OUTPUT_ID = "out_00000000000000000000000000000001"
RENAMED_TITLE = "제주 가족여행 준비 요약"
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
FORBIDDEN_SAVE_KEYS = frozenset({"model", "provider", "route", "business14", "attachments"})


@dataclass
class FixtureState:
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_posts: list[dict[str, Any]] = field(default_factory=list)
    output_patches: list[dict[str, Any]] = field(default_factory=list)
    output_deletes: int = 0
    stream_posts: list[dict[str, Any]] = field(default_factory=list)

    def listing(self) -> list[dict[str, Any]]:
        result = []
        for item in self.outputs.values():
            result.append(
                {
                    "id": item["id"],
                    "title": item["title"],
                    "conversation_id": None,
                    "project_id": None,
                    "created_at": item["created_at"],
                    "updated_at": item["updated_at"],
                }
            )
        return result


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
            body="/* deterministic Saved Outputs browser QA: decorative font suppressed */\n",
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
                    "id": "usr_outputs_browser_fixture",
                    "email": "outputs@example.test",
                    "name": USER_NAME,
                    "picture": "",
                },
            },
        )

    async def projects(route: Route) -> None:
        await _fulfill_json(route, {"projects": []})

    async def conversations(route: Route) -> None:
        await _fulfill_json(route, {"conversations": []})

    async def stream(route: Route) -> None:
        if route.request.method != "POST":
            await _fulfill_json(route, {"error": {"code": "method_not_allowed"}}, status=405)
            return
        body = _payload(route)
        state.stream_posts.append(body)
        if any(key in body for key in ("model", "provider", "route", "business14")):
            raise AssertionError(f"browser selected routing internals: {body!r}")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages or messages[-1] != {"role": "user", "content": QUESTION}:
            raise AssertionError(f"unexpected chat payload: {body!r}")
        sse = (
            "event: delta\n"
            f"data: {_json({'delta': ANSWER})}\n\n"
            "event: done\n"
            f"data: {_json({'done': True, 'conversation_id': 'chat_outputs_browser_0000000000000001'})}\n\n"
        )
        await route.fulfill(
            status=200,
            content_type="text/event-stream; charset=utf-8",
            body=sse,
            headers={"Cache-Control": "no-store"},
        )

    async def outputs_root(route: Route) -> None:
        if route.request.method == "GET":
            await _fulfill_json(route, {"outputs": state.listing()})
            return
        if route.request.method == "POST":
            body = _payload(route)
            state.output_posts.append(body)
            if set(body) != {"title", "content"}:
                raise AssertionError(f"save payload must contain title/content only: {body!r}")
            if any(key in body for key in FORBIDDEN_SAVE_KEYS):
                raise AssertionError(f"save payload leaked routing/attachment metadata: {body!r}")
            if body.get("content") != ANSWER:
                raise AssertionError(f"saved content differs from visible assistant answer: {body!r}")
            title = body.get("title")
            if not isinstance(title, str) or not title or len(title) > 100:
                raise AssertionError(f"invalid generated title: {title!r}")
            item = {
                "id": OUTPUT_ID,
                "title": title,
                "content": ANSWER,
                "conversation_id": None,
                "project_id": None,
                "created_at": "2026-08-28T05:00:00Z",
                "updated_at": "2026-08-28T05:00:00Z",
            }
            state.outputs[OUTPUT_ID] = item
            await _fulfill_json(route, {"output": item}, status=201)
            return
        await _fulfill_json(route, {"error": {"code": "method_not_allowed"}}, status=405)

    async def output_detail(route: Route) -> None:
        output_id = route.request.url.rsplit("/", 1)[-1].split("?", 1)[0]
        item = state.outputs.get(output_id)
        if not item:
            await _fulfill_json(route, {"error": {"code": "not_found"}}, status=404)
            return
        if route.request.method == "GET":
            await _fulfill_json(route, {"output": item})
            return
        if route.request.method == "PATCH":
            body = _payload(route)
            state.output_patches.append(body)
            if body != {"title": RENAMED_TITLE}:
                raise AssertionError(f"rename payload must be bounded title only: {body!r}")
            item = dict(item)
            item["title"] = RENAMED_TITLE
            item["updated_at"] = "2026-08-28T05:01:00Z"
            state.outputs[output_id] = item
            await _fulfill_json(route, {"output": item})
            return
        if route.request.method == "DELETE":
            state.output_deletes += 1
            del state.outputs[output_id]
            await _fulfill_json(route, {"deleted": True})
            return
        await _fulfill_json(route, {"error": {"code": "method_not_allowed"}}, status=405)

    await page.route("**/api/auth/status", auth_status)
    await page.route("**/api/projects", projects)
    await page.route("**/api/conversations", conversations)
    await page.route("**/api/chat/stream", stream)
    await page.route("**/api/outputs", outputs_root)
    await page.route("**/api/outputs/*", output_detail)


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


async def _assert_download(page: Page, selector: str) -> str:
    async with page.expect_download(timeout=5_000) as pending:
        await page.locator(selector).click()
    download = await pending.value
    filename = download.suggested_filename
    if not filename.endswith(".txt"):
        raise AssertionError(f"expected UTF-8 text download filename, got {filename!r}")
    return filename


async def _run_view(page: Page, *, name: str, width: int, height: int, mobile: bool) -> dict[str, Any]:
    state = FixtureState()
    unexpected_external_hosts: set[str] = set()
    stubbed_static_hosts: set[str] = set()

    def observe(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_external_hosts.add(host)

    page.on("request", observe)
    await page.add_init_script(
        """
        (() => {
          const writes = [];
          Object.defineProperty(window, '__qaClipboardWrites', { value: writes, writable: false });
          try {
            Object.defineProperty(navigator, 'clipboard', {
              configurable: true,
              value: { writeText: async (text) => { writes.push(String(text)); } }
            });
          } catch (_) {}
        })();
        """
    )
    await _install_static_font_stubs(page, stubbed_static_hosts)
    await _install_fixtures(page, state)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

    await page.wait_for_function(
        "expected => document.getElementById('loginButton')?.textContent.trim() === '로그아웃' && document.getElementById('accountName')?.textContent.trim() === expected && document.getElementById('outputsNavButton')?.hidden === false && document.getElementById('outputsNavButton')?.disabled === false",
        arg=USER_NAME,
        timeout=5_000,
    )
    await _assert_no_overflow(page, f"{name}-ready")

    await page.locator("#messageInput").fill(QUESTION)
    await page.locator("#sendButton").click()
    await _wait_text(page, "#messageList", ANSWER)
    await page.locator("#messageList .answer-copy").wait_for(state="visible")
    await page.locator("#messageList .answer-download").wait_for(state="visible")
    await page.locator("#messageList .answer-save").wait_for(state="visible")
    await page.screenshot(path=str(OUT_DIR / f"{name}-answer-actions.png"), full_page=True)

    await page.locator("#messageList .answer-copy").click()
    await page.wait_for_function("expected => window.__qaClipboardWrites?.at(-1) === expected", arg=ANSWER, timeout=5_000)
    answer_download = await _assert_download(page, "#messageList .answer-download")

    await page.locator("#messageList .answer-save").click()
    await page.wait_for_function(
        "() => document.querySelector('#messageList .answer-save')?.dataset.saved === 'true' && document.querySelector('#messageList .answer-save')?.textContent.trim() === '저장됨'",
        timeout=5_000,
    )
    if len(state.output_posts) != 1:
        raise AssertionError(f"expected one output save POST, saw {len(state.output_posts)}")

    await _open_sidebar_if_mobile(page, mobile)
    await page.wait_for_function(
        "() => document.querySelectorAll('#outputsList .output-item').length === 1 && document.getElementById('outputsBadge')?.textContent.trim() === '1'",
        timeout=5_000,
    )
    saved_title = state.outputs[OUTPUT_ID]["title"]
    if ANSWER in await page.locator("#outputsList").inner_text():
        raise AssertionError("output list leaked full saved content")
    await page.screenshot(path=str(OUT_DIR / f"{name}-outputs-list.png"), full_page=True)

    await page.locator("#outputsList .output-item").click()
    await page.locator("#savedOutputDialog").wait_for(state="visible")
    await page.wait_for_function(
        "expected => document.getElementById('savedOutputContent')?.textContent.trim() === expected",
        arg=ANSWER,
        timeout=5_000,
    )
    if await page.locator("#savedOutputTitleInput").input_value() != saved_title:
        raise AssertionError("saved output title did not reopen correctly")
    await page.screenshot(path=str(OUT_DIR / f"{name}-output-open.png"), full_page=True)

    await page.locator("#savedOutputCopy").click()
    await page.wait_for_function("expected => window.__qaClipboardWrites?.length >= 2 && window.__qaClipboardWrites.at(-1) === expected", arg=ANSWER, timeout=5_000)
    dialog_download = await _assert_download(page, "#savedOutputDownload")

    await page.locator("#savedOutputTitleInput").fill(RENAMED_TITLE)
    await page.locator("#savedOutputRename").click()
    await _wait_text(page, "#savedOutputStatus", "제목을 저장했습니다.")
    if len(state.output_patches) != 1:
        raise AssertionError(f"expected one output rename PATCH, saw {len(state.output_patches)}")
    await _open_sidebar_if_mobile(page, mobile)
    await _wait_text(page, "#outputsList", RENAMED_TITLE)

    page.once("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    await page.locator("#savedOutputDelete").click()
    await page.wait_for_function("() => document.getElementById('savedOutputDialog')?.open === false", timeout=5_000)
    await page.wait_for_function(
        "() => document.querySelectorAll('#outputsList .output-item').length === 0 && document.getElementById('outputsBadge')?.textContent.trim() === '비어 있음'",
        timeout=5_000,
    )
    if state.output_deletes != 1:
        raise AssertionError(f"expected one output DELETE, saw {state.output_deletes}")
    if page.locator("#messageList").is_visible and ANSWER not in await page.locator("#messageList").inner_text():
        raise AssertionError("deleting saved output unexpectedly removed source chat answer")
    await _assert_no_overflow(page, f"{name}-deleted")
    await page.screenshot(path=str(OUT_DIR / f"{name}-outputs-deleted.png"), full_page=True)

    if unexpected_external_hosts:
        raise AssertionError(f"browser QA made unexpected external requests: {sorted(unexpected_external_hosts)}")

    clipboard_writes = await page.evaluate("window.__qaClipboardWrites || []")
    return {
        "stream_requests": len(state.stream_posts),
        "save_posts": len(state.output_posts),
        "rename_patches": len(state.output_patches),
        "delete_requests": state.output_deletes,
        "clipboard_writes": len(clipboard_writes),
        "answer_download": answer_download,
        "dialog_download": dialog_download,
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
                desktop = await browser.new_page(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                report["views"]["desktop"] = await _run_view(
                    desktop, name="desktop", width=1440, height=1000, mobile=False
                )
                await desktop.close()

                mobile = await browser.new_page(viewport={"width": 390, "height": 844}, accept_downloads=True)
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
