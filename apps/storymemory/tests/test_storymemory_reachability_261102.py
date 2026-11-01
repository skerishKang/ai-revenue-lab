"""B61 StoryMemory — reachability pass 261102, measured in Chromium.

Four user-visible defects were found while walking the core flow (서재 → 책 열기 →
index → 리더 → 읽기 설정) at 390·768·1440:

* every chapter dot on the phone index resolved to the decorative
  ``#chapterSpecimenNo`` instead of itself (16 of 16 at 390),
* the shelf marker row (one dot per book) could not fit its grid column below
  ~1180px, so 5 of 11 markers sat off the left edge at 390 and 4 of 11 sat under
  ``#openBook``/``#nextBook`` at 768,
* the reading-settings buttons — the controls the owner uses to change 글자 크기 and
  테마 — were 24px tall with 11px labels at 390,
* the browser tab still read "StoryMemory Visual Prototype v3.4.10-rc2 · …".

Each test below pins one fix. The desktop numbers are pinned in the opposite
direction: the phone sheet must not reach 1440.
"""

from __future__ import annotations

import http.server
import re
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    PlaywrightTimeout = Exception
    sync_playwright = None

pytestmark = pytest.mark.skipif(
    sync_playwright is None,
    reason="playwright is not installed in this environment",
)

PUBLIC = Path(__file__).resolve().parents[1] / "public"
INDEX = (PUBLIC / "index.html").read_text(encoding="utf-8")
OVERRIDES = (PUBLIC / "styles" / "storymemory-b61-overrides-v1.css").read_text(encoding="utf-8")
SETTINGS_CSS = (PUBLIC / "styles" / "storymemory-reader-settings-v1.css").read_text(encoding="utf-8")

PHONE = (390, 844)
TABLET = (768, 1024)
DESKTOP = (1440, 900)
TARGET_FLOOR = 44.0
TEXT_FLOOR = 14.0

# The centre of a control is where a press lands. A control whose centre belongs
# to a stranger cannot be used, however visible it looks.
HIT_TEST = """(sel) => {
  const out = [];
  document.querySelectorAll(sel).forEach((el) => {
    const b = el.getBoundingClientRect();
    if (b.width <= 0 || b.height <= 0) return;
    const s = getComputedStyle(el);
    if (s.display === 'none' || s.visibility === 'hidden') return;
    const x = b.left + b.width / 2, y = b.top + b.height / 2;
    if (x < 0 || y < 0 || x > window.innerWidth || y > window.innerHeight) {
      out.push({ miss: 'off-screen', rect: [b.x, b.y, b.width, b.height] });
      return;
    }
    const hit = document.elementFromPoint(x, y);
    if (!hit) { out.push({ miss: 'no-hit', rect: [b.x, b.y, b.width, b.height] }); return; }
    if (el.contains(hit) || hit.contains(el)) return;
    out.push({
      miss: hit.id ? '#' + hit.id : hit.tagName.toLowerCase() + '.' + String(hit.className).split(' ')[0],
      rect: [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)],
    });
  });
  return out;
}"""

PANEL_BUTTONS = """() => {
  const panel = document.querySelector('.srsg-panel');
  if (!panel) return null;
  return Array.from(panel.querySelectorAll('button')).map((b) => {
    const r = b.getBoundingClientRect();
    return {
      label: (b.textContent || b.getAttribute('aria-label') || '').trim().slice(0, 12),
      w: Math.round(r.width * 10) / 10,
      h: Math.round(r.height * 10) / 10,
      font: parseFloat(getComputedStyle(b).fontSize),
    };
  });
}"""


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)

    def log_message(self, *args):  # silence the request line
        pass


@pytest.fixture(scope="module")
def base_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d/index.html" % server.server_port
    server.shutdown()
    thread.join(timeout=5)


def _settle(page):
    """Let screen transitions finish, bounded.

    The library and reader carry endless decorative animations (orbits, dust, the
    light sweep), so waiting for the document to go quiet would never return; the
    entry transitions we care about are finite.
    """
    page.wait_for_timeout(400)
    try:
        page.wait_for_function(
            """() => document.getAnimations().filter((a) => {
                 if (a.playState !== 'running') return false;
                 const t = a.effect && a.effect.getTiming ? a.effect.getTiming() : null;
                 return !t || t.iterations !== Infinity;
               }).length === 0""",
            timeout=6000,
        )
    except PlaywrightTimeout:
        pass
    page.wait_for_timeout(250)


