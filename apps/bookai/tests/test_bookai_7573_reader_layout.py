"""#7573 (1·2·3·8): the reading screen must not block the text or the page buttons.

Owner check 2026-11-12 on the reader at 1920·1440·1280·820·390 found four
obstructions that this file pins:

1. entered the reader with both Memory and AI panels already open, covering the
   paper and clipping the first verse ("형제들아" → "제들아") and the title;
2. the page-turn buttons were unclickable at 1440 (#aiReadingContext), 1280
   (.under-sheet.under2) and 820 (#scrim), so a page could not be turned;
3. the 820×1180 tablet opened the Memory sheet over the whole body, with the
   scrim over the paper and under the chapter chip, the ⋯ menu and the page
   buttons;
8. the desk/paper light followed the pointer on every event, so the reading
   surface flickered like a failing fluorescent tube (owner saw the flicker,
   liked the edge colour change).

This suite boots its own static server on an ephemeral loopback port and shares
one browser, the same way test_bookai_reader_layout_mobile_261105.py does, so it
needs nothing from the fixture lanes CI does not start.
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

VIEWPORTS = [
    ("desktop-1920", {"width": 1920, "height": 1080}),
    ("desktop-1440", {"width": 1440, "height": 900}),
    ("desktop-1280", {"width": 1280, "height": 800}),
    ("tablet-820", {"width": 820, "height": 1180}),
    ("phone-390", {"width": 390, "height": 844}),
]


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def guess_type(self, path):
        content_type = super().guess_type(path)
        return "text/html; charset=utf-8" if path.endswith(".html") else content_type

    def log_message(self, *args):
        pass


class StaticServer(http.server.ThreadingHTTPServer):
    # Chrome opens more parallel connections than the 5-deep default accept
    # queue takes, so a busy page load loses CSS files under load.
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


def _settled(page, selector):
    """Sheets and panels animate; every measurement reads the resting box."""
    page.wait_for_function(
        f"""() => {{
          const el = document.querySelector('{selector}');
          if (!el) return false;
          const style = getComputedStyle(el);
          if (style.display === 'none') return true;
          const t = style.transform;
          return t === 'none' || t === 'matrix(1, 0, 0, 1, 0, 0)';
        }}"""
    )


def _first_verse_visible(page):
    """The first body character is on screen and nothing above it covers it."""
    return page.evaluate(
        """() => {
          const verse = document.querySelector('#readerPageBody .verse:not(.verse-en)');
          if (!verse) return {ok: false, why: 'no verse rendered'};
          const text = verse.textContent.trim();
          if (!text) return {ok: false, why: 'empty verse'};
          // The first glyph of the first verse is the character the owner saw clipped.
          const range = document.createRange();
          const node = verse.firstChild && verse.firstChild.nodeType === 3
            ? verse.firstChild : verse;
          range.setStart(node, 0);
          range.setEnd(node, Math.min(2, (node.textContent || '').length));
          const rect = range.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) {
            return {ok: false, why: 'zero-size first glyph', text: text.slice(0, 12)};
          }
          const cx = rect.left + Math.min(rect.width / 2, 6);
          const cy = rect.top + rect.height / 2;
          const hit = document.elementFromPoint(cx, cy);
          const paper = document.getElementById('paper');
          const covered = !hit || !(paper.contains(hit) || hit === paper);
          return {ok: !covered, why: covered ? (hit ? hit.id || hit.className : 'null') : '',
                  text: text.slice(0, 16), cx: Math.round(cx), cy: Math.round(cy)};
        }"""
    )


def _button_hit(page, button_id):
    return page.evaluate(
        """(id) => {
          const el = document.getElementById(id);
          if (!el) return {ok: false, why: 'missing'};
          // A button the reader cannot press is not a covered button: the first
          // page has no previous page, and the product marks that with :disabled
          // (opacity .18 + pointer-events:none) exactly as before this change.
          if (el.disabled || getComputedStyle(el).pointerEvents === 'none') {
            return {ok: true, why: 'disabled'};
          }
          const rect = el.getBoundingClientRect();
          if (rect.width === 0 || rect.height === 0) return {ok: false, why: 'zero size'};
          const cx = rect.left + rect.width / 2;
          const cy = rect.top + rect.height / 2;
          const hit = document.elementFromPoint(cx, cy);
          return {ok: hit === el, why: hit ? (hit.id || hit.className || hit.tagName) : 'null',
                  cx: Math.round(cx), cy: Math.round(cy)};
        }""",
        button_id,
    )


@pytest.mark.parametrize("label,viewport", VIEWPORTS)
def test_both_panels_are_closed_when_the_reader_opens(browser, base_url, label, viewport):
    """1: nothing opens for the reader; a panel shows only when the user asks."""
    page = _reader_page(browser, viewport, base_url)
    try:
        _open_chapter_1corinthians_3(page, base_url)
        # A sheet counts as open only where it is actually on screen: the phone
        # and tablet sheets keep a full-width box while parked below the fold,
        # so a width test cannot answer this.
        state = page.evaluate(
            """() => {
              // Open means: a real sheet box (wider than the 44 px collapsed rail
              // strip) that is on screen. A parked phone/tablet sheet keeps its
              // full width but sits below the fold; a desktop rail strip is on
              // screen but only 44 px wide. Both are closed.
              const sheetOnScreen = (selector) => {
                const el = document.querySelector(selector);
                if (!el) return false;
                const style = getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = el.getBoundingClientRect();
                if (rect.width <= 60) return false;
                return rect.bottom > 8 && rect.top < window.innerHeight - 8;
              };
              return {
                memory: document.body.classList.contains('memory-open'),
                ai: document.body.classList.contains('ai-open'),
                memorySheetOpen: sheetOnScreen('.reader-layout > .memory-rail'),
                aiSheetOpen: sheetOnScreen('.reader-layout > .ai-panel')
              };
            }"""
        )
        assert state == {
            "memory": False, "ai": False, "memorySheetOpen": False, "aiSheetOpen": False
        }, f"{label}: the reader opened with a panel already open: {state}"

        visible = _first_verse_visible(page)
        assert visible["ok"] is True, f"{label}: first verse covered by {visible['why']} ({visible})"
    finally:
        page.close()


@pytest.mark.parametrize("label,viewport", VIEWPORTS)
def test_page_turn_buttons_take_the_click(browser, base_url, label, viewport):
    """2: the centre of each page-turn button hits that button at every width."""
    page = _reader_page(browser, viewport, base_url)
    try:
        _open_chapter_1corinthians_3(page, base_url)
        # The desktop button is centred by translateY(-50%), so a "transform is
        # none" probe never passes; wait for a real box and one painted frame.
        page.wait_for_function(
            "() => { const el=document.getElementById('pageTurnNext');"
            " if(!el) return false; const r=el.getBoundingClientRect();"
            " return r.width>0 && r.height>0; }"
        )
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        for button_id in ("pageTurnNext", "pageTurnPrev"):
            hit = _button_hit(page, button_id)
            assert hit["ok"] is True, (
                f"{label}: {button_id} centre is covered by {hit['why']} at "
                f"({hit.get('cx')},{hit.get('cy')})"
            )
    finally:
        page.close()


def test_tablet_820_starts_with_the_sheets_closed_and_scrim_under_the_sheet(browser, base_url):
    """3: 769–1024 px starts closed; an opened sheet keeps the scrim between it and the paper."""
    page = _reader_page(browser, {"width": 820, "height": 1180}, base_url)
    try:
        _open_chapter_1corinthians_3(page, base_url)
        state = page.evaluate(
            "() => ({memory: document.body.classList.contains('memory-open'),"
            " ai: document.body.classList.contains('ai-open')})"
        )
        assert state == {"memory": False, "ai": False}, f"820 starts with a sheet open: {state}"
        visible = _first_verse_visible(page)
        assert visible["ok"] is True, f"820 first verse covered by {visible['why']}"

        # The user opens Memory on purpose: the sheet is above the scrim and
        # the body text underneath the scrim is out of reach.
        page.evaluate("() => document.getElementById('memoryRailTab').click()")
        page.wait_for_function("() => document.body.classList.contains('memory-open')")
        _settled(page, ".reader-layout > .memory-rail")
        layers = page.evaluate(
            """() => {
              const sheet = document.querySelector('.reader-layout > .memory-rail');
              const scrim = document.getElementById('scrim');
              const paper = document.getElementById('paper');
              const sheetBox = sheet.getBoundingClientRect();
              const paperBox = paper.getBoundingClientRect();
              const sheetZ = Number(getComputedStyle(sheet).zIndex) || 0;
              const scrimZ = Number(getComputedStyle(scrim).zIndex) || 0;
              const sheetPoint = [
                sheetBox.left + Math.min(60, sheetBox.width / 2),
                sheetBox.top + Math.min(120, sheetBox.height / 2)
              ];
              // A paper point the sheet does not cover: the sheet is docked to
              // one side, so the opposite side of the paper is always free.
              const leftFree = sheetBox.left - paperBox.left;
              const paperPoint = leftFree > 80
                ? [paperBox.left + Math.min(40, leftFree / 2), paperBox.top + paperBox.height / 2]
                : [paperBox.right - 40, paperBox.top + paperBox.height / 2];
              const atSheet = document.elementFromPoint(sheetPoint[0], sheetPoint[1]);
              const atPaper = document.elementFromPoint(paperPoint[0], paperPoint[1]);
              return {
                sheetZ, scrimZ,
                sheetPoint, paperPoint,
                sheetOwns: !!atSheet && (atSheet === sheet || sheet.contains(atSheet)),
                atPaper: atPaper ? (atPaper.id || atPaper.className || atPaper.tagName) : 'null',
                scrimOwnsPaper: atPaper === scrim,
                paperIsAboveSheet: !!atPaper && (atPaper === paper || paper.contains(atPaper))
              };
            }"""
        )
        assert layers["sheetPoint"] and layers["paperPoint"], f"bad probe geometry: {layers}"
        assert layers["sheetZ"] > layers["scrimZ"], f"scrim must sit under the sheet: {layers}"
        assert layers["paperIsAboveSheet"] is False, f"the paper is above the sheet: {layers}"
        assert layers["sheetOwns"] is True, f"the scrim covers the open sheet: {layers}"
    finally:
        page.close()


def test_the_desk_light_does_not_follow_the_pointer_directly(browser, base_url):
    """8: --desk-* stays 0 and --lamp-* moves only by eased steps, then stops."""
    page = _reader_page(browser, {"width": 1440, "height": 900}, base_url)
    try:
        _open_chapter_1corinthians_3(page, base_url)
        stage = page.locator(".reader-stage")
        box = stage.bounding_box()
        readings = page.evaluate(
            """async () => {
              const stage = document.querySelector('.reader-stage');
              const paper = document.getElementById('paper');
              const read = () => ({
                deskX: stage.style.getPropertyValue('--desk-x'),
                deskY: stage.style.getPropertyValue('--desk-y'),
                lampX: paper.style.getPropertyValue('--lamp-x'),
                lampY: paper.style.getPropertyValue('--lamp-y')
              });
              const before = read();
              const rect = stage.getBoundingClientRect();
              const seen = [];
              for (let i = 1; i <= 12; i += 1) {
                const x = rect.left + rect.width * (i / 13);
                const y = rect.top + rect.height * (i / 13);
                stage.dispatchEvent(new PointerEvent('pointermove', {
                  bubbles: true, clientX: x, clientY: y
                }));
                seen.push(read());
              }
              await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
              const after = read();
              return {before, seen, after};
            }"""
        )
        for reading in readings["seen"] + [readings["after"]]:
            assert reading["deskX"] in ("", "0px") and reading["deskY"] in ("", "0px"), (
                "--desk-x/--desk-y must stay 0 while the pointer moves: "
                f"{reading['deskX']}/{reading['deskY']}"
            )
        changed = {r["lampX"] for r in readings["seen"]} | {r["lampY"] for r in readings["seen"]}
        assert len(changed) <= 2, f"the lamp jumps on every pointer event: {sorted(changed)}"
    finally:
        page.close()


def test_reduced_motion_keeps_the_lamp_centred(browser, base_url):
    """8: with prefers-reduced-motion the lamp does not follow the pointer."""
    page = _reader_page(browser, {"width": 1440, "height": 900}, base_url)
    try:
        page.emulate_media(reduced_motion="reduce")
        _open_chapter_1corinthians_3(page, base_url)
        readings = page.evaluate(
            """async () => {
              const stage = document.querySelector('.reader-stage');
              const paper = document.getElementById('paper');
              const rect = stage.getBoundingClientRect();
              for (let i = 1; i <= 6; i += 1) {
                stage.dispatchEvent(new PointerEvent('pointermove', {
                  bubbles: true,
                  clientX: rect.left + rect.width * (i / 7),
                  clientY: rect.top + rect.height * (i / 7)
                }));
              }
              await new Promise(resolve => requestAnimationFrame(
                () => requestAnimationFrame(resolve)));
              const computed = getComputedStyle(paper);
              return {
                lampX: computed.getPropertyValue('--lamp-x').trim(),
                lampY: computed.getPropertyValue('--lamp-y').trim(),
                deskX: stage.style.getPropertyValue('--desk-x'),
                deskY: stage.style.getPropertyValue('--desk-y'),
                pageHoverKept: true
              };
            }"""
        )
        assert readings["lampX"] in ("50%", "50.0%"), f"lamp not centred: {readings}"
        assert readings["lampY"] in ("50%", "50.0%"), f"lamp not centred: {readings}"
        assert readings["deskX"] in ("", "0px") and readings["deskY"] in ("", "0px"), (
            f"--desk-* must stay 0: {readings}"
        )
    finally:
        page.close()


def test_the_edge_colour_change_stays(browser, base_url):
    """8: the page-hover edge emphasis the owner likes is untouched."""
    page = _reader_page(browser, {"width": 1440, "height": 900}, base_url)
    try:
        _open_chapter_1corinthians_3(page, base_url)
        read = (
            "() => { const rail = document.querySelector('.reader-layout > .memory-rail');"
            " const style = getComputedStyle(rail);"
            " return {hover: document.querySelector('.reader-layout')"
            "   .classList.contains('page-hover'), opacity: style.opacity,"
            "   shadow: getComputedStyle(document.getElementById('paper')).boxShadow}; }"
        )
        # Park the real pointer away from the paper first: the entry clicks
        # leave it over the page, which would make the "before" already hovered.
        page.mouse.move(4, 4)
        page.wait_for_function(
            "() => !document.querySelector('.reader-layout').classList.contains('page-hover')"
        )
        before = page.evaluate(read)
        page.evaluate(
            "() => document.getElementById('paper')"
            ".dispatchEvent(new PointerEvent('pointerenter', {bubbles: false}))"
        )
        page.wait_for_function(
            "() => document.querySelector('.reader-layout').classList.contains('page-hover')"
        )
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        during = page.evaluate(read)
        page.evaluate(
            "() => document.getElementById('paper')"
            ".dispatchEvent(new PointerEvent('pointerleave', {bubbles: false}))"
        )
        page.wait_for_function(
            "() => !document.querySelector('.reader-layout').classList.contains('page-hover')"
        )
        assert before["hover"] is False and during["hover"] is True
        assert before["opacity"] != during["opacity"] or before["shadow"] != during["shadow"], (
            f"the page-hover edge emphasis is gone: {before} vs {during}"
        )
    finally:
        page.close()
