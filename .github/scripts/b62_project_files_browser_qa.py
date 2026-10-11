from __future__ import annotations

import asyncio
import base64
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


BASE_URL = os.environ.get("B62_PROJECT_FILES_QA_BASE_URL", "http://127.0.0.1:8772")
OUT_DIR = Path(os.environ.get("B62_PROJECT_FILES_QA_OUT_DIR", ".tmp/b62-project-files-browser-qa"))
OUT_DIR.mkdir(parents=True, exist_ok=True)

USER_NAME = "프로젝트 파일 브라우저 사용자"
PROJECT_ID = "proj_00000000000000000000000000000011"
PROJECT_NAME = "제주 자료실"
PROJECT_INSTRUCTIONS = "부모님도 읽기 쉽게 핵심부터 설명해줘."
FILE_ID = "file_00000000000000000000000000000022"
FILE_NAME = "guide.md"
FILE_TYPE = "text/markdown"
FILE_TEXT = "# 제주 준비\nPROJECT_FILE_PRIVATE_MARKER_1032\n신분증과 충전기를 챙긴다."
# #2342 additive PDF/DOCX fixtures: real base64 payloads, server-side extracted text markers.
PDF_NAME = "positive.pdf"
PDF_MEDIA_TYPE = "application/pdf"
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
PDF_BASE64 = base64.b64encode(PDF_BYTES).decode("ascii")
PDF_EXTRACTED_TEXT = "Positive PDF Text\nPROJECT_FILE_BINARY_PRIVATE_MARKER_2342"
DOCX_NAME = "report.docx"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX_BYTES = b"PK\x03\x04deterministic-docx-zip-stub-bytes-for-browser-qa"
DOCX_BASE64 = base64.b64encode(DOCX_BYTES).decode("ascii")
DOCX_EXTRACTED_TEXT = "Positive DOCX Text\nPROJECT_FILE_BINARY_PRIVATE_MARKER_2342"
BINARY_ID_PREFIX = "file_binary_"
SERVER_REJECT_MARKER = "PROJECT_FILE_SERVER_REJECT_MARKER_2342"
QUESTION = "프로젝트 자료를 참고해서 준비물을 정리해줘"
ANSWER = "프로젝트 자료를 참고해 신분증과 충전기를 먼저 챙기세요."
STATIC_FONT_HOSTS = frozenset({"cdn.jsdelivr.net", "fonts.googleapis.com", "fonts.gstatic.com"})
FORBIDDEN_CHAT_KEYS = frozenset({"model", "provider", "route", "business14", "project_file_id", "project_file_ids", "project_files", "file_id", "file_ids"})


