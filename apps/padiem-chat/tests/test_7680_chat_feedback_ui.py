"""Node-only DOM contracts: no local service, browser profile or login."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
HARNESS = Path(__file__).with_name("chat_feedback_harness.js")


@pytest.mark.parametrize("scenario", [
    "guest_and_default_consent", "submit_receipt_and_bounds", "consent_and_minimal_screen",
    "own_pagination_and_safe_text", "admin_capability_and_status", "fixed_notification_and_version_race",
    "account_switch_and_late_submit", "late_list_and_admin_role", "sanitized_errors_and_no_retry",
    "locale_focus_close_and_lifecycle", "admin_reply_and_ai_toggle", "own_reply_and_unread_notice",
    "reply_validation_and_no_values", "site_admin_sees_only_site_feedback", "usage_tab_admin_scope",
    # #7835: the '고침 알림 확인' button lives only on a '고침' row, records once,
    # and a list request that never answers must not freeze the panel.
    "fixed_ack_button_lifecycle", "read_state_survives_a_reload_and_other_statuses_have_no_button",
    "a_stalled_list_request_does_not_freeze_the_panel",
])
def test_feedback_dom_contract(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for feedback DOM contracts")
    result = subprocess.run([node, str(HARNESS), str(STATIC), scenario], capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"passed": scenario}


def test_feedback_assets_and_complete_locales():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "chat-feedback-module.js").read_text(encoding="utf-8")
    css = (STATIC / "chat-feedback.css").read_text(encoding="utf-8")
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert html.index("./auth-session.js") < html.index("./chat-feedback-module.js")
    assert 'href="./chat-feedback.css"' in html
    assert '<dialog class="feedback-dialog" id="feedbackDialog" aria-labelledby="feedbackTitle">' in html
    checkbox = re.search(r'<input id="feedbackConsent"[^>]*>', html).group()
    assert "checked" not in checkbox
    assert "chat-feedback" not in (STATIC / "app.js").read_text(encoding="utf-8")
    assert "min-height: 44px" in css and "font-size: 14px" in css
    keys = set(re.findall(r'data-locale-(?:key|aria-label)="(feedback-[a-z-]+)"', html))
    keys |= {"feedback-" + key for key in re.findall(r'copy\("([a-z-]+)"', js) if key not in ("status-", "reply-")}
    for key in keys:
        assert locale.count('"' + key + '":') == 2, key
    for status, label in (("new", "받음"), ("reviewing", "확인 중"), ("fixed", "고침"), ("deferred", "닫음")):
        assert f'"feedback-status-{status}": "{label}"' in locale
        assert f'data-locale-key="feedback-status-{status}">{label}</option>' in html
    assert '"feedback-status-fixed": "Fixed"' in locale


def test_7835_the_panel_never_stays_loading_after_a_lost_reply():
    js = (STATIC / "chat-feedback-module.js").read_text(encoding="utf-8")
    # A silent connection is bounded, and the loading flag is cleared before any
    # early return — otherwise one lost reply disables the button for good.
    assert "const REQUEST_TIMEOUT_MS = 15000;" in js
    assert "const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);" in js
    assert "finally { clearTimeout(timer);" in js
    load = js[js.index("async function load("):js.index("async function submit(")]
    assert load.index("state[loading] = false;") < load.index("if (!reply)")
    acknowledge = js[js.index("async function acknowledge("):js.index("function show(")]
    assert acknowledge.index("state.busy = false;") < acknowledge.index("if (!reply)")


def test_7835_the_button_is_bound_to_fixed_and_says_when_it_is_done():
    js = (STATIC / "chat-feedback-module.js").read_text(encoding="utf-8")
    assert 'if (item.status === "fixed") {' in js
    assert 'button(item.unread_fixed ? "acknowledge" : "acknowledged", () => void acknowledge(item))' in js
    assert "read.disabled = !item.unread_fixed || state.busy || state.ownLoading;" in js
    assert 'read.setAttribute("aria-disabled", String(read.disabled));' in js
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert '"feedback-acknowledged": "확인함"' in locale
    assert '"feedback-acknowledged": "Read"' in locale
