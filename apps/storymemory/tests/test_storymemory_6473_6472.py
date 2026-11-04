"""Focused browser regressions for B61 issues #6473 and #6472."""

from __future__ import annotations

import http.server
import os
import re
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(sync_playwright is None, reason="playwright is not installed")
PUBLIC = Path(__file__).resolve().parents[1] / "public"
DEV_COPY = re.compile(r"visual\s+prototype|\bprototype\b|\bdemo\b|프로토타입|개발용|실제 제품|source span", re.I)


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def guess_type(self, path):
        content_type = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else content_type

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def base_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/index.html"
    server.shutdown()
    thread.join(timeout=5)


def _launch(browser_type):
    executable = os.getenv("B61_CHROME_PATH")
    if not executable and os.name == "nt":
        for candidate in (
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Microsoft/Edge/Application/msedge.exe",
        ):
            if candidate.exists():
                executable = str(candidate)
                break
    return browser_type.launch(headless=True, executable_path=executable)


def _capture(page, name):
    target = os.getenv("B61_SCREENSHOT_DIR")
    if not target:
        return
    directory = Path(target)
    directory.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(directory / name), full_page=True)


def _open_reader(page, base_url):
    page.goto(base_url, wait_until="load")
    page.wait_for_function("() => typeof setReaderContext === 'function'")
    page.wait_for_function("() => document.querySelector('.screen.active')?.id === 'library'")
    _capture(page, "01-first-screen.png")
    page.locator("#openBook").click()
    page.wait_for_function("() => document.querySelector('.screen.active')?.id === 'index'")
    _capture(page, "02-book-selection.png")
    page.locator("#openChapter").click()
    page.wait_for_function("() => document.querySelector('.screen.active')?.id === 'reader'")


def _assert_no_dev_copy(page):
    assert not DEV_COPY.search(page.title())
    assert not DEV_COPY.search(page.locator("body").inner_text())


def test_visible_product_copy_has_no_prototype_labels(base_url):
    with sync_playwright() as pw:
        browser = _launch(pw.chromium)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(10000)
        try:
            _open_reader(page, base_url)
            page.wait_for_function("() => storyMemoryReaderBindingStatus().mode === 'static'")
            _assert_no_dev_copy(page)
            assert page.locator("#readerSourceBadge").inner_text() in {"한글", "한글 · 영어", "영어", "본문"}
            legacy_answer = page.evaluate("buildSupportedTextAnswer('이 부분을 설명해 주세요').body")
            assert not DEV_COPY.search(legacy_answer)
            _capture(page, "03-reader-copy.png")

            page.evaluate("document.getElementById('memoryRailTab').click()")
            page.wait_for_timeout(150)
            _assert_no_dev_copy(page)
            assert "아직 저장한 메모가 없습니다." in page.locator("#userMemoryList").inner_text()

            page.evaluate("document.getElementById('aiRailTab').click()")
            page.wait_for_timeout(150)
            _assert_no_dev_copy(page)
            assert page.locator("#askInput").get_attribute("placeholder") == "현재 본문에 대해 물어보세요"

            page.evaluate(
                """() => {
                  __smCurrentReaderKind='bible';
                  __smCurrentReaderLabel='고린도전서 3장';
                  __smDynamicReaderState={...__smDynamicReaderState,mode:'fallback'};
                  updateReaderSourceBadge();
                }"""
            )
            badge = page.locator("#readerSourceBadge")
            assert badge.inner_text() == "화면 예시 · 본문 아님"
            assert "실제 성경 본문이 아닙니다" in badge.get_attribute("title")
            page.evaluate("__smV319RefreshMemoryRail()")
            assert page.locator("#currentChapterMemoryList .system-memory").count() == 0
            assert page.locator("#currentChapterMemoryList .memory-current-empty").inner_text() == (
                "본문을 이용할 수 없어 관련 기억을 확인할 수 없습니다."
            )
            page.evaluate("__smCurrentReaderLabel='사도행전 9장';updateReaderSourceBadge()")
            assert badge.inner_text() == "본문 이용 불가"

            page.evaluate("openAuthGate()")
            page.wait_for_function("() => document.body.classList.contains('auth-gate-open')")
            assert "현재 이용할 수 없습니다" in page.locator("#authGateCopy").inner_text()
            assert page.locator("#authGatePrimary").is_hidden()
            _assert_no_dev_copy(page)
        finally:
            browser.close()


