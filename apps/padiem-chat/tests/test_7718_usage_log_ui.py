"""#7718 3단계 — 운영센터 '사용 일지' 탭 DOM 계약 (브라우저·서비스 불필요)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
HARNESS = Path(__file__).with_name("chat_usage_log_harness.js")


@pytest.mark.parametrize("scenario", ["default_is_empty", "fixture_injected"])
def test_usage_log_dom_contract(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for usage log DOM contracts")
    result = subprocess.run([node, str(HARNESS), str(STATIC), scenario], capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"passed": scenario}


def test_usage_log_assets_and_complete_locales():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    module = (STATIC / "chat-usage-log-module.js").read_text(encoding="utf-8")
    css = (STATIC / "chat-feedback.css").read_text(encoding="utf-8")
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert html.index("./chat-feedback-module.js") < html.index("./chat-usage-log-module.js")
    assert 'id="feedbackUsageTab"' in html and 'id="feedbackUsagePanel"' in html
    feedback = (STATIC / "chat-feedback-module.js").read_text(encoding="utf-8")
    assert "usageTab" not in (STATIC / "app.js").read_text(encoding="utf-8")
    assert "nodes.usageTab.hidden = !state.admin" in feedback
    assert 'if (view === "usage" && !state.admin) view = "own"' in feedback
    assert ".usage-metric" in css and ".usage-empty" in css and "min-height: 44px" in css
    keys = set(re.findall(r'data-locale-key="(usage-[a-z-]+)"', html))
    keys |= {"usage-" + key for key in re.findall(r'copy\("([a-z-]+)"', module)}
    for key in keys:
        assert locale.count('"' + key + '":') == 2, key
    assert '"usage-tab": "사용 일지"' in locale
