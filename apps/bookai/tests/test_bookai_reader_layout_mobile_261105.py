"""Reader layout regressions for the 2026-11-05 mobile reader repair.

Covers the four owner-reported surfaces through the product's own controls:
- 375x812 page mode with the largest type: chapter length in pages, no
  sub-sentence Korean fragments, and the same page count on repeated measures.
- 744x1133 and 768x1024: AI and Memory sheet controls take the tap instead of
  the scrim swallowing it.
- 1280x800: the AI panel is wide enough to type into.
- Library to reader entry stays inside one second.

The suite boots its own static server on an ephemeral loopback port and shares one
browser, so it needs nothing from the 127.0.0.1:18782 fixture lane and runs inside
the BookAI keyboard-focus CI job.
"""

from __future__ import annotations

import http.server
import os
import statistics
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
    with sync_playwright() as instance:
        yield instance


@pytest.fixture(scope="module")
def browser(playwright_instance):
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
    launched = (
        playwright_instance.chromium.launch(headless=True, executable_path=executable)
        if executable
        else playwright_instance.chromium.launch(headless=True)
    )
    yield launched
    launched.close()


def _reader_page(browser, viewport, base_url):
    page = browser.new_page(viewport=viewport)
    page.set_default_timeout(30000)
    page.goto(base_url, wait_until="load")
    return page


def _open_chapter_1corinthians_3(page, base_url):
    """Library -> Bible index -> 고린도전서 3장 through the real controls."""
    if "index.html" not in page.url:
        page.goto(base_url, wait_until="load")
    page.wait_for_function("() => typeof setReaderContext === 'function'")
    page.wait_for_function("() => document.querySelector('.screen.active')?.id === 'library'")
    page.locator("#openBook").click()
    page.wait_for_function("() => document.querySelector('.screen.active')?.id === 'index'")
    page.locator("#openChapter").click()
    page.wait_for_function("() => document.querySelector('.screen.active')?.id === 'reader'")
    page.wait_for_function("() => storyMemoryReaderBindingStatus().mode === 'static'")
    page.wait_for_function("() => __smDynamicReaderState.passages.length > 0")
    page.wait_for_function("() => __smReaderSimplificationV2.fontsReady()", timeout=20000)


def _largest_type_page_mode(page):
    page.evaluate(
        """() => {
          const largest = document.querySelector('.srsg-seg[data-field="fontSize"] button[data-value="xl"]');
          if (largest) largest.click();
          applyReaderViewMode('page');
        }"""
    )
    page.wait_for_function("() => document.body.classList.contains('smr-fs-xl')")
    # the fit is debounced; wait for it to settle instead of guessing a sleep
    page.wait_for_function("() => { __smReaderSimplificationV2.fitPages(); return true; }")
    page.wait_for_timeout(400)
    return page.evaluate("() => READER_PAGES.length")


def _korean_lines_per_page(page):
    """Korean passage text per page, with verse numbers and English removed."""
    return page.evaluate(
        """() => READER_PAGES.map(html => {
          const box = document.createElement('div');
          box.innerHTML = html;
          return Array.from(box.querySelectorAll('.verse:not(.verse-en)')).map(el => {
            const copy = el.cloneNode(true);
            copy.querySelectorAll('.vn').forEach(node => node.remove());
            return copy.textContent.replace(/\\s+/g, ' ').trim();
          }).filter(text => text.length);
        })"""
    )


def _whole_verses(page):
    return page.evaluate(
        "() => __smDynamicReaderState.passages.map(p => String(p.text||'').replace(/\\s+/g,' ').trim())"
    )


def _settled_selector(selector):
    """The sheets slide with a .3s transform; the hit test must read the resting box."""
    return f"""() => {{
      const el = document.querySelector('{selector}');
      const transform = getComputedStyle(el).transform;
      return transform === 'none' || transform === 'matrix(1, 0, 0, 1, 0, 0)';
    }}"""


def _open_ai_sheet(page):
    page.evaluate("() => document.getElementById('aiRailTab').click()")
    page.wait_for_function("() => document.body.classList.contains('ai-open')")
    page.wait_for_function(_settled_selector(".ai-panel"))
    page.wait_for_function("() => { const b=document.getElementById('sendBtn'); const r=b.getBoundingClientRect(); return r.width>0 && r.height>0; }")


def _open_memory_sheet(page):
    page.evaluate(
        "() => { document.body.classList.remove('ai-open'); document.getElementById('memoryRailTab').click(); }"
    )
    page.wait_for_function("() => document.body.classList.contains('memory-open')")
    page.wait_for_function(_settled_selector(".memory-rail"))


def test_chapter_fits_in_twelve_pages_at_375_with_largest_type(browser, base_url):
    page = _reader_page(browser, {"width": 375, "height": 812}, base_url)
    try:
        _open_chapter_1corinthians_3(page, base_url)
        pages = _largest_type_page_mode(page)
        assert pages <= 12, f"375x812 page mode produced {pages} pages, expected <= 12"
    finally:
        page.close()


