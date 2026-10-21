"""#5453 + #5221: the work status card is a disclosure, and the activity signal
is a sweep that only rides a real working state.

The shared "AI 작업 상태" card already carries the real orchestration stages
(the only stage vocabulary the product has). Two things were missing:

  - the card was always expanded, so a finished turn carried a full stage
    list in the message flow, and
  - a turn that was really running had no movement next to its status text.

These regressions assert (a) the card is a disclosure whose summary always
names the real current state, (b) the sweep is a shared, non-progress
animation that only rides a state the product is really in, and (c) neither
change invents a state, a phase or a measurement.

No new panel, endpoint, state store or execution engine is introduced, and the
#1817 shared capability presentation contract is untouched by this file.
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
SHARED_CSS = STATIC / "padiem-shared-ui.css"
CAPABILITY_CSS = STATIC / "capability-presentation.css"
LIFECYCLE_JS = STATIC / "message-lifecycle.js"
APP_JS = STATIC / "app.js"
B66_JS = STATIC / "b66-quote-runtime.js"

WINDOWS = ((390, 844), (1440, 900))

AUTH = {
    "ready": True,
    "authenticated": True,
    "user": {"name": "Padiem Owner", "email": "owner@example.invalid"},
    "session_state": "active",
    "history_ready": True,
    "project_files_ready": True,
    "methods": {"google": True, "password": False},
}
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


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path == "/health":
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
        yield f"http://127.0.0.1:{web.server_address[1]}/index.html?theme=padiem-glass&capability-preview=synthetic"
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


def test_the_sweep_is_a_shared_activity_signal_and_not_a_progress_bar():
    """#5453: a short bright segment travels back and forth.

    There is no measured progress behind it, so it must not look like one:
    there is no progress element, no percentage and no filling bar.
    """
    css = SHARED_CSS.read_text(encoding="utf-8")
    assert ".padiem-activity-sweep" in css
    assert "@keyframes padiem-activity-sweep" in css
    assert "prefers-reduced-motion" in css
    for forbidden in ("progressbar", "<progress", "width: 50%", "conic-gradient"):
        assert forbidden not in css, forbidden


def test_the_sweep_uses_the_existing_theme_tokens():
    """The sweep reads the same in every theme; it owns no new colour."""
    css = SHARED_CSS.read_text(encoding="utf-8")
    assert "var(--accent" in css
    assert "var(--padiem-sweep-highlight" in css


def test_the_work_card_is_a_disclosure_with_a_summary():
    """#5221: the card keeps the answer primary and opens on demand."""
    css = CAPABILITY_CSS.read_text(encoding="utf-8")
    assert ".capability-kit-disclosure" in css
    assert ".capability-kit-header" in css
    assert "::-webkit-details-marker" in css
    assert ".capability-kit-caret" in css
    assert "prefers-reduced-motion" in css

    source = LIFECYCLE_JS.read_text(encoding="utf-8")
    assert 'createElement("details")' in source
    assert 'createElement("summary")' in source
    assert 'className = "capability-kit-disclosure"' in source
    assert 'className = "capability-kit-caret"' in source


def test_the_disclosure_state_survives_a_live_stage_update():
    """A reader who opened the card does not have it closed by the next event."""
    source = LIFECYCLE_JS.read_text(encoding="utf-8")
    assert 'previousDisclosure' in source
    assert "disclosure.open = wasOpen" in source


def test_the_sweep_only_rides_a_real_working_state():
    """No invented phase, no sweep on a finished or failed turn."""
    source = LIFECYCLE_JS.read_text(encoding="utf-8")
    # The sweep rides the card's current stage only while that stage is active
    # and the run has no terminal state.
    assert 'presentation.latest.state === "active"' in source
    assert "!presentation.terminal" in source
    # The status chip carries the sweep only while the turn is really running.
    assert "article.dataset.lifecycle === states.STREAMING" in source
    # The label always names the real state; no "thinking" phase is invented.
    for forbidden in ("생각 중", "thinking", "정리 중"):
        assert forbidden not in source, forbidden


def test_the_shared_ui_file_stays_a_shared_utility():
    """The sweep is shared, so the file stays the shared utility sheet."""
    css = SHARED_CSS.read_text(encoding="utf-8")
    assert "[hidden] { display: none !important; }" in css


