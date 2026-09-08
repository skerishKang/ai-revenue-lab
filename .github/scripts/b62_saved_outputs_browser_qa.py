from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import Page, Route, async_playwright

from b62_product_confirm_helpers import (
    accept_product_confirm,
    cancel_product_confirm,
    install_native_dialog_guard,
    open_product_confirm,
)


BASE_URL = os.environ.get("B62_OUTPUTS_QA_BASE_URL", "http://127.0.0.1:8771")
OUT_DIR = Path(os.environ.get("B62_OUTPUTS_QA_OUT_DIR", ".tmp/b62-saved-outputs-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

USER_NAME = "저장 답변 브라우저 사용자"
QUESTION = "제주 가족여행 준비를 한 문장으로 정리해줘"
ANSWER = "신분증과 충전기, 날씨에 맞는 옷을 먼저 챙기고 일정은 여유 있게 잡아보세요."
OUTPUT_ID = "out_00000000000000000000000000000001"
RENAMED_TITLE = "제주 가족여행 준비 요약"
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
FORBIDDEN_KEYS = frozenset({"model", "provider", "route", "business14", "attachments"})


@dataclass
class FixtureState:
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_posts: list[dict[str, Any]] = field(default_factory=list)
    output_patches: list[dict[str, Any]] = field(default_factory=list)
    output_deletes: int = 0
    stream_posts: list[dict[str, Any]] = field(default_factory=list)

    def listing(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item["id"],
                "title": item["title"],
                "conversation_id": None,
                "project_id": None,
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
            for item in self.outputs.values()
        ]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


async def _reply_json(route: Route, payload: Any, status: int = 200) -> None:
    await route.fulfill(
        status=status,
        content_type="application/json; charset=utf-8",
        body=_json(payload),
        headers={"Cache-Control": "no-store"},
    )


def _request_json(route: Route) -> dict[str, Any]:
    raw = route.request.post_data
    value = json.loads(raw) if raw else {}
    if not isinstance(value, dict):
        raise AssertionError(f"expected object payload, got {value!r}")
    return value


async def _stub_fonts(page: Page, seen: set[str]) -> None:
    async def css(route: Route) -> None:
        seen.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(status=200, content_type="text/css; charset=utf-8", body="/* deterministic Saved Outputs QA font stub */\n")

    async def font(route: Route) -> None:
        seen.add((urlparse(route.request.url).hostname or "").lower())
        await route.fulfill(status=204, body="")

    await page.route("https://cdn.jsdelivr.net/**", css)
    await page.route("https://fonts.googleapis.com/**", css)
    await page.route("https://fonts.gstatic.com/**", font)


async def _install_api(page: Page, state: FixtureState) -> None:
    async def auth(route: Route) -> None:
        await _reply_json(route, {
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
        })

    async def projects(route: Route) -> None:
        await _reply_json(route, {"projects": []})

    async def conversations(route: Route) -> None:
        await _reply_json(route, {"conversations": []})

    async def stream(route: Route) -> None:
        body = _request_json(route)
        state.stream_posts.append(body)
        if any(key in body for key in ("model", "provider", "route", "business14")):
            raise AssertionError(f"browser selected routing internals: {body!r}")
        if body.get("messages", [])[-1:] != [{"role": "user", "content": QUESTION}]:
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
            await _reply_json(route, {"outputs": state.listing()})
            return
        if route.request.method != "POST":
            await _reply_json(route, {"error": {"code": "method_not_allowed"}}, status=405)
            return
        body = _request_json(route)
        state.output_posts.append(body)
        if set(body) != {"title", "content"} or any(key in body for key in FORBIDDEN_KEYS):
            raise AssertionError(f"save payload is not bounded to title/content: {body!r}")
        if body.get("content") != ANSWER:
            raise AssertionError(f"save content differs from visible answer: {body!r}")
        title = body.get("title")
        if not isinstance(title, str) or not title or len(title) > 100:
            raise AssertionError(f"invalid saved title: {title!r}")
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
        await _reply_json(route, {"output": item}, status=201)

    async def output_detail(route: Route) -> None:
        output_id = route.request.url.rsplit("/", 1)[-1].split("?", 1)[0]
        item = state.outputs.get(output_id)
        if item is None:
            await _reply_json(route, {"error": {"code": "not_found"}}, status=404)
            return
        if route.request.method == "GET":
            await _reply_json(route, {"output": item})
            return
        if route.request.method == "PATCH":
            body = _request_json(route)
            state.output_patches.append(body)
            if body != {"title": RENAMED_TITLE}:
                raise AssertionError(f"rename must send title only: {body!r}")
            updated = dict(item, title=RENAMED_TITLE, updated_at="2026-08-28T05:01:00Z")
            state.outputs[output_id] = updated
            await _reply_json(route, {"output": updated})
            return
        if route.request.method == "DELETE":
            state.output_deletes += 1
            del state.outputs[output_id]
            await _reply_json(route, {"deleted": True})
            return
        await _reply_json(route, {"error": {"code": "method_not_allowed"}}, status=405)

    await page.route("**/api/auth/status", auth)
    await page.route("**/api/projects", projects)
    await page.route("**/api/conversations", conversations)
    await page.route("**/api/chat/stream", stream)
    await page.route("**/api/outputs", outputs_root)
    await page.route("**/api/outputs/*", output_detail)


async def _open_sidebar(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    menu = page.locator("#mobileMenu")
    await menu.wait_for(state="visible")
    if await menu.get_attribute("aria-expanded") != "true":
        await menu.click()
    await page.wait_for_function("() => document.querySelector('.app-shell')?.classList.contains('sidebar-open')")


async def _wait_text(page: Page, selector: str, text: str) -> None:
    await page.wait_for_function(
        "([selector, text]) => document.querySelector(selector)?.textContent.includes(text)",
        arg=[selector, text],
        timeout=5_000,
    )


async def _no_overflow(page: Page, stage: str) -> None:
    values = await page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    if values[0] > values[1] + 1:
        raise AssertionError(f"horizontal overflow at {stage}: {values}")


async def _download(page: Page, selector: str) -> str:
    async with page.expect_download(timeout=5_000) as pending:
        await page.locator(selector).click()
    item = await pending.value
    if not item.suggested_filename.endswith(".txt"):
        raise AssertionError(f"expected .txt download, got {item.suggested_filename!r}")
    return item.suggested_filename


async def _run(page: Page, *, label: str, width: int, height: int, mobile: bool) -> dict[str, Any]:
    state = FixtureState()
    unexpected_hosts: set[str] = set()
    stubbed_hosts: set[str] = set()
    native_dialogs: list[str] = []

    def observe(request) -> None:
        host = (urlparse(request.url).hostname or "").lower()
        if host not in {"127.0.0.1", "localhost"} and host not in STATIC_FONT_HOSTS:
            unexpected_hosts.add(host)

    page.on("request", observe)
    await install_native_dialog_guard(page, native_dialogs)
    await page.add_init_script(
        """
        (() => {
          const writes = [];
          Object.defineProperty(window, '__qaClipboardWrites', {value: writes});
          Object.defineProperty(navigator, 'clipboard', {
            configurable: true,
            value: {writeText: async text => { writes.push(String(text)); }}
          });
        })();
        """
    )
    await _stub_fonts(page, stubbed_hosts)
    await _install_api(page, state)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

    await page.wait_for_function(
        "expected => document.getElementById('loginButton')?.textContent.trim() === '로그아웃' && document.getElementById('accountName')?.textContent.trim() === expected && !document.getElementById('outputsNavButton')?.hidden && !document.getElementById('outputsNavButton')?.disabled",
        arg=USER_NAME,
        timeout=5_000,
    )
    await _no_overflow(page, f"{label}-ready")

    await page.locator("#messageInput").fill(QUESTION)
    await page.locator("#sendButton").click()
    await _wait_text(page, "#messageList", ANSWER)
    for selector in (".answer-copy", ".answer-download", ".answer-save"):
        await page.locator(f"#messageList {selector}").wait_for(state="visible")

    await page.locator("#messageList .answer-copy").click()
    await page.wait_for_function("expected => window.__qaClipboardWrites?.at(-1) === expected", arg=ANSWER)
    answer_download = await _download(page, "#messageList .answer-download")

    await page.locator("#messageList .answer-save").click()
    await page.wait_for_function(
        "() => document.querySelector('#messageList .answer-save')?.dataset.saved === 'true' && document.querySelector('#messageList .answer-save')?.textContent.trim() === '저장됨'",
        timeout=5_000,
    )
    if len(state.output_posts) != 1:
        raise AssertionError(f"expected one save POST, saw {len(state.output_posts)}")

    await _open_sidebar(page, mobile)
    await page.wait_for_function(
        "() => document.querySelectorAll('#outputsList .output-item').length === 1 && document.getElementById('outputsBadge')?.textContent.trim() === '1'",
        timeout=5_000,
    )
    saved_title = state.outputs[OUTPUT_ID]["title"]
    list_text = (await page.locator("#outputsList .output-item").inner_text()).strip()
    if list_text != saved_title:
        raise AssertionError(f"Saved Outputs list must render title only: {list_text!r} != {saved_title!r}")

    await page.locator("#outputsList .output-item").click()
    await page.locator("#savedOutputDialog").wait_for(state="visible")
    await page.wait_for_function(
        "expected => document.getElementById('savedOutputContent')?.textContent.trim() === expected",
        arg=ANSWER,
        timeout=5_000,
    )
    if await page.locator("#savedOutputTitleInput").input_value() != saved_title:
        raise AssertionError("saved output title did not reopen correctly")

    await page.locator("#savedOutputCopy").click()
    await page.wait_for_function(
        "expected => window.__qaClipboardWrites?.length >= 2 && window.__qaClipboardWrites.at(-1) === expected",
        arg=ANSWER,
    )
    dialog_download = await _download(page, "#savedOutputDownload")

    await page.locator("#savedOutputTitleInput").fill(RENAMED_TITLE)
    await page.locator("#savedOutputRename").click()
    await _wait_text(page, "#savedOutputStatus", "제목을 저장했습니다.")
    if state.output_patches != [{"title": RENAMED_TITLE}]:
        raise AssertionError(f"unexpected rename requests: {state.output_patches!r}")
    await _wait_text(page, "#outputsList", RENAMED_TITLE)

    delete_button = page.locator("#savedOutputDelete")
    if mobile:
        box = await delete_button.bounding_box()
        if not box or box["height"] < 44:
            raise AssertionError(f"mobile saved-output delete target below 44px: {box}")
    await open_product_confirm(page, delete_button, title_contains="저장한 답변을 삭제할까요?", message_contains="원래 대화는 삭제되지 않습니다")
    await cancel_product_confirm(page, expected_focus_id="savedOutputDelete")
    if state.output_deletes != 0 or OUTPUT_ID not in state.outputs:
        raise AssertionError("cancel deleted Saved Output")
    if not await page.locator("#savedOutputDialog").is_visible():
        raise AssertionError("cancel unexpectedly closed Saved Output detail dialog")

    await open_product_confirm(page, delete_button, title_contains="저장한 답변을 삭제할까요?", message_contains="저장한 답변만 삭제합니다")
    await accept_product_confirm(page)
    await page.wait_for_function("() => document.getElementById('savedOutputDialog')?.open === false", timeout=5_000)
    await page.wait_for_function(
        "() => document.querySelectorAll('#outputsList .output-item').length === 0 && document.getElementById('outputsBadge')?.textContent.trim() === '비어 있음'",
        timeout=5_000,
    )
    if state.output_deletes != 1:
        raise AssertionError(f"expected one delete, saw {state.output_deletes}")
    if ANSWER not in await page.locator("#messageList").inner_text():
        raise AssertionError("deleting saved output removed source chat answer")
    await _no_overflow(page, f"{label}-deleted")
    await page.screenshot(path=str(OUT_DIR / f"{label}-outputs-deleted.png"), full_page=True)

    if native_dialogs:
        raise AssertionError(f"native browser dialog used by destructive flow: {native_dialogs!r}")
    if unexpected_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_hosts)}")

    clipboard = await page.evaluate("window.__qaClipboardWrites || []")
    return {
        "stream_requests": len(state.stream_posts),
        "save_posts": len(state.output_posts),
        "rename_patches": len(state.output_patches),
        "delete_requests": state.output_deletes,
        "clipboard_writes": len(clipboard),
        "answer_download": answer_download,
        "dialog_download": dialog_download,
        "native_dialogs": native_dialogs,
        "stubbed_static_hosts": sorted(stubbed_hosts),
        "unexpected_external_hosts": sorted(unexpected_hosts),
        "viewport": {"width": width, "height": height},
    }


async def main() -> None:
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "views": {},
        "window_confirm_destructive_flows": 0,
        "saved_output_delete_scope": "saved-output-only",
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for label, width, height, mobile in (
                ("desktop", 1280, 800, False),
                ("mobile", 390, 844, True),
            ):
                page = await browser.new_page(accept_downloads=True)
                try:
                    report["views"][label] = await _run(page, label=label, width=width, height=height, mobile=mobile)
                finally:
                    await page.close()
        finally:
            await browser.close()

    (OUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
