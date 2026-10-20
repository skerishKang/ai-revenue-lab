"""#5297: the first screen must not move when the composer's device band mounts.

The reported defect is the Chat/Claw first screen shifting after it appears. The
measured cause is the shared composer: `#clawDeviceManager` is the first visible
child of the fixed `.composer-wrap`, it is created by a script that runs after the
first paint, and the wrap is anchored to the bottom of the viewport, so the band
arriving pushed the whole input upward. It is the dominant layout-shift entry on
every first screen (a phone 0.01909 and a desktop 0.00476-0.00943 on the band
alone), and on a phone it was the only entry the first screen produced.

The fix reserves the band and retires the reservation the moment the real block
exists, so the settled layout keeps exactly one band and no extra height. These
regressions therefore assert (a) the reservation mirrors the mounted block's own
declared geometry, (b) the fixed input does not move while the first screen
settles, (c) the reserved band and the mounted band measure the same box, and
(d) the Claw workbench is never given a phantom band.

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
DEVICE_CSS = STATIC / "claw-device-manager.css"

# The phone landing and the narrowed desktop window from the report.
WINDOWS = ((390, 844), (1024, 800))

RESERVATION = re.compile(
    r'\.app-shell:is\(\[data-state="home"\], \[data-state="chat"\]\)\s*'
    r'\.composer-wrap:not\(:has\(> #clawDeviceManager\)\)::before \{(?P<body>[^}]*)\}'
)


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


def _declaration(body: str, property_name: str) -> str:
    found = re.search(rf"{property_name}:\s*([^;]+);", body)
    assert found is not None, body
    return " ".join(found.group(1).split())


def test_the_reservation_mirrors_the_mounted_band_geometry():
    """A reservation that drifts from the block it replaces is a new shift.

    The mounted band is the device manager root's own vertical margins around
    its toggle's touch floor, so the reservation has to declare the same values.
    """
    status = STATUS_CSS.read_text(encoding="utf-8")
    device = DEVICE_CSS.read_text(encoding="utf-8")

    rule = RESERVATION.search(status)
    assert rule is not None, "the first-screen composer band is not reserved"
    body = rule.group("body")
    assert _declaration(body, "content") == '""'
    assert _declaration(body, "display") == "block"

    toggle = re.search(r"\.claw-device-manager-toggle \{(?P<body>[^}]*)\}", device)
    mounted = re.search(r"\.claw-device-manager \{(?P<body>[^}]*)\}", device)
    assert toggle is not None and mounted is not None
    assert _declaration(body, "min-height") == _declaration(toggle.group("body"), "min-height")
    assert _declaration(body, "margin") == _declaration(mounted.group("body"), "margin")


def test_the_reservation_is_the_only_writer_of_the_composer_band():
    """A second writer with a different height becomes the next shift.

    The Claw workbench owns its own composer, so the landing reservation must be
    the single place that opens a band in the fixed wrap.
    """
    sheets = sorted(STATIC.glob("*.css"))
    writers = [
        sheet.name
        for sheet in sheets
        if re.search(r"\.composer-wrap\b[^{]*::?before", sheet.read_text(encoding="utf-8"))
    ]
    assert writers == [STATUS_CSS.name], writers
    status = STATUS_CSS.read_text(encoding="utf-8")
    # It retires through the mounted block itself, never through a timer or a delay.
    assert ":not(:has(> #clawDeviceManager))" in RESERVATION.search(status).group(0)
    assert "transition" not in RESERVATION.search(status).group("body")


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
})();"""


@requires_browser
@pytest.mark.parametrize("width,height", WINDOWS)
def test_the_fixed_input_never_moves_while_the_first_screen_settles(
    browser, server, width, height
):
    """The defect itself: the bottom-anchored input jumped up when the band arrived.

    The wrap height and its top edge are sampled every frame from the first
    frame to the settled screen, so a single late band still shows up here.
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
    # The band is mounted by the time the screen settles, so this is the settled
    # layout being compared, not an empty one.
    assert samples[-1]["band"] is True, samples
    heights = {sample["height"] for sample in samples}
    tops = {sample["top"] for sample in samples}
    assert len(heights) == 1, ("the composer height changed on the first screen", samples)
    assert len(tops) == 1, ("the composer top edge moved on the first screen", samples)
    assert state["shifts"] == 0, ("band-attributed layout shift", state, samples)
    # The reservation is in effect at the frame that shows the landing, before
    # the mount, and is gone on the frame that shows the mounted band.
    pre = [sample for sample in samples if not sample["band"]]
    if pre:
        assert all(sample["reserved"] > 0 for sample in pre), pre
        assert all(sample["height"] == samples[-1]["height"] for sample in pre), samples
    assert samples[-1]["reserved"] == 0, samples
    assert not errors, errors
    page.close()


@requires_browser
def test_the_reserved_band_and_the_mounted_band_are_the_same_box(browser, server):
    """Proves the reservation is live and exactly sized, not inert CSS.

    With the real band removed, the retired-reservation path must reproduce the
    mounted height to the pixel; a rule that never matched, or one that reserved
    a different height, fails here instead of passing on the source text.
    """
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.add_init_script(FIRST_SCREEN)
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    with_band = page.evaluate("() => window.__sample()")
    assert with_band["band"] is True, with_band

    page.evaluate("""() => {
      const band = document.getElementById("clawDeviceManager");
      band.remove();
    }""")
    page.wait_for_timeout(500)
    reserved = page.evaluate("() => window.__sample()")
    assert reserved["band"] is False, reserved
    assert reserved["reserved"] == 44, reserved
    assert reserved["height"] == with_band["height"], (with_band, reserved)
    assert reserved["top"] == with_band["top"], (with_band, reserved)

    # The same surface with the reservation disabled has to move, or this test
    # proves nothing about the rule it claims to check.
    page.add_style_tag(content="""
      .app-shell:is([data-state="home"], [data-state="chat"])
        .composer-wrap:not(:has(> #clawDeviceManager))::before {
        content: none !important;
        min-height: 0 !important;
        margin: 0 !important;
      }
    """)
    page.wait_for_timeout(500)
    unreserved = page.evaluate("() => window.__sample()")
    assert unreserved["height"] < with_band["height"], (with_band, unreserved)
    page.close()
