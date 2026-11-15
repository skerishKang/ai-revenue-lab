"""Node-only DOM contracts for the '새 소식' screen; no local service or login."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "static"
HARNESS = Path(__file__).with_name("chat_news_harness.js")


@pytest.mark.parametrize("scenario", [
    "guest_has_no_entry_and_makes_no_calls", "unread_dot_opens_list_and_marks_seen",
    "empty_list_error_and_recovery", "fixed_feedback_links_to_news_item",
    "locale_switch_rerenders_and_guest_lockout",
])
def test_news_dom_contract(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for news DOM contracts")
    result = subprocess.run([node, str(HARNESS), str(STATIC), scenario], capture_output=True,
                            text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"passed": scenario}


def test_news_assets_and_complete_locales():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "chat-news-module.js").read_text(encoding="utf-8")
    css = (STATIC / "chat-news.css").read_text(encoding="utf-8")
    locale = (STATIC / "locale.js").read_text(encoding="utf-8")
    assert html.index("./chat-feedback-module.js") < html.index("./chat-news-module.js")
    assert 'href="./chat-news.css"' in html
    assert '<dialog class="news-dialog" id="newsDialog" aria-labelledby="newsTitle">' in html
    assert "chat-news" not in (STATIC / "app.js").read_text(encoding="utf-8")
    assert "min-height: 44px" in css and "font-size: 14px" in css
    keys = set(re.findall(r'data-locale-(?:key|aria-label)="(news-[a-z-]+)"', html))
    keys |= {"news-" + key for key in re.findall(r'copy\("([a-z-]+)"', js)}
    for key in keys:
        assert locale.count('"' + key + '":') == 2, key
    for key, label in (("news-kind-improved", "새로워진 것"), ("news-kind-fixed", "고친 것"),
                       ("news-source-ai-tester", "AI 테스터가 찾아 준 것"),
                       ("news-source-user", "사용자 의견으로 고친 것")):
        assert f'"{key}": "{label}"' in locale
    # The jump button lives in the feedback module's own label namespace.
    assert locale.count('"feedback-news-open":') == 2
    assert 'id="newsDot"' in html and "news-dot" in css
