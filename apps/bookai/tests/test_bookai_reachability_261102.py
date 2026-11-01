"""bookAI (apps/bookai) — pass 261102, measured in Chromium.

The old StoryMemory pass (9392223b9) fixed four defects. Re-walking the bookAI
screens at 390·768·1440 showed which of them still exist here:

* chapter dots — still broken: at 390 all 16 dots and 4 of 6 chapter stacks
  answered as ``#chapterSpecimenNo`` instead of themselves,
* shelf markers — already fixed here (#library .markers is a scrollable 44px row
  below 900px; every marker reaches its own press after scrolling), so this file
  only pins it against regressions,
* reading settings — half fixed: the controls already reach 44px, but their labels
  were 11px (reset 10px) and the overflow-menu rows that open the panel were 37px
  with 13px labels,
* tab title — already the product name, no prototype build string.

Each test below pins one fix. The desktop numbers are pinned in the opposite
direction: the phone floor must not reach 1440.
"""

from __future__ import annotations

import http.server
import os
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

MENU_ROWS = """() => Array.from(document.querySelectorAll('#smalOverflowMenu .smal-ov-item, #smalOverflowMenu .srsg-btn'))
  .filter((b) => b.getBoundingClientRect().height > 0)
  .map((b) => ({
    label: (b.textContent || '').trim().slice(0, 12),
    h: Math.round(b.getBoundingClientRect().height),
    font: parseFloat(getComputedStyle(b).fontSize),
  }))"""

# Words the owner asked to see nowhere on screen: the demo/preview shell is gone
# and the product runs on real content, so no screen may advertise a prototype.
# The scan is deliberately wider than the wording the owner listed ('데모',
# 'DEMO PREVIEW', …) so a source label such as 'Bible Demo Source' cannot slip
# through if a screen ever renders it. Code comments and metadata keys are not
# screen text, so the static source check below only pins the visible strings.
BANNED_COPY = re.compile(r"데모|demo|프로토타입|prototype|preview", re.I)

# Markup text only: comments, <script> bodies and attribute values are not screen
# copy, and the app legitimately keeps identifiers such as 'bible-demo' or
# `Object.prototype`. What a reader sees before the scripts run is the text between
# tags, so the static pass strips everything else -- the point is screen text, not
# developer comments.
_MARKUP = re.sub(r"<!--.*?-->", " ", INDEX, flags=re.S)
_MARKUP = re.sub(r"<(script|style)\b.*?</\1>", " ", _MARKUP, flags=re.S | re.I)
MARKUP_TEXT = re.sub(r"<[^>]+>", " ", _MARKUP)

SCREEN_COPY = """() => {
  const banned = new RegExp(%r, 'i');
  const hits = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walk.nextNode())) {
    const t = (node.textContent || '').trim();
    if (!t || !banned.test(t)) continue;
    const el = node.parentElement;
    if (!el) continue;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (r.width <= 0 || r.height <= 0 || s.display === 'none' || s.visibility === 'hidden') continue;
    hits.push(t.slice(0, 70));
  }
  const attrs = [];
  document.querySelectorAll('[title],[aria-label],[placeholder],[alt]').forEach((el) => {
    for (const a of ['title', 'aria-label', 'placeholder', 'alt']) {
      const v = el.getAttribute(a) || '';
      if (banned.test(v)) attrs.push(a + '=' + v.slice(0, 70));
    }
  });
  return hits.concat(attrs);
}""" % BANNED_COPY.pattern

