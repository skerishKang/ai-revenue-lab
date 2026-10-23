"""#5014: the fixed Chat/Claw composer must never cover the content above it.

Real-browser (Chromium) measurement of the actual bounding rectangles across
the desktop, tablet and mobile matrix, at 100% / 125% / 150% zoom, for both
products. It protects:

* the last conversation turn and the last home card,
* the answer error card and its retry button,
* the PC connection status cell of a Claw connection card,
* the Claw connection guidance panel's toggle and close controls,
* the shared "My computers" entry, panel and device rows,
* the task hub and the history shortcut.

The reserved space comes from the measured `--padiem-composer-clearance`
(the composer's real height plus the software-keyboard inset); no arbitrary
pixel inset may stand in for it.
"""
from __future__ import annotations

import http.server
import json
import re
import threading
from pathlib import Path

import pytest

try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
ENDPOINT = "/api/claw/local-access/devices"

# Interactive controls that must stay operable wherever they sit.
CONTROLS = {
    "guide-toggle": "#clawDeviceGuidanceToggle",
    "guide-close": ".claw-device-guidance-close",
    "manager-toggle": "#clawDeviceManagerToggle",
    "manager-close": ".claw-device-manager-close",
    "manager-refresh": ".claw-device-manager-refresh",
    "manager-select": ".claw-device-manager-select",
    "card-connection": ".claw-home-card > .claw-connection-toggle",
    "retry-button": ".retry-button",
    "history-shortcut": "#clawPreviousConversations",
}
# Content surfaces that must be able to rest above the fixed input. They are
# measured at the end of the scroll, which is the worst case.
SURFACES = {
    "card-status": ".claw-home-card > .claw-card-status",
    "error-card": ".error-box",
    "last-card": ".starter-grid > *:last-child",
    "last-message": "#messageList > *:last-child",
}