def test_no_page_carries_a_sub_sentence_korean_fragment(browser, base_url):
    page = _reader_page(browser, {"width": 375, "height": 812}, base_url)
    try:
        _open_chapter_1corinthians_3(page, base_url)
        _largest_type_page_mode(page)
        whole = set(_whole_verses(page))
        fragments = [text for rows in _korean_lines_per_page(page) for text in rows]
        cut_mid_sentence = [
            text
            for text in fragments
            if text not in whole
            and not text.rstrip('"\'”’').endswith((".", "!", "?", "。", "？", "！"))
        ]
        assert not cut_mid_sentence, f"pages hold fragments cut below sentence level: {cut_mid_sentence[:3]}"
        assert fragments, "the chapter must render Korean text"
    finally:
        page.close()


def test_page_count_is_identical_across_three_measurements(browser, base_url):
    counts = []
    for _ in range(3):
        page = _reader_page(browser, {"width": 375, "height": 812}, base_url)
        try:
            _open_chapter_1corinthians_3(page, base_url)
            counts.append(_largest_type_page_mode(page))
        finally:
            page.close()
    assert len(set(counts)) == 1, f"page count is not stable: {counts}"


@pytest.mark.parametrize("viewport", [{"width": 744, "height": 1133}, {"width": 768, "height": 1024}])
def test_sheet_controls_take_the_tap_instead_of_the_scrim(browser, base_url, viewport):
    page = _reader_page(browser, viewport, base_url)
    try:
        _open_chapter_1corinthians_3(page, base_url)
        page.wait_for_function("() => __smReaderCompactMode() === true")

        _open_ai_sheet(page)
        box = page.locator("#sendBtn").bounding_box()
        on_target = page.evaluate(
            """() => {
              const target = document.getElementById('sendBtn');
              const rect = target.getBoundingClientRect();
              return document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2) === target;
            }"""
        )
        assert on_target is True, f"the scrim covers #sendBtn at {box['width']}x{box['height']}"

        _open_memory_sheet(page)
        first = page.locator(".memory-rail button:visible").first
        first.wait_for()
        reached = first.evaluate(
            """(el) => {
              const rect = el.getBoundingClientRect();
              const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
              return hit === el || (hit !== null && el.contains(hit));
            }"""
        )
        assert reached is True, "the scrim covers the first memory-sheet control"
    finally:
        page.close()


def test_ai_input_is_wide_enough_to_type_at_1280(browser, base_url):
    page = _reader_page(browser, {"width": 1280, "height": 800}, base_url)
    try:
        _open_chapter_1corinthians_3(page, base_url)
        _open_ai_sheet(page)
        width = page.evaluate("() => document.getElementById('askInput').getBoundingClientRect().width")
        assert width >= 220, f"#askInput is {round(width)}px wide at 1280x800, expected >= 220"
    finally:
        page.close()


def _measure_library_to_reader_entry(browser, base_url):
    context = browser.new_context(viewport={"width": 375, "height": 812})
    page = context.new_page()
    page.set_default_timeout(30000)
    try:
        page.goto(base_url, wait_until="load")
        page.wait_for_function("() => document.querySelector('.screen.active')?.id === 'library'")
        # The library screen is static markup, but prevBook is wired by the
        # deferred boot scripts. Wait for the control so the click cannot land
        # before the shelf exists.
        page.wait_for_function(
            "() => typeof document.getElementById('prevBook').onclick === 'function'"
        )
        # A non-scripture book opens straight into the reading surface; the
        # scripture shelf stops at its chapter index first. The selection is
        # confirmed before the clock starts, so the measure cannot be taken on
        # the wrong card when the shelf boots on a different default book.
        page.evaluate("() => document.getElementById('prevBook').click()")
        page.wait_for_function(
            """() => {
              const rig = document.querySelector('.book-rig.selected');
              return !!rig && !rig.textContent.includes('성경');
            }""",
            timeout=10000,
        )
        # The clock runs inside the page: this is the reader's own click-to-visible interval.
        page.evaluate("() => { window.__entryStart = performance.now(); document.getElementById('openBook').click(); }")
        page.wait_for_function("() => document.querySelector('.screen.active')?.id === 'reader'")
        return page.evaluate("() => (performance.now() - window.__entryStart) / 1000")
    finally:
        context.close()


def test_library_to_reader_entry_stays_under_one_second(browser, base_url):
    _measure_library_to_reader_entry(browser, base_url)  # discard the first-load warm-up
    measurements = [
        _measure_library_to_reader_entry(browser, base_url)
        for _ in range(3)
    ]

    median = statistics.median(measurements)
    assert median < 1.0, (
        f"library-to-reader entry median was {median:.4f}s "
        f"from 3 measurements {measurements}, expected < 1.0s"
    )
