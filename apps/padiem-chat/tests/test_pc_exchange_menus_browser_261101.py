"""Real browser coverage for the existing shared PC picker on the speech utility.

All API calls are intercepted, including PC operations; no real PC is accessed.
"""
from __future__ import annotations

import http.server
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
STATIC = Path(__file__).resolve().parents[1] / "static"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass


@pytest.fixture(scope="module")
def site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/index.html"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        yield browser
        browser.close()


def open_speech(browser, site, *, linked):
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    calls, results = [], {}
    counter = 0

    def route_api(route):
        nonlocal counter
        request = route.request
        parsed = urlsplit(request.url)
        if parsed.netloc != urlsplit(site).netloc:
            route.abort()
            return
        path = parsed.path
        if not path.startswith("/api/"):
            route.continue_()
            return
        body = request.post_data_json if request.method == "POST" else None
        calls.append((path, body))
        if path == "/api/auth/status":
            response = {"ready": True, "authenticated": True, "session_state": "signed_in",
                        "user": {"name": "Synthetic"}, "history_ready": True}
        elif path == "/api/pc/pairings":
            response = {"links": [{"state": "active"}] if linked else []}
        elif path == "/api/projects":
            response = {"projects": []}
        elif path == "/api/chat":
            response = {"answer": "완성된 축사입니다."}
        elif path in {"/api/pc/browse", "/api/pc/find", "/api/pc/fetch", "/api/pc/save"}:
            counter += 1
            dispatch = "dsp_" + str(counter).zfill(32)
            if path == "/api/pc/browse":
                result = {"ok": True, "state": "ready", "items": [
                    {"name": "예전글.txt", "kind": "file", "size_bytes": 48}
                ]}
            elif path == "/api/pc/find":
                result = {"ok": True, "state": "ready", "folders": [], "found": [
                    {"name": "예전글.txt", "kind": "file", "size_bytes": 48,
                     "path": "예전글.txt"}
                ]}
            elif path == "/api/pc/fetch":
                result = {"ok": True, "state": "ready", "content_kind": "text",
                          "content": "지난 행사에서 쓴 축사입니다.", "size_bytes": 48}
            else:
                result = {"ok": True, "state": "ready", "saved": {
                    "ok": True, "op": "write", "backup": "synthetic-backup", "bytes": 48,
                }}
            results[dispatch] = result
            response = {"ok": True, "state": "working", "dispatch_id": dispatch,
                        "poll_seconds": 0.01}
        elif path == "/api/pc/result":
            dispatch = parse_qs(urlsplit(request.url).query)["dispatch_id"][0]
            response = results[dispatch]
        else:
            response = {"ok": True}
        route.fulfill(status=200, json=response)

    page.route("**/*", route_api)
    page.goto(site, wait_until="domcontentloaded")
    page.wait_for_function("() => window.PadiemAuthGate?.authenticated() === true")
    page.locator("#utilNavButton").click()
    page.locator('#utilSubmenu [data-util="speech"]').click()
    page.locator("#utilSpeechPcRef").wait_for(state="visible")
    return page, calls


def test_speech_import_search_and_save_use_shared_pc_exchange(browser, site):
    page, calls = open_speech(browser, site, linked=True)
    try:
        page.locator("#utilSpeechPcRef .util-pc-ref-pick").click()
        page.locator(".pc-exchange-entry").first.wait_for(state="visible")
        page.locator(".pc-exchange-search").fill("예전글")
        page.locator(".pc-exchange-search-button").click()
        page.locator('.pc-exchange-entry[data-name="예전글.txt"]').click()
        page.locator(".pc-exchange-pick").click()
        page.locator("#utilSpeechPcRef .util-pc-ref-preview").wait_for(state="visible")
        assert "지난 행사에서 쓴 축사입니다." in page.locator("#utilSpeechPcRef").inner_text()
        page.locator('#utilSpeechForm [name="event"]').fill("창립 기념")
        page.locator("#utilSpeechForm .util-generate").click()
        page.wait_for_function("() => document.querySelector('#utilSpeechOutput').value === '완성된 축사입니다.'")
        request = next(body for path, body in calls if path == "/api/chat")
        assert "지난 행사에서 쓴 축사입니다." in request["messages"][0]["content"]
        page.locator("#utilSpeechPcSave").click()
        page.locator(".pc-exchange-filename").wait_for(state="visible")
        page.locator(".pc-exchange-filename").fill("결과.txt")
        page.locator(".pc-exchange-save").click()
        page.locator(".pc-exchange-dialog").wait_for(state="detached")
        saved = [body for path, body in calls if path == "/api/pc/save"]
        assert len(saved) == 1 and saved[0]["content"] == "완성된 축사입니다."
        assert saved[0]["path"].endswith("결과.txt")
        for path in ("/api/pc/browse", "/api/pc/find", "/api/pc/fetch", "/api/pc/save"):
            assert any(name == path for name, _ in calls), path
    finally:
        page.close()


