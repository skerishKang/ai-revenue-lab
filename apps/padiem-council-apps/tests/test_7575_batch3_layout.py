# -*- coding: utf-8 -*-
"""#7575 batch 3 — measured result-box growth after programmatic text.

The long answer is delivered through a stubbed stream exactly as the real chat
endpoint does; the assertion reads the rendered textarea, not source strings.
"""
from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
LONG_ANSWER = "\n".join("제%d항목 — 주민과 함께하는 따뜻한 행사 이야기입니다." % i for i in range(1, 41))


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def translate_path(self, path):
        if path.startswith("/static/"):
            path = path[len("/static"):]
        elif path == "/" or path == "/index.html" or not path.startswith("/api"):
            path = "/index.html"
        return super().translate_path(path)

    def guess_type(self, path):
        value = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else value

    def log_message(self, *_args):
        pass


@pytest.fixture(scope="module")
def url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:%d/index.html" % server.server_port
    server.shutdown()


def _open(page, url):
    files = {}

    def route(r):
        u = r.request.url
        m = r.request.method
        if u.endswith("/api/auth/status"):
            return r.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"authenticated": True, "methods": {"password": True},
                                              "member_grade": "free"}))
        if "/api/chat/stream" in u:
            body = "event: delta\ndata: " + json.dumps({"delta": LONG_ANSWER}) + "\n\n"
            body += "event: done\ndata: " + json.dumps({"done": True}) + "\n\n"
            return r.fulfill(status=200, content_type="text/event-stream", body=body)
        if u.endswith("/api/projects"):
            if m == "GET":
                return r.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"projects": [{"id": "p1", "name": "QA"}]}))
            return r.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"project": {"id": "p1", "name": "QA"}}))
        if "/api/projects/p1/files/" in u:
            fid = u.rsplit("/", 1)[-1]
            entry = files.get(fid, {})
            return r.fulfill(status=200, content_type="application/json",
                             body=json.dumps({"file": {"id": fid, "content": entry.get("content", "")}}))
        if "/api/projects/p1/files" in u:
            if m == "GET":
                return r.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"files": list(files.values())}))
            body = json.loads(r.request.post_data or "{}")
            fid = "f%d" % (len(files) + 1)
            files[fid] = {"id": fid, "name": body.get("name", "x.txt"),
                          "content": body.get("text", ""),
                          "content_chars": len(body.get("text", "")),
                          "doc_kind": body.get("doc_kind", "")}
            return r.fulfill(status=200, content_type="application/json", body=json.dumps({"file": files[fid]}))
        return r.continue_()

    page.route("**/*", route)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("#councilHeroTitle, .council-card-select")
    page.wait_for_timeout(250)
    if page.locator("#councilBack").count() and page.locator("#councilBack").is_visible():
        page.click("#councilBack")
        page.wait_for_timeout(200)


def _generated(page, tool, fill):
    page.locator('.council-card[data-tool="%s"] .council-card-select' % tool).click()
    page.wait_for_timeout(250)
    fill(page)
    page.click("#council%sGenerate" % ("Speech" if tool == "speech" else "Sns" if tool == "sns" else "Meeting"))
    page.wait_for_timeout(1800)


def _measure(page, output_id):
    return page.evaluate("""(id) => {
      const t = document.getElementById(id);
      return {h: Math.round(t.getBoundingClientRect().height),
              scroll: t.scrollHeight, client: t.clientHeight, len: t.value.length,
              hidden: t.hidden || t.offsetParent === null};
    }""", output_id)


def _assert_grown(m):
    assert not m["hidden"], m
    assert m["len"] > 500, m
    assert m["scroll"] <= m["client"] + 2, m
    assert m["h"] >= m["scroll"], m


def test_long_generated_results_fit_their_box(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _open(page, url)
            _generated(page, "speech", lambda p: p.fill("#councilSpeechForm [name=event]", "김장 나눔 행사"))
            speech = _measure(page, "councilSpeechOutput")
            page.click("#councilBack"); page.wait_for_timeout(200)

            _generated(page, "sns", lambda p: (p.fill("#councilSnsForm [name=event]", "김장 나눔 행사"),
                                               p.fill("#councilSnsForm [name=content]", "주민과 함께하는 김장 나눔")))
            page.click("#councilSnsEdit"); page.wait_for_timeout(200)
            sns = _measure(page, "councilSnsOutput")
            page.click("#councilBack"); page.wait_for_timeout(200)

            _generated(page, "meeting", lambda p: (
                p.fill("#councilMeetingForm [name=title]", "월례 회의"),
                p.fill("#councilMeetingForm [name=content]", "안건 논의"),
                p.evaluate("()=>{const e=document.querySelector('#councilMeetingForm [name=when]');if(e)e.value='2026-12-05T10:00';}")))
            meeting = _measure(page, "councilMeetingOutput")

            for m in (speech, sns, meeting):
                _assert_grown(m)
        finally:
            page.close()
        browser.close()


def test_book_generated_result_fits_its_box(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _open(page, url)
            # Save one long meeting so the activity-book has a record to choose.
            _generated(page, "meeting", lambda p: (
                p.fill("#councilMeetingForm [name=title]", "월례 회의"),
                p.fill("#councilMeetingForm [name=content]", "안건 논의"),
                p.evaluate("()=>{const e=document.querySelector('#councilMeetingForm [name=when]');if(e)e.value='2026-12-05T10:00';}")))
            page.click("#councilMeetingSave"); page.wait_for_timeout(700)
            checks = page.locator("#councilMeetingArchive .council-book-check")
            assert checks.count() >= 1, "no saved meeting to select"
            checks.first.check()
            page.click("#councilBookGenerate"); page.wait_for_timeout(1800)
            book = _measure(page, "councilBookOutput")
            _assert_grown(book)
        finally:
            page.close()
        browser.close()


def test_opening_a_saved_draft_resizes_the_result_box(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _open(page, url)
            _generated(page, "speech", lambda p: p.fill("#councilSpeechForm [name=event]", "김장 나눔 행사"))
            page.click("#councilSpeechSave"); page.wait_for_timeout(700)
            # A fresh page has no in-memory draft; opening the saved file must grow.
            page.reload(wait_until="domcontentloaded"); page.wait_for_timeout(600)
            if page.locator("#councilBack").is_visible():
                page.click("#councilBack"); page.wait_for_timeout(200)
            page.locator('.council-card[data-tool="speech"] .council-card-select').click()
            page.wait_for_timeout(250)
            page.locator(".council-saved-open").first.click()
            page.wait_for_timeout(400)
            _assert_grown(_measure(page, "councilSpeechOutput"))
        finally:
            page.close()
        browser.close()


def test_saved_list_count_matches_the_visible_draft(url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        try:
            _open(page, url)
            _generated(page, "speech", lambda p: p.fill("#councilSpeechForm [name=event]", "김장 나눔 행사"))
            padded = "  \n" + page.evaluate("()=>document.getElementById('councilSpeechOutput').value") + "\n  "
            page.evaluate("(v)=>{const t=document.getElementById('councilSpeechOutput');t.value=v;t.dispatchEvent(new Event('input',{bubbles:true}));}", padded)
            page.click("#councilSpeechSave"); page.wait_for_timeout(700)
            label = page.locator(".council-saved-open").first.inner_text()
            assert "(%d자)" % len(padded) in label, (label, len(padded))
        finally:
            page.close()
        browser.close()
