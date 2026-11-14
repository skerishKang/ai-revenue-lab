"""#261114 북AI 화면 문구 한국어화 + 휴대폰 기억 시트 검증.

1. 원본 파일에서 영어·내부 용어가 사라졌는지 확인한다.
2. 390 기억 시트의 위 여백·글자 크기·탭 높이를 확인한다.
3. 1440 화면의 기준값이 바뀌지 않았는지 확인한다.
4. 글래스 테마에서도 같은 화면이 깨지지 않는지 확인한다.
"""

from __future__ import annotations

import http.server
import os
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")

PUBLIC = Path(__file__).resolve().parents[1] / "public"
CHROME = next(
    (
        candidate
        for candidate in (
            os.environ.get("B61_CHROME_PATH"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        )
        if candidate and Path(candidate).is_file()
    ),
    None,
)

FORBIDDEN = [
    "MEMORY TIMELINE",
    "MARGINALIA / INDEX",
    "CANONICAL MEMORY",
    "PERSONAL READING HOME",
    "LOCAL · SAVED",
    "Recall 시작",
    "← Library",
    "ORDER · 서가순",
    "AI Companion",
    "STORYMEMORY · READ / REMEMBER",
    "MEMORY EDITION",
    "READING COPY",
    "ANNOTATED COMPANION",
    "READING COMPANION",
    "LOCAL FIRST",
    "NEW TESTAMENT",
    "BOOK INDEX",
    "LIBRARY ARCHIVE",
    "READING DESK",
    "PERSONAL COPY",
    "THE FIRST LETTER TO THE CORINTHIANS",
    "DRAG THE PAGE EDGE",
    "CURATED SHELF",
    "ARCHIVE ROOM",
    "SELECT · OPEN · REMEMBER",
    "BOOK AI EDITION",
    "CLOTH · FOIL",
    "GOLD FOIL / MATTE CLOTH",
    "HOMER · EPIC",
    "DOSTOEVSKY · NOVEL",
    "SCRIPTURE · 66 BOOKS",
    "LEWIS CARROLL · WONDERLAND",
    "CONTINUE READING",
    "AI Memory",
    "Memory 메모",
    "AI MEMORY",
    "CH.0",
]

SOURCE_FILES = [
    PUBLIC / "index.html",
    PUBLIC / "storymemory-library-ui-v1.js",
    PUBLIC / "storymemory-memory-ui-v1.js",
    PUBLIC / "storymemory-reader-view-runtime-v1.js",
    PUBLIC / "storymemory-locator-progress-v1.js",
]


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def guess_type(self, path):
        value = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else value

    def log_message(self, *_args):
        pass


class StaticServer(http.server.ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


@pytest.fixture(scope="module")
def base_url():
    server = StaticServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        launched = (
            playwright.chromium.launch(headless=True, executable_path=CHROME)
            if CHROME
            else playwright.chromium.launch(headless=True)
        )
        yield launched
        launched.close()


def test_source_has_no_english_ui_terms():
    for path in SOURCE_FILES:
        text = path.read_text(encoding="utf-8")
        for term in FORBIDDEN:
            assert term not in text, f"{path.name}: 영어·내부 용어가 남아 있음: {term}"


def _open_memory(page, base_url, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.emulate_media(reduced_motion="reduce")
    page.goto(base_url, wait_until="load")
    page.wait_for_function("() => typeof window.setReaderContext === 'function'")
    page.wait_for_timeout(900)
    page.evaluate(
        "() => { setReaderContext({kind:'bible',book:'성경',volume:'고린도전서',chapter:3,chapterCount:16});"
        "transitionTo('reader'); }"
    )
    page.wait_for_timeout(1200)
    page.evaluate("() => document.getElementById('memoryRailTab').click()")
    page.wait_for_function("() => document.body.classList.contains('memory-open')")
    page.wait_for_timeout(500)


def _measure(page):
    return page.evaluate(
        """() => {
          const rail=document.querySelector('#reader .memory-rail');
          const rr=rail.getBoundingClientRect();
          const head=rail.querySelector('.side-head').getBoundingClientRect();
          const btn=rail.querySelector('.memory-scope-toggle button');
          const br=btn.getBoundingClientRect();
          const bs=getComputedStyle(btn);
          return {
            vw:innerWidth, vh:innerHeight,
            railTop:+rr.top.toFixed(1), railLeft:+rr.left.toFixed(1),
            railRight:+rr.right.toFixed(1), railBottom:+rr.bottom.toFixed(1),
            railWidth:+rr.width.toFixed(1),
            gap:+(head.top-rr.top).toFixed(1),
            font:parseFloat(bs.fontSize), buttonH:+br.height.toFixed(1),
            scrollW:document.documentElement.scrollWidth,
            overflow:document.documentElement.scrollWidth>innerWidth,
            inView:rr.top>=-1&&rr.left>=-1&&rr.right<=innerWidth+1&&rr.bottom<=innerHeight+1,
            folio:getComputedStyle(rail.querySelector('.rail-folio')).display,
          };
        }"""
    )


def test_phone_memory_sheet_metrics(browser, base_url):
    page = browser.new_page(viewport={"width": 390, "height": 844})
    try:
        _open_memory(page, base_url, 390, 844)
        m = _measure(page)
        assert m["gap"] <= 8, f"390 기억 시트 위 여백: {m}"
        assert m["font"] >= 14, f"390 현재 읽기/전체 기억 글자 크기: {m}"
        assert m["buttonH"] >= 44, f"390 기억 시트 탭 높이: {m}"
        assert m["folio"] == "none", f"390 기억 시트 빈 레일 머리: {m}"
        assert m["inView"] is True, f"390 기억 시트가 화면 밖: {m}"
        assert m["overflow"] is False, f"390 가로 넘침: {m}"
    finally:
        page.close()


def test_desktop_memory_sheet_unchanged(browser, base_url):
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        _open_memory(page, base_url, 1440, 900)
        m = _measure(page)
        assert m["font"] <= 12.5, f"1440 기억 시트 글자 크기 변경: {m}"
        assert m["gap"] >= 12, f"1440 기억 시트 위 여백 변경: {m}"
        assert m["buttonH"] <= 32, f"1440 기억 시트 탭 높이 변경: {m}"
        assert m["inView"] is True, f"1440 기억 시트가 화면 밖: {m}"
        assert m["overflow"] is False, f"1440 가로 넘침: {m}"
    finally:
        page.close()


@pytest.mark.parametrize("width,height", [(390, 844), (1440, 900)])
def test_glass_theme_keeps_memory_sheet(browser, base_url, width, height):
    page = browser.new_page(viewport={"width": width, "height": height})
    try:
        _open_memory(page, base_url, width, height)
        page.evaluate("() => document.body.classList.add('smr-theme-glass')")
        page.wait_for_timeout(250)
        m = _measure(page)
        assert m["inView"] is True, f"{width} 글래스 기억 시트가 화면 밖: {m}"
        assert m["overflow"] is False, f"{width} 글래스 가로 넘침: {m}"
        if width <= 720:
            assert m["gap"] <= 8, f"{width} 글래스 기억 시트 위 여백: {m}"
            assert m["font"] >= 14, f"{width} 글래스 기억 시트 글자 크기: {m}"
            assert m["buttonH"] >= 44, f"{width} 글래스 기억 시트 탭 높이: {m}"
        else:
            assert m["font"] <= 12.5, f"{width} 글래스 기억 시트 글자 크기 변경: {m}"
            assert m["buttonH"] <= 32, f"{width} 글래스 기억 시트 탭 높이 변경: {m}"
    finally:
        page.close()