@dataclass
class FixtureState:
    files: dict[str, dict[str, Any]] = field(default_factory=dict)
    file_posts: list[dict[str, Any]] = field(default_factory=list)
    file_deletes: list[str] = field(default_factory=list)
    stream_posts: list[dict[str, Any]] = field(default_factory=list)
    binary_posts: list[dict[str, Any]] = field(default_factory=list)
    reject_next_uploads: int = 0

    @property
    def project(self) -> dict[str, Any]:
        return {
            "id": PROJECT_ID,
            "name": PROJECT_NAME,
            "instructions": PROJECT_INSTRUCTIONS,
            "created_at": "2026-08-28T05:10:00Z",
            "updated_at": "2026-08-28T05:10:00Z",
        }

    def public_files(self) -> list[dict[str, Any]]:
        return [
            {
                "id": item["id"],
                "project_id": item["project_id"],
                "name": item["name"],
                "media_type": item["media_type"],
                "content_chars": item["content_chars"],
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
            for item in self.files.values()
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
        await route.fulfill(status=200, content_type="text/css; charset=utf-8", body="/* deterministic Project Files QA font stub */\n")

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
            "project_files_ready": True,
            "user": {
                "id": "usr_project_files_browser_fixture",
                "email": "project-files@example.test",
                "name": USER_NAME,
                "picture": "",
            },
        })

    async def projects_root(route: Route) -> None:
        if route.request.method == "GET":
            await _reply_json(route, {"projects": [state.project]})
            return
        await _reply_json(route, {"error": {"code": "method_not_allowed"}}, status=405)

    async def project_files(route: Route) -> None:
        if route.request.method == "GET":
            await _reply_json(route, {"files": state.public_files()})
            return
        if route.request.method != "POST":
            await _reply_json(route, {"error": {"code": "method_not_allowed"}}, status=405)
            return
        body = _request_json(route)
        state.file_posts.append(body)
        keys = set(body)
        if state.reject_next_uploads > 0:
            state.reject_next_uploads -= 1
            await _reply_json(route, {"error": {"code": "invalid_project_file", "message": SERVER_REJECT_MARKER}}, status=422)
            return
        if keys == {"name", "media_type", "base64"}:
            # #2342 binary branch: server-legal project binaries are PDF/DOCX only and the
            # POST must carry exactly {name, media_type, base64}. Persisted rows project the
            # server-side extracted media type; original bytes never come back to the browser.
            extracted = {PDF_MEDIA_TYPE: ("extracted/pdf", PDF_EXTRACTED_TEXT, PDF_BASE64),
                         DOCX_MEDIA_TYPE: ("extracted/docx", DOCX_EXTRACTED_TEXT, DOCX_BASE64)}
            if body["media_type"] not in extracted:
                await _reply_json(route, {"error": {"code": "invalid_project_file", "message": "지원하지 않는 파일 형식입니다."}}, status=422)
                return
            if body["base64"] != extracted[body["media_type"]][2]:
                raise AssertionError(f"{body['media_type']} binary POST must carry the exact base64 of the picked file")
            stored_type, extracted_text, _ = extracted[body["media_type"]]
            state.binary_posts.append(dict(body))
            record = {
                "id": f"{BINARY_ID_PREFIX}{len(state.binary_posts):02d}",
                "project_id": PROJECT_ID,
                "name": body["name"],
                "media_type": stored_type,
                "content_text": extracted_text,
                "content_chars": len(extracted_text),
                "created_at": "2026-09-11T05:11:00Z",
                "updated_at": "2026-09-11T05:11:00Z",
            }
            state.files[record["id"]] = record
            public = dict(record)
            public.pop("content_text")
            await _reply_json(route, {"file": public}, status=201)
            return
        if keys != {"name", "media_type", "text"}:
            raise AssertionError(f"unexpected Project File POST payload keys: {sorted(keys)}")
        expected = {"name": FILE_NAME, "media_type": FILE_TYPE, "text": FILE_TEXT}
        if body != expected:
            raise AssertionError(f"Project File POST must be exact bounded document payload: {body!r}")
        record = {
            "id": FILE_ID,
            "project_id": PROJECT_ID,
            "name": FILE_NAME,
            "media_type": FILE_TYPE,
            "content_text": FILE_TEXT,
            "content_chars": len(FILE_TEXT),
            "created_at": "2026-08-28T05:11:00Z",
            "updated_at": "2026-08-28T05:11:00Z",
        }
        state.files[FILE_ID] = record
        public = dict(record)
        public.pop("content_text")
        await _reply_json(route, {"file": public}, status=201)

    async def project_file_detail(route: Route) -> None:
        file_id = route.request.url.rsplit("/", 1)[-1].split("?", 1)[0]
        if route.request.method != "DELETE":
            await _reply_json(route, {"error": {"code": "method_not_allowed"}}, status=405)
            return
        if file_id not in state.files:
            await _reply_json(route, {"error": {"code": "not_found"}}, status=404)
            return
        state.file_deletes.append(file_id)
        del state.files[file_id]
        await _reply_json(route, {"deleted": True})

    async def conversations(route: Route) -> None:
        await _reply_json(route, {"conversations": []})

    async def outputs(route: Route) -> None:
        await _reply_json(route, {"outputs": []})

    async def stream(route: Route) -> None:
        body = _request_json(route)
        state.stream_posts.append(body)
        if any(key in body for key in FORBIDDEN_CHAT_KEYS):
            raise AssertionError(f"project chat leaked lower-layer/file routing fields: {body!r}")
        if body.get("project_id") != PROJECT_ID:
            raise AssertionError(f"project chat missing server-owned project reference: {body!r}")
        if FILE_ID in _json(body) or FILE_TEXT in _json(body) or PDF_BASE64 in _json(body) or DOCX_BASE64 in _json(body):
            raise AssertionError(f"browser sent persisted Project File id/content/base64 in chat request: {body!r}")
        if body.get("messages", [])[-1:] != [{"role": "user", "content": QUESTION}]:
            raise AssertionError(f"unexpected project chat message payload: {body!r}")
        sse = (
            "event: delta\n"
            f"data: {_json({'delta': ANSWER})}\n\n"
            "event: done\n"
            f"data: {_json({'done': True, 'conversation_id': 'chat_project_files_browser_1', 'project_id': PROJECT_ID, 'project': {'id': PROJECT_ID, 'name': PROJECT_NAME}, 'project_files_used': 1})}\n\n"
        )
        await route.fulfill(
            status=200,
            content_type="text/event-stream; charset=utf-8",
            body=sse,
            headers={"Cache-Control": "no-store"},
        )

    await page.route("**/api/auth/status", auth)
    await page.route("**/api/projects", projects_root)
    await page.route("**/api/conversations", conversations)
    await page.route("**/api/outputs", outputs)
    await page.route("**/api/chat/stream", stream)
    await page.route("**/api/projects/*/files", project_files)
    await page.route("**/api/projects/*/files/*", project_file_detail)


