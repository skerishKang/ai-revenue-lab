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

from css_rules import declaration, rules_for_sheet  # noqa: E402

NARROW = "(max-width: 920px)"

AUTH_ENDPOINT = "/api/auth/status"
RULES_ENDPOINT = "/api/claw/automation/rules"

PHONE_WIDTHS = (320, 390)
DESKTOP_WIDTH = 1440

BOOT_READY_TIMEOUT_MS = 15_000
SURFACES_READY_TIMEOUT_MS = 10_000


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC), **kwargs)

    def log_message(self, *_args):
        pass


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # Chromium opens many resources in parallel; the default listen backlog of
    # five drops connections and leaves the page without its boot scripts.
    request_queue_size = 128


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
    page.wait_for_function(
        "() => window.PadiemAppSwitch !== undefined &&"
        " window.PadiemAuthSession?.get?.()?.authenticated === true",
        timeout=BOOT_READY_TIMEOUT_MS,
        polling=100,
    )
    page.evaluate(
        "(t) => { document.documentElement.setAttribute('data-theme', t);"
        " if (document.body) document.body.setAttribute('data-theme', t); }",
        theme,
    )
    page.evaluate(
        "(id) => document.getElementById(id).click()",
        "automationNavButton" if view == "automation" else "connectorsNavButton",
    )
    _wait_for_surfaces_ready(page)


# ---------------------------------------------------------------------------
# Static contracts (always run)
# ---------------------------------------------------------------------------


def _alpha(value: str) -> float:
    """CSS alphas are written without the leading zero in this codebase."""
    text = value.strip().rstrip(";").strip()
    if text.startswith("."):
        text = "0" + text
    return float(text)


def _rgba_alpha(value: str) -> float | None:
    match = re.search(r"rgba\([^)]*?,\s*([0-9.]+)\s*\)", value)
    return _alpha(match.group(1)) if match else None


def _rules(sheet: str, *, media: str | None = "__any__"):
    rules = rules_for_sheet(sheet)
    if media != "__any__":
        rules = [rule for rule in rules if rule.media == media]
    return rules


def test_the_narrow_window_raises_the_theme_surface_alpha() -> None:
    """The cards have to stop showing the artwork through them."""
    alphas: dict[str, float] = {}
    for rule in _rules("padiem-glass-portrait.css", media=NARROW):
        for name in ("--card-bg", "--glass-card-surface"):
            value = declaration(rule, name)
            if value is not None:
                alpha = _rgba_alpha(value)
                if alpha is not None:
                    alphas[name] = alpha
    assert alphas.get("--card-bg", 0) >= 0.9, alphas
    assert alphas.get("--glass-card-surface", 0) >= 0.9, alphas


def test_the_standalone_views_take_a_sheet_on_a_narrow_window() -> None:
    """Their header and tagline sit straight on the page, not on a card."""
    # #5028: the sheet went fully opaque so the whole standalone page family
    # (Automation, Connectors, Meeting, Library) shares one frame colour.
    opaque = None
    for rule in _rules("padiem-glass-portrait.css", media=NARROW):
        if not any(".standalone-view" in selector for selector in rule.selectors):
            continue
        value = declaration(rule, "background")
        if value is None:
            continue
        opaque = 1.0 if not value.startswith("rgba(") else _rgba_alpha(value)
    assert opaque is not None, "the standalone views have no narrow-window sheet"
    assert opaque >= 0.96, opaque


def test_the_wide_screen_keeps_the_theme_surfaces() -> None:
    """The desktop Glass composition is untouched."""
    portrait = next(
        rule
        for rule in _rules("padiem-glass-portrait.css", media=None)
        if any(selector == 'html[data-theme="padiem-glass"]' for selector in rule.selectors)
    )
    assert _rgba_alpha(declaration(portrait, "--glass-card-surface")) == 0.72
    theme = next(
        rule
        for rule in _rules("padiem-glass.css", media=None)
        if any(selector == 'html[data-theme="padiem-glass"]' for selector in rule.selectors)
    )
    assert _rgba_alpha(declaration(theme, "--card-bg")) == 0.48


def test_the_shell_portrait_keeps_its_reveal_channel() -> None:
    """The portrait's opacity belongs to the shell state machine.

    The repository's own browser QA asserts that the resting shell stays at
    full opacity on a touch device, so a narrow-window treatment may not take
    that channel. The fade belongs to the surfaces instead.
    """
    for sheet in ("padiem-glass.css", "padiem-glass-portrait.css"):
        for rule in _rules(sheet, media=NARROW):
            if not any(".glass-shell-portrait" in selector for selector in rule.selectors):
                continue
            assert declaration(rule, "opacity") is None, (
                f"{sheet} takes the shell portrait's opacity in a media query"
            )


def test_the_primary_action_uses_the_shared_primary_tokens() -> None:
    """A translucent accent fill left the label below the 4.5:1 it needs."""
    primary = next(
        rule
        for rule in _rules("standalone-views.css", media=None)
        if any(".claw-inbox-primary" in selector for selector in rule.selectors)
    )
    assert declaration(primary, "background") == "var(--accent)"
    assert declaration(primary, "color") == "var(--accent-contrast)"
    assert "rgba(121, 188, 231, .18)" not in " ".join(primary.declarations.values())


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


def _surfaces_ready_script(timeout_ms: int) -> str:
    return (
        "() => new Promise((resolve) => {\n"
        f"  const sample = {SURFACES};\n"
        f"  const deadline = performance.now() + {timeout_ms};\n"
        "  let previous = JSON.stringify(sample());\n"
        "  let settled = false;\n"
        "  const finish = (value) => { if (!settled) { settled = true; resolve(value); } };\n"
        "  const tick = () => {\n"
        "    if (settled) return;\n"
        "    const current = sample();\n"
        "    const key = JSON.stringify(current);\n"
        "    if (key === previous) { finish(current); return; }\n"
        "    previous = key;\n"
        "    if (performance.now() >= deadline) { finish(current); return; }\n"
        "    requestAnimationFrame(tick);\n"
        "  };\n"
        "  requestAnimationFrame(tick);\n"
        f"  setTimeout(() => finish(sample()), {timeout_ms + 250});\n"
        "})"
    )


def _wait_for_surfaces_ready(page) -> None:
    """Wait for the entry animations to settle instead of a fixed sleep.

    The five computed surface values are sampled once per animation frame;
    two consecutive identical samples are the readiness signal. The deadline
    is a hang guard, not the completion mechanism: if it passes, the caller
    still asserts on the last sampled values with the original thresholds.
    """
    page.evaluate(_surfaces_ready_script(SURFACES_READY_TIMEOUT_MS))


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
