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
    "locale_focus_close_and_lifecycle",
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
    keys |= {"feedback-" + key for key in re.findall(r'copy\("([a-z-]+)"', js) if key != "status-"}
    for key in keys:
        assert locale.count('"' + key + '":') == 2, key
    for status, label in (("new", "새 의견"), ("reviewing", "확인 중"), ("fixed", "고침"), ("deferred", "보류")):
        assert f'"feedback-status-{status}": "{label}"' in locale
        assert f'data-locale-key="feedback-status-{status}">{label}</option>' in html
    assert '"feedback-status-fixed": "Fixed"' in locale
