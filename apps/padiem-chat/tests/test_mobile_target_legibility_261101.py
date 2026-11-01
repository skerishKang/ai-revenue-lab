"""#chat-mobile-pass: the phone floor for Chat and Claw, measured in a browser.

390x844 and 360x780 are the two phone sizes the owner reads on. Three numbers
are pinned here: nothing sticks out past the viewport, every press target is at
least 44px on both axes, and every run of text a person reads is at least 14px.
The first screen must also reach the composer without scrolling, and the
desktop must not feel any of it.
"""

from __future__ import annotations

import http.server
import re
import threading
from pathlib import Path

import pytest

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:  # pragma: no cover
    sync_playwright = None

pytestmark = pytest.mark.skipif(
    sync_playwright is None,
    reason="playwright is not installed in this environment",
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")
SHEET = (STATIC / "mobile-target-legibility.css").read_text(encoding="utf-8")
THEME_JS = (STATIC / "theme.js").read_text(encoding="utf-8")
LOCALE = (STATIC / "locale.js").read_text(encoding="utf-8")
PHONE_WIDTHS = ((390, 844), (360, 780))
PHONE_BREAKPOINT = 920
TARGET_FLOOR = 44.0
TEXT_FLOOR = 14.0

MEASURE = """(cfg) => {
  const round = (n) => Math.round(n * 10) / 10;
  const vw = window.innerWidth;
  const label = (el) => el.id ? '#' + el.id
    : el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split('\\s+').slice(0, 2).join('.') : '');
  const text = (el) => (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && !el.closest('[hidden]');
  };
  const taps = [], fonts = [], wide = [];
  const interactive = 'a[href], button, input:not([type=hidden]), select, textarea, summary,'
    + ' [role="button"], [role="tab"], [role="menuitem"], [role="checkbox"], [role="switch"]';
  document.querySelectorAll('body *').forEach((el) => {
    if (!visible(el)) return;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    if (r.right > vw + 1 || r.left < -1) wide.push({ el: label(el), text: text(el), right: round(r.right) });
    if (el.matches(interactive)) {
      // A checkbox is drawn small on purpose and its label row is the press
      // target, so the row is what has to reach the floor.
      const host = el.matches('input[type="checkbox"], input[type="radio"]') ? el.closest('label') : null;
      const box = host ? host.getBoundingClientRect() : r;
      if (round(box.width) < cfg.floor || round(box.height) < cfg.floor) {
        taps.push({ el: label(el), text: text(el), w: round(box.width), h: round(box.height) });
      }
    }
    let own = false;
    for (const n of el.childNodes) { if (n.nodeType === 3 && n.textContent.trim()) { own = true; break; } }
    if (!own) return;
    const size = parseFloat(s.fontSize);
    // A declared 0 is a screen-reader label behind an icon, not readable text.
    if (size > 0 && size < cfg.textFloor) fonts.push({ el: label(el), size: round(size), text: text(el) });
  });
  const composer = document.getElementById('messageInput');
  const composerBox = composer ? composer.getBoundingClientRect() : null;
  const portrait = getComputedStyle(document.querySelector('.main-panel'), '::before');
  return {
    vw, scrollWidth: document.documentElement.scrollWidth,
    overflowPx: round(document.documentElement.scrollWidth - vw),
    wide, taps, fonts,
    composerVisible: composerBox ? composerBox.top >= 0 && composerBox.bottom <= window.innerHeight + 1 : false,
    portraitContent: portrait.content,
    shellPortrait: getComputedStyle(document.querySelector('.glass-shell-portrait') || document.body).display,
    bodyOverflow: getComputedStyle(document.body).overflow,
  };
}
"""


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *args):  # silence the request line
        pass


@pytest.fixture(scope="module")
def static_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d/index.html?theme=padiem-glass" % server.server_port
    server.shutdown()
    thread.join(timeout=5)


