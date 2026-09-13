"""#2341 Task/Alert inbox UI + HTTP seam source contracts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
LOCALE = (ROOT / "static" / "locale.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "claw-workspace.css").read_text(encoding="utf-8")
SIDEBAR_CSS = (ROOT / "static" / "sidebar-utility.css").read_text(encoding="utf-8")
ROUTES = (ROOT / "app" / "claw_inbox_routes.py").read_text(encoding="utf-8")
FACTORY = (ROOT / "app" / "app_factory.py").read_text(encoding="utf-8")


def test_existing_nav_buttons_are_consumed_not_orphaned():
    assert 'id="tasksNavButton"' in INDEX
    assert 'id="alertsNavButton"' in INDEX
    assert 'getElementById("tasksNavButton")' in APP
    assert 'getElementById("alertsNavButton")' in APP
    assert 'openClawInbox("tasks")' in APP
    assert 'openClawInbox("alerts")' in APP


def test_accessible_loading_empty_error_retry_surface():
    for token in (
        'id="clawInbox"',
        'aria-live="polite"',
        'id="clawInboxLoading"',
        'id="clawInboxEmpty"',
        'id="clawInboxError"',
        'id="clawInboxRetry"',
    ):
        assert token in INDEX
    assert '"claw-inbox-loading"' in LOCALE
    assert '"claw-inbox-empty-tasks"' in LOCALE
    assert '"claw-inbox-empty-alerts"' in LOCALE
    assert '"claw-inbox-error"' in LOCALE
    assert '"retry"' in LOCALE


def test_bounded_owner_workspace_http_contract():
    assert "MAX_INBOX_HTTP_LIMIT = 50" in ROUTES
    assert "_STORE_SCAN_LIMIT = 256" in ROUTES
    assert "_require_owner(request)" in ROUTES
    assert "_resolve_memory_workspace(request, uid)" in ROUTES
    assert 'getattr(item, "member_id", None) == uid' in ROUTES
    assert "member_id=uid" in ROUTES
    assert ROUTES.count('"inbox_item_not_found"') >= 3


def test_status_update_is_bounded_to_existing_store_contract():
    assert "ClawTaskStatus(status_value)" in ROUTES
    assert "ClawAlertStatus(status_value)" in ROUTES
    assert "set_task_status" in ROUTES
    assert "set_alert_status" in ROUTES
    for forbidden in ("scheduler", "cron", "connector.write", "CREATE TABLE"):
        assert forbidden not in ROUTES


def test_factory_reuses_existing_d1_authority():
    assert "D1ClawTaskAlertStore" in FACTORY
    assert "claw_task_alert_store" in FACTORY
    assert 'Route("/api/claw/inbox/{kind}"' in FACTORY
    assert 'Route("/api/claw/inbox/{kind}/{item_id}"' in FACTORY


def test_mobile_and_theme_contracts_use_shared_tokens():
    assert "@media (max-width: 760px)" in CSS
    assert "--claw-" not in CSS.split("/* #2341 task/alert inbox */", 1)[-1]
    assert "var(--" in CSS.split("/* #2341 task/alert inbox */", 1)[-1]


def test_no_raw_locale_key_sink_for_inbox():
    assert "claw-inbox-" in LOCALE
    assert 'uiT("claw-inbox-loading")' in APP
    assert 'uiT("claw-inbox-error")' in APP
    assert "function inboxT(" not in APP
    assert ".textContent = inboxT(" not in APP


def test_sidebar_bottom_cannot_shrink_over_clickable_history_or_outputs():
    sidebar = SIDEBAR_CSS.split(".sidebar {", 1)[1].split("}", 1)[0]
    block = SIDEBAR_CSS.split(".sidebar-bottom {", 1)[1].split("}", 1)[0]
    assert "overflow-y: auto;" in sidebar
    assert "overflow-x: hidden;" in sidebar
    assert "flex: 0 0 auto;" in block
    assert "min-height: max-content;" in block


def test_auth_loss_clears_rendered_inbox_dom():
    assert "if (!authenticated) {" in APP
    assert 'document.getElementById("clawInboxList")' in APP
    assert "inboxList.replaceChildren();" in APP
    assert 'delete workspace.dataset.inboxKind;' in APP
