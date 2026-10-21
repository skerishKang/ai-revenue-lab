"""B62 Chat/Claw — the Glass theme stays legible on a narrow window.

#5485: on a phone the Glass shell portrait layer covered the whole content
column, so the standalone workspace views (Automation, Connectors) read their
text against the artwork. The artwork itself already had a narrow-window
treatment for the other instance of the same picture, and the Automation page's
own primary action used a translucent accent fill that measured 3.31:1 on the
Glass card.

This file pins the contract:

* the narrow-window treatment for the shell portrait layer exists, sits after
  the base portrait rule so it wins on source order, and keeps the artwork
  faint and pushed off-canvas;
* the wide-screen composition is untouched;
* the Automation primary action uses the shared primary tokens, so its label
  measures at least 4.5:1 against its own opaque background in every theme.

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


def _open_automation(page, server, *, theme: str = "padiem-glass") -> None:
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
    page.evaluate("() => document.getElementById('automationNavButton').click()")
    page.wait_for_timeout(1200)


# ---------------------------------------------------------------------------
# Static contracts (always run)
# ---------------------------------------------------------------------------


def test_the_shell_portrait_has_a_narrow_window_treatment() -> None:
    """The portrait layer is faint and pushed off-canvas on a narrow window."""
    css = PORTRAIT_CSS.read_text(encoding="utf-8")
    narrow = css[css.rfind("@media (max-width: 920px) {"):]
    portrait = re.search(
        r"html\[data-theme=\"padiem-glass\"\] \.glass-shell-portrait,\s*"
        r"html\[data-theme=\"padiem-glass\"\] \.glass-shell-field \{(?P<decl>.*?)\}",
        narrow,
        re.S,
    )
    assert portrait is not None, "the portrait layer has no narrow-window rule"
    decl = portrait.group("decl")
    assert "opacity: .22" in decl, "the artwork stays fully opaque on a phone"
    assert "right: -24vw" in decl, "the artwork is not pushed off-canvas"
    assert "blur(" in decl, "the artwork is not softened on a phone"


def test_the_narrow_window_rule_comes_after_the_base_portrait_rule() -> None:
    """Only a later source order can override the base portrait rule."""
    css = PORTRAIT_CSS.read_text(encoding="utf-8")
    base = css.find(
        ".glass-shell-portrait,\nhtml[data-theme=\"padiem-glass\"] .glass-shell-field {"
    )
    assert base > 0, "the base portrait rule is missing"
    narrow = css.find("@media (max-width: 920px) {", base)
    assert narrow > base, "the narrow-window rule is declared before the base rule"


def test_the_phone_treatment_is_fainter_still() -> None:
    css = PORTRAIT_CSS.read_text(encoding="utf-8")
    phone = css[css.rfind("@media (max-width: 620px) {"):]
    portrait = re.search(
        r"html\[data-theme=\"padiem-glass\"\] \.glass-shell-portrait,\s*"
        r"html\[data-theme=\"padiem-glass\"\] \.glass-shell-field \{(?P<decl>.*?)\}",
        phone,
        re.S,
    )
    assert portrait is not None, "the portrait layer has no phone rule"
    assert "opacity: .16" in portrait.group("decl")
    assert "right: -34vw" in portrait.group("decl")


def test_the_primary_action_uses_the_shared_primary_tokens() -> None:
    """A translucent accent fill left the label below the 4.5:1 it needs."""
    css = VIEWS_CSS.read_text(encoding="utf-8")
    primary = re.search(
        r"\.claw-inbox-primary \{(?P<body>.*?)\n\}", css, re.S
    )
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
    color: cs.color,
    background: cs.backgroundColor,
  };
}"""


@requires_browser
@pytest.mark.parametrize("theme", ["padiem-glass", "light", "dark"])
def test_the_primary_action_meets_the_text_contrast(browser, server, theme) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844})
    _open_automation(page, server, theme=theme)
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
def test_the_artwork_does_not_cover_the_content_column(browser, server, width) -> None:
    """On a phone the artwork is faint, so the content owns the contrast."""
    page = browser.new_page(viewport={"width": width, "height": 844})
    _open_automation(page, server)
    state = page.evaluate(
        """() => {
          const portrait = document.querySelector('.glass-shell-portrait');
          const card = document.querySelector('#clawAutomation');
          if (!portrait || !card) return null;
          const pcs = getComputedStyle(portrait);
          const cardRect = card.getBoundingClientRect();
          return {
            opacity: parseFloat(pcs.opacity),
            filter: pcs.filter,
            cardLeft: Math.round(cardRect.left),
            cardRight: Math.round(cardRect.right),
            textVisible: document.querySelector(
              '#clawAutomationList .claw-inbox-card strong') !== null,
          };
        }"""
    )
    assert state is not None
    # The artwork is a background here, not a layer on top of the content.
    assert state["opacity"] <= 0.25, state
    assert "blur(" in state["filter"], state
    assert state["textVisible"] is True, state
    page.close()


@requires_browser
def test_the_wide_screen_artwork_is_untouched(browser, server) -> None:
    """The desktop composition keeps its full artwork.

    The narrow-window rule dims the artwork to .22 and pushes it off-canvas.
    None of that may reach the wide screen, so the artwork has to stay opaque,
    pinned to the right and wide enough to read as a portrait column.
    """
    page = browser.new_page(viewport={"width": DESKTOP_WIDTH, "height": 900})
    _open_automation(page, server)
    state = page.evaluate(
        """() => {
          const portrait = document.querySelector('.glass-shell-portrait');
          if (!portrait) return null;
          const cs = getComputedStyle(portrait);
          const rect = portrait.getBoundingClientRect();
          return {
            display: cs.display,
            width: rect.width,
            opacity: parseFloat(cs.opacity),
            right: cs.right,
            filter: cs.filter,
          };
        }"""
    )
    assert state is not None
    assert state["display"] != "none", state
    assert state["opacity"] >= 0.9, state
    assert state["right"] == "0px", state
    assert state["width"] >= 400, state
    page.close()


@requires_browser
def test_the_console_reports_no_error(browser, server) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _open_automation(page, server)
    assert not errors, errors
    page.close()