async def _open_sidebar(page: Page, mobile: bool) -> None:
    if not mobile:
        return
    menu = page.locator("#mobileMenu")
    await menu.wait_for(state="visible")
    if await menu.get_attribute("aria-expanded") != "true":
        await menu.click()
    await page.wait_for_function("() => document.querySelector('.app-shell')?.classList.contains('sidebar-open')")


async def _wait_text(page: Page, selector: str, expected: str) -> None:
    await page.wait_for_function(
        "([selector, expected]) => document.querySelector(selector)?.textContent.includes(expected)",
        arg=[selector, expected],
        timeout=5_000,
    )


async def _no_overflow(page: Page, stage: str) -> None:
    widths = await page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth]")
    if widths[0] > widths[1] + 1:
        raise AssertionError(f"horizontal overflow at {stage}: {widths}")


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
    await _stub_fonts(page, stubbed_hosts)
    await _install_api(page, state)
    await page.set_viewport_size({"width": width, "height": height})
    await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)

    await page.wait_for_function(
        "expected => document.getElementById('loginButton')?.textContent.trim() === '로그아웃' && document.getElementById('accountName')?.textContent.trim() === expected && !document.getElementById('projectsNavButton')?.disabled",
        arg=USER_NAME,
        timeout=5_000,
    )
    await _open_sidebar(page, mobile)
    project_button = page.locator("#projectsList .project-item", has_text=PROJECT_NAME)
    await project_button.wait_for(state="visible")
    await project_button.click()
    await page.wait_for_function(
        "expected => !document.getElementById('projectBanner')?.hidden && document.getElementById('activeProjectName')?.textContent.trim() === expected",
        arg=PROJECT_NAME,
        timeout=5_000,
    )
    await _no_overflow(page, f"{label}-project-selected")

    # Add a persisted Project File and verify the bounded write payload.
    await page.locator("#editProjectButton").click()
    await page.locator("#projectDialog").wait_for(state="visible")
    if await page.locator("#projectFilesPanel").is_hidden():
        raise AssertionError("Project Files panel must be visible when project_files_ready=true")
    await _wait_text(page, "#projectFilesEmpty", "저장된 프로젝트 파일이 없습니다.")
    await page.locator("#projectFileInput").set_input_files({
        "name": FILE_NAME,
        "mimeType": FILE_TYPE,
        "buffer": FILE_TEXT.encode("utf-8"),
    })
    await page.wait_for_function(
        "expected => document.querySelector('#projectFilesList .project-file-row strong')?.textContent.trim() === expected",
        arg=FILE_NAME,
        timeout=5_000,
    )
    if state.file_posts != [{"name": FILE_NAME, "media_type": FILE_TYPE, "text": FILE_TEXT}]:
        raise AssertionError(f"unexpected Project File create calls: {state.file_posts!r}")
    await _wait_text(page, "#activeProjectFiles", "파일 1개")
    if "PROJECT_FILE_PRIVATE_MARKER_1032" in await page.locator("body").inner_text():
        raise AssertionError("Project File content leaked into visible UI")

    # Chat sends only Project authority reference; persisted file id/content remain server-owned.
    await page.locator("#projectDialogClose").click()
    await page.locator("#messageInput").fill(QUESTION)
    await page.locator("#sendButton").click()
    await _wait_text(page, "#messageList", ANSWER)
    await _wait_text(page, "#messageList .reference-note", "프로젝트 파일 1개를 참고했습니다.")
    if len(state.stream_posts) != 1:
        raise AssertionError(f"expected one project stream request, saw {len(state.stream_posts)}")
    if FILE_TEXT in await page.locator("body").inner_text():
        raise AssertionError("Project File private text leaked after chat completion")

    # Reopen, verify safe cancel path then intentionally confirm deletion.
    await page.locator("#editProjectButton").click()
    await page.locator("#projectDialog").wait_for(state="visible")
    await page.wait_for_function(
        "expected => document.querySelector('#projectFilesList .project-file-row strong')?.textContent.trim() === expected",
        arg=FILE_NAME,
        timeout=5_000,
    )
    delete_button = page.locator("#projectFilesList .project-file-row button", has_text="삭제")
    if mobile:
        box = await delete_button.bounding_box()
        if not box or box["width"] < 44 or box["height"] < 44:
            raise AssertionError(f"mobile Project File delete target below 44px: {box}")

    await open_product_confirm(page, delete_button, title_contains="프로젝트 파일을 삭제할까요?", message_contains=FILE_NAME)
    await cancel_product_confirm(page)
    if not await delete_button.evaluate("node => document.activeElement === node"):
        raise AssertionError("Project File cancel did not return focus to delete trigger")
    if state.file_deletes:
        raise AssertionError(f"cancel issued Project File DELETE: {state.file_deletes!r}")
    if await page.locator("#projectFilesList .project-file-row").count() != 1:
        raise AssertionError("cancel removed Project File row")

    await open_product_confirm(page, delete_button, title_contains="프로젝트 파일을 삭제할까요?", message_contains="복구할 수 없습니다")
    await accept_product_confirm(page)
    await page.wait_for_function(
        "() => document.querySelectorAll('#projectFilesList .project-file-row').length === 0 && !document.getElementById('projectFilesEmpty')?.hidden",
        timeout=5_000,
    )
    if state.file_deletes != [FILE_ID]:
        raise AssertionError(f"unexpected Project File DELETE calls: {state.file_deletes!r}")
    await page.wait_for_function("() => document.getElementById('activeProjectFiles')?.hidden === true", timeout=5_000)
    await _no_overflow(page, f"{label}-project-file-deleted")
    await page.screenshot(path=str(OUT_DIR / f"{label}-project-file-deleted.png"), full_page=True)

    # ── #2342 additive: PDF/DOCX binary consumption + server-error retry ──────
    # The manage dialog is already open with an empty file list after the delete above.
    await page.wait_for_function("() => document.querySelectorAll('#projectFilesList .project-file-row').length === 0", timeout=5_000)

    async def wait_for_binary_row(name: str, stored_type: str) -> None:
        await page.wait_for_function(
            "([name, storedType]) => Array.from(document.querySelectorAll('#projectFilesList .project-file-row')).some((row) => row.querySelector('strong')?.textContent.trim() === name && row.querySelector('small')?.textContent.includes(storedType)) && !document.getElementById('projectFilesPanel')?.hasAttribute('aria-busy')",
            arg=[name, stored_type],
            timeout=5_000,
        )

    await page.locator("#projectFileInput").set_input_files({
        "name": PDF_NAME,
        "mimeType": PDF_MEDIA_TYPE,
        "buffer": PDF_BYTES,
    })
    await wait_for_binary_row(PDF_NAME, "extracted/pdf")
    await page.locator("#projectFileInput").set_input_files({
        "name": DOCX_NAME,
        "mimeType": DOCX_MEDIA_TYPE,
        "buffer": DOCX_BYTES,
    })
    await wait_for_binary_row(DOCX_NAME, "extracted/docx")
    expected_binary_posts = [
        {"name": PDF_NAME, "media_type": PDF_MEDIA_TYPE, "base64": PDF_BASE64},
        {"name": DOCX_NAME, "media_type": DOCX_MEDIA_TYPE, "base64": DOCX_BASE64},
    ]
    if state.binary_posts != expected_binary_posts:
        raise AssertionError(f"unexpected binary Project File POSTs: {state.binary_posts!r}")
    if [post for post in state.file_posts if set(post) == {"name", "media_type", "base64"}] != expected_binary_posts:
        raise AssertionError(f"binary POSTs missing from recorded file_posts: {state.file_posts!r}")
    body_text = await page.locator("body").inner_text()
    if PDF_BASE64 in body_text or DOCX_BASE64 in body_text:
        raise AssertionError("base64 payload leaked into visible UI")
    if "PROJECT_FILE_BINARY_PRIVATE_MARKER_2342" in body_text:
        raise AssertionError("extracted binary content leaked into visible UI")

    # Server validation authority: a 422 message surfaces in role=alert, no row is added,
    # and re-picking the file after the server accepts it succeeds (accessible retry path).
    state.reject_next_uploads = 1
    await page.locator("#projectFileInput").set_input_files({
        "name": "retry.pdf",
        "mimeType": PDF_MEDIA_TYPE,
        "buffer": PDF_BYTES,
    })
    await _wait_text(page, "#projectFormError", SERVER_REJECT_MARKER)
    if await page.locator("#projectFilesList .project-file-row").count() != 2:
        raise AssertionError("rejected upload added a Project File row")
    if len(state.binary_posts) != 2:
        raise AssertionError(f"rejected upload was accepted by stub: {state.binary_posts!r}")
    await page.locator("#projectFileInput").set_input_files({
        "name": "retry.pdf",
        "mimeType": PDF_MEDIA_TYPE,
        "buffer": PDF_BYTES,
    })
    await wait_for_binary_row("retry.pdf", "extracted/pdf")
    await page.wait_for_function("() => document.getElementById('projectFormError')?.hidden === true", timeout=5_000)
    await _no_overflow(page, f"{label}-project-binary-uploaded")
    await page.screenshot(path=str(OUT_DIR / f"{label}-project-binary-uploaded.png"), full_page=True)

    if native_dialogs:
        raise AssertionError(f"native browser dialog used by destructive flow: {native_dialogs!r}")
    if unexpected_hosts:
        raise AssertionError(f"unexpected external browser hosts: {sorted(unexpected_hosts)}")

    return {
        "file_posts": len(state.file_posts),
        "binary_posts": len(state.binary_posts),
        "file_deletes": len(state.file_deletes),
        "stream_posts": len(state.stream_posts),
        "final_file_count": len(state.files),
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
        "project_file_authority": "server-owned",
    }
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            for label, width, height, mobile in (
                ("desktop", 1280, 800, False),
                ("mobile", 390, 844, True),
            ):
                page = await browser.new_page()
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
