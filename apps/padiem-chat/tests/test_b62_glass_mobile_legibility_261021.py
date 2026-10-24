"""B62 Chat/Claw — the Glass theme stays legible on a narrow window.

#5505: on a phone the Glass shell portrait stands behind the whole content
column, and the theme's card surfaces are only 48% opaque there, so the
artwork showed through the cards and their text was read against the picture
instead of against a surface. The Automation page's own primary action had a
translucent accent fill that measured 3.31:1 on that card.

This file pins the contract:

* on a narrow window the Glass theme raises its own surface alpha and gives
  the standalone views the same sheet the Chat conversation already takes;
* the wide-screen composition keeps the theme's original surfaces;
* the primary action uses the shared primary tokens, so its label measures at
  least 4.5:1 against its own opaque background in every theme;
* the shell portrait keeps its reveal channel: the fade is a surface decision,
  the portrait's own opacity still belongs to the shell state machine.

The static contract tests below run everywhere (the required CI lane installs
no browser), so Playwright is optional here and only the real browser checks
are skipped when it is absent.
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
GLASS_CSS = STATIC / "padiem-glass.css"
PORTRAIT_CSS = STATIC / "padiem-glass-portrait.css"
VIEWS_CSS = STATIC / "standalone-views.css"

AUTH_ENDPOINT = "/api/auth/status"
RULES_ENDPOINT = "/api/claw/automation/rules"

PHONE_WIDTHS = (320, 390)
DESKTOP_WIDTH = 1440


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


def _open_view(page, server, *, view: str = "automation", theme: str = "padiem-glass") -> None:
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
    page.route(
        "**" + RULES_ENDPOINT,
        lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": True,
                    "rules": [
                        {
                            "rule_id": "r1",
                            "name": "매일 아침 보고서 요약",
                            "schedule_expression": "0 9 * * *",
                            "schedule_timezone": "Asia/Seoul",
                            "enabled": True,
                            "state": "READY",
                            "target_source": "memory",
                            "output_type": "alert",
                            "background_eligible": True,
                            "authority_status": "canonical",
                        }
                    ],
                }
            ),
        ),
    )
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    page.evaluate(
        "(t) => { document.documentElement.setAttribute('data-theme', t);"
        " if (document.body) document.body.setAttribute('data-theme', t); }",
        theme,
    )
    page.evaluate(
        "(id) => document.getElementById(id).click()",
        "automationNavButton" if view == "automation" else "connectorsNavButton",
    )
    page.wait_for_timeout(1200)


# ---------------------------------------------------------------------------
# Static contracts (always run)
# ---------------------------------------------------------------------------


def _alpha(text: str) -> float:
    """CSS alphas are written without the leading zero in this codebase."""
    text = text.strip()
    if text.startswith("."):
        text = "0" + text
    return float(text)


def _media_blocks(css: str) -> list[tuple[str, str]]:
    """Every @media (condition, body) pair, matched with its own braces."""
    blocks: list[tuple[str, str]] = []
    for match in re.finditer(r"@media(?P<condition>[^{]*)\{", css):
        depth = 1
        index = match.end()
        while index < len(css) and depth:
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
            index += 1
        blocks.append((match.group("condition"), css[match.end() : index - 1]))
    return blocks


def _rules(css: str) -> list[tuple[str, str]]:
    """Every (selector, declarations) pair in a flat block."""
    return [(m.group(1), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def _narrow_window_block(css: str) -> str:
    for condition, body in _media_blocks(css):
        if "max-width: 920px" in condition:
            return body
    raise AssertionError("the narrow-window block is missing")


def test_the_narrow_window_raises_the_theme_surface_alpha() -> None:
    """The cards have to stop showing the artwork through them."""
    body = _narrow_window_block(PORTRAIT_CSS.read_text(encoding="utf-8"))
    alphas: dict[str, float] = {}
    for _selector, declarations in _rules(body):
        for name in ("--card-bg", "--glass-card-surface"):
            match = re.search(
                rf"{re.escape(name)}: rgba\([^)]*?,\s*(?P<alpha>[0-9.]+)\);", declarations
            )
            if match is not None:
                alphas[name] = _alpha(match.group("alpha"))
    assert alphas.get("--card-bg", 0) >= 0.9, alphas
    assert alphas.get("--glass-card-surface", 0) >= 0.9, alphas


def test_the_standalone_views_take_a_sheet_on_a_narrow_window() -> None:
    """Their header and tagline sit straight on the page, not on a card."""
    body = _narrow_window_block(PORTRAIT_CSS.read_text(encoding="utf-8"))
    # #5028: the sheet went fully opaque so the whole standalone page family
    # (Automation, Connectors, Meeting, Library) shares one frame colour.
    opaque = None
    for selector, declarations in _rules(body):
        if ".standalone-view" not in selector:
            continue
        match = re.search(r"background: (?P<col>#f2f5f7|rgb\(242, 245, 247\)|rgba\(242, 245, 247, (?P<alpha>[0-9.]+)\));", declarations)
        if match is not None:
            col = match.group("col")
            opaque = 1.0 if (col.startswith("#") or col.startswith("rgb(")) else _alpha(match.group("alpha"))
    assert opaque is not None, "the standalone views have no narrow-window sheet"
    assert opaque >= 0.96, opaque


def test_the_wide_screen_keeps_the_theme_surfaces() -> None:
    """The desktop Glass composition is untouched."""
    css = PORTRAIT_CSS.read_text(encoding="utf-8")
    base = re.search(r"--glass-card-surface: rgba\(244, 247, 249, (?P<alpha>[0-9.]+)\);", css)
    assert base is not None
    assert _alpha(base.group("alpha")) == 0.72, base.group("alpha")
    theme = GLASS_CSS.read_text(encoding="utf-8")
    card = re.search(r"--card-bg: rgba\(239, 243, 246, (?P<alpha>[0-9.]+)\);", theme)
    assert card is not None
    assert _alpha(card.group("alpha")) == 0.48, card.group("alpha")


def test_the_shell_portrait_keeps_its_reveal_channel() -> None:
    """The portrait's opacity belongs to the shell state machine.

    The repository's own browser QA asserts that the resting shell stays at
    full opacity on a touch device, so a narrow-window treatment may not take
    that channel. The fade belongs to the surfaces instead.
    """
    for path in (GLASS_CSS, PORTRAIT_CSS):
        css = path.read_text(encoding="utf-8")
        for _condition, block in _media_blocks(css):
            for selector, declarations in _rules(block):
                if ".glass-shell-portrait" not in selector:
                    continue
                assert "opacity" not in declarations, (
                    f"{path.name} takes the shell portrait's opacity in a media query"
                )


def test_the_primary_action_uses_the_shared_primary_tokens() -> None:
    """A translucent accent fill left the label below the 4.5:1 it needs."""
    css = VIEWS_CSS.read_text(encoding="utf-8")
    primary = re.search(r"\.claw-inbox-primary \{(?P<body>.*?)\n\}", css, re.S)
    assert primary is not None
    body = primary.group("body")
    assert "background: var(--accent);" in body
    assert "color: var(--accent-contrast);" in body
    assert "rgba(121, 188, 231, .18)" not in body


# ---------------------------------------------------------------------------
# Browser contracts
# ---------------------------------------------------------------------------


CONTRAST = """() => {
  const button = document.getElementById('clawAutomationCreateOpen');
  if (!button) return null;
  const cs = getComputedStyle(button);
  const parse = (value) => {
    const parts = value.replace(/rgba?\\(/, '').replace(')', '').split(',');
    return {
      r: parseFloat(parts[0]),
      g: parseFloat(parts[1]),
      b: parseFloat(parts[2]),
      a: parts.length > 3 ? parseFloat(parts[3]) : 1,
    };
  };
  const lum = (c) => {
    const f = (v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const fg = parse(cs.color);
  const bg = parse(cs.backgroundColor);
  const l1 = lum(fg);
  const l2 = lum(bg);
  const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  return {
    ratio: Math.round(ratio * 100) / 100,
    backgroundAlpha: bg.a,
  };
}"""

SURFACES = """() => {
  const root = getComputedStyle(document.documentElement);
  const alpha = (value) => {
    const match = value.replace(/rgba?\\(/, '').replace(')', '').split(',');
    return match.length > 3 ? parseFloat(match[3]) : 1;
  };
  const view = document.querySelector('.standalone-view:not([hidden])');
  const portrait = document.querySelector('.glass-shell-portrait');
  const panel = document.querySelector('#clawAutomation');
  return {
    cardBg: alpha(root.getPropertyValue('--card-bg').trim() || 'rgba(0,0,0,0)'),
    cardSurface: alpha(root.getPropertyValue('--glass-card-surface').trim() || 'rgba(0,0,0,0)'),
    viewAlpha: view ? alpha(getComputedStyle(view).backgroundColor) : null,
    panelAlpha: panel ? alpha(getComputedStyle(panel).backgroundColor) : null,
    portraitOpacity: portrait ? parseFloat(getComputedStyle(portrait).opacity) : null,
  };
}"""


@requires_browser
@pytest.mark.parametrize("theme", ["padiem-glass", "light", "dark"])
def test_the_primary_action_meets_the_text_contrast(browser, server, theme) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844})
    _open_view(page, server, theme=theme)
    measured = page.evaluate(CONTRAST)
    assert measured is not None, "the primary action is missing"
    # The action label is 13px bold, so it is not large text: it needs 4.5:1.
    assert measured["backgroundAlpha"] == 1, (
        "the primary action fill is still translucent, so its own background "
        "is not the background the label is read against",
    )
    assert measured["ratio"] >= 4.5, measured
    page.close()


@requires_browser
@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_surfaces_hold_the_artwork_back_on_a_phone(browser, server, width) -> None:
    page = browser.new_page(viewport={"width": width, "height": 844})
    _open_view(page, server)
    state = page.evaluate(SURFACES)
    assert state["cardBg"] >= 0.9, state
    assert state["cardSurface"] >= 0.9, state
    assert state["viewAlpha"] is None or state["viewAlpha"] >= 0.85, state
    assert state["panelAlpha"] is None or state["panelAlpha"] >= 0.85, state
    page.close()


@requires_browser
def test_the_shell_keeps_its_resting_opacity_on_a_phone(browser, server) -> None:
    """The touch contract: the resting shell stays assembled and shown."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    _open_view(page, server)
    state = page.evaluate(SURFACES)
    assert state["portraitOpacity"] is not None
    assert state["portraitOpacity"] >= 0.8, state
    page.close()


@requires_browser
def test_the_wide_screen_surfaces_are_unchanged(browser, server) -> None:
    page = browser.new_page(viewport={"width": DESKTOP_WIDTH, "height": 900})
    _open_view(page, server)
    state = page.evaluate(SURFACES)
    assert state["cardBg"] == 0.48, state
    assert state["cardSurface"] == 0.72, state
    assert state["portraitOpacity"] >= 0.8, state
    page.close()


@requires_browser
def test_the_console_reports_no_error(browser, server) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _open_view(page, server)
    assert not errors, errors
    page.close()