def test_the_claw_and_b66_statuses_sweep_only_while_they_run():
    """Chat, Claw and B66 use the same sweep, on their real states."""
    app = APP_JS.read_text(encoding="utf-8")
    assert 'classList?.toggle?.("padiem-activity-sweep", state === "running")' in app
    b66 = B66_JS.read_text(encoding="utf-8")
    assert 'classList?.toggle?.("padiem-activity-sweep", state === "working")' in b66


def test_the_live_claw_events_reach_the_shared_card():
    """The real stage events of a run reach the card, and only those."""
    app = APP_JS.read_text(encoding="utf-8")
    assert "liveOrchestrationEvents" in app
    assert "PadiemChatOrchestrationUI?.render?.(article, { events: liveOrchestrationEvents }, {})" in app


# ---------------------------------------------------------------------------
# Browser contracts
# ---------------------------------------------------------------------------

CARD_STATE = r"""
() => {
  const kit = document.querySelector('.capability-kit');
  if (!kit) return null;
  const details = kit.querySelector('.capability-kit-disclosure');
  const summary = details?.querySelector('summary');
  const stages = kit.querySelector('.capability-stage-list');
  const current = kit.querySelector('.capability-current');
  const stageBox = stages ? stages.getBoundingClientRect() : null;
  return {
    isDetails: details ? details.tagName : null,
    summaryTag: summary ? summary.tagName : null,
    open: details ? details.open : null,
    summaryText: summary ? summary.innerText.replace(/\\s+/g, ' ').trim() : '',
    stageVisible: stages ? stages.checkVisibility() : null,
    stageRows: stages ? stages.children.length : 0,
    kitHeight: kit ? Math.round(kit.getBoundingClientRect().height) : null,
    currentText: current ? current.innerText.trim() : '',
    currentSweep: current ? current.classList.contains('padiem-activity-sweep') : null,
    animation: current ? getComputedStyle(current, '::after').animationName : null,
  };
}
"""


@requires_browser
@pytest.mark.parametrize("width,height", WINDOWS)
def test_the_work_card_closes_and_opens_on_demand(browser, server, width, height):
    """The reader gets the stage list one click away, and the summary stays."""
    page = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    opened = page.evaluate(CARD_STATE)
    assert opened is not None, "the work card was not rendered"
    assert opened["isDetails"] == "DETAILS", opened
    assert opened["summaryTag"] == "SUMMARY", opened
    # The summary names the real state, never an invented phase.
    assert opened["summaryText"], opened
    assert "생각 중" not in opened["summaryText"], opened
    assert opened["stageRows"] >= 1, opened

    # The synthetic preview is a UI surface: it starts open.
    assert opened["open"] is True, opened
    assert opened["stageVisible"] is True, opened

    # The reader closes it, and the stages are really gone.
    page.evaluate("() => document.querySelectorAll('.capability-kit-disclosure').forEach((d) => { d.open = false; })")
    page.wait_for_timeout(200)
    closed = page.evaluate(CARD_STATE)
    assert closed["open"] is False, closed
    assert closed["stageVisible"] is False, closed
    assert closed["kitHeight"] < opened["kitHeight"], (opened, closed)
    # The summary is still there, with the real state.
    assert closed["summaryText"] == opened["summaryText"], (opened, closed)
    assert not errors, errors
    page.close()


@requires_browser
def test_the_sweep_moves_only_while_a_stage_is_running(browser, server):
    """The sweep is the movement of a real running stage."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    state = page.evaluate(CARD_STATE)
    assert state["currentSweep"] is True, state
    assert state["animation"] == "padiem-activity-sweep", state
    page.close()


@requires_browser
def test_a_reduced_motion_reader_gets_the_state_without_the_movement(browser, server):
    """The state is the same, the movement is not."""
    context = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    page = context.new_page()
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    state = page.evaluate(CARD_STATE)
    assert state["currentSweep"] is True, state
    assert state["animation"] == "none", state
    assert state["currentText"], state
    await_close = page.evaluate("() => document.querySelectorAll('.capability-kit-disclosure').forEach((d) => { d.open = false; })")
    assert await_close is None
    page.close()
    context.close()
