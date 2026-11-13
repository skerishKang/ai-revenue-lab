"""#7573 읽기 화면 이동 레인(확인된 사실 4·5·6·7)의 브라우저 시험.

제품이 실제로 동작하는 모습을 자체 정적 서버와 로컬 Chromium로 확인한다:
- 4: 읽기 화면에서 입력창 포커스가 없을 때 ←/→ 로 페이지가 넘어가고, 입력창에
  포커스가 있으면 넘어가지 않는다. 마지막 페이지에서 → 는 다음 장.
- 5: 마지막 페이지 '다음' → 다음 장 첫 페이지, 책의 마지막 장 → 다음 책 1장,
  요한계시록 22장 끝 → 멈춤, 첫 페이지 '이전' → 이전 장 마지막 페이지,
  창세기 1장 처음 → 멈춤, 스크롤 보기 본문 끝 "다음 장 · <책> <장> →".
- 6: "<책> ▾" 칩 → 읽기 화면을 떠나지 않는 장 번호 격자(1~N, 버튼 44px 이상,
  현재 장 표시), "다른 책"은 기존 책 선택 화면, Esc·바깥 누르기로 닫힘,
  시편 150장 격자는 화면 안에서 스크롤.
- 7: 새로 열면 첫 화면은 항상 홈(서재), 홈의 이어 읽기 버튼으로 저장 위치 복원.

페이지 버튼이 다른 요소에 가려지는 문제는 별도 레인이 다룬다(이슈 2·3번). 이
시험은 버튼의 click() 호출과 키보드 입력으로 동작만 확인한다.
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


@pytest.fixture(scope="module")
def playwright_instance():
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="module")
def browser(playwright_instance):
    executable = os.getenv("B61_CHROME_PATH") or None
    browser = (
        playwright_instance.chromium.launch(headless=True, executable_path=executable)
        if executable
        else playwright_instance.chromium.launch(headless=True)
    )
    yield browser
    browser.close()


@pytest.fixture()
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(20000)
    yield page
    context.close()


def open_chapter(page, volume: str, chapter: int):
    """제품의 setReaderContext 경로로 해당 장을 열고 본문 묶음까지 기다린다."""
    page.wait_for_function("() => typeof setReaderContext === 'function'")
    page.evaluate(
        f"() => setReaderContext({{kind:'bible',book:'성경',volume:{volume!r},"
        f"chapter:{chapter},chapterCount:VOLUME_CHAPTERS[{volume!r}]}})"
    )
    page.evaluate("() => showScreen('reader')")
    wait_bound(page, f"{volume} {chapter}장")


def wait_bound(page, label: str, timeout: int = 20000):
    page.wait_for_function(f"() => __smCurrentReaderLabel === {label!r}", timeout=timeout)
    page.wait_for_function(
        "() => __smDynamicReaderState.passages.length > 0"
        " && storyMemoryReaderBindingStatus().mode !== 'fallback'",
        timeout=timeout,
    )


def force_page_mode(page):
    page.wait_for_function("() => typeof applyReaderViewMode === 'function'")
    page.evaluate("() => applyReaderViewMode('page')")
    page.wait_for_function("() => readerViewMode === 'page'")


def go_to_last_page(page):
    page.evaluate("() => { readerPageIndex = READER_PAGES.length - 1; renderReaderPage(0); }")
    page.wait_for_function("() => readerPageIndex === READER_PAGES.length - 1")


def click_page_turn(page, which: str):
    # 페이지 버튼이 가려지는 문제는 다른 레인의 몫이므로 hit-test 없이 click()으로 확인한다.
    page.evaluate(f"() => document.getElementById({which!r}).click()")


def active_screen(page) -> str:
    return page.evaluate("() => document.querySelector('.screen.active')?.id || ''")


# ---- 4: 키보드 ←/→ 페이지 이동 -------------------------------------------------


def test_arrow_right_and_left_turn_pages(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "고린도전서", 3)
    force_page_mode(page)
    page.wait_for_function("() => readerPageIndex === 0")

    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => readerPageIndex === 1")
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => readerPageIndex === 2")
    page.keyboard.press("ArrowLeft")
    page.wait_for_function("() => readerPageIndex === 1")


def test_arrows_do_not_turn_while_input_focused(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "고린도전서", 3)
    force_page_mode(page)
    page.wait_for_function("() => readerPageIndex === 0")

    # #7573: the reader no longer opens with the Memory panel out, so the
    # search box is reachable only after the reader opens it — exactly the way
    # a person gets to that input before typing.
    page.evaluate("() => document.getElementById('memoryRailTab').click()")
    page.wait_for_function("() => document.body.classList.contains('memory-open')")
    page.focus("#memorySearchInput")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(400)
    assert page.evaluate("() => readerPageIndex") == 0
    assert page.evaluate("() => document.activeElement?.id") == "memorySearchInput"

    page.evaluate("() => document.getElementById('memorySearchInput').blur()")
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => readerPageIndex === 1")


def test_arrow_right_on_last_page_goes_to_next_chapter(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "고린도전서", 3)
    force_page_mode(page)
    go_to_last_page(page)

    page.keyboard.press("ArrowRight")
    wait_bound(page, "고린도전서 4장")
    page.wait_for_function(
        "() => __smDynamicReaderState.passages.length > 0 && readerPageIndex === 0"
    )


# ---- 5: 장 끝 이어 읽기 -------------------------------------------------------


def test_last_page_next_button_goes_to_next_chapter_first_page(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "고린도전서", 3)
    force_page_mode(page)
    go_to_last_page(page)

    click_page_turn(page, "pageTurnNext")
    wait_bound(page, "고린도전서 4장")
    page.wait_for_function(
        "() => __smDynamicReaderState.passages.length > 0 && readerPageIndex === 0"
    )
    assert active_screen(page) == "reader"


def test_book_last_chapter_next_goes_to_next_book_chapter_1(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "말라기", 4)
    force_page_mode(page)
    go_to_last_page(page)

    click_page_turn(page, "pageTurnNext")
    wait_bound(page, "마태복음 1장")
    page.wait_for_function(
        "() => __smDynamicReaderState.passages.length > 0 && readerPageIndex === 0"
    )


def test_revelation_22_end_stops(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "요한계시록", 22)
    force_page_mode(page)
    go_to_last_page(page)
    before = page.evaluate("() => [__smCurrentReaderLabel, readerPageIndex]")

    click_page_turn(page, "pageTurnNext")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(600)
    assert page.evaluate("() => [__smCurrentReaderLabel, readerPageIndex]") == before


def test_first_page_prev_button_goes_to_prev_chapter_last_page(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "고린도전서", 3)
    force_page_mode(page)
    page.wait_for_function("() => readerPageIndex === 0")

    click_page_turn(page, "pageTurnPrev")
    wait_bound(page, "고린도전서 2장")
    page.wait_for_function(
        "() => __smDynamicReaderState.passages.length > 0"
        " && readerPageIndex === READER_PAGES.length - 1"
    )


def test_genesis_1_first_page_prev_stops(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "창세기", 1)
    force_page_mode(page)
    page.wait_for_function("() => readerPageIndex === 0")
    before = page.evaluate("() => [__smCurrentReaderLabel, readerPageIndex]")

    click_page_turn(page, "pageTurnPrev")
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(600)
    assert page.evaluate("() => [__smCurrentReaderLabel, readerPageIndex]") == before


def test_flow_view_end_has_next_chapter_link(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "고린도전서", 3)
    page.evaluate("() => applyReaderViewMode('flow')")
    page.wait_for_function("() => document.querySelector('#readerPageBody .reader-flow-section')")

    link = page.locator("#readerPageBody .sm7573-next-chapter")
    assert link.inner_text() == "다음 장 · 고린도전서 4장 →"
    # 링크가 흐름 보기 애니메이션 위에 있어 안정 클릭이 어렵다 — click() 으로 동작을 확인한다.
    page.evaluate("() => document.querySelector('#readerPageBody .sm7573-next-chapter').click()")
    wait_bound(page, "고린도전서 4장")
    # 장을 바꾸면 제품의 기존 규칙(저장된 보기 방식 없으면 기본 방식)을 따른다.
    # 첫 위치만 확인한다: 흐름이면 맨 위, 페이지면 첫 페이지.
    page.wait_for_function(
        "() => readerViewMode === 'flow'"
        " ? document.querySelector('.paper-inner').scrollTop < 4"
        " : readerPageIndex === 0"
    )


# ---- 6: 칩 → 장 격자 ----------------------------------------------------------


def test_chip_opens_chapter_grid_without_leaving_reader(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "고린도전서", 3)

    page.evaluate("() => document.getElementById('v2ChapterChip').click()")
    page.wait_for_selector("#sm7573ChapterGrid", state="visible")
    assert active_screen(page) == "reader"

    cells = page.locator(".sm7573-grid-cell")
    assert cells.count() == 16
    current = page.locator(".sm7573-grid-cell.on")
    assert current.count() == 1
    assert current.inner_text() == "3"

    page.locator(".sm7573-grid-cell").nth(4).click()
    wait_bound(page, "고린도전서 5장")
    page.wait_for_function(
        "() => __smDynamicReaderState.passages.length > 0 && readerPageIndex === 0"
    )
    assert active_screen(page) == "reader"
    assert page.locator("#sm7573ChapterGrid").count() == 0


def test_grid_closes_on_escape_and_outside_click(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "고린도전서", 3)

    page.evaluate("() => document.getElementById('v2ChapterChip').click()")
    page.wait_for_selector("#sm7573ChapterGrid", state="visible")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.getElementById('sm7573ChapterGrid')")
    assert active_screen(page) == "reader"

    page.evaluate("() => document.getElementById('v2ChapterChip').click()")
    page.wait_for_selector("#sm7573ChapterGrid", state="visible")
    page.mouse.click(8, 8)
    page.wait_for_function("() => !document.getElementById('sm7573ChapterGrid')")
    assert active_screen(page) == "reader"


def test_grid_other_books_goes_to_existing_book_selection(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "고린도전서", 3)

    page.evaluate("() => document.getElementById('v2ChapterChip').click()")
    page.wait_for_selector("#sm7573ChapterGrid", state="visible")
    page.locator(".sm7573-grid-otherbooks").click()
    page.wait_for_function("() => document.querySelector('.screen.active')?.id === 'index'")


def test_psalm_grid_has_150_scrolled_cells_at_least_44px(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "시편", 5)

    page.evaluate("() => document.getElementById('v2ChapterChip').click()")
    page.wait_for_selector("#sm7573ChapterGrid", state="visible")
    assert page.locator(".sm7573-grid-cell").count() == 150

    box = page.locator(".sm7573-grid-cell").first.bounding_box()
    assert box["width"] >= 44 and box["height"] >= 44

    scrolls = page.evaluate(
        "() => { const c=document.querySelector('.sm7573-grid-cells');"
        " return {scroll:c.scrollHeight, client:c.clientHeight}; }"
    )
    assert scrolls["scroll"] > scrolls["client"], "150장 격자는 화면 안에서 스크롤되어야 한다"

    page.locator(".sm7573-grid-cell").nth(99).click()
    wait_bound(page, "시편 100장")


# ---- 7: 새로 열면 첫 화면은 홈 ------------------------------------------------


def test_fresh_open_lands_home_and_continue_button_resumes(page, base_url):
    page.goto(base_url, wait_until="load")
    page.evaluate("() => window.BookAIReady")
    open_chapter(page, "고린도전서", 3)
    force_page_mode(page)
    page.evaluate("() => { readerPageIndex = 2; renderReaderPage(0); }")
    page.wait_for_function("() => readerPageIndex === 2")
    page.wait_for_timeout(600)  # 통합 저장이 끝날 시간

    page.reload(wait_until="load")
    page.evaluate("() => window.BookAIReady")
    page.wait_for_timeout(600)

    # 대표 결정 2026-11-10: 새로 열면 첫 화면은 항상 홈(서재)이다.
    assert active_screen(page) == "library", "새로 열면 읽기 화면으로 옮기지 않는다"

    open_book = page.locator("#openBook")
    # 홈(서재)의 이어 읽기 버튼: 읽던 상태에 따라 이어서 읽기/계속 읽기/다시 읽기로 쓰인다.
    assert open_book.inner_text() in {"이어서 읽기", "계속 읽기", "다시 읽기"}
    open_book.click()
    page.wait_for_function("() => document.querySelector('.screen.active')?.id === 'reader'")
    wait_bound(page, "고린도전서 3장")
    page.wait_for_function("() => readerPageIndex === 2")