def _open_surfaces(page, url, width, height):
    """Measure the phone screens that a page without a session can reach."""
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_function("() => document.getElementById('messageInput') !== null")
    results = {}
    results["home"] = page.evaluate(MEASURE, {"floor": TARGET_FLOOR, "textFloor": TEXT_FLOOR})
    page.evaluate("() => document.getElementById('mobileMenu').click()")
    page.wait_for_timeout(250)
    results["drawer"] = page.evaluate(MEASURE, {"floor": TARGET_FLOOR, "textFloor": TEXT_FLOOR})
    results["scroll_lock"] = page.evaluate(
        """() => {
          const scroller = document.scrollingElement || document.documentElement;
          const before = scroller.scrollTop;
          scroller.scrollTop = before + 240;
          const moved = scroller.scrollTop - before;
          scroller.scrollTop = before;
          return { moved, bodyOverflow: getComputedStyle(document.body).overflow,
                   open: document.querySelector('.app-shell').classList.contains('sidebar-open') };
        }"""
    )
    page.evaluate("() => document.getElementById('mobileClose').click()")
    page.wait_for_timeout(200)
    for nav in ("utilNavButton", "clawNavButton", "filesNavButton", "calendarNavButton",
                "automationNavButton", "connectorsNavButton", "meetingNavButton"):
        page.evaluate("(id) => document.getElementById(id)?.click()", nav)
        page.wait_for_timeout(320)
        results[nav] = page.evaluate(MEASURE, {"floor": TARGET_FLOOR, "textFloor": TEXT_FLOOR})
    return results


@pytest.mark.parametrize("width,height", PHONE_WIDTHS)
def test_no_phone_screen_sticks_out_past_the_viewport(static_url, width, height):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            for name, value in _open_surfaces(page, static_url, width, height).items():
                if name == "scroll_lock":
                    continue
                offenders = value["wide"]
                assert value["overflowPx"] <= 1, "%s overflows by %spx: %s" % (name, value["overflowPx"], offenders[:4])
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", PHONE_WIDTHS)
def test_every_phone_press_target_reaches_44px(static_url, width, height):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            for name, value in _open_surfaces(page, static_url, width, height).items():
                if name == "scroll_lock":
                    continue
                assert not value["taps"], "%s keeps a target under 44px: %s" % (name, value["taps"][:6])
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", PHONE_WIDTHS)
def test_every_phone_text_reaches_14px(static_url, width, height):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            for name, value in _open_surfaces(page, static_url, width, height).items():
                if name == "scroll_lock":
                    continue
                assert not value["fonts"], "%s keeps text under 14px: %s" % (name, value["fonts"][:6])
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", PHONE_WIDTHS)
def test_the_first_screen_reaches_the_composer_and_hides_the_portrait_art(static_url, width, height):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            page.set_viewport_size({"width": width, "height": height})
            page.goto(static_url, wait_until="domcontentloaded")
            page.wait_for_function("() => document.getElementById('messageInput') !== null")
            page.wait_for_timeout(400)
            value = page.evaluate(MEASURE, {"floor": TARGET_FLOOR, "textFloor": TEXT_FLOOR})
            assert value["composerVisible"], "the composer is below the fold on the first screen"
            assert value["portraitContent"] == "none", "the decorative portrait still paints over the phone screen"
            assert value["shellPortrait"] == "none", "the shell portrait layer still paints over the phone screen"
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", PHONE_WIDTHS)
def test_the_drawer_locks_the_screen_behind_it(static_url, width, height):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            values = _open_surfaces(page, static_url, width, height)
        finally:
            browser.close()
    lock = values["scroll_lock"]
    assert lock["open"], "the drawer did not open"
    assert lock["moved"] == 0, "the screen behind the drawer scrolled"
    assert lock["bodyOverflow"].split()[0] == "hidden", "the drawer does not lock the body: %s" % lock["bodyOverflow"]


