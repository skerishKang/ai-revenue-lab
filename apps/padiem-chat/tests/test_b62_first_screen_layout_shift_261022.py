"""#5297 first screen: the composer does not move while the first screen settles.

The composer action row is not complete at the first paint. Three things land
later and each of them used to move the composer:

  - the two voice controls, mounted into the action row by voice-composer.js
    and voice-ui-menu.js, which makes the tools row 108px narrower,
  - the tier pill, released when product-capabilities.js installs the tier
    control, and
  - the web-search control, revealed when the deployment capability arrives.

The tools row is the free space of the action row, so on a phone it is 182px
wide and it wraps. Whichever of the late arrivals crosses 182px first re-wraps
the row into a second line, the composer grows by a whole tool row, and the
settled first screen jumps. The web-search control also slides the tier pill
at every width, because it is ordered before the pill.

These regressions assert (a) the composer reserves the space of everything that
lands after the first paint, (b) the first screen does not shift while it
settles, and (c) the settled composer is the composer of today - the same
rects, the same control states.

No new component, screen, endpoint, hidden control or delay is introduced, and
the #5014 clearance contract, the #5222 selection contract and the #4379
attachment contracts are untouched by this file.
"""
from __future__ import annotations

import http.server
import json
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
PREVIEW_CSS = STATIC / "owner-model-preview.css"

# The phone and the desktop of the report.
WINDOWS = ((390, 844), (1440, 900))

# The deployment capability of the running service, and a signed-in account, so
# the late arrivals of the first screen really happen.
HEALTH = {
    "web_tools_ready": True,
    "deep_research_ready": False,
    "auth_configured": True,
    "history_store_bound": True,
    "projects_code_ready": True,
    "projects_code_store_bound": True,
    "saved_outputs_code_ready": True,
    "saved_output_store_bound": True,
}
AUTH = {
    "ready": True,
    "authenticated": True,
    "user": {"name": "Padiem Owner", "email": "owner@example.invalid"},
    "session_state": "active",
    "history_ready": True,
    "project_files_ready": True,
    "methods": {"google": True, "password": False},
}

# How long the capability takes, so the late arrival lands inside the test.
CAPABILITY_DELAY_SECONDS = 1.5

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
    ".ico": "image/x-icon",
}


def preview_rules() -> str:
    """The reservations without the comments, so a rule body is a rule body."""
    css = PREVIEW_CSS.read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


