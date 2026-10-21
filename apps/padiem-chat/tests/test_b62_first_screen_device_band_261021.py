"""#5446 follow-up of #4488: the composer shows ONE computer connection entry.

This file keeps the historical name of the #5297 regression (the first screen
device band). The band itself is gone with the duplicate entry line, so the
first-screen shift it used to cause is now guarded by "there is no band".

The Chat/Claw composer showed the computer connection state twice: a separate
entry line above the input (the device manager's own entry control) and the
small status control in the input's top-right corner. The owner's decision keeps
the small status control and removes the duplicate entry line.

This file carries the #5297 first-screen regression forward under the new
contract. The defect that file measured is still a defect: the shared composer
`#clawDeviceManager` is created by a script that runs after the first paint and
the wrap is anchored to the bottom of the viewport, so a block arriving above
the input pushes the fixed input upward. With the duplicate entry line gone the
block shows nothing, so the composer reserves nothing and the input never
moves.

These regressions assert (a) no stylesheet reserves a composer band any more,
(b) the fixed input does not move while the first screen settles, (c) the block
above the composer shows nothing, and (d) the composer's status control is the
visible entry that opens the existing management panel.

No new component, screen, endpoint or fixed pixel height is introduced, and the
#5014 clearance contract, the #5222 selection contract and the #4379 attachment
contracts are untouched by this file.
"""
from __future__ import annotations

import http.server
import re
import threading
from pathlib import Path

import pytest

# The static contract tests below must run everywhere (the required CI lane
# installs no browser), so Playwright is optional here and only the real
# browser checks are skipped when it is absent.
try:  # pragma: no cover - environment dependent
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - environment dependent
    sync_playwright = None

requires_browser = pytest.mark.skipif(
    sync_playwright is None, reason="playwright is not installed in this environment"
)

APP_ROOT = Path(__file__).resolve().parents[1]
STATIC = APP_ROOT / "static"
STATUS_CSS = STATIC / "claw-composer-connection-status.css"
STATUS_JS = STATIC / "claw-composer-connection-status.js"
DEVICE_CSS = STATIC / "claw-device-manager.css"

# The phone landing and the narrowed desktop window from the report.
WINDOWS = ((390, 844), (1024, 800))


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


# ---------------------------------------------------------------------------
# Static contracts (always run)
# ---------------------------------------------------------------------------


def test_no_stylesheet_reserves_a_composer_band_any_more():
    """The band is gone, so nothing may reserve room for it.

    A reservation that outlives the block it replaced is a layout shift and an
    empty gap above the input, so the only writer of such a reservation is
    removed and the contract is that there is none.
    """
    sheets = sorted(STATIC.glob("*.css"))
    writers = [
        sheet.name
        for sheet in sheets
        if re.search(r"\.composer-wrap\b[^{]*::?before", sheet.read_text(encoding="utf-8"))
    ]
    assert writers == [], writers


def test_the_duplicate_entry_line_is_not_shown():
    """The composer's connection entry is the small status control.

    The device manager keeps its element and its own open/close state, so the
    rule only hides the duplicate entry line. Nothing is removed from the
    document, so the panel's existing entry control keeps working.
    """
    status = STATUS_CSS.read_text(encoding="utf-8")
    assert "#clawDeviceManager > .claw-device-manager-toggle" in status
    rule = re.search(
        r"#clawDeviceManager > \.claw-device-manager-toggle \{(?P<body>[^}]*)\}", status
    )
    assert rule is not None
    assert "display: none" in rule.group("body")


def test_the_empty_block_keeps_no_margin_above_the_composer():
    """The block above the composer holds nothing, so it reserves nothing."""
    status = STATUS_CSS.read_text(encoding="utf-8")
    assert "#clawDeviceManager:not(:has(> .claw-device-manager-panel:not([hidden])))" in status
    rule = re.search(
        r"#clawDeviceManager:not\(:has\(> \.claw-device-manager-panel:not\(\[hidden\]\)\)\)"
        r" \{(?P<body>[^}]*)\}",
        status,
    )
    assert rule is not None
    body = rule.group("body")
    assert "margin-top: 0" in body
    assert "margin-bottom: 0" in body


def test_the_status_control_opens_the_existing_panel():
    """The visible entry drives the existing management panel."""
    source = STATUS_JS.read_text(encoding="utf-8")
    # The existing entry control of the existing panel is reused.
    assert 'document.getElementById("clawDeviceManagerToggle")' in source
    # The visible control carries the expanded state of the panel it opens.
    assert 'aria-expanded' in source
    assert 'aria-controls' in source
    # No second panel or screen is created here.
    assert 'createElement("section")' not in source
    assert 'createElement("aside")' not in source
    assert 'createElement("dialog")' not in source


# ---------------------------------------------------------------------------
# Browser contracts
# ---------------------------------------------------------------------------

