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


def _lifecycle_function(name: str, next_name: str) -> str:
    """The exact shipped source of one module function."""
    source = LIFECYCLE_JS.read_text(encoding="utf-8")
    start = source.index(f"  function {name}(")
    return source[start:source.index(f"  function {next_name}(", start)]


def _live_status_wording(key: str) -> str:
    """The Korean copy the shipped catalog assigns to a live status key."""
    source = LIFECYCLE_JS.read_text(encoding="utf-8")
    line = next(
        row for row in source.splitlines()
        if row.strip().startswith(f"{key}: Object.freeze(")
    )
    found = re.search(r'state: "\w+", ko: "([^"]+)", en: "[^"]+"', line)
    assert found is not None, line
    return found.group(1)


def test_a_card_refresh_renders_the_header_a_running_card_already_shows():
    """#5573 3-D-2: re-rendering the card must not blank the status it shows.

    Recording a stage or setting a hint re-renders the card. A refresh that
    carried no label and claimed live:false erased the running wording and its
    sweep mid-turn, which every plain submit and every web search hits.
    """
    refresh = _lifecycle_function("refreshTaskStatus", "terminalFor")
    plain = _lifecycle_function("renderTaskStatus", "renderCapabilityKit")
    # One derived status feeds all three header fields, so a refresh cannot
    # render a card that disagrees with itself.
    assert "const status = taskStatusFor(" in refresh, refresh
    for shared in (
        'statusLabel: status ? status.label : ""',
        'live: Boolean(status) && status.state === "active"',
    ):
        assert shared in refresh, refresh
        assert shared in plain, plain
    assert "live: false," not in refresh, refresh


def test_a_finished_turn_stops_carrying_a_live_status_hint():
    """The wording of a running turn cannot survive into a finished one."""
    status_for = _lifecycle_function("taskStatusFor", "labeledStatus")
    after_hint = status_for[status_for.index("const hint"):]
    assert "!terminalCatalog[lifecycle]" in after_hint, status_for
    # The guard sits on the hint itself, so a terminal turn cannot fall through
    # into the streaming chip either.
    assert "states.STREAMING" in after_hint, status_for
    assert after_hint.index("!terminalCatalog[lifecycle]") < after_hint.index("states.STREAMING")


def test_the_terminal_state_clears_only_this_module_s_live_wording():
    """A stage label the orchestration presentation rendered is not ours to erase."""
    source = LIFECYCLE_JS.read_text(encoding="utf-8")
    setter = source[source.index("    set(article, state) {"):source.index("    applyRuntimeLabel,")]
    assert "cardShowsLiveStatus(article)" in setter, setter
    # set() is also called on a bare article object (the shipped node contract),
    # so the card node is read the same guarded way the badge marker is.
    assert 'article.querySelector ? article.querySelector(".capability-current") : null' in setter, setter
    assert 'if (LIVE_STATUS_TEXTS.has((current.textContent || "").trim())) {' in setter, setter
    assert setter.index("LIVE_STATUS_TEXTS.has(") < setter.index('current.textContent = "";')
    assert 'current.classList?.remove?.("padiem-activity-sweep")' in setter, setter
    # The set is derived from the catalog, never hand-copied, so a live wording
    # added to the catalog is covered without a second list to forget.
    seeds = source[source.index("  const LIVE_STATUS_TEXTS"):source.index("  // The real steps of a turn")]
    assert "Object.values(taskStatusCatalog)" in seeds, seeds


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


# The plain lane, driven the way static/app.js drives it around a PC wait:
# the chip copy and the card hint are both applied, and the outcome settles
# them. The card is mounted on a real assistant article from the shipped
# template, so its meta-row chip is the real one.
ONE_STATUS_SURFACE = r"""
(runningLabel) => {
  const api = window.PadiemChatLifecycle;
  const kit = document.querySelector('.capability-kit');
  const article = kit ? kit.closest('article') : null;
  if (!article) return { error: 'no work card was rendered' };
  delete article.dataset.capabilityPreview;
  article.querySelectorAll('[data-orchestration-ui]').forEach((node) => node.remove());
  const read = () => {
    const current = article.querySelector('.capability-current');
    const chip = article.querySelector('[data-runtime-label]');
    const cardShows = Boolean(current && current.innerText.trim() && current.checkVisibility());
    const chipShows = Boolean(chip && chip.innerText.trim() && chip.checkVisibility());
    return {
      lifecycle: article.dataset.lifecycle || null,
      taskHint: article.dataset.taskHint || '',
      cardText: current ? current.innerText.trim() : '(no node)',
      cardSweep: current ? current.classList.contains('padiem-activity-sweep') : null,
      chipText: chip ? chip.innerText.trim() : '(no node)',
      chipVisible: chip ? chip.checkVisibility() : null,
      visibleSurfaces: (cardShows ? 1 : 0) + (chipShows ? 1 : 0),
    };
  };
  const out = {};
  api.recordTaskEvent(article, 'request_sent');
  api.renderTaskStatus(article);
  api.set(article, 'streaming');
  api.applyRuntimeLabel(article, runningLabel, 'status');
  api.setTaskHint(article, 'tool');
  out.running = read();
  api.renderTaskStatus(article);
  out.runningAfterRender = read();
  api.setTaskHint(article, 'tool');
  api.setTaskHint(article, null);
  api.set(article, 'completed');
  out.finished = read();
  api.setTaskHint(article, 'tool');
  out.hintAfterFinish = read();
  api.set(article, 'streaming');
  const current = article.querySelector('.capability-current');
  current.textContent = 'foreign-orchestration-stage-label';
  api.set(article, 'completed');
  out.foreignLabel = read();
  return out;
}
"""


@requires_browser
def test_a_running_pc_step_shows_once_and_leaves_nothing_when_it_ends(browser, server):
    """#5735: the observed step is visible on the one surface, then gone."""
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)

    running = _live_status_wording("tool")
    out = page.evaluate(ONE_STATUS_SURFACE, running)
    page.close()
    assert "error" not in out, out

    live = out["running"]
    assert live["lifecycle"] == "streaming", live
    assert live["cardText"] == running, live
    assert live["cardSweep"] is True, live
    # The chip carries the same fact and stays hidden while the card shows it:
    # #5559 allows exactly one visible status per turn, never two copies.
    assert live["chipText"] == running, live
    assert live["chipVisible"] is False, live
    assert live["visibleSurfaces"] == 1, live

    again = out["runningAfterRender"]
    assert again["cardText"] == running, again
    assert again["cardSweep"] is True, again
    assert again["visibleSurfaces"] == 1, again

    done = out["finished"]
    assert done["lifecycle"] == "completed", done
    assert done["cardText"] == "", done
    assert done["cardSweep"] is False, done

    late = out["hintAfterFinish"]
    assert late["taskHint"] == "tool", late
    assert late["cardText"] == "", late
    assert late["cardSweep"] is False, late

    # A stage label the orchestration presentation rendered is not this
    # module's wording, so a terminal state leaves it in place.
    foreign = out["foreignLabel"]
    assert foreign["cardText"] == "foreign-orchestration-stage-label", foreign
    assert foreign["cardSweep"] is False, foreign
    assert not errors, errors