class Handler(http.server.SimpleHTTPRequestHandler):
    """The static page plus the two endpoints the first screen waits for."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/health":
            import time

            time.sleep(CAPABILITY_DELAY_SECONDS)
            return self._json(HEALTH)
        if path == "/api/auth/status":
            return self._json(AUTH)
        return super().do_GET()

    def _json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture(scope="module")
def server():
    with Server(("127.0.0.1", 0), Handler) as web:
        thread = threading.Thread(target=web.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html?theme=padiem-glass"
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


def test_the_tier_pill_keeps_its_slot_before_the_tier_control_is_installed():
    """The pill is hidden by the first-use rule until the tier control exists.

    The slot is reserved with the pill's own box, so the tier control's
    installation does not re-wrap the tools row.
    """
    css = preview_rules()
    rule = re.search(
        r"#composerForm \.composer-tools \.model-pill\s*\{(?P<body>[^}]*)\}", css
    )
    assert rule is not None, "the tier pill reservation is missing"
    body = rule.group("body")
    # The first-use rule hides the pill; the reservation keeps its box.
    assert "display: inline-flex !important" in body
    assert "visibility: hidden" in body
    assert "width: 116px" in body


def test_the_web_search_control_keeps_its_slot_before_the_capability_arrives():
    """The capability reveals the control; its slot is reserved until then."""
    css = preview_rules()
    rule = re.search(
        r"#composerForm \.composer-tools #webSearchButton\[hidden\]\s*\{(?P<body>[^}]*)\}",
        css,
    )
    assert rule is not None, "the web-search reservation is missing"
    body = rule.group("body")
    # The shared rule hides every hidden element; the reservation keeps the box.
    assert "display: inline-grid !important" in body
    assert "visibility: hidden" in body
    # The touch-target size the released control has.
    assert "width: 44px" in body
    assert "height: 44px" in body


def test_the_voice_controls_space_is_reserved_and_given_back():
    """The voice controls are mounted after the first paint.

    Their space is reserved while they are missing, and the reservation is
    given back when they are there, so the settled composer is laid out
    exactly as it is today.
    """
    css = preview_rules()
    rule = re.search(
        r"\.composer-actions:not\(:has\(> #voiceMicButton\)\):not\(:has\(> #voiceWaveformButton\)\)"
        r" #sendButton\s*\{(?P<body>[^}]*)\}",
        css,
    )
    assert rule is not None, "the voice control space reservation is missing"
    assert "margin-left" in rule.group("body")


def test_no_control_is_hidden_from_the_user_by_the_reservations():
    """A reservation is not a removal.

    The controls are hidden by the product's own rules, not by this change:
    the tier control is installed by product-capabilities.js and the
    web-search control is revealed by the deployment capability. No rule here
    may remove a control the product shows.
    """
    css = preview_rules()
    assert "display: none" not in css, "a reservation may not remove a control"
    # The pill is shown again as soon as the tier control exists.
    shown = re.search(
        r"#composerForm \.composer-tools \.model-pill\[data-mode-control=\"true\"\]\s*"
        r"\{(?P<body>[^}]*)\}",
        css,
    )
    assert shown is not None, "the tier pill is never shown again"
    assert "visibility: visible" in shown.group("body")


# ---------------------------------------------------------------------------
# Browser contracts
# ---------------------------------------------------------------------------

FIRST_SCREEN = r"""
(() => {
  window.__b = {cls: 0, entries: [], composer: [], tools: [], form: []};
  const isComposer = (node) => Boolean(node) && (
    node.id === 'composerForm' || node.id === 'messageInput' ||
    node.id === 'webSearchButton' ||
    node.classList && (node.className || '').toString().split(' ').some(
      (name) => ['composer-wrap', 'composer-tools', 'model-pill'].includes(name)));
  new PerformanceObserver((list) => {
    list.getEntries().forEach((entry) => {
      if (entry.hadRecentInput) return;
      const hits = (entry.sources || []).filter((s) => isComposer(s.node));
      if (!hits.length) return;
      window.__b.cls += entry.value;
      window.__b.entries.push(Number(entry.value.toFixed(5)));
    });
  }).observe({type: 'layout-shift', buffered: true});
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
  };
  const snap = () => {
    const wrap = document.querySelector('.composer-wrap');
    if (!wrap) return null;
    const r = wrap.getBoundingClientRect();
    if (r.height < 2) return null;
    return {
      top: Math.round(r.y),
      height: Math.round(r.height),
      tools: rect(document.querySelector('.composer-tools')),
      form: rect(document.getElementById('composerForm')),
      input: rect(document.getElementById('messageInput')),
      send: rect(document.getElementById('sendButton')),
    };
  };
  const tick = () => {
    const now = snap();
    if (now) {
      const last = window.__b.composer[window.__b.composer.length - 1];
      if (!last || last.top !== now.top || last.height !== now.height) {
        window.__b.composer.push(now);
      }
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
})()
"""


@requires_browser
@pytest.mark.parametrize("width,height", WINDOWS)
def test_the_first_screen_does_not_shift_while_it_settles(browser, server, width, height):
    """The defect itself: the composer must not move on the first screen.

    The composer is sampled every frame from the first frame to the settled
    screen, and every layout shift that touches the composer is recorded, so
    a late arrival still shows up here.
    """
    page = browser.new_page(viewport={"width": width, "height": height})
    page.add_init_script(FIRST_SCREEN)
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(int(CAPABILITY_DELAY_SECONDS * 1000) + 3000)

    state = page.evaluate("() => window.__b")
    samples = state["composer"]
    assert samples, "the composer was never sampled"
    heights = {sample["height"] for sample in samples}
    tops = {sample["top"] for sample in samples}
    assert len(heights) == 1, ("the composer height changed on the first screen", samples)
    assert len(tops) == 1, ("the composer top edge moved on the first screen", samples)
    assert state["cls"] == 0, ("composer-attributed layout shift", state, samples)
    assert not errors, errors
    page.close()


@requires_browser
def test_the_settled_composer_is_the_composer_of_today(browser, server):
    """The reservation changes the first screen, not the settled composer.

    Every control the deployment serves is in its final place and visible, and
    the composer keeps the size the settled screen has.
    """
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(int(CAPABILITY_DELAY_SECONDS * 1000) + 3000)

    state = page.evaluate(
        """() => {
          const rect = (sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
          };
          const pill = document.querySelector('.composer-tools .model-pill');
          const web = document.getElementById('webSearchButton');
          return {
            tools: rect('.composer-tools'),
            form: rect('#composerForm'),
            send: rect('#sendButton'),
            pillVisible: Boolean(pill) && getComputedStyle(pill).visibility === 'visible',
            pillModeControl: pill ? pill.getAttribute('data-mode-control') : null,
            webVisible: Boolean(web) && getComputedStyle(web).visibility === 'visible',
            webHidden: web ? web.hasAttribute('hidden') : null,
            micMounted: Boolean(document.getElementById('voiceMicButton')),
            waveMounted: Boolean(document.getElementById('voiceWaveformButton')),
          };
        }"""
    )
    # The tier control is installed and the tier pill is shown.
    assert state["pillModeControl"] == "true", state
    assert state["pillVisible"] is True, state
    # The capability arrived and the web-search control is shown.
    assert state["webHidden"] is False, state
    assert state["webVisible"] is True, state
    # The voice controls are mounted and the composer is laid out.
    assert state["micMounted"] is True, state
    assert state["waveMounted"] is True, state
    assert state["tools"] is not None and state["tools"][3] == 94, state
    assert state["form"] is not None, state
    assert not errors, errors
    page.close()
