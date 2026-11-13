"""#7026: a single failed chapter JSON request must not pin the 본문 불가 note.

Observed on 390x844: the first entry into 고린도전서 4장 showed
"고린도전서 4장의 본문을 현재 이용할 수 없습니다" with zero `.verse` elements, and the
same path worked on the next attempt. The chapter body is fetched once per
context change, under the placeholder that `setReaderContext` renders; that one
fetch failing was enough to keep the placeholder for the whole visit.

This test boots the product's own static server, serves the real controls, fails
the first `book-1CO-chapter-004.json` request only, and then requires that the
chapter is fetched again and rendered after a 3장 -> 4장 move through the
reader's own chapter grid (#7573: the chip no longer leaves the reader).
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

pytestmark = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed"
)

PUBLIC = Path(__file__).resolve().parents[1] / "public"
CHAPTER_4 = "**/book-1CO-chapter-004.json"


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
    server.server_close()


def _executable() -> str | None:
    configured = os.getenv("B61_CHROME_PATH")
    if configured:
        return configured
    if os.name == "nt":
        for candidate in (
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Microsoft/Edge/Application/msedge.exe",
        ):
            if candidate.exists():
                return str(candidate)
    return None


def _open_chapter_3(page, base_url: str) -> None:
    page.goto(base_url, wait_until="load")
    page.wait_for_function("() => typeof setReaderContext === 'function'")
    page.wait_for_function(
        "() => document.querySelector('.screen.active')?.id === 'library'"
    )
    page.locator("#openBook").click()
    page.wait_for_function(
        "() => document.querySelector('.screen.active')?.id === 'index'"
    )
    page.locator("#openChapter").click()
    page.wait_for_function(
        "() => document.querySelector('.screen.active')?.id === 'reader'"
    )
    page.wait_for_function(
        "() => storyMemoryReaderBindingStatus().mode === 'static'"
        " && __smDynamicReaderState.passages.length > 0"
    )
    page.wait_for_function(
        "() => document.getElementById('readerChapterTitle').textContent === '3장'"
    )


def test_chapter_4_body_renders_after_one_transient_json_failure(base_url):
    with sync_playwright() as instance:
        executable = _executable()
        browser = (
            instance.chromium.launch(headless=True, executable_path=executable)
            if executable
            else instance.chromium.launch(headless=True)
        )
        try:
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.set_default_timeout(30000)
            attempts = {"chapter4": 0}

            def fail_first_chapter_4(route):
                attempts["chapter4"] += 1
                if attempts["chapter4"] == 1:
                    route.fulfill(
                        status=503,
                        headers={"content-type": "application/json"},
                        body='{"error":"transient"}',
                    )
                else:
                    route.continue_()

            page.route(CHAPTER_4, fail_first_chapter_4)
            _open_chapter_3(page, base_url)

            # 3장 독자 -> 장 칩 -> 장 격자(#7573) -> 4장 읽기: the path from the report.
            page.locator("#v2ChapterChip").click()
            page.wait_for_selector("#sm7573ChapterGrid", state="visible")
            page.wait_for_function(
                "() => document.querySelector('.screen.active')?.id === 'reader'"
            )
            page.locator(".sm7573-grid-cell").nth(3).click()
            page.wait_for_function(
                "() => document.getElementById('readerChapterTitle').textContent"
                " === '4장'"
            )
            page.wait_for_function(
                "() => document.querySelector('.screen.active')?.id === 'reader'"
            )
            page.wait_for_function(
                "() => document.getElementById('readerChapterTitle').textContent"
                " === '4장'"
            )
            page.wait_for_function(
                "() => __smDynamicReaderState.mode === 'static'"
                " && __smDynamicReaderState.passages.length > 0"
            )

            text = page.locator("#readerPageBody").inner_text()
            verses = page.evaluate(
                "() => document.querySelectorAll('#readerPageBody .verse').length"
            )
            assert "이용할 수 없습니다" not in text
            assert verses > 0, text[:400]
            # The first request was made to fail; the chapter only renders if the
            # load was attempted again.
            assert attempts["chapter4"] >= 2, attempts
        finally:
            browser.close()
