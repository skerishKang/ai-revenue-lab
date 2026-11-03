"""북AI landing shelf — the TODAY button must appear and work under keyboard focus.

`storymemory-b61-overrides-v1.css` hides the landing-shelf controls with
`opacity:0;pointer-events:none` and revealed them only under `.library:hover`.
Neither property takes the button out of the tab order, so a keyboard user could
Tab onto a control they could not see and press Enter on something invisible.
This walks the real desktop screen with the Tab key — never `.focus()`, which
would pass without proving anything about the tab order — and pins the three
facts that make the control usable: hidden at rest, visible and hit-testable
once focused, and Enter performs the navigation.
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
    sync_playwright is None,
    reason="playwright is not installed in this environment",
)

PUBLIC = Path(__file__).resolve().parents[1] / "public"

STATE = """() => {
  const el = document.getElementById('todayEntry');
  if (!el) return null;
  const s = getComputedStyle(el);
  const r = el.getBoundingClientRect();
  const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return {
    opacity: s.opacity,
    pointerEvents: s.pointerEvents,
    focused: document.activeElement === el,
    inTabRing: document.activeElement === el,
    hitIsSelfOrChild: !!hit && (hit === el || el.contains(hit)),
    label: (el.innerText || '').replace(/\\s+/g, ' ').trim(),
  };
}"""

TODAY_ACTIVE = "() => { const s = document.querySelector('#today'); return !!s && s.classList.contains('active'); }"


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


def _tab_to(page, target_id, limit=25):
    for press in range(1, limit + 1):
        page.keyboard.press("Tab")
        if page.evaluate("() => document.activeElement && document.activeElement.id") == target_id:
            return press
    raise AssertionError(f"#{target_id} was not reachable by Tab within {limit} presses")


@pytest.mark.parametrize("width", [1440, 1000])
def test_today_button_revealed_and_pressable_by_keyboard(width, base_url):
    with sync_playwright() as pw:
        browser = _launch(pw)
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.goto(base_url, wait_until="load")
            page.wait_for_selector("#todayEntry")
            page.wait_for_timeout(500)

            # The precondition is the defect's other half: if the control were
            # already visible, this test would prove nothing about focus.
            rest = page.evaluate(STATE)
            assert rest is not None, "#todayEntry is missing from the landing shelf"
            assert rest["opacity"] == "0", f"control should be hidden at rest: {rest}"
            assert rest["pointerEvents"] == "none", f"control should be unpressable at rest: {rest}"

            presses = _tab_to(page, "todayEntry")
            # The reveal is transitioned over .2s, so a read taken the instant focus
            # lands still reports the pre-focus opacity. Wait for the transition,
            # then measure.
            page.wait_for_function(
                "() => getComputedStyle(document.getElementById('todayEntry')).opacity === '1'",
                timeout=3_000,
            )
            focused = page.evaluate(STATE)
            assert focused["focused"] is True, f"Tab did not land on the button in {presses} presses"
            assert focused["opacity"] == "1", f"focus did not reveal the button: {focused}"
            assert focused["pointerEvents"] == "auto", f"focus left the button unpressable: {focused}"
            assert focused["hitIsSelfOrChild"] is True, f"a stranger covers the focused button: {focused}"

            page.keyboard.press("Enter")
            page.wait_for_function(TODAY_ACTIVE, timeout=10_000)
            assert page.evaluate(TODAY_ACTIVE) is True, "Enter on the focused TODAY button did not open the TODAY screen"
        finally:
            browser.close()
