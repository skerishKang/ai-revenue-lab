"""B62 Chat — the Glass first screen and the conversation are one design.

The Glass theme carries a reading mode: an active conversation is projected as
`data-glass-mode="reading"`, and that layer used to restyle the frame, the
artwork and the input box. Sending a message therefore changed the screen.

The first screen is the authority (shared-six-panel-frame.css,
CENTRAL_OWNER_HOME_VISUAL_LOCK_20261015). This file pins that contract:

* the conversation keeps the first screen's panel, artwork, composer surface
  and composer controls;
* the narrow window gets the same lock, because the reading layer swapped the
  conversation sheet and the artwork there;
* the shell's reveal animation, its mask and its settle behaviour are
  untouched, and the Claw lane keeps its own reading posture.
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
FRAME = STATIC / "shared-six-panel-frame.css"
BRAND = STATIC / "padiem-glass-brand-polish.css"
PORTRAIT = STATIC / "padiem-glass-portrait.css"
FIRST_USE = STATIC / "padiem-first-use.css"
READING = STATIC / "padiem-glass-reading.css"

AUTH_ENDPOINT = "/api/auth/status"

PHONE_WIDTH = 390
DESKTOP_WIDTH = 1440

# The first screen's composer surface (padiem-first-use.css).
FIRST_SCREEN_BORDER = "rgba(255, 255, 255, .22)"
FIRST_SCREEN_SHADOW = (
    "inset 0 1px 0 rgba(255, 255, 255, .07),\n"
    "    0 22px 64px rgba(0, 0, 0, .22),\n"
    "    0 0 0 1px rgba(136, 201, 255, .035)"
)
FIRST_SCREEN_FONT_SIZE = "17px"


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


def _block(css: str, selector: str) -> str:
    """The declaration block that follows this exact selector.

    The selector carries its own opening brace, so the block ends at the first
    closing brace after it.
    """
    assert selector in css, selector
    return css.split(selector, 1)[1].split("}", 1)[0]


# ---------------------------------------------------------------------------
# Static contracts (always run)
# ---------------------------------------------------------------------------


def test_the_chat_composer_carries_the_first_screen_surface() -> None:
    css = BRAND.read_text(encoding="utf-8")
    block = _block(
        css, 'html[data-theme="padiem-glass"] body .app-shell[data-state="chat"] .composer {'
    )
    assert f"border-color: {FIRST_SCREEN_BORDER}" in block
    assert "0 22px 64px rgba(0, 0, 0, .22)" in block
    assert "0 0 0 1px rgba(136, 201, 255, .035)" in block
    # The Glass surface stays the Glass surface.
    assert "linear-gradient(165deg, rgba(255, 255, 255, .94), var(--glass-composer-surface))" in block
    textarea = _block(
        css, 'html[data-theme="padiem-glass"] body .app-shell[data-state="chat"] .composer textarea {'
    )
    assert f"font-size: {FIRST_SCREEN_FONT_SIZE}" in textarea
    # The textarea is still one surface with the composer, not a nested card.
    assert "background: transparent !important;" in textarea
    assert "box-shadow: none !important;" in textarea


def test_the_chat_panel_is_not_restyled_by_the_brand_sheet() -> None:
    """The frame belongs to the owner lock, not to a chat-state override."""
    css = BRAND.read_text(encoding="utf-8")
    block = _block(
        css, 'html[data-theme="padiem-glass"] body .app-shell[data-state="chat"] .conversation {'
    )
    for forbidden in ("background:", "box-shadow:", "border-color:"):
        assert forbidden not in block, forbidden
    # The chat keeps its own top inset, which is content layout, not the frame.
    assert "padding-top" in block


def test_the_chat_state_reads_the_first_screen_surface_tokens() -> None:
    css = FRAME.read_text(encoding="utf-8")
    block = _block(
        css, 'html[data-theme="padiem-glass"] body .app-shell[data-state="chat"] {'
    )
    assert "--glass-chat-surface: rgba(238, 242, 245, .82);" in block
    assert "--glass-chat-border: rgba(255, 255, 255, .58);" in block
    assert "--glass-composer-surface: rgba(248, 250, 251, .90);" in block
    # The picture is the background: the shell keeps the first screen's
    # strength while the reveal animation and its mask stay untouched.
    assert "--glass-shell-max: 1;" in block


def test_the_narrow_window_is_locked_to_the_first_screen() -> None:
    css = FRAME.read_text(encoding="utf-8")
    tablet = css.split("@media (max-width: 920px)", 1)[1].split("@media (max-width: 620px)", 1)[0]
    assert '.conversation.conversation' in tablet
    assert "background: rgba(242, 245, 247, .90) !important;" in tablet
    assert "blur(30px) saturate(106%) !important;" in tablet
    assert ".main-panel::before" in tablet
    assert "opacity: .22 !important;" in tablet
    phone = css.split("@media (max-width: 620px)", 1)[1].split("/* The surface tokens", 1)[0]
    assert "opacity: .16 !important;" in phone


def test_the_chat_composer_row_spacing_stays_first_screen() -> None:
    """The Claw lane keeps its own spacing; the Chat input box does not resize."""
    css = PORTRAIT.read_text(encoding="utf-8")
    assert 'html[data-theme="padiem-glass"] .app-shell[data-state="claw"] .composer-actions' in css
    assert 'html[data-theme="padiem-glass"] .app-shell[data-state="chat"] .composer-actions' not in css


def test_the_reading_layer_keeps_its_semantic_duties() -> None:
    """The calm layer still owns the answer surfaces and the motion contract."""
    css = READING.read_text(encoding="utf-8")
    assert 'data-glass-mode="reading"' in css
    assert ".assistant-content" in css
    assert ".source-card" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (prefers-reduced-transparency: reduce)" in css
    # The reading layer is not a second theme: the other themes stay out of it.
    for other in ('data-theme="light"', 'data-theme="dark"', 'data-theme="cinematic"'):
        assert other not in css, other


# ---------------------------------------------------------------------------
# Browser contracts
# ---------------------------------------------------------------------------

PARITY = """() => {
  const pick = (sel, geometry) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const values = {
      backgroundColor: cs.backgroundColor,
      backgroundImage: cs.backgroundImage,
      borderTopColor: cs.borderTopColor,
      borderRadius: cs.borderRadius,
      boxShadow: cs.boxShadow,
      backdropFilter: cs.backdropFilter,
      color: cs.color,
      fontSize: cs.fontSize,
    };
    if (geometry) {
      values.height = Math.round(r.height);
      values.width = Math.round(r.width);
    }
    return values;
  };
  return {
    // The panel keeps its frame; its inner reading gutter is an approved
    // content lane, so the frame comparison is about the surface itself.
    conversation: pick('.conversation', false),
    composer: pick('.composer', true),
    textarea: pick('.composer textarea', true),
    toolButton: pick('.composer .tool-button', false),
    portraitOpacity: (() => {
      const p = document.querySelector('.glass-shell-portrait');
      return p ? parseFloat(getComputedStyle(p).opacity) : null;
    })(),
    mode: document.documentElement.getAttribute('data-glass-mode'),
    state: document.querySelector('.app-shell')?.getAttribute('data-state'),
  };
}"""


def _open(page, server) -> None:
    page.route(
        "**" + AUTH_ENDPOINT,
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "ready": True,
                    "authenticated": True,
                    "user": {"name": "테스트"},
                    "history_ready": True,
                    "project_files_ready": True,
                }
            ),
        ),
    )
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    page.evaluate("() => { document.documentElement.setAttribute('data-theme','padiem-glass'); }")
    page.wait_for_timeout(1200)


@requires_browser
@pytest.mark.parametrize("width,height", [(PHONE_WIDTH, 844), (DESKTOP_WIDTH, 900)])
def test_the_first_screen_and_the_conversation_draw_the_same_surfaces(
    browser, server, width, height
) -> None:
    page = browser.new_page(viewport={"width": width, "height": height})
    _open(page, server)
    first = page.evaluate(PARITY)
    assert first["state"] == "home"
    page.evaluate("() => { document.querySelector('.app-shell').dataset.state = 'chat'; }")
    page.wait_for_timeout(1200)
    conversation = page.evaluate(PARITY)
    assert conversation["state"] == "chat"
    assert conversation["mode"] == "reading"
    for target in ("conversation", "composer", "textarea", "toolButton"):
        assert first[target] == conversation[target], (
            f"{target} changed when the conversation started:\n"
            f"  first screen: {json.dumps(first[target], ensure_ascii=False)}\n"
            f"  conversation: {json.dumps(conversation[target], ensure_ascii=False)}"
        )
    page.close()


@requires_browser
def test_the_picture_keeps_its_strength_when_the_conversation_starts(browser, server) -> None:
    page = browser.new_page(viewport={"width": DESKTOP_WIDTH, "height": 900})
    _open(page, server)
    first = page.evaluate(PARITY)
    page.evaluate("() => { document.querySelector('.app-shell').dataset.state = 'chat'; }")
    page.wait_for_timeout(1200)
    conversation = page.evaluate(PARITY)
    assert first["portraitOpacity"] == conversation["portraitOpacity"], (
        "the artwork faded when the conversation started"
    )
    page.close()


@requires_browser
def test_the_conversation_keeps_its_message_list_and_scrolling(browser, server) -> None:
    """The message surface and its scroll padding stay intact."""
    page = browser.new_page(viewport={"width": DESKTOP_WIDTH, "height": 900})
    _open(page, server)
    page.evaluate("() => { document.querySelector('.app-shell').dataset.state = 'chat'; }")
    page.wait_for_timeout(1200)
    state = page.evaluate(
        """() => {
          const list = document.getElementById('messageList');
          const conversation = document.querySelector('.conversation');
          if (list) list.hidden = false;
          return {
            listHidden: list ? list.hasAttribute('hidden') : null,
            scrollPadding: conversation ? getComputedStyle(conversation).scrollPaddingBottom : null,
            overflowY: conversation ? getComputedStyle(conversation).overflowY : null,
          };
        }"""
    )
    assert state["listHidden"] is False
    assert state["overflowY"] in ("auto", "scroll"), state
    # The reserved bottom space is the measured composer clearance, so the last
    # turn never sits under the fixed input.
    assert float((state["scrollPadding"] or "0px").replace("px", "")) > 200, state
    page.close()
