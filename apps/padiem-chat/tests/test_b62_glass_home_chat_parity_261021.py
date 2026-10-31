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
    # #5561: this rule used to hold a third !important inset for the same element
    # (clamp(24px, 4vh, 44px), against the frame's 88px and the first screen's own
    # value), so one box had three answers and the landing and a new Chat started
    # the same empty screen 85px apart. The rule is gone, not re-tuned: the brand
    # sheet has no vertical origin for the shared panel.
    css = BRAND.read_text(encoding="utf-8")
    assert ('body .app-shell[data-state="chat"] .conversation {') not in css


# ---------------------------------------------------------------------------
# #5561: one first-screen origin, read from one token by every Glass surface
# ---------------------------------------------------------------------------

# The files that own the shipped first-screen layout. A product or a mode adding
# its own copy of the origin is what drifted the Claw brand line ~30px below the
# Chat one, invisibly: nothing compared the two products' Y coordinates.
ORIGIN_CONTRACT_FILES = (
    "padiem-first-use.css", "shared-six-panel-frame.css",
    "padiem-glass-brand-polish.css", "padiem-glass-portrait.css",
)
ORIGIN_TOKEN = "--padiem-first-screen-inset"


def test_the_first_screen_origin_is_declared_once() -> None:
    """One token holds the row the brand line and the hero start on."""
    frame = FRAME.read_text(encoding="utf-8")
    assert frame.count(f"{ORIGIN_TOKEN}:") == 1, "the token has two definitions"
    assert "max(12px, calc((100dvh - 747px) / 3))" in frame
    # The Claw hero block is 89px taller than Chat's (565px against 476px). The
    # old second constant let that content difference move the shared origin,
    # which is what the owner saw. The second expression is gone from both files.
    second_constant = "100dvh - 836px"
    assert second_constant not in frame
    assert second_constant not in FIRST_USE.read_text(encoding="utf-8")
    # Phase 2: the sheet that carried the two per-product constants no longer
    # carries a consumer rule either. The one desktop origin rule sits next to
    # the token, in the shared frame, and selects the layout variant a page opts
    # into rather than an enumeration of product states.
    first_use = FIRST_USE.read_text(encoding="utf-8")
    assert "padding-top: var(--padiem-first-screen-inset" not in first_use
    assert '.app-shell[data-layout-variant="conversation"]\n    .conversation:has(#emptyState:not([hidden]))' in frame


def test_no_glass_surface_carries_its_own_copy_of_the_origin() -> None:
    """Every first-screen inset on the shared panel reads the token.

    The scan walks innermost declaration blocks, so a duplicate hiding inside a
    media query -- which is where the phone and tablet copies lived -- is caught
    the same way as a top-level one.
    """
    offenders = []
    declaration = re.compile(r"(?:^|;)\s*padding-top\s*:")
    for name in ORIGIN_CONTRACT_FILES:
        # Comments are stripped and the property is matched as a declaration, so
        # a note about the inset or a scroll-padding-top does not read as one.
        css = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"),
                     flags=re.S)
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            if not declaration.search(body):
                continue
            # Only a rule that insets the shared panel itself owns the origin. A
            # rule reaching past it -- the continuous thread's message list, for
            # instance -- styles another element and stays that owner's business.
            tails = [part.split()[-1] for part in selector.split(",") if part.split()]
            if not any(tail.startswith(".conversation") for tail in tails):
                continue
            if f"var({ORIGIN_TOKEN}" in body:
                continue
            offenders.append((name, " ".join(selector.split())[:120],
                              " ".join(body.split())[:80]))
    assert offenders == [], offenders


def css_rules(css: str) -> list[tuple[str, str]]:
    """Innermost (selector, body) pairs of a sheet, comments removed."""
    return re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S))


def selector_tails(selector: str) -> list[str]:
    return [part.split()[-1] for part in selector.split(",") if part.split()]


def test_the_origin_is_read_only_by_the_shared_frame() -> None:
    """The inset value is defined once and one sheet is allowed to apply it.

    Phase 2 moved the consumer rule next to the definition, so the whole
    first-screen composition has one owner. A new sheet that insets the shared
    panel with its own copy of the origin is what made Home, Chat and Claw
    disagree, so this scan runs over every sheet in the app, not a list.
    """
    readers = set()
    for sheet in sorted(STATIC.glob("*.css")):
        for selector, body in css_rules(sheet.read_text(encoding="utf-8")):
            if not re.search(r"(?:^|;)\s*padding-top\s*:", body):
                continue
            if not any(tail.startswith(".conversation") for tail in selector_tails(selector)):
                continue
            if f"var({ORIGIN_TOKEN}" in body:
                readers.add(sheet.name)
    assert readers == {FRAME.name}, readers