GATE_COPY = """() => {
  document.querySelectorAll('#todayCloudButton, #authGatePrimary, #authGateCopy'); 
  document.getElementById('authGateSheet')?.setAttribute('aria-hidden', 'false');
  document.body.classList.add('auth-gate-open');
  return new Promise((resolve) => setTimeout(() => resolve({
    state: document.getElementById('authGateCopy').textContent,
    primary: document.getElementById('authGatePrimary').textContent,
    label: document.getElementById('todayCloudLabel').textContent,
  }), 400));
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


def _launch(pw):
    chrome = os.environ.get("B61_CHROME_PATH")
    return pw.chromium.launch(executable_path=chrome) if chrome else pw.chromium.launch()


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
    page.goto(base_url + "?view=library", wait_until="load")
    page.wait_for_timeout(1500)
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
    page.wait_for_timeout(1200)
    _settle(page)
    page.wait_for_function(
        """() => { const b = document.getElementById('smalOverflowBtn');
                  return b && b.getBoundingClientRect().width > 0; }""",
        timeout=15000,
    )
    page.evaluate("() => document.getElementById('smalOverflowBtn').click()")
    page.wait_for_timeout(350)
    _settle(page)
    page.evaluate("() => document.querySelector('#smalOverflowMenu .srsg-btn').click()")
    page.wait_for_timeout(400)
    _settle(page)


@pytest.mark.parametrize("width,height", [PHONE, TABLET])
def test_every_chapter_dot_answers_its_own_press(base_url, width, height):
    """The SELECTED SHEET label is decoration and must never eat a chapter tap."""
    with sync_playwright() as pw:
        browser = _launch(pw)
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
def test_chapter_stacks_are_not_swallowed_by_the_specimen_label(base_url, width, height):
    """The covered half of the same defect: the label sat over the chapter cards."""
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            _open_library(page, base_url, width, height)
            _open_index(page)
            stacks = page.evaluate("() => document.querySelectorAll('#index .chapter-stack').length")
            misses = page.evaluate(HIT_TEST, "#index .chapter-stack")
        finally:
            browser.close()
    assert stacks >= 6, "the chapter carousel lost its stacks"
    covered = [m for m in misses if m["miss"] != "off-screen"]
    assert covered == [], "a chapter card is covered by decoration: %s" % covered[:4]
    assert len(misses) < stacks, "every chapter card is out of the viewport"


@pytest.mark.parametrize("width,height", [PHONE, TABLET])
def test_reading_settings_reach_the_phone_floor(base_url, width, height):
    """44px targets and 14px labels for the panel that changes 글자 크기 and 테마."""
    with sync_playwright() as pw:
        browser = _launch(pw)
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


@pytest.mark.parametrize("width,height", [PHONE, TABLET])
def test_overflow_menu_rows_reach_the_phone_floor(base_url, width, height):
    """The menu rows are the way into the settings panel; they had 37px rows."""
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            _open_library(page, base_url, width, height)
            page.evaluate("() => document.getElementById('openBook').click()")
            page.wait_for_function(
                "() => document.getElementById('index')?.classList.contains('active')", timeout=15000
            )
            page.evaluate("() => document.getElementById('openChapter').click()")
            page.wait_for_function(
                "() => document.getElementById('reader')?.classList.contains('active')", timeout=15000
            )
            page.wait_for_timeout(1200)
            _settle(page)
            page.wait_for_function(
                """() => { const b = document.getElementById('smalOverflowBtn');
                          return b && b.getBoundingClientRect().width > 0; }""",
                timeout=15000,
            )
            page.evaluate("() => document.getElementById('smalOverflowBtn').click()")
            page.wait_for_timeout(350)
            _settle(page)
            rows = page.evaluate(MENU_ROWS)
        finally:
            browser.close()
    assert rows, "the reader overflow menu did not open"
    short = [r for r in rows if r["h"] < TARGET_FLOOR]
    tiny = [r for r in rows if r["font"] < TEXT_FLOOR]
    assert short == [], "an overflow menu row is under 44px: %s" % short[:4]
    assert tiny == [], "an overflow menu label is under 14px: %s" % tiny[:4]


@pytest.mark.parametrize("width,height", [PHONE, DESKTOP])
def test_no_demo_or_prototype_copy_reaches_the_screen(base_url, width, height):
    """대표 결정: 화면에 '데모'·'프로토타입' 문구 0건."""
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": width, "height": height})
        found = {}
        try:
            _open_library(page, base_url, width, height)
            found["library"] = page.evaluate(SCREEN_COPY)
            _open_index(page)
            found["index"] = page.evaluate(SCREEN_COPY)
            _open_settings(page)
            found["settings"] = page.evaluate(SCREEN_COPY)
            page.evaluate(
                """() => { document.body.classList.remove('reader-settings-open');
                          document.getElementById('authGateSheet')?.setAttribute('aria-hidden', 'false');
                          document.body.classList.add('auth-gate-open'); }"""
            )
            page.wait_for_timeout(500)
            found["authGate"] = page.evaluate(SCREEN_COPY)
        finally:
            browser.close()
    assert not any(found.values()), "demo/prototype wording is still on screen: %s" % found
    for leaked in ("데모", "프로토타입", "DEMO PREVIEW", "NO FALSE TEXT"):
        assert leaked.lower() not in MARKUP_TEXT.lower(), "index.html markup still carries %r" % leaked


def test_the_cloud_sheet_describes_login_as_it_is(base_url):
    """#6520 shipped the b61 client, so the sheet may not say login is '준비 중'."""
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": PHONE[0], "height": PHONE[1]})
        try:
            _open_library(page, base_url, *PHONE)
            gate = page.evaluate(GATE_COPY)
        finally:
            browser.close()
    for stale in ("준비 중", "로그인 안내", "미구현", "not implemented"):
        assert stale not in gate["state"], "the cloud sheet still says %r: %s" % (stale, gate["state"])
        assert stale not in gate["primary"], "the login button still says %r: %s" % (stale, gate["primary"])
    assert "파디엠" in gate["primary"] or "파디엠" in gate["state"], "the sheet does not name the account: %s" % gate
    assert gate["label"], "the cloud label lost its text"
    for stale in ('로그인 안내', "동기화는 준비 중", "동기화는 아직 준비 중"):
        assert stale not in INDEX, "index.html still carries the stale login notice %r" % stale


