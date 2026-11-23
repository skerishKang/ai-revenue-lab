"""Node-only DOM contracts for the '새 소식' screen; no local service or login."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
# #8060: shipped reads live in _support; assertions stay here.
from _support.chat_news_disclosure_source import (
    app_js, conversation_module_js, index_html, locale_source, memory_module_js,
    news_css, news_harness, news_js, run_history_module_js, six_panel_css, tokens_css,
)

STATIC = Path(__file__).resolve().parents[1] / "static"
HARNESS = Path(__file__).with_name("chat_news_harness.js")


@pytest.mark.parametrize("scenario", [
    "guest_has_no_entry_and_makes_no_calls", "unread_dot_opens_list_and_marks_seen",
    "source_label_marks_each_attributed_item", "empty_list_error_and_recovery", "fixed_feedback_links_to_news_item",
    "locale_switch_rerenders_and_guest_lockout", "version_groups_newest_first_with_other_last",
    "history_is_chronological_and_separate_from_news_fixtures", "history_empty_state_when_no_entries",
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
    html = index_html()
    js = news_js()
    css = news_css()
    locale = locale_source()
    tokens = tokens_css()
    assert html.index("./chat-feedback-module.js") < html.index("./chat-news-module.js")
    assert 'href="./chat-news.css"' in html
    assert '<dialog class="news-dialog" id="newsDialog" aria-labelledby="newsTitle">' in html
    assert '<section class="news-history" aria-labelledby="newsHistoryTitle">' in html
    assert "chat-news" not in app_js()
    assert "min-height: 44px" in css and "font-size: 14px" in css
    assert "overflow-wrap: anywhere" in css and ".news-title" in css and ".news-detail" in css
    assert "background: var(--news-dialog-surface" in css
    news_surfaces = re.findall(r"^\s*--news-dialog-surface:\s*(#[0-9a-fA-F]{6});$", tokens, re.MULTILINE)
    assert len(news_surfaces) == 5
    keys = set(re.findall(r'data-locale-(?:key|aria-label)="(news-[a-z-]+)"', html))
    keys |= {"news-" + key for key in re.findall(r'copy\("([a-z-]+)"', js)}
    for key in keys:
        assert locale.count('"' + key + '":') == 2, key
    for key, label in (("news-kind-improved", "새로워진 것"), ("news-kind-fixed", "고친 것"),
                       ("news-source-ai-tester", "AI 명예회원이 알려 준 것"),
                       ("news-source-user", "사용자 의견으로 고친 것")):
        assert f'"{key}": "{label}"' in locale
    # The customer-facing naming is 'AI 명예회원'; the code identifiers
    # (feedback-ai-tester, ai_tester fields, --ai-tester option) stay as they are.
    for key, label in (("feedback-ai-tester", "AI 명예회원"),
                       ("feedback-ai-saved", "AI 명예회원 표시를 저장했습니다."),
                       ("feedback-sender-ai", "AI 명예회원 {account}")):
        assert locale.count('"' + key + '":') == 2, key
        assert f'"{key}": "{label}"' in locale
    assert "AI 테스터" not in locale and "AI tester" not in locale
    # The jump button lives in the feedback module's own label namespace.
    assert locale.count('"feedback-news-open":') == 2
    assert 'id="newsDot"' in html and "news-dot" in css


def test_history_has_verified_dates_and_no_test_fixture_data_in_operational_javascript():
    js = news_js()
    harness = news_harness()
    start = js.index("const HISTORY_EVENTS = Object.freeze([")
    end = js.index("  ]);", start) + len("  ]);")
    history = js[start:end]
    dates = re.findall(r'date: "(\d{4}-\d{2}-\d{2})"', history)
    assert len(dates) == 17
    assert dates == sorted(dates)
    assert re.search(r"#\d+", history) is None
    assert history.count("title: { ko:") == 17
    assert history.count("detail: { ko:") == 17

    fixture_markers = ("fixture history title", "fixture history detail", "2099-01-01", "987654321")
    for marker in fixture_markers:
        assert marker in harness
        assert marker not in js
    for fake_name in ("Fixture Person", "Test User", "Visual review", "visual@example.invalid"):
        assert fake_name not in history