def test_the_first_screen_layout_model_has_one_owner() -> None:
    """No product may restate the hero container's layout model.

    Claw carried `display: grid !important` for its own copy of the hero because
    the theme sheet left the block a sequence: the brand line started 7.66px
    lower in Chat at 900x900 and at 820x1180 with identical content, because a
    block puts the line on a text line box and a grid puts it in the first row.
    The shared frame declares the model once for the layout variant, so a rule
    that scopes the same declaration to one product state is the second copy.
    """
    offenders = []
    for sheet in sorted(STATIC.glob("*.css")):
        for selector, body in css_rules(sheet.read_text(encoding="utf-8")):
            if "data-state" not in selector:
                continue
            hero = any(
                tail.startswith((".empty-state", "#emptyState"))
                for tail in selector_tails(selector)
            )
            if hero and re.search(r"(?:^|;)\s*display\s*:\s*grid", body):
                offenders.append((sheet.name, " ".join(selector.split())[:120]))
    assert offenders == [], offenders


SHARED_SURFACES = (".conversation", "#emptyState", ".empty-state", ".composer-wrap",
                   ".composer", ".starter-grid", ".eyebrow")


def test_no_two_product_scopes_declare_the_same_geometry() -> None:
    """One decision, one rule -- a second sheet copying it for another product fails.

    This is the shape the owner asked to make impossible: #2594 added Claw to
    the Chat desktop breathing room by pasting the whole block again with the
    same four values, and the shared frame carried a second copy of the composer
    lane position for Claw next to the Chat one, so the next product would add a
    third. The scan strips the product scope from a selector and asks whether the
    same shape then declares the same value from a different sheet: three states
    in one rule is the correct form, two sheets for one decision is not.
    `display` is left out because hiding the conversation on the calendar,
    library and utility pages is each page's own answer, not a shared geometry.
    """
    state_scope = re.compile(r'\[data-state="[a-z]+"\]|:is\(\s*(?:\[data-state="[a-z]+"\]\s*,?\s*)+\)')
    declarations: dict[tuple[str, str, str], set[str]] = {}
    for sheet in sorted(STATIC.glob("*.css")):
        for selector, body in css_rules(sheet.read_text(encoding="utf-8")):
            if "data-state" not in selector:
                continue
            shape = " ".join(state_scope.sub("", selector).split())
            if not any(surface in shape for surface in SHARED_SURFACES):
                continue
            for declaration in body.split(";"):
                parts = declaration.split(":", 1)
                if len(parts) != 2 or not parts[0].strip():
                    continue
                prop = " ".join(parts[0].split())
                if prop == "display":
                    continue
                key = (shape, prop, " ".join(parts[1].split()))
                declarations.setdefault(key, set()).add(sheet.name)
    cross_sheet = {key: sorted(sheets) for key, sheets in declarations.items() if len(sheets) > 1}
    assert cross_sheet == {}, cross_sheet


def test_every_reachable_shell_state_declares_its_page_contract() -> None:
    """The page contract covers every state the modules can put the shell in.

    The registry is what tells the shared sheet which surface a page is, so a
    state missing from it would silently lose the first-screen geometry. The scan
    follows the assignments wherever they are written, because the workflow pages
    set their own state in their own module.
    """
    sources = "\n".join(
        (STATIC / name).read_text(encoding="utf-8")
        for name in ("app.js", "calendar.js", "library.js", "util-menu.js")
    )
    states = set(re.findall(r'shell\.dataset\.state\s*=\s*"([a-z]+)"', sources))
    assert states, "no shell state is assigned anywhere"
    registry = (STATIC / "app.js").read_text(encoding="utf-8").split("const PAGE_VIEWS", 1)[1]
    declared = set(re.findall(r'pageId: "([a-z]+)"', registry.split("];", 1)[0]))
    assert states <= declared, states - declared
    assert 'shell.dataset.layoutVariant = conversationHero ? "conversation" : page.layoutVariant' in registry
    assert "shell.dataset.pageId = page.pageId" in registry
    # The landing must carry the contract in the markup too, or the first paint
    # before app.js runs shows the hero without its origin.
    markup = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'data-layout-variant="conversation"' in markup


def test_every_page_view_reads_the_same_origin_token() -> None:
    """The five workflow pages already say they use the Chat/Claw eyebrow row."""
    css = FRAME.read_text(encoding="utf-8")
    shared = css.split(".calendar-view, .connectors-view, .library-view", 1)[1][:400]
    assert f"var({ORIGIN_TOKEN})" in shared
    # The copied expression is what made the other pages drift with the hero.
    assert "clamp(52px, 7.4vh, 88px)" not in shared


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