def test_memory_rail_tracks_current_chapter_and_shows_empty_state(base_url):
    with sync_playwright() as pw:
        browser = _launch(pw.chromium)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.set_default_timeout(10000)
        try:
            _open_reader(page, base_url)
            page.evaluate(
                """() => {
                  localStorage.clear();
                  localStorage.setItem('storymemory.pinnedEntities.v1', JSON.stringify(['아브라함','요셉']));
                  setReaderContext({kind:'bible',volume:'사도행전',chapter:9,chapterCount:28});
                }"""
            )
            page.wait_for_function("() => storyMemoryReaderBindingStatus().mode === 'static'")
            page.wait_for_function("() => document.querySelectorAll('#currentChapterMemoryList .system-memory').length > 0")
            page.evaluate("__smV319RefreshMemoryRail()")

            current = page.locator("#currentChapterMemoryList .system-memory b").all_inner_texts()
            other = page.locator("#otherChapterMemoryList .system-memory b").all_inner_texts()
            assert "사울" in current and "다메섹" in current
            assert "아브라함" not in current and "요셉" not in current
            assert {"아브라함", "요셉"}.issubset(set(other))
            assert page.locator("#otherChapterMemoryHeading").is_visible()
            assert "다비다" not in current  # later in the chapter and outside the read range
            assert page.evaluate(
                """(names) => {
                  const box=document.createElement('div');
                  box.innerHTML=READER_PAGES.slice(0,readerPageIndex+1).join(' ');
                  const text=box.textContent||'';
                  return names.every(name=>text.includes(name));
                }""",
                current,
            )
            _capture(page, "04-memory-acts-9.png")

            page.evaluate("readerPageIndex=READER_PAGES.length-1;renderReaderPage(0)")
            page.wait_for_function(
                "() => [...document.querySelectorAll('#currentChapterMemoryList .system-memory b')].some(x=>x.textContent==='다비다')"
            )

            page.evaluate(
                "setReaderContext({kind:'bible',volume:'사도행전',chapter:10,chapterCount:28})"
            )
            page.wait_for_function(
                "() => storyMemoryReaderBindingStatus().mode === 'static' && __smCurrentReaderLabel === '사도행전 10장'"
            )
            page.evaluate("__smV319RefreshMemoryRail()")
            chapter_ten = page.locator("#currentChapterMemoryList .system-memory b").all_inner_texts()
            assert "사울" not in chapter_ten and "아나니아" not in chapter_ten
            assert {"아브라함", "요셉"}.issubset(
                set(page.locator("#otherChapterMemoryList .system-memory b").all_inner_texts())
            )

            page.evaluate("setReaderContext({kind:'bible',volume:'시편',chapter:1,chapterCount:150})")
            page.wait_for_function(
                "() => storyMemoryReaderBindingStatus().mode === 'static' && __smCurrentReaderLabel === '시편 1장'"
            )
            page.evaluate("__smV319RefreshMemoryRail()")
            assert page.locator("#currentChapterMemoryList .system-memory").count() == 0
            assert page.locator("#currentChapterMemoryList .memory-current-empty").inner_text() == (
                "현재 읽은 본문에서 연결된 인물·장소·개념이 없습니다."
            )
            _capture(page, "05-memory-empty.png")

            page.evaluate("setReaderContext({kind:'book',book:'미연결 자료'})")
            page.wait_for_timeout(100)
            page.evaluate("__smV319RefreshMemoryRail()")
            assert page.locator("#currentChapterMemoryList .system-memory").count() == 0
            assert page.locator("#currentChapterMemoryList .memory-current-empty").inner_text() == (
                "본문을 이용할 수 없어 관련 기억을 확인할 수 없습니다."
            )
            assert {"아브라함", "요셉"}.issubset(
                set(page.locator("#otherChapterMemoryList .system-memory b").all_inner_texts())
            )
            _capture(page, "06-memory-unavailable.png")
        finally:
            browser.close()
