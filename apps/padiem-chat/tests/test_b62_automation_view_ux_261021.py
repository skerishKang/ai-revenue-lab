"""B62 Chat/Claw — the Automation page carries one entry and honest states.

#5028 turned the Automation page into its own destination and left the
section's own header, the technical paragraphs and the permanent retry button
behind. This file pins the follow-up contract:

* the page header carries the one primary action, and the section's own
  heading is only the Claw workspace's title;
* a retry exists only while a load actually failed, and a permission refusal
  is its own state instead of a generic load error;
* the always-on technical prose is gone from the top of the page and sits with
  the thing it explains;
* the create form is opened from the visible header control and keeps the
  existing form, the existing endpoints and the existing permission checks.

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
INDEX = STATIC / "index.html"
APP_JS = STATIC / "app.js"
VIEWS_CSS = STATIC / "standalone-views.css"
LOCALE_JS = STATIC / "locale.js"

AUTH_ENDPOINT = "/api/auth/status"
RULES_ENDPOINT = "/api/claw/automation/rules"

RULES = {
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
        },
        {
            "rule_id": "r2",
            "name": "주간 판매 채널 점검",
            "schedule_expression": "daypart:monday:09:00",
            "schedule_timezone": "Asia/Seoul",
            "enabled": False,
            "state": "PAUSED",
            "target_source": "connectors",
            "output_type": "report",
            "background_eligible": True,
            "authority_status": "canonical",
        },
    ],
}

AUTH_STATE = {
    "ok": True,
    "ready": True,
    "authenticated": True,
    "user": {"name": "테스트"},
    "history_ready": True,
    "project_files_ready": True,
}


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


def _open_automation(page, server, *, rules_status: int = 200, rules_body=None) -> None:
    page.route(
        "**" + AUTH_ENDPOINT,
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(AUTH_STATE)
        ),
    )
    body = rules_body if rules_body is not None else RULES
    page.route(
        "**" + RULES_ENDPOINT,
        lambda route: route.fulfill(
            status=rules_status, content_type="application/json", body=json.dumps(body)
        ),
    )
    page.goto(server, wait_until="domcontentloaded")
    page.wait_for_timeout(1200)
    # The sidebar entry can sit outside the viewport on a narrow window, so the
    # navigation is triggered the way the app triggers it.
    page.evaluate("() => document.getElementById('automationNavButton').click()")
    page.wait_for_timeout(1200)


# ---------------------------------------------------------------------------
# Static contracts (always run)
# ---------------------------------------------------------------------------


def test_the_header_carries_the_one_primary_action() -> None:
    index = INDEX.read_text(encoding="utf-8")
    header = re.search(
        r'<div class="claw-inbox-header">(?P<body>.*?)</div>\s*</div>', index, re.S
    )
    assert header is not None, "the automation header is missing"
    body = header.group("body")
    # The primary action opens the existing create disclosure.
    assert 'id="clawAutomationCreateOpen"' in body
    assert 'aria-controls="clawAutomationCreate"' in body
    assert 'aria-expanded="false"' in body
    # The alerts entry is a secondary control, not a second primary.
    assert 'id="automationAlertsButton"' in body
    assert 'class="claw-inbox-secondary"' in body


def test_a_retry_is_not_part_of_the_permanent_header() -> None:
    index = INDEX.read_text(encoding="utf-8")
    retry = re.search(r'<button[^>]*id="clawAutomationRetry"[^>]*>', index)
    assert retry is not None, "the retry control is missing"
    assert "hidden" in retry.group(0), "the retry control is visible by default"


def test_the_always_on_technical_prose_left_the_top_of_the_page() -> None:
    index = INDEX.read_text(encoding="utf-8")
    section = re.search(
        r'<section class="claw-inbox" id="clawAutomation".*?</section>', index, re.S
    )
    assert section is not None, "the automation section is missing"
    body = section.group(0)
    # The scope note now sits inside the create form, where the create action
    # is, instead of above the rule list.
    help_at = body.find('id="clawAutomationHelp"')
    create_at = body.find('id="clawAutomationCreate"')
    assert help_at > create_at, "the scope note is not inside the create form"
    # The stored-setting legend sits with the rule rows it explains.
    note_at = body.find('id="clawAutomationSchedulerNote"')
    list_at = body.find('id="clawAutomationList"')
    assert note_at > list_at, "the rule legend is not next to the rule list"


def test_the_states_are_separate_elements() -> None:
    index = INDEX.read_text(encoding="utf-8")
    for node_id in (
        "clawAutomationLoading",
        "clawAutomationError",
        "clawAutomationForbidden",
        "clawAutomationEmpty",
    ):
        assert f'id="{node_id}"' in index, node_id
    locale = LOCALE_JS.read_text(encoding="utf-8")
    assert '"claw-automation-forbidden"' in locale
    # Both languages carry it, so the state is never shown in one language only.
    assert locale.count('"claw-automation-forbidden"') == 2


def test_the_list_load_tells_a_permission_refusal_from_a_failed_load() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    assert "setClawAutomationForbidden" in source
    assert "owner_role_required" in source
    # The retry belongs to the failure state and is hidden by the reset.
    reset = re.search(
        r"function resetClawAutomationState\(\) \{(?P<body>.*?)\n  \}", source, re.S
    )
    assert reset is not None
    assert "setClawAutomationRetryVisible(false)" in reset.group("body")
    failure = re.search(
        r"function setClawAutomationError\(\) \{(?P<body>.*?)\n  \}", source, re.S
    )
    assert failure is not None
    assert "setClawAutomationRetryVisible(true)" in failure.group("body")
    # A permission refusal offers no retry, because a retry cannot change it.
    refusal = re.search(
        r"function setClawAutomationForbidden\(\) \{(?P<body>.*?)\n  \}", source, re.S
    )
    assert refusal is not None
    assert "setClawAutomationRetryVisible(true)" not in refusal.group("body")


def test_the_page_header_owns_the_title_of_the_moved_section() -> None:
    source = APP_JS.read_text(encoding="utf-8")
    mount = re.search(
        r"function mountAutomationView\(\) \{(?P<body>.*?)\n  \}", source, re.S
    )
    assert mount is not None
    assert 'setAttribute("aria-labelledby", "automationViewTitle")' in mount.group("body")


def test_no_execution_surface_changed() -> None:
    """The rules endpoint, the store and the scheduler are untouched."""
    source = APP_JS.read_text(encoding="utf-8")
    # The page talks to exactly the endpoints it talked to before: the
    # catalogue read, the per-rule edit and the per-rule enable toggle.
    endpoints = set(
        re.findall(r"/api/claw/automation[^'\"` ]*", source)
    )
    assert endpoints == {
        "/api/claw/automation/rules",
        "/api/claw/automation/rules/${encodeURIComponent(ruleId)}",
        "/api/claw/automation/rules/${encodeURIComponent(ruleId)}/enabled",
    }, endpoints
    for forbidden in (
        "/api/claw/automation/execute",
        "scheduler_activate",
        "automation_schedules",
    ):
        assert forbidden not in source, forbidden


def test_the_page_adds_no_new_visual_language() -> None:
    css = VIEWS_CSS.read_text(encoding="utf-8")
    # The new controls use the tokens the other destinations already use.
    assert "var(--accent-strong, #2f6f99)" in css
    assert "var(--line, rgba(66, 106, 135, .28))" in css
    assert "var(--focus-ring, rgba(101, 87, 232, .24))" in css
    # The page stays inside the existing standalone-view frame.
    assert '.app-shell[data-state="automation"] #clawAutomation' in css


# ---------------------------------------------------------------------------
# Browser contracts
# ---------------------------------------------------------------------------


@requires_browser
def test_the_ready_state_shows_one_entry_and_no_retry(browser, server) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _open_automation(page, server)
    state = page.evaluate(
        """() => {
          const vis = (sel) => {
            const node = document.querySelector(sel);
            if (!node) return false;
            return getComputedStyle(node).display !== 'none'
              && node.getBoundingClientRect().height > 0;
          };
          const panel = document.getElementById('clawAutomation');
          return {
            ctaVisible: vis('#clawAutomationCreateOpen'),
            alertsVisible: vis('#automationAlertsButton'),
            retryVisible: vis('#clawAutomationRetry'),
            errorVisible: vis('#clawAutomationError'),
            forbiddenVisible: vis('#clawAutomationForbidden'),
            emptyVisible: vis('#clawAutomationEmpty'),
            rows: document.querySelectorAll('#clawAutomationList .claw-inbox-card').length,
            labelledBy: panel ? panel.getAttribute('aria-labelledby') : null,
            pageTitle: document.getElementById('automationViewTitle')?.textContent,
          };
        }"""
    )
    assert state["ctaVisible"] is True
    assert state["alertsVisible"] is True
    # No failure, so no retry.
    assert state["retryVisible"] is False
    assert state["errorVisible"] is False
    assert state["forbiddenVisible"] is False
    assert state["emptyVisible"] is False
    assert state["rows"] == 2
    # The moved section takes the visible page title as its accessible name.
    assert state["labelledBy"] == "automationViewTitle"
    assert state["pageTitle"]
    assert not errors, errors
    page.close()


@requires_browser
def test_the_primary_action_opens_the_existing_create_form(browser, server) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    _open_automation(page, server)
    assert page.evaluate("() => document.getElementById('clawAutomationCreate').open") is False
    page.evaluate("() => document.getElementById('clawAutomationCreateOpen').click()")
    page.wait_for_timeout(600)
    state = page.evaluate(
        """() => ({
          open: document.getElementById('clawAutomationCreate').open,
          expanded: document.getElementById('clawAutomationCreateOpen')
            .getAttribute('aria-expanded'),
          formVisible: document.getElementById('clawAutomationCreateForm')
            .getBoundingClientRect().height > 0,
          focusInForm: document.activeElement?.id === 'clawAutomationCreateName',
        })"""
    )
    assert state["open"] is True
    assert state["expanded"] == "true"
    assert state["formVisible"] is True
    # The existing form takes the focus, so a keyboard user lands in it.
    assert state["focusInForm"] is True
    assert not errors, errors
    page.close()


@requires_browser
def test_a_failed_load_offers_the_retry(browser, server) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    _open_automation(page, server, rules_status=503, rules_body={"ok": False})
    state = page.evaluate(
        """() => {
          const vis = (sel) => {
            const node = document.querySelector(sel);
            if (!node) return false;
            return getComputedStyle(node).display !== 'none'
              && node.getBoundingClientRect().height > 0;
          };
          return {
            errorVisible: vis('#clawAutomationError'),
            retryVisible: vis('#clawAutomationRetry'),
            forbiddenVisible: vis('#clawAutomationForbidden'),
          };
        }"""
    )
    assert state["errorVisible"] is True
    assert state["retryVisible"] is True
    assert state["forbiddenVisible"] is False
    page.close()


@requires_browser
def test_a_permission_refusal_is_its_own_state(browser, server) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    _open_automation(
        page, server, rules_status=403, rules_body={"ok": False, "code": "owner_role_required"}
    )
    state = page.evaluate(
        """() => {
          const vis = (sel) => {
            const node = document.querySelector(sel);
            if (!node) return false;
            return getComputedStyle(node).display !== 'none'
              && node.getBoundingClientRect().height > 0;
          };
          return {
            errorVisible: vis('#clawAutomationError'),
            forbiddenVisible: vis('#clawAutomationForbidden'),
            retryVisible: vis('#clawAutomationRetry'),
            rows: document.querySelectorAll('#clawAutomationList .claw-inbox-card').length,
          };
        }"""
    )
    # A permission refusal is not a failed load, and a retry would not change it.
    assert state["forbiddenVisible"] is True
    assert state["errorVisible"] is False
    assert state["retryVisible"] is False
    assert state["rows"] == 0
    page.close()


@requires_browser
def test_an_empty_list_is_not_shown_as_a_failure(browser, server) -> None:
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    _open_automation(page, server, rules_body={"ok": True, "rules": []})
    state = page.evaluate(
        """() => {
          const vis = (sel) => {
            const node = document.querySelector(sel);
            if (!node) return false;
            return getComputedStyle(node).display !== 'none'
              && node.getBoundingClientRect().height > 0;
          };
          return {
            emptyVisible: vis('#clawAutomationEmpty'),
            errorVisible: vis('#clawAutomationError'),
            retryVisible: vis('#clawAutomationRetry'),
          };
        }"""
    )
    assert state["emptyVisible"] is True
    assert state["errorVisible"] is False
    assert state["retryVisible"] is False
    page.close()
