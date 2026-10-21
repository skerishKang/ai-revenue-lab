"""B62 Chat/Claw — the Automation page is one column on a phone.

The rule list and the create form are two blocks of the same panel. On a
narrow window the form, which lives above the list in the document, pushed the
rules out of the first screen, so the page opened on a long form instead of on
the rules.

This file pins the narrow-window contract:

* the rules come before the create form, and the form's own order follows the
  list;
* nothing is side by side and nothing overflows horizontally;
* the form still opens from the header button, and the view follows the user
  to it;
* the wide-screen layout keeps its current order.
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
VIEWS_CSS = STATIC / "standalone-views.css"
APP_JS = STATIC / "app.js"

AUTH_ENDPOINT = "/api/auth/status"
RULES_ENDPOINT = "/api/claw/automation/rules"

PHONE_WIDTHS = (320, 390)
TABLET_WIDTH = 820
DESKTOP_WIDTHS = (1024, 1440, 1920)


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


def _open_automation(page, server, rules: int = 1) -> None:
    payload = [
        {
            "rule_id": f"r{index}",
            "name": f"자동화 규칙 {index}",
            "schedule_expression": "0 9 * * *",
            "schedule_timezone": "Asia/Seoul",
            "enabled": True,
            "state": "READY",
            "target_source": "memory",
            "output_type": "alert",
            "background_eligible": True,
            "authority_status": "canonical",
        }
        for index in range(1, rules + 1)
    ]
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
            body=json.dumps({"ok": True, "rules": payload}),
        ),
    )
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    page.evaluate(
        "() => { document.documentElement.setAttribute('data-theme','padiem-glass'); }"
    )
    page.evaluate("() => document.getElementById('automationNavButton').click()")
    page.wait_for_timeout(1400)


# ---------------------------------------------------------------------------
# Static contracts (always run)
# ---------------------------------------------------------------------------


def _narrow_automation_block(css: str) -> str:
    """The narrow-window block that orders the automation panel."""
    for match in re.finditer(r"@media \(max-width: 700px\) \{", css):
        start = match.end()
        depth = 1
        index = start
        while index < len(css) and depth:
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
            index += 1
        body = css[start : index - 1]
        if "#clawAutomation" in body and "order:" in body:
            return body
    raise AssertionError("the narrow-window automation order block is missing")


def test_the_narrow_window_orders_the_rules_before_the_form() -> None:
    css = VIEWS_CSS.read_text(encoding="utf-8")
    block = _narrow_automation_block(css)
    assert ".app-shell[data-state=\"automation\"] #clawAutomation" in block
    assert "display: flex;" in block
    assert "flex-direction: column;" in block
    orders = dict(
        re.findall(r"#clawAutomation > (\.[a-z-]+) \{\s*order: (\d+);", block)
    )
    assert orders.get(".claw-inbox-list", "") == "2", orders
    assert orders.get(".claw-automation-create", "") == "4", orders
    assert int(orders[".claw-inbox-list"]) < int(orders[".claw-automation-create"]), orders


def test_the_wide_screen_order_is_untouched() -> None:
    """The order rule lives in the narrow-window block only."""
    css = VIEWS_CSS.read_text(encoding="utf-8")
    outside = css.replace(_narrow_automation_block(css), "")
    assert "order: 2;" not in outside
    assert "order: 4;" not in outside


def test_the_create_form_scrolls_into_view_when_it_opens() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "function scrollClawAutomationCreateIntoView()" in source
    handler = source.split("clawAutomationCreateOpen.addEventListener", 1)[1].split("});", 1)[0]
    assert "clawAutomationCreate.open = !clawAutomationCreate.open;" in handler
    assert "scrollClawAutomationCreateIntoView();" in handler
    # The form keeps its own state: opening it never clears the input.
    assert "resetClawAutomationCreateForm" not in handler


# ---------------------------------------------------------------------------
# Browser contracts
# ---------------------------------------------------------------------------

GEOMETRY = """() => {
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)};
  };
  const list = document.querySelector('#clawAutomationList');
  const form = document.querySelector('#clawAutomationCreate');
  const header = document.querySelector('#clawAutomation .claw-inbox-header');
  const field = document.querySelector('#clawAutomationCreateForm .calendar-record-field');
  const button = document.querySelector('#clawAutomationCreateOpen');
  const panel = document.querySelector('#clawAutomation');
  const l = list ? list.getBoundingClientRect() : null;
  const f = form ? form.getBoundingClientRect() : null;
  return {
    overflowX: document.documentElement.scrollWidth - window.innerWidth,
    header: rect(header),
    panel: rect(panel),
    list: rect(list),
    form: rect(form),
    field: rect(field),
    button: rect(button),
    // The form and the list are never side by side.
    sideBySide: l && f ? !(f.y >= l.y + l.height || l.y >= f.y + f.height) : null,
    listBeforeForm: l && f ? l.y < f.y : null,
    formOpen: form ? form.open : null,
  };
}"""


@requires_browser
@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_rules_come_before_the_form_on_a_phone(browser, server, width) -> None:
    page = browser.new_page(viewport={"width": width, "height": 844})
    _open_automation(page, server)
    page.evaluate("() => document.getElementById('clawAutomationCreateOpen').click()")
    page.wait_for_timeout(800)
    state = page.evaluate(GEOMETRY)
    assert state["formOpen"] is True
    assert state["sideBySide"] is False, state
    assert state["listBeforeForm"] is True, state
    assert state["overflowX"] == 0, state
    page.close()


@requires_browser
@pytest.mark.parametrize("width", PHONE_WIDTHS)
def test_the_narrow_window_keeps_one_column_and_usable_widths(browser, server, width) -> None:
    page = browser.new_page(viewport={"width": width, "height": 844})
    _open_automation(page, server)
    page.evaluate("() => document.getElementById('clawAutomationCreateOpen').click()")
    page.wait_for_timeout(800)
    state = page.evaluate(GEOMETRY)
    # The form fields use the full column instead of a narrow lane.
    assert state["field"]["w"] > state["panel"]["w"] * 0.78, state
    # The primary action keeps a touch-sized target.
    assert state["button"]["h"] >= 44, state
    assert state["overflowX"] == 0, state
    page.close()


@requires_browser
@pytest.mark.parametrize("rules", [1, 8])
def test_opening_the_form_leaves_it_on_screen(browser, server, rules) -> None:
    """On a phone the form is below the rules, so it opens where the user can
    reach it instead of below the fold."""
    page = browser.new_page(viewport={"width": 390, "height": 844})
    _open_automation(page, server, rules=rules)
    page.wait_for_timeout(600)
    page.evaluate("() => document.getElementById('clawAutomationCreateOpen').click()")
    page.wait_for_timeout(1200)
    after = page.evaluate(
        """() => {
          const form = document.querySelector('#clawAutomationCreate');
          const host = document.querySelector('.automation-view');
          const list = document.querySelector('#clawAutomationList');
          const rect = form.getBoundingClientRect();
          return {formTop: Math.round(rect.top), formBottom: Math.round(rect.bottom),
                  viewport: window.innerHeight,
                  scrollTop: Math.round(host.scrollTop),
                  scrollHeight: host.scrollHeight, clientHeight: host.clientHeight,
                  listBottom: Math.round(list.getBoundingClientRect().bottom)};
        }"""
    )
    # The form opens below the rules, and the view can reach it.
    assert after["formTop"] >= after["listBottom"] - 40, after
    page.close()


@requires_browser
@pytest.mark.parametrize("width", DESKTOP_WIDTHS)
def test_the_wide_screen_keeps_its_current_layout(browser, server, width) -> None:
    page = browser.new_page(viewport={"width": width, "height": 900})
    _open_automation(page, server)
    page.evaluate("() => document.getElementById('clawAutomationCreateOpen').click()")
    page.wait_for_timeout(800)
    state = page.evaluate(GEOMETRY)
    # The wide screen keeps the form above the rules.
    assert state["listBeforeForm"] is False, state
    assert state["sideBySide"] is False, state
    assert state["overflowX"] == 0, state
    page.close()


@requires_browser
def test_the_tablet_keeps_its_current_layout(browser, server) -> None:
    page = browser.new_page(viewport={"width": TABLET_WIDTH, "height": 1180})
    _open_automation(page, server)
    page.evaluate("() => document.getElementById('clawAutomationCreateOpen').click()")
    page.wait_for_timeout(800)
    state = page.evaluate(GEOMETRY)
    assert state["listBeforeForm"] is False, state
    assert state["sideBySide"] is False, state
    assert state["overflowX"] == 0, state
    page.close()