# desktop, narrow window, tablet (landscape/portrait), mobile
VIEWPORTS = [
    (1920, 1080), (1440, 900), (1366, 768),
    (1024, 768), (920, 900), (768, 1024), (600, 900),
    (430, 932), (390, 844), (360, 800), (320, 700),
]
ZOOM_VIEWPORTS = [(1440, 900), (768, 1024), (390, 844)]


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        thread = threading.Thread(target=web.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html"
        web.shutdown()


@pytest.fixture(scope="module")
def browser():
    if sync_playwright is None:
        pytest.skip("playwright is not installed in this environment")
    with sync_playwright() as pw:
        instance = pw.chromium.launch(headless=True)
        yield instance
        instance.close()


MEASURE = """() => {
  const wrap = document.querySelector('.composer-wrap');
  const wrapRect = wrap.getBoundingClientRect();
  const root = getComputedStyle(document.documentElement);
  const out = { composer: {
      top: Math.round(wrapRect.top), bottom: Math.round(wrapRect.bottom),
      left: Math.round(wrapRect.left), right: Math.round(wrapRect.right),
      height: Math.round(wrapRect.height) },
    clearance: root.getPropertyValue('--padiem-composer-clearance').trim(),
    keyboardInset: root.getPropertyValue('--padiem-visual-keyboard-inset').trim(),
    horizontalOverflow:
      document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    controls: {}, surfaces: {} };
  const measure = (el) => {
    const style = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (style.display === 'none' || style.visibility === 'hidden' || r.width === 0) return null;
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    const reachable = Boolean(top) && (el === top || el.contains(top) || top.contains(el));
    const overlap = !(r.right <= wrapRect.left || r.left >= wrapRect.right
      || r.bottom <= wrapRect.top || r.top >= wrapRect.bottom);
    return { top: Math.round(r.top), bottom: Math.round(r.bottom),
             left: Math.round(r.left), right: Math.round(r.right),
             overlap, reachable, insideComposer: wrap.contains(el),
             coveredBy: top ? (top.id || top.className || top.tagName) : null };
  };
  // The last content of the document is the worst case for the fixed input:
  // measure it at the end of the scroll.
  window.scrollTo(0, document.documentElement.scrollHeight);
  for (const [label, selector] of Object.entries(%s)) {
    const el = document.querySelector(selector);
    out.surfaces[label] = el ? measure(el) : null;
  }
  // A control must be operable wherever it sits: reveal it the way a reader
  // would, then ask the browser what is on top of it.
  for (const [label, selector] of Object.entries(%s)) {
    const el = document.querySelector(selector);
    if (!el) { out.controls[label] = null; continue; }
    el.scrollIntoView({ block: 'center', inline: 'nearest' });
    out.controls[label] = measure(el);
  }
  return out;
}""" % (json.dumps(SURFACES), json.dumps(CONTROLS))


def open_surface(page, url, product: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(900)
    page.evaluate(
        """(product) => {
          const shell = document.querySelector('.app-shell');
          const ws = document.getElementById('clawWorkspace');
          const empty = document.getElementById('emptyState');
          if (product === 'claw') {
            shell.setAttribute('data-state', 'claw');
            ws.hidden = false;
            ws.setAttribute('data-view', 'general');
            if (empty) empty.hidden = false;
          } else {
            shell.setAttribute('data-state', 'home');
            if (empty) empty.hidden = false;
          }
        }""",
        product,
    )
    page.wait_for_timeout(500)
    # Open the Claw connection guidance and the shared computer directory: the
    # two connection surfaces that used to grow over the content above them.
    page.evaluate("() => document.getElementById('clawDeviceGuidanceToggle')?.click()")
    page.wait_for_timeout(200)
    page.route(
        re.compile(r".*/api/claw/local-access/devices$"),
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({
                "ok": True, "available": True, "ownerScoped": True,
                "devices": [{
                    "deviceId": "home", "deviceName": "집 컴퓨터", "platform": "Windows",
                    "state": "CONNECTED", "usable": True,
                    "executable": True, "selectable": True,
                }],
            }, ensure_ascii=False),
        ),
    )
    page.evaluate("() => document.getElementById('clawDeviceManagerToggle')?.click()")
    page.wait_for_timeout(400)


def assert_no_overlap(measured, context: str) -> None:
    problems = []
    for label, box in (measured.get("surfaces") or {}).items():
        if not box:
            continue
        # Content must be able to rest above the fixed input at the end of the
        # scroll; that is the case a reader actually hits.
        if box["overlap"]:
            problems.append(f"surface.{label} overlaps the composer {box}")
    for label, box in (measured.get("controls") or {}).items():
        if not box:
            continue
        # A control must stay operable: nothing may sit on top of it.
        if not box["reachable"]:
            problems.append(f"control.{label} is covered by {box['coveredBy']} {box}")
    assert not problems, f"{context}: " + "; ".join(problems)


@requires_browser
@pytest.mark.parametrize("product", ["chat", "claw"])
@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_no_control_or_surface_sits_under_the_fixed_composer(browser, server, product, width, height):
    """Every viewport: nothing above the input may be covered by it."""
    page = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_surface(page, server, product)
    measured = page.evaluate(MEASURE)
    assert_no_overlap(measured, f"{product} {width}x{height}")
    assert measured["horizontalOverflow"] is False, measured
    assert not errors, errors
    page.close()


@requires_browser
@pytest.mark.parametrize("zoom", [1.25, 1.5])
@pytest.mark.parametrize("product", ["chat", "claw"])
@pytest.mark.parametrize("width,height", ZOOM_VIEWPORTS)
def test_zoomed_viewports_keep_the_same_clearance(browser, server, product, width, height, zoom):
    """125% / 150% zoom must not let the input cover the content above it."""
    page = browser.new_page(viewport={"width": width, "height": height})
    page.evaluate("(z) => { document.body.style.zoom = String(z); }", zoom)
    open_surface(page, server, product)
    measured = page.evaluate(MEASURE)
    assert_no_overlap(measured, f"{product} {width}x{height} zoom {zoom}")
    page.close()


@requires_browser
@pytest.mark.parametrize("product", ["chat", "claw"])
def test_expanded_composer_and_open_attachment_tray_reserve_their_measured_height(browser, server, product):
    """A taller composer must grow the reserved space with it."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_surface(page, server, product)
    before = page.evaluate(MEASURE)
    # Grow the composer: a long prompt, an attachment and the status row.
    page.evaluate("""() => {
      const input = document.getElementById('messageInput');
      input.value = 'a'.repeat(400);
      input.dispatchEvent(new Event('input', { bubbles: true }));
      const tray = document.getElementById('attachmentTray');
      if (tray) {
        tray.hidden = false;
        const name = document.getElementById('attachmentName');
        if (name) name.textContent = 'report.xlsx';
        const size = document.getElementById('attachmentSize');
        if (size) size.textContent = '120 KB';
      }
    }""")
    page.wait_for_timeout(500)
    after = page.evaluate(MEASURE)
    assert int(after["composer"]["height"]) > int(before["composer"]["height"]), (before, after)
    assert_no_overlap(after, f"{product} expanded composer")
    assert not errors, errors
    page.close()


@requires_browser
@pytest.mark.parametrize("product", ["chat", "claw"])
def test_a_long_answer_can_be_scrolled_above_the_composer(browser, server, product):
    """The last turn of a long answer stays reachable above the input."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    open_surface(page, server, product)
    page.evaluate("""() => {
      const list = document.getElementById('messageList');
      list.hidden = false;
      for (let index = 0; index < 6; index += 1) {
        const answer = document.createElement('article');
        answer.className = 'assistant-message';
        answer.innerHTML = '<div class="assistant-content"><p>' + 'long answer '.repeat(60) + '</p></div>';
        list.appendChild(answer);
      }
    }""")
    page.wait_for_timeout(300)
    page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
    page.wait_for_timeout(400)
    measured = page.evaluate(MEASURE)
    last = measured["surfaces"]["last-message"]
    assert last is not None, measured
    assert last["bottom"] <= measured["composer"]["top"], measured
    assert_no_overlap(measured, f"{product} long answer")
    assert not errors, errors
    page.close()


def test_the_reserved_space_is_measured_not_an_arbitrary_inset():
    """One measured clearance authority for every surface above the composer."""
    polish = (STATIC / "interaction-polish.css").read_text(encoding="utf-8")
    assert "var(--padiem-composer-clearance, 230px)" in polish
    assert "var(--padiem-visual-keyboard-inset, 0px)" in polish
    for sheet, forbidden in (
        ("claw-workspace.css", "0 280px"),
        ("claw-focus-layout.css", "max-height: calc(100dvh - 92px)"),
        ("claw-task-hub.css", "--claw-composer-clearance"),
    ):
        text = (STATIC / sheet).read_text(encoding="utf-8")
        assert forbidden not in text, f"{sheet} still pins an arbitrary inset: {forbidden}"
    # The directory panel is owned by the shared composer: it opens directly
    # above the composer area, inside the composer's width.
    manager = (STATIC / "claw-device-manager.js").read_text(encoding="utf-8")
    assert "root.append(toggle, panel)" in manager
    assert "composerColumn.insertBefore(panel, composerArea)" not in manager


WORKBENCH_BOX = """() => {
  const conv = document.querySelector('.conversation');
  const rect = conv.getBoundingClientRect();
  return {
    top: rect.top, bottom: rect.bottom, height: rect.height,
    flexBasis: getComputedStyle(conv).flexBasis,
    documentHeight: document.documentElement.scrollHeight,
    viewportHeight: window.innerHeight,
  };
}"""


def open_claw_view(page, url: str, view: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(900)
    page.evaluate(
        """(view) => {
          const shell = document.querySelector('.app-shell');
          const ws = document.getElementById('clawWorkspace');
          shell.setAttribute('data-state', 'claw');
          ws.hidden = false;
          ws.setAttribute('data-view', view);
          const form = document.getElementById('clawManualForm');
          if (form) form.hidden = view !== 'manual';
          const empty = document.getElementById('emptyState');
          if (empty) empty.hidden = true;
        }""",
        view,
    )
    page.wait_for_timeout(500)


@requires_browser
@pytest.mark.parametrize("width,height", [(1920, 1080), (1440, 900), (1024, 768), (820, 900), (390, 844)])
def test_the_claw_workbench_canvas_stays_inside_the_viewport(browser, server, width, height):
    """The workbench canvas is bounded by the column, never by its content.

    The shared .conversation rule carries a percentage flex basis. Against the
    auto-height content column that percentage cannot be resolved, so the base
    size fell back to the content height: the column grew past the viewport and
    the last turn ended below the fold, under the fixed input.
    """
    page = browser.new_page(viewport={"width": width, "height": height})
    open_claw_view(page, server, "manual")
    measured = page.evaluate(WORKBENCH_BOX)
    assert measured["documentHeight"] <= measured["viewportHeight"] + 1, measured
    assert measured["bottom"] <= measured["viewportHeight"] + 1, measured
    assert measured["flexBasis"] == "0px", measured
    page.close()


@requires_browser
@pytest.mark.parametrize("width,height", [(1440, 900), (390, 844)])
def test_the_claw_landing_keeps_scrolling_with_the_document(browser, server, width, height):
    """The first-use landing keeps its document-scrolling lane."""
    page = browser.new_page(viewport={"width": width, "height": height})
    open_claw_view(page, server, "general")
    measured = page.evaluate(WORKBENCH_BOX)
    assert measured["flexBasis"] == "0%", measured
    page.close()


def test_the_workbench_canvas_uses_a_content_independent_flex_basis():
    """The canvas base size may not follow the content height again."""
    workspace = (STATIC / "claw-workspace.css").read_text(encoding="utf-8")
    assert 'data-view="general"] ~ .conversation)) .conversation' in workspace
    assert "flex: 1 1 0;" in workspace