FIRST_SCREEN = """(() => {
  window.__b = {samples: [], shifts: 0, shiftEntries: []};
  const isBand = (node) => Boolean(node) && (
    node.id === "composerForm" || node.id === "clawDeviceManager" ||
    (node.classList && (node.classList.contains("composer-wrap") ||
      node.classList.contains("claw-device-manager"))));
  new PerformanceObserver((list) => {
    list.getEntries().forEach((entry) => {
      if (entry.hadRecentInput) return;
      const hits = (entry.sources || []).filter((s) => isBand(s.node));
      if (!hits.length) return;
      window.__b.shifts += entry.value;
      window.__b.shiftEntries.push(Number(entry.value.toFixed(5)));
    });
  }).observe({type: "layout-shift", buffered: true});
  window.__sample = () => {
    const wrap = document.querySelector(".composer-wrap");
    if (!wrap) return null;
    const rect = wrap.getBoundingClientRect();
    if (rect.height < 2) return null;
    return {
      top: Math.round(rect.y),
      height: Math.round(rect.height),
      band: Boolean(document.getElementById("clawDeviceManager")),
      reserved: Math.round(parseFloat(getComputedStyle(wrap, "::before").height) || 0),
    };
  };
  const tick = () => {
    const now = window.__sample();
    if (now) {
      const last = window.__b.samples[window.__b.samples.length - 1];
      if (!last || last.top !== now.top || last.height !== now.height ||
          last.band !== now.band || last.reserved !== now.reserved) {
        window.__b.samples.push(now);
      }
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})()"""


@requires_browser
@pytest.mark.parametrize("width,height", WINDOWS)
def test_the_fixed_input_never_moves_while_the_first_screen_settles(
    browser, server, width, height
):
    """The defect itself: the bottom-anchored input must not jump.

    The wrap height and its top edge are sampled every frame from the first
    frame to the settled screen, so a late block still shows up here.
    """
    page = browser.new_page(viewport={"width": width, "height": height})
    page.add_init_script(FIRST_SCREEN)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    state = page.evaluate("() => window.__b")
    samples = state["samples"]
    assert samples, "the fixed composer was never sampled"
    # The block is mounted by the time the screen settles, so this is the
    # settled layout being compared, not an empty one.
    assert samples[-1]["band"] is True, samples
    heights = {sample["height"] for sample in samples}
    tops = {sample["top"] for sample in samples}
    assert len(heights) == 1, ("the composer height changed on the first screen", samples)
    assert len(tops) == 1, ("the composer top edge moved on the first screen", samples)
    assert state["shifts"] == 0, ("band-attributed layout shift", state, samples)
    # Nothing is reserved before or after the block arrives: there is no band
    # to reserve, so the fixed input never has to move.
    assert all(sample["reserved"] == 0 for sample in samples), samples
    assert not errors, errors
    page.close()


@requires_browser
def test_the_block_above_the_composer_shows_nothing(browser, server):
    """The duplicate entry line is gone and the block is empty above the input.

    With the real block removed the composer wrap must measure exactly the
    same, because the block reserved nothing while it was there.
    """
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.add_init_script(FIRST_SCREEN)
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    mounted = page.evaluate("() => window.__sample()")
    assert mounted["band"] is True, mounted

    # The duplicate entry line is not shown, and the block holds no height.
    assert page.locator(".claw-device-manager-toggle").is_hidden()
    assert page.locator("#clawDeviceManager").bounding_box()["height"] == 0
    # The composer's own status control is the visible entry.
    assert page.locator("#composerPcStatus").is_visible()

    page.evaluate("""() => {
      const band = document.getElementById("clawDeviceManager");
      band.remove();
    }""")
    page.wait_for_timeout(500)
    removed = page.evaluate("() => window.__sample()")
    assert removed["band"] is False, removed
    assert removed["reserved"] == 0, removed
    # Removing an empty block changes nothing, so the input cannot move.
    assert removed["height"] == mounted["height"], (mounted, removed)
    assert removed["top"] == mounted["top"], (mounted, removed)
    page.close()


@requires_browser
def test_the_status_control_opens_the_existing_panel(browser, server):
    """One click on the visible entry opens the existing management panel."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.locator("#composerPcStatus").wait_for(state="attached", timeout=15000)
    page.wait_for_timeout(400)

    page.click("#composerPcStatus")
    page.wait_for_timeout(900)
    state = page.evaluate(
        """() => {
          const panel = document.getElementById('clawDeviceManagerPanel');
          const chip = document.getElementById('composerPcStatus');
          return {
            panelVisible: panel ? !panel.hidden : false,
            chipExpanded: chip ? chip.getAttribute('aria-expanded') : null,
            chipControls: chip ? chip.getAttribute('aria-controls') : null,
            focusInsidePanel: panel && panel.contains(document.activeElement),
          };
        }"""
    )
    assert state["panelVisible"] is True
    # The visible control is the owner of the panel it opens.
    assert state["chipExpanded"] == "true"
    assert state["chipControls"] == "clawDeviceManagerPanel"
    # The focus follows the panel, so a keyboard user lands in it.
    assert state["focusInsidePanel"] is True
    assert not errors, errors

    # Closing the panel returns the focus to the visible control, because the
    # manager's own entry control is not shown any more.
    page.locator(".claw-device-manager-close").click()
    page.wait_for_timeout(400)
    closed = page.evaluate(
        """() => {
          const chip = document.getElementById('composerPcStatus');
          return {
            panelHidden: document.getElementById('clawDeviceManagerPanel').hidden,
            chipExpanded: chip.getAttribute('aria-expanded'),
            focusOnChip: document.activeElement === chip,
          };
        }"""
    )
    assert closed["panelHidden"] is True
    assert closed["chipExpanded"] == "false"
    assert closed["focusOnChip"] is True
    assert not errors, errors
    page.close()