def test_the_phone_floor_stays_out_of_the_desktop_layout(base_url):
    """1440 keeps the compact panel (292px, 11px labels) and has no sideways overflow."""
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": DESKTOP[0], "height": DESKTOP[1]})
        try:
            _open_library(page, base_url, *DESKTOP)
            library_overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - window.innerWidth"
            )
            _open_index(page)
            index_overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - window.innerWidth"
            )
            page.evaluate("() => document.getElementById('openChapter').click()")
            page.wait_for_function(
                "() => document.getElementById('reader')?.classList.contains('active')", timeout=15000
            )
            page.wait_for_timeout(1200)
            _settle(page)
            reader_overflow = page.evaluate(
                "() => document.documentElement.scrollWidth - window.innerWidth"
            )
            page.evaluate("() => document.getElementById('smalOverflowBtn').click()")
            page.wait_for_timeout(350)
            page.evaluate("() => document.querySelector('#smalOverflowMenu .srsg-btn').click()")
            page.wait_for_timeout(400)
            _settle(page)
            panel = page.evaluate(
                """() => { const p = document.querySelector('.srsg-panel');
                           const r = p.getBoundingClientRect();
                           return { w: Math.round(r.width), h: Math.round(r.height) }; }"""
            )
            buttons = page.evaluate(PANEL_BUTTONS)
        finally:
            browser.close()
    assert (library_overflow, index_overflow, reader_overflow) == (0, 0, 0), (
        "desktop overflow appeared: %s" % [library_overflow, index_overflow, reader_overflow]
    )
    assert panel["w"] == 292, "the desktop panel width changed: %s" % panel
    assert buttons
    assert any(b["font"] < TEXT_FLOOR for b in buttons), "the 14px phone floor leaked into the desktop panel"


def test_the_fixes_stay_inside_their_breakpoints() -> None:
    """Cheap guard: the label stays decorative and the floor stays phone-only."""
    assert "#index .chapter-specimen{pointer-events:none}" in OVERRIDES
    assert "#reader.active .smal-overflow-menu .smal-ov-item" in SETTINGS_CSS
    phone_block = SETTINGS_CSS[SETTINGS_CSS.index("phone floor for the reading settings"):]
    assert "@media(max-width:768px)" in phone_block
    assert "min-height:44px" in phone_block
    assert "font-size:14px" in phone_block