def _open_library(page, base_url, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(base_url, wait_until="load")
    page.wait_for_timeout(1200)
    _settle(page)
    for _ in range(3):
        if page.evaluate("() => (document.querySelector('.screen.active') || {}).id") == "library":
            return
        clicked = page.evaluate(
            """() => {
              const b = document.querySelector('.screen.active .back-btn');
              if (!b) return false;
              b.click();
              return true;
            }"""
        )
        if not clicked:
            break
        page.wait_for_timeout(900)
        _settle(page)
    raise AssertionError("the library screen could not be reached")


def _open_index(page):
    page.evaluate("() => document.getElementById('openBook').click()")
    page.wait_for_function(
        "() => document.getElementById('index')?.classList.contains('active')",
        timeout=15000,
    )
    page.wait_for_timeout(1000)
    _settle(page)


def _open_settings(page):
    page.evaluate("() => document.getElementById('openChapter').click()")
    page.wait_for_function(
        "() => document.getElementById('reader')?.classList.contains('active')",
        timeout=15000,
    )
    page.wait_for_timeout(1000)
    _settle(page)
    page.evaluate("() => document.getElementById('smalOverflowBtn').click()")
    page.wait_for_timeout(250)
    page.evaluate("() => document.querySelector('#smalOverflowMenu .srsg-btn').click()")
    page.wait_for_timeout(350)
    _settle(page)


@pytest.mark.parametrize("width,height", [PHONE, TABLET])
def test_every_chapter_dot_answers_its_own_press(base_url, width, height):
    """The SELECTED SHEET label is decoration and must never eat a chapter tap."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            _open_library(page, base_url, width, height)
            _open_index(page)
            dots = page.evaluate("() => document.querySelectorAll('#index .chapter-dot').length")
            misses = page.evaluate(HIT_TEST, "#index .chapter-dot")
        finally:
            browser.close()
    assert dots >= 16, "the chapter carousel lost its dots"
    assert misses == [], "a chapter dot cannot receive its own press: %s" % misses[:4]


@pytest.mark.parametrize("width,height", [PHONE, TABLET])
def test_every_shelf_marker_answers_its_own_press_and_stays_on_screen(base_url, width, height):
    """One marker per book; below ~1180px the row needs a line of its own."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            _open_library(page, base_url, width, height)
            markers = page.evaluate("() => document.querySelectorAll('#library .marker').length")
            misses = page.evaluate(HIT_TEST, "#library .marker")
        finally:
            browser.close()
    assert markers >= 11, "the shelf lost its book markers"
    assert misses == [], "a shelf marker is out of reach: %s" % misses[:4]


@pytest.mark.parametrize("width,height", [PHONE, TABLET])
def test_reading_settings_reach_the_phone_floor(base_url, width, height):
    """44px targets and 14px labels for the panel that changes 글자 크기 and 테마."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            _open_library(page, base_url, width, height)
            _open_settings(page)
            buttons = page.evaluate(PANEL_BUTTONS)
        finally:
            browser.close()
    assert buttons, "the reading settings panel did not open"
    small = [b for b in buttons if b["w"] < TARGET_FLOOR or b["h"] < TARGET_FLOOR]
    tiny = [b for b in buttons if b["font"] < TEXT_FLOOR]
    assert small == [], "a settings target is under 44px: %s" % small[:4]
    assert tiny == [], "a settings label is under 14px: %s" % tiny[:4]


def test_the_reading_settings_panel_keeps_its_compact_desktop_layout(base_url):
    """The phone floor must not reach 1440: same panel, same small controls."""
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": DESKTOP[0], "height": DESKTOP[1]})
        try:
            _open_library(page, base_url, *DESKTOP)
            _open_settings(page)
            buttons = page.evaluate(PANEL_BUTTONS)
        finally:
            browser.close()
    assert buttons
    assert any(b["h"] < TARGET_FLOOR for b in buttons), "the 44px floor leaked into the desktop panel"
    assert any(b["font"] < TEXT_FLOOR for b in buttons), "the 14px floor leaked into the desktop panel"


def test_the_tab_title_names_the_product_not_a_prototype_build():
    """#6473: the owner's browser tab read 'Visual Prototype v3.4.10-rc2 · …'."""
    title = re.search(r"<title>(.*?)</title>", INDEX, re.S).group(1).strip()
    assert title, "index.html has no title"
    for leaked in ("prototype", "visual prototype", "rc1", "rc2", "v3."):
        assert leaked not in title.lower(), "the tab title still carries the build string %r: %s" % (leaked, title)
    assert "StoryMemory" in title


def test_the_reachability_rules_stay_inside_their_breakpoints() -> None:
    """Cheap guard: the fixes are breakpoint-scoped and the label stays decorative."""
    assert "#index .chapter-specimen{pointer-events:none}" in OVERRIDES
    assert "@media(max-width:1180px)" in OVERRIDES
    assert "#reader.active .smal-overflow-menu .smal-ov-item" in SETTINGS_CSS
    phone_block = SETTINGS_CSS[SETTINGS_CSS.index("phone floor for the reading settings"):]
    assert "@media(max-width:768px)" in phone_block
    assert "min-height:44px" in phone_block
