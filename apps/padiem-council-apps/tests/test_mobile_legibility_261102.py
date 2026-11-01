"""#5987-style phone floor for the council app, measured in a real browser.

390x844 and 360x780 are the two phone sizes the owner reads on. Three numbers
are pinned: nothing sticks out past the viewport, every press target is at
least 44px on both axes, and every run of readable text is at least 14px.
The desktop keeps its measured values, so the phone floor never leaks upward.
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

pytestmark = pytest.mark.skipif(
    sync_playwright is None,
    reason="playwright is not installed in this environment",
)

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
PHONE_WIDTHS = ((390, 844), (360, 780))
DESKTOP_WIDTH = 1440
TARGET_FLOOR = 44.0
TEXT_FLOOR = 14.0

MEASURE = """(cfg) => {
  const round = (n) => Math.round(n * 10) / 10;
  const vw = window.innerWidth;
  const label = (el) => el.id ? '#' + el.id
    : el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className.trim()
      ? '.' + el.className.trim().split(/\\s+/).slice(0, 2).join('.') : '');
  const text = (el) => (el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 40);
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const s = getComputedStyle(el);
    return s.display !== 'none' && s.visibility !== 'hidden' && !el.closest('[hidden]');
  };
  const taps = [], fonts = [], wide = [];
  const interactive = 'a[href], button, input:not([type=hidden]), select, textarea, summary,'
    + ' [role="button"], [role="radio"], [role="tab"], [role="menuitem"]';
  document.querySelectorAll('body *').forEach((el) => {
    if (!visible(el)) return;
    const r = el.getBoundingClientRect();
    // A skip link parks itself off-screen until it takes focus; its box is
    // measured where it will actually be pressed.
    if (el.classList.contains('council-skip')) {
      el.focus();
      const focused = el.getBoundingClientRect();
      if (round(focused.width) < cfg.floor || round(focused.height) < cfg.floor) {
        taps.push({ el: label(el), text: text(el), w: round(focused.width), h: round(focused.height) });
      }
      el.blur();
      return;
    }
    const s = getComputedStyle(el);
    if (r.right > vw + 1 || r.left < -1) wide.push({ el: label(el), text: text(el), right: round(r.right) });
    if (el.matches(interactive)) {
      if (round(r.width) < cfg.floor || round(r.height) < cfg.floor) {
        taps.push({ el: label(el), text: text(el), w: round(r.width), h: round(r.height) });
      }
    }
    let own = false;
    for (const n of el.childNodes) { if (n.nodeType === 3 && n.textContent.trim()) { own = true; break; } }
    if (!own) return;
    const size = parseFloat(s.fontSize);
    // A declared 0 is a screen-reader label behind an icon, not readable text.
    if (size > 0 && size < cfg.textFloor) fonts.push({ el: label(el), size: round(size), text: text(el) });
  });
  return {
    vw, overflowPx: round(document.documentElement.scrollWidth - vw),
    wide, taps, fonts,
  };
}
"""

DESKTOP_PROBE = """() => {
  const size = (selector) => {
    const el = document.querySelector(selector);
    return el ? parseFloat(getComputedStyle(el).fontSize) : null;
  };
  const box = (selector) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return [Math.round(r.width), Math.round(r.height)];
  };
  return {
    eyebrow: size('.council-hero-copy .council-eyebrow'),
    worksEyebrow: size('.council-works-intro .council-eyebrow'),
    cardButton: size('.council-card-select'),
    cardTitle: size('.council-card h2'),
    heroTitle: size('.council-hero .council-title'),
    skip: box('.council-skip'),
    body: size('body'),
    photo: box('.council-photo-layer'),
    scrollWidth: document.documentElement.scrollWidth,
  };
}
"""


THEMES = ROOT.parent / "padiem-chat" / "static" / "padiem-themes.css"

PROJECT = {"id": "proj_council_qa", "name": "의원3종", "instructions": "",
           "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z"}
# A long Korean name, a short one and a mixed Korean/English one: the archive
# row must clip them the same way at 390 and 360.
ARCHIVE_FILES = (
    {"id": "file_qa_long", "name": "E2E 회의록 작성 및 일정 정리 최종본.txt",
     "doc_kind": "meeting", "content_chars": 71, "country": "kr"},
    {"id": "file_qa_short", "name": "회의.txt",
     "doc_kind": "meeting", "content_chars": 12, "country": "kr"},
    {"id": "file_qa_mixed", "name": "Budget Review with Ministry of Finance Q4.txt",
     "doc_kind": "meeting", "content_chars": 240, "country": "kr"},
)


ARCHIVE_ROW = """() => {
  const round = (n) => Math.round(n * 10) / 10;
  const rows = [...document.querySelectorAll('.council-archive-item')];
  const archive = document.querySelector('.council-archive');
  const limit = archive ? archive.getBoundingClientRect().right : 0;
  return rows.map((row) => {
    const button = row.querySelector('button:not(.council-record-move)');
    const name = button && button.querySelector('.council-archive-name');
    const count = button && button.querySelector('.council-archive-count');
    const moves = [...row.querySelectorAll('.council-record-move')];
    const buttonBox = button.getBoundingClientRect();
    const nameBox = name.getBoundingClientRect();
    const countBox = count.getBoundingClientRect();
    const room = {
      rowRight: round(row.getBoundingClientRect().right),
      limit: round(limit),
      buttonH: round(buttonBox.height),
      whiteSpace: getComputedStyle(name).whiteSpace,
      nameH: round(nameBox.height),
      lineH: round(parseFloat(getComputedStyle(name).lineHeight)),
      clipped: name.scrollWidth > name.clientWidth + 1,
      countAfterName: countBox.left >= nameBox.right - 1,
      countBeforeMoves: !moves.length || countBox.right <= moves[0].getBoundingClientRect().left + 1,
      text: button.textContent.trim().slice(0, 60),
    };
    return room;
  });
}"""


class StaticHandler(http.server.SimpleHTTPRequestHandler):
    # The archive only exists for a signed-in owner; the home/theme screens are
    # measured signed out, so each test states which session it wants.
    authenticated = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *args):  # silence the request line
        pass

    def _json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def translate_path(self, path):
        # Cache-busted asset names carry ?v=; the file on disk does not. The
        # page is served one level down like /apps/council/, so its "./static/"
        # assets arrive here as "/static/static/...".
        clean = path.split("?", 1)[0]
        if clean.startswith("/static/static/"):
            clean = "/static/" + clean[len("/static/static/"):]
        return super().translate_path(clean)

    def do_GET(self):  # noqa: N802 - the page asks who is signed in first
        path = self.path.split("?")[0]
        if path == "/api/auth/status":
            if self.authenticated:
                self._json({"ready": True, "authenticated": True,
                            "user": {"id": "usr_qa", "name": "의원"}})
            else:
                self._json({"ready": True, "authenticated": False, "user": None})
            return
        if path == "/api/projects":
            self._json({"projects": [PROJECT]})
            return
        if path == "/api/projects/%s/files" % PROJECT["id"]:
            self._json({"files": list(ARCHIVE_FILES)})
            return
        if path.startswith("/api/projects/"):
            self._json({"files": list(ARCHIVE_FILES)})
            return
        if path == "/padiem-themes.css":
            # The host sheet the deployed origin serves at the site root.
            body = THEMES.read_bytes() if THEMES.exists() else b""
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802 - the app pins or creates its one project
        path = self.path.split("?")[0]
        if path == "/api/projects":
            self._json({"project": PROJECT}, status=201)
            return
        self._json({"ok": True})


@pytest.fixture(scope="module")
def static_url():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StaticHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d/static/index.html" % server.server_port
    server.shutdown()
    thread.join(timeout=5)


def _open_screens(page, url, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector("#councilHeroTitle")
    page.wait_for_timeout(300)
    results = {"home": page.evaluate(MEASURE, {"floor": TARGET_FLOOR, "textFloor": TEXT_FLOOR})}
    page.evaluate("() => document.getElementById('councilThemeTrigger').click()")
    page.wait_for_timeout(250)
    results["theme"] = page.evaluate(MEASURE, {"floor": TARGET_FLOOR, "textFloor": TEXT_FLOOR})
    return results


def _measure_at(url, width, height):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            return _open_screens(page, url, width, height)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", PHONE_WIDTHS)
def test_no_phone_screen_sticks_out_past_the_viewport(static_url, width, height):
    for name, value in _measure_at(static_url, width, height).items():
        assert value["overflowPx"] <= 0, "%s overflows by %spx: %s" % (name, value["overflowPx"], value["wide"][:4])
        assert not value["wide"], "%s keeps an element past the viewport: %s" % (name, value["wide"][:4])


@pytest.mark.parametrize("width,height", PHONE_WIDTHS)
def test_every_phone_press_target_reaches_44px(static_url, width, height):
    for name, value in _measure_at(static_url, width, height).items():
        assert not value["taps"], "%s keeps a target under 44px: %s" % (name, value["taps"][:6])


@pytest.mark.parametrize("width,height", PHONE_WIDTHS)
def test_every_phone_text_reaches_14px(static_url, width, height):
    for name, value in _measure_at(static_url, width, height).items():
        assert not value["fonts"], "%s keeps text under 14px: %s" % (name, value["fonts"][:6])


def test_the_desktop_keeps_its_measured_values(static_url):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": DESKTOP_WIDTH, "height": 900})
        try:
            page.goto(static_url, wait_until="domcontentloaded")
            page.wait_for_selector("#councilHeroTitle")
            page.wait_for_timeout(300)
            value = page.evaluate(DESKTOP_PROBE)
        finally:
            browser.close()
    # Measured on main before the phone pass; the phone block must not move
    # any of these.
    assert value["eyebrow"] == 11.5
    assert value["worksEyebrow"] == 11.5
    assert value["cardButton"] == 13.5
    assert value["cardTitle"] == 20
    assert value["heroTitle"] == 44
    assert value["body"] == 16
    assert value["scrollWidth"] <= DESKTOP_WIDTH
    # The skip link width depends on font rasterisation (87px locally, 88px on the
    # CI runner); allow 2px, keep the height exact.
    assert abs(value["skip"][0] - 87) <= 2 and value["skip"][1] == 26, value["skip"]


def _archive_rows(url, width, height):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": width, "height": height})
        try:
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_selector("#councilHeroTitle")
            page.evaluate(
                "() => document.querySelector('#council-meeting .council-card-select').click()")
            page.wait_for_selector(".council-archive-item", timeout=15000)
            page.wait_for_timeout(400)
            return page.evaluate(ARCHIVE_ROW)
        finally:
            browser.close()


@pytest.mark.parametrize("width,height", PHONE_WIDTHS)
def test_the_archive_row_keeps_its_name_on_one_line(static_url, width, height):
    previous = StaticHandler.authenticated
    StaticHandler.authenticated = True
    try:
        rows = _archive_rows(static_url, width, height)
    finally:
        StaticHandler.authenticated = previous
    assert len(rows) == 3, rows
    for row in rows:
        assert row["whiteSpace"] == "nowrap", row
        assert row["nameH"] <= row["lineH"] + 1, "the name wrapped to a second line: %s" % row
        assert row["buttonH"] == 44, "the row is not one 44px line: %s" % row
        assert row["countAfterName"], "the count overlaps the name: %s" % row
        assert row["countBeforeMoves"], "the count overlaps the move buttons: %s" % row
        assert row["rowRight"] <= row["limit"] + 1, "the row spills past the archive: %s" % row
    clipped = [row["clipped"] for row in rows]
    assert clipped == [True, False, True], "long names clip, the short one does not: %s" % rows
