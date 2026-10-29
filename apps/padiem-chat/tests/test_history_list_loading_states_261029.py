"""#6119 follow-up - a failed recent-conversation-list read is never drawn as an empty list.

**The defect this pins.** ``loadRecentConversations`` caught every read failure
and called ``clearHistoryUI()``, so a transient 1101/1102 from the Python
Worker (the same GIL race as #5479) painted "no conversations" - or hid the
section entirely - while the server still held the user's real list. The owner
saw the sidebar go blank and assumed the history was gone.

**The contract.**

1. while the read is in flight the sidebar shows its own skeleton rows, never
   a blank panel,
2. a read that produced no answer is asked one more time before anything is
   reported,
3. only a second failure draws one honest Korean row with a working retry
   button, and that row never claims the list is empty,
4. ``clearHistoryUI`` stays what it always was: the signed-out cleanup, not a
   failure renderer.
"""
from __future__ import annotations

from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "static"
APP = (BASE / "app.js").read_text(encoding="utf-8")
LOCALE = (BASE / "locale.js").read_text(encoding="utf-8")
CSS = (BASE / "history.css").read_text(encoding="utf-8")


def _load_recent_body() -> str:
    start = APP.index("async function loadRecentConversations() {")
    depth = 0
    for index in range(APP.index("{", start), len(APP)):
        char = APP[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return APP[start : index + 1]
    raise AssertionError("loadRecentConversations is never closed")


def test_the_read_is_asked_twice_before_anything_is_reported():
    body = _load_recent_body()
    assert "renderHistorySkeleton();" in body
    assert "for (let attempt = 0; attempt < 2; attempt += 1) {" in body
    assert "data = await fetchRecentConversations();" in body
    # A failure is a failure row, never the signed-out cleanup.
    assert "clearHistoryUI" not in body.split("renderHistorySkeleton();", 1)[1]


def test_the_second_failure_draws_the_retry_row_and_the_button_reloads():
    start = APP.index("function renderHistoryLoadFailed() {")
    depth = 0
    for index in range(APP.index("{", start), len(APP)):
        char = APP[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                renderer = APP[start : index + 1]
                break
    else:
        raise AssertionError("renderHistoryLoadFailed is never closed")
    assert 'row.className = "history-row history-load-failed";' in renderer
    assert 'text.textContent = uiT("history-load-failed");' in renderer
    assert 'retry.textContent = uiT("history-retry");' in renderer
    assert "void loadRecentConversations();" in renderer


def test_both_languages_ship_the_two_labels():
    assert '"history-load-failed": "대화 목록을 불러오지 못했어요"' in LOCALE
    assert '"history-retry": "다시 시도"' in LOCALE
    assert '"history-load-failed": "Couldn\'t load the conversation list."' in LOCALE
    assert '"history-retry": "Retry"' in LOCALE


def test_the_skeleton_paints_through_the_sidebar_row_wipe():
    # sidebar-history-scroll.css wipes .history-row backgrounds with
    # !important; the skeleton must out-specify it or it is invisible.
    assert "html body .app-shell .sidebar .history-row.history-skeleton {" in CSS
    rule = CSS.split("html body .app-shell .sidebar .history-row.history-skeleton {", 1)[1].split("}", 1)[0]
    assert "background:" in rule and "!important" in rule
    assert "linear-gradient(" in rule
    # The failure row reads in the sidebar's own gray, like .history-empty.
    failed_rule = CSS.split(".history-row.history-load-failed {", 1)[1].split("}", 1)[0]
    assert "#8a8f98" in failed_rule