def test_speech_without_pc_shows_connect_guidance(browser, site):
    page, calls = open_speech(browser, site, linked=False)
    try:
        notice = page.locator("#utilSpeechPcRef .util-pc-ref-note")
        notice.wait_for(state="visible")
        assert "PC를 연결하면 예전 글을 가져올 수 있습니다." in notice.inner_text()
        assert notice.locator(".util-pc-ref-connect").is_visible()
        assert page.locator("#utilSpeechPcRef .util-pc-ref-pick").is_hidden()
        assert not any(path.startswith("/api/pc/browse") for path, _ in calls)
    finally:
        page.close()


def open_sns(browser, site, *, linked):
    page, calls = open_speech(browser, site, linked=linked)
    page.locator('#utilSubmenu [data-util="sns"]').click()
    page.locator("#utilSnsRef").wait_for(state="visible")
    return page, calls


def test_sns_import_and_save_with_fake_pc(browser, site):
    page, calls = open_sns(browser, site, linked=True)
    try:
        page.locator("#utilSnsRef .util-pc-ref-pick").click()
        page.locator('.pc-exchange-entry[data-name="예전글.txt"]').click()
        page.locator(".pc-exchange-pick").click()
        page.locator("#utilSnsRef .util-pc-ref-preview").wait_for(state="visible")
        page.locator('#utilSnsForm [name="event"]').fill("창립 기념")
        page.locator('#utilSnsForm [name="content"]').fill("행사 내용")
        page.locator("#utilSnsForm").evaluate("(form) => form.requestSubmit()")
        page.wait_for_function("() => document.querySelector('#utilSnsOutput').value === '완성된 축사입니다.'")
        request = next(body for path, body in calls if path == "/api/chat")
        assert "지난 행사에서 쓴 축사입니다." in request["messages"][0]["content"]
        page.locator("#utilSnsPcSave").click()
        page.locator(".pc-exchange-filename").fill("sns.txt")
        page.locator(".pc-exchange-save").click()
        page.locator(".pc-exchange-dialog").wait_for(state="detached")
        saved = [body for path, body in calls if path == "/api/pc/save"]
        assert len(saved) == 1 and saved[0]["content"] == "완성된 축사입니다."
        assert saved[0]["path"].endswith("sns.txt")
    finally:
        page.close()


def test_sns_without_pc_shows_connect_guidance(browser, site):
    page, calls = open_sns(browser, site, linked=False)
    try:
        notice = page.locator("#utilSnsRef .util-pc-ref-note")
        notice.wait_for(state="visible")
        assert "PC를 연결하면 예전 글을 가져올 수 있습니다." in notice.inner_text()
        assert notice.locator(".util-pc-ref-connect").is_visible()
        assert page.locator("#utilSnsRef .util-pc-ref-pick").is_hidden()
        assert not any(path == "/api/pc/browse" for path, _ in calls)
    finally:
        page.close()


def test_pdfmd_existing_result_save_and_paused_import(browser, site):
    page, calls = open_speech(browser, site, linked=True)
    def conversions(route):
        path = urlsplit(route.request.url).path
        if path.endswith("/markdown"):
            route.fulfill(status=200, content_type="text/plain", body="# 변환 결과")
        elif path.endswith("/job1"):
            route.fulfill(status=200, json={"items": [
                {"id": "item1", "name": "문서.pdf", "status": "done", "has_markdown": True}
            ]})
        else:
            route.fulfill(status=200, json={"jobs": [
                {"id": "job1", "created_at": "2026-10-01T00:00:00Z",
                 "status": "done", "mode": "fast", "item_count": 1}
            ]})
    page.route("**/api/document-conversions**", conversions)
    page.route("**/api/document-conversions/**", conversions)
    try:
        page.locator('#utilSubmenu [data-util="pdfmd"]').click()
        page.locator("#pdfmdPcPick").wait_for(state="visible")
        assert page.locator("#pdfmdPcPick").is_disabled()
        page.locator(".pdfmd-history-item").click()
        page.get_by_role("button", name="문서.pdf 내 PC에 저장").click()
        page.locator(".pc-exchange-filename").wait_for(state="visible")
        page.locator(".pc-exchange-save").click()
        page.locator(".pc-exchange-dialog").wait_for(state="detached")
        saved = [body for path, body in calls if path == "/api/pc/save"]
        assert len(saved) == 1 and saved[0]["content"] == "# 변환 결과"
        assert saved[0]["path"].endswith("문서.md")
    finally:
        page.close()


def test_pdfmd_without_pc_shows_connect_guidance(browser, site):
    page, calls = open_speech(browser, site, linked=False)
    try:
        page.locator('#utilSubmenu [data-util="pdfmd"]').click()
        page.locator("#pdfmdPcNote").wait_for(state="visible")
        assert "PC를 연결하면" in page.locator("#pdfmdPcNote").inner_text()
        assert page.locator("#pdfmdPcPick").is_disabled()
        assert not any(path == "/api/pc/browse" for path, _ in calls)
    finally:
        page.close()
