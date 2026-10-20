"""#5014: the fixed Chat/Claw composer must not cover the conversation surface.

The reported defect was a Windows desktop window that the representative had
narrowed: the bottom of the conversation area, the PC selection / execution
target cells and the fixed input were painted on top of each other.

The root cause is that the reserved space below the conversation was declared
in more than one place with different values, so the fixed input and the
conversation disagreed about the band they share, and the surface opened at the
top of its content instead of at the position where its last element already
clears the input.

These regressions use the EXISTING clearance contract
(`--padiem-composer-clearance`) and the EXISTING composer lane that measures
the fixed input; no new endpoint, screen, component or fixed pixel height is
introduced.
"""
from __future__ import annotations

import http.server
import re
import socketserver
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
MOTION_JS = STATIC / "conversation-motion.js"
POLISH_JS = STATIC / "interaction-polish.js"
POLISH_CSS = STATIC / "interaction-polish.css"
BRAND_CSS = STATIC / "padiem-glass-brand-polish.css"

# The representative's own window sizes: a narrowed desktop window and the
# short laptop height, plus the narrow-desktop breakpoint.
WINDOWS = ((1024, 800), (1366, 768))


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


def test_both_clearance_writers_use_the_same_floor_and_gap():
    """Two writers with different floors raced for the same custom property.

    The composer lane owns the ongoing publication and this lane publishes
    the same reservation as soon as it boots, because the composer lane is
    injected later and the stylesheet default alone does not cover a grown
    composer. The two writers therefore have to declare the same floor and
    the same gap, and this contract keeps them equal.
    """
    polish = POLISH_JS.read_text(encoding="utf-8")
    motion = MOTION_JS.read_text(encoding="utf-8")

    def constants(text: str) -> tuple[int, int]:
        floor = re.search(r"MIN_CONVERSATION_CLEARANCE\s*=\s*(\d+)", text)
        gap = re.search(r"COMPOSER_CLEARANCE_GAP\s*=\s*(\d+)", text)
        assert floor is not None and gap is not None, text[:400]
        return int(floor.group(1)), int(gap.group(1))

    assert constants(polish) == constants(motion), (constants(polish), constants(motion))
    # The reservation follows the measured composer and the keyboard inset.
    assert "var(--padiem-visual-keyboard-inset, 0px)" in POLISH_CSS.read_text(encoding="utf-8")
    assert 'setProperty("--padiem-composer-clearance"' in motion


def test_no_lane_declares_a_second_reserved_bottom_space():
    """One reservation per lane: a second copy drops the keyboard inset."""
    polish = POLISH_CSS.read_text(encoding="utf-8")
    brand = BRAND_CSS.read_text(encoding="utf-8")
    # The shared Chat/home rule owns the reserved space for both states.
    assert '.app-shell:is([data-state="home"], [data-state="chat"]) .conversation' in polish
    assert "var(--padiem-composer-clearance, 230px)" in polish
    assert "var(--padiem-visual-keyboard-inset, 0px)" in polish
    # The brand sheet may not restate the Chat reservation.
    brand_chat = re.search(
        r'\.app-shell\[data-state="chat"\] \.conversation \{[^}]*\}', brand, re.S
    )
    assert brand_chat is not None
    assert "padding-bottom" not in brand_chat.group(0), brand_chat.group(0)


def test_the_phone_landing_keeps_the_compact_first_screen():
    """The phone compaction belonged to the chat state only.

    The first screen runs in the home state, so the landing was rendered with
    the desktop card sizes and its last card row ended under the input.
    """
    polish = POLISH_CSS.read_text(encoding="utf-8")
    phone = re.search(
        r"@media \(max-width: 620px\) \{(?P<body>.*?)\n\}", polish, re.S
    )
    assert phone is not None
    body = phone.group("body")
    assert ':is([data-state="home"], [data-state="chat"])' in body
    assert "grid-template-columns: repeat(2, minmax(0, 1fr))" in body


