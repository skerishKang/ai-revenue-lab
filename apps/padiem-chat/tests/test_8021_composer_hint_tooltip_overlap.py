"""#8021: the composer's own notice and chip never sit on the composer buttons.

Two overlaps came out of the 2026-11-19 visual audit:

- the empty-send notice (``#composerInlineHint``) was absolutely positioned
  inside the form at the tools-row height, so it rendered on top of the
  microphone/waveform/send buttons it is supposed to accompany;
- the shared chip tooltip stayed on screen after the click that triggered it,
  overlapping the input on the 390px layout.

The notice now takes its own line above the composer box and the chip closes
on a press anywhere, on focus moving away and on the first keystroke. This
suite loads the real ``static/index.html`` and measures painted boxes — it
asserts the notice and the chip stay clear of every composer button box and
that the chip actually dismisses. Skipped when Playwright is not installed,
like the other browser suites in this directory.
"""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")
from playwright.sync_api import sync_playwright  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"

SIGNED_IN = {
    "ready": True, "authenticated": True, "history_ready": True,
    "user": {"name": "Padiem", "email": "owner", "tier": "plus"},
    "model_requires_session": False,
}

THEMES = ("padiem-home", "light", "dark", "cinematic", "padiem-glass")
VIEWPORTS = ((1440, 900), (390, 844))

MEASURE = """() => {
  const rectOf = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const painted = r.width > 0 && r.height > 0 && cs.display !== 'none'
      && cs.visibility !== 'hidden';
    return {x: r.x, y: r.y, right: r.right, bottom: r.bottom,
            w: r.width, h: r.height, painted};
  };
  const hint = rectOf(document.getElementById('composerInlineHint'));
  const buttons = [...document.querySelectorAll('#composerForm button')]
    .map(rectOf).filter((b) => b && b.painted);
  const chip = rectOf(document.getElementById('padiem-shared-tooltip'));
  return {hint, buttons, chip, innerWidth: window.innerWidth,
          innerHeight: window.innerHeight};
}"""

TOOLTIP_STATE = """() => {
  const chip = document.getElementById('padiem-shared-tooltip');
  return chip ? chip.dataset.padiemTooltipState : null;
}"""


@pytest.fixture(scope="module")
def static_url():
    handler = partial(SimpleHTTPRequestHandler, directory=str(STATIC))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def _stub(page):
    def handle(route):
        url = route.request.url
        if "/api/auth/status" in url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(SIGNED_IN))
        elif "/health" in url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"status": "ok", "app": "padiem-chat",
                                           "runtime": "mock"}))
        elif any(k in url for k in ("/api/conversations", "/api/projects",
                                    "/api/connectors", "/api/claw/runs")):
            route.fulfill(status=200, content_type="application/json",
                          body='{"items":[]}')
        else:
            route.continue_()

    page.route("**/*", handle)


def _overlaps(a, b) -> bool:
    return a["x"] < b["right"] and b["x"] < a["right"] \
        and a["y"] < b["bottom"] and b["y"] < a["bottom"]


def _open(browser, static_url, width, height, theme):
    ctx = browser.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    _stub(page)
    page.goto(static_url + "/?theme=" + theme, wait_until="domcontentloaded",
              timeout=30_000)
    page.wait_for_timeout(800)
    return ctx, page


@pytest.mark.parametrize("width,height", VIEWPORTS)
@pytest.mark.parametrize("theme", THEMES)
def test_composer_notice_and_chip_stay_off_the_buttons(static_url, width, height, theme):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx, page = _open(browser, static_url, width, height, theme)

        # The empty-send notice: click send with an empty input, then measure.
        page.evaluate("document.getElementById('sendButton').click()")
        page.wait_for_timeout(150)
        state = page.evaluate(MEASURE)
        hint = state["hint"]
        assert hint and hint["painted"], (theme, width, state)
        # Its own line above the composer box, fully on screen.
        assert hint["y"] >= 0 and hint["bottom"] <= state["innerHeight"], (theme, width, hint)
        assert hint["x"] >= 0 and hint["right"] <= state["innerWidth"], (theme, width, hint)
        # No composer button box under it — the overlap that hid the message.
        covered = [b for b in state["buttons"] if _overlaps(hint, b)]
        assert covered == [], (theme, width, covered)

        # The shared chip: keyboard focus on send shows it after ~120ms.
        page.evaluate("document.getElementById('sendButton').focus()")
        page.wait_for_timeout(350)
        chip = page.evaluate(MEASURE)["chip"]
        assert chip and chip["painted"], (theme, width, state)
        assert page.evaluate(TOOLTIP_STATE) == "visible", (theme, width)
        covered = [b for b in state["buttons"] if _overlaps(chip, b)]
        assert covered == [], (theme, width, covered)

        # The first keystroke closes it, immediately.
        page.evaluate(
            "() => document.getElementById('messageInput')"
            ".dispatchEvent(new Event('input', {bubbles: true}))"
        )
        assert page.evaluate(TOOLTIP_STATE) == "hidden", (theme, width)

        # A press anywhere outside closes a freshly shown one.
        page.evaluate(
            "() => { document.getElementById('messageInput').focus();"
            " document.getElementById('sendButton').focus(); }"
        )
        page.wait_for_timeout(350)
        assert page.evaluate(TOOLTIP_STATE) == "visible", (theme, width)
        page.evaluate(
            """() => document.body.dispatchEvent(new PointerEvent('pointerdown',
                 {bubbles: true, pointerType: 'mouse'}))"""
        )
        assert page.evaluate(TOOLTIP_STATE) == "hidden", (theme, width)

        ctx.close()
        browser.close()
