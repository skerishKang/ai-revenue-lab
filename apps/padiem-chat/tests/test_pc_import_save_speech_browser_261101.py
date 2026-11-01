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