MEASURE = """() => {
  const conv = document.querySelector('.conversation');
  const wrap = document.querySelector('.composer-wrap');
  const wrapRect = wrap.getBoundingClientRect();
  const convRect = conv.getBoundingClientRect();
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || Number(s.opacity) === 0) return false;
    if (el.closest('[hidden]')) return false;
    return true;
  };
  const overlaps = (a, b) => Boolean(a && b &&
    a.bottom > b.top + 1 && a.top < b.bottom - 1 &&
    a.right > b.left + 1 && a.left < b.right - 1);
  const nodes = [...conv.querySelectorAll('*')].filter(visible);
  const overlapping = nodes.filter((el) => overlaps(el.getBoundingClientRect(), wrapRect));
  let lowest = null;
  for (const el of nodes) {
    const r = el.getBoundingClientRect();
    if (lowest === null || r.bottom > lowest.bottom) {
      lowest = { name: String(el.className || el.tagName).slice(0, 40), bottom: r.bottom };
    }
  }
  const hero = document.querySelector('#emptyState h1');
  const heroRect = hero ? hero.getBoundingClientRect() : null;
  const isScroller = conv.scrollHeight > conv.clientHeight + 1;
  return {
    composerTop: Math.round(wrapRect.top),
    composerHeight: Math.round(wrapRect.height),
    convTop: Math.round(convRect.top),
    convBottom: Math.round(convRect.bottom),
    overlapCount: overlapping.length,
    overlapTags: [...new Set(overlapping.map((el) => el.className || el.tagName))].slice(0, 5),
    lowestBottom: lowest ? Math.round(lowest.bottom) : null,
    lowestName: lowest ? lowest.name : null,
    heroBottom: heroRect ? Math.round(heroRect.bottom) : null,
    scrollTop: isScroller ? Math.round(conv.scrollTop) : Math.round(window.scrollY),
    clearance: getComputedStyle(document.documentElement)
      .getPropertyValue('--padiem-composer-clearance').trim(),
    convPadBottom: getComputedStyle(conv).paddingBottom,
  };
}"""


@requires_browser
@pytest.mark.parametrize("width,height", WINDOWS)
def test_the_narrow_desktop_landing_opens_clear_of_the_fixed_composer(
    browser, server, width, height
):
    """The reported defect: the bottom cells sat under the fixed input.

    The surface has to OPEN with its last element already above the input, in
    the Chat first screen and in the Claw workbench, and the greeting may not
    simply scroll away.
    """
    page = browser.new_page(viewport={"width": width, "height": height})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1600)

    chat = page.evaluate(MEASURE)
    assert chat["overlapCount"] == 0, ("chat-home", chat)
    assert chat["lowestBottom"] <= chat["composerTop"], ("chat-home", chat)
    # The greeting is still on the surface, not scrolled out of the panel.
    assert chat["heroBottom"] is not None and chat["heroBottom"] > chat["convTop"], chat

    page.evaluate("""() => {
      const shell = document.querySelector('.app-shell');
      shell.dataset.state = 'claw';
      const workspace = document.getElementById('clawWorkspace');
      workspace.hidden = false;
      workspace.dataset.view = 'general';
    }""")
    page.wait_for_timeout(1200)
    claw = page.evaluate(MEASURE)
    assert claw["overlapCount"] == 0, ("claw-home", claw)
    assert claw["lowestBottom"] <= claw["composerTop"], ("claw-home", claw)
    assert claw["heroBottom"] is not None and claw["heroBottom"] > claw["convTop"], claw

    # The reserved space still tracks the measured composer.
    clearance = int(float(chat["clearance"].replace("px", "")))
    assert clearance >= chat["composerHeight"], chat
    assert int(float(chat["convPadBottom"].replace("px", ""))) >= chat["composerHeight"], chat
    assert not errors, errors
    page.close()


@requires_browser
def test_a_real_turn_stays_above_the_fixed_composer(browser, server):
    """A streamed turn is the other half of the report: the newest turn must
    not hide behind the input, and a reader who scrolled back is not dragged
    to the bottom again.
    """
    page = browser.new_page(viewport={"width": 1024, "height": 800})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    page.evaluate("""() => {
      const list = document.getElementById('messageList');
      list.hidden = false;
      const shell = document.querySelector('.app-shell');
      shell.dataset.state = 'chat';
      const empty = document.getElementById('emptyState');
      if (empty) empty.hidden = true;
      for (let i = 0; i < 6; i += 1) {
        const turn = document.createElement('div');
        turn.className = 'message assistant-message';
        turn.textContent = '답변 ' + i;
        list.appendChild(turn);
      }
    }""")
    page.wait_for_timeout(1200)
    measured = page.evaluate(MEASURE)
    assert measured["overlapCount"] == 0, measured
    assert measured["lowestBottom"] <= measured["composerTop"], measured

    # A reader who scrolls back is not forced to the bottom again.
    page.evaluate("""() => {
      const conv = document.querySelector('.conversation');
      if (conv.scrollHeight > conv.clientHeight + 1) conv.scrollTop = 0;
      else window.scrollTo(0, 0);
    }""")
    page.wait_for_timeout(400)
    before = page.evaluate("() => Math.round(window.scrollY)")
    page.evaluate("""() => {
      const list = document.getElementById('messageList');
      const turn = document.createElement('div');
      turn.className = 'message assistant-message';
      turn.textContent = '새 답변';
      list.appendChild(turn);
    }""")
    page.wait_for_timeout(800)
    after = page.evaluate("() => Math.round(window.scrollY)")
    assert after <= before + 2, (before, after)
    assert not errors, errors
    page.close()