def test_a_long_sidebar_title_stays_one_cell_and_ellipsises(static_url):
    """The rows are built at runtime, so the markup is reproduced here."""
    long_title = "강남구 주민센터 주민 참여 예산 설명회 준비와 참석자 명단 정리 그리고 사후 홍보 글 작성"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            page.goto(static_url, wait_until="domcontentloaded")
            page.wait_for_function("() => document.getElementById('historyList') !== null")
            built = page.evaluate(
                """(title) => {
                  const section = document.getElementById('historySection');
                  section.hidden = false;
                  const row = document.createElement('div');
                  row.className = 'history-row';
                  const button = document.createElement('button');
                  button.type = 'button';
                  button.className = 'recent-item history-item';
                  button.textContent = title;
                  row.append(button);
                  document.getElementById('historyList').append(row);
                  const s = getComputedStyle(button);
                  const r = button.getBoundingClientRect();
                  return { clipped: button.scrollWidth > button.clientWidth + 1,
                           textOverflow: s.textOverflow, whiteSpace: s.whiteSpace,
                           width: Math.round(r.width), height: Math.round(r.height),
                           rows: document.getElementById('historyList').childElementCount };
                }""",
                long_title)
        finally:
            browser.close()
    assert built["rows"] == 1
    assert built["clipped"], "the long title was not truncated into one cell"
    assert built["textOverflow"] == "ellipsis"
    assert built["whiteSpace"] in {"nowrap", "nowrap;"}
    assert built["height"] >= TARGET_FLOOR


def test_the_desktop_keeps_its_own_metrics(static_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        try:
            page.goto(static_url, wait_until="domcontentloaded")
            page.wait_for_function("() => document.getElementById('messageInput') !== null")
            page.wait_for_timeout(400)
            value = page.evaluate(MEASURE, {"floor": TARGET_FLOOR, "textFloor": TEXT_FLOOR})
            nav = page.evaluate(
                """() => {
                  const el = document.getElementById('filesNavButton');
                  return el ? Math.round(el.getBoundingClientRect().height) : null;
                }"""
            )
        finally:
            browser.close()
    assert value["overflowPx"] <= 1
    assert value["portraitContent"] != "none", "the phone rule reached the desktop portrait"
    assert value["shellPortrait"] != "none", "the phone rule reached the desktop shell portrait"
    assert nav is not None and nav < TARGET_FLOOR, "the phone press floor leaked into the desktop sidebar"


def test_the_phone_sheet_is_last_and_stays_inside_its_media_query() -> None:
    link = 'href="./mobile-target-legibility.css"'
    assert link in INDEX
    assert INDEX.rindex(link) > INDEX.rindex('href="./mobile-header-collapse.css"'), \
        "the phone sheet must load after the sheets it corrects"
    media = "@media (max-width: %dpx)" % PHONE_BREAKPOINT
    assert SHEET.count(media) >= 3, "the sheet is expected to keep one media block per pass"
    assert SHEET.count("@media") == SHEET.count(media), "every media block in the sheet is the phone breakpoint"
    # Every rule lives inside a phone media block: after comments go, no
    # selector may start at column zero.
    bare = re.sub(r"/\*.*?\*/", "", SHEET, flags=re.S)
    for line in bare.splitlines():
        if re.match(r"^[a-z#.#\[:]", line) and not line.startswith("@media"):
            raise AssertionError("declaration outside the phone media query: %s" % line.strip())


def test_the_phone_copy_keys_exist_in_both_locales_and_no_hardcoded_english_label() -> None:
    for key in ("glass-mask-mode", "glass-mask-auto", "glass-mask-on", "glass-mask-off", "glass-motion-speed"):
        assert LOCALE.count('"%s":' % key) == 2, "%s must carry a Korean and an English value" % key
    assert '"nav-util": "유틸",' in LOCALE, "the Korean sidebar must not switch its own label to English"
    assert '"nav-util": "Util",' in LOCALE.split("en: {")[1], "the English label stays English"
    for key in ("glass-mask-mode", "glass-mask-auto", "glass-mask-on", "glass-mask-off", "glass-motion-speed"):
        assert key in THEME_JS, "theme.js must read %s from the locale" % key
    for literal in ('label.textContent="Shell mask"', 'speedLabel.textContent="Motion speed"'):
        assert literal not in THEME_JS, "theme.js paints a hard-coded English label: %s" % literal
    for literal in (">ADMIN<", ">DATA<", ">ACCOUNT<", ">PROJECT<", "APPEARANCE", "LANGUAGE"):
        assert literal not in INDEX, "index.html still paints %s before the locale runs" % literal
