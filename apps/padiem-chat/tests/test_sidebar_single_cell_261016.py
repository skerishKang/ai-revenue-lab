"""Sidebar one-cell UI + preserved server-backed search contract (#4488).

The static browser wiring stays unchanged; no new search endpoint or auth
authority is added. These focused checks qualify the existing B62 UI-mixed
lane and avoid running unrelated model/Claw backend regression.
"""
from pathlib import Path
import re

STATIC = Path(__file__).resolve().parents[1] / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "sidebar-unified.css").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")
SEARCH = (STATIC / "conversation-search.js").read_text(encoding="utf-8")


def test_one_visual_row_has_three_distinct_keyboard_actions():
    start = HTML.index('class="sidebar-actions-row sidebar-unified-row"')
    end = HTML.index("</div>", start)
    region = HTML[start:end]
    # #5654 added the notification bell as a third row action, so the group now
    # carries three instead of two.
    assert region.count("<button") == 3
    # Every action stays keyboard-activatable: real buttons, never a div or link.
    assert region.count('type="button"') == 3
    assert region.index('id="newChatButton"') < region.index('id="sidebarSearchButton"')
    assert region.index('id="sidebarSearchButton"') < region.index('id="notificationsBellButton"')
    assert 'class="visually-hidden" data-locale-key="search"' in region
    # The bell keeps its dialog semantics rather than borrowing the search label.
    assert 'id="notificationsBellButton" type="button"' in region
    assert 'data-locale-aria-label="notification-inbox-bell"' in region
    assert 'aria-label="알림함"' in region
    assert 'aria-haspopup="dialog"' in region
    assert 'aria-controls="notificationInbox"' in region
    # The group announcement names all three actions it now contains.
    assert 'aria-label="새 채팅, 대화 검색, 알림함"' in region
    assert re.search(r"sidebar-unified-row\s*\{[^}]*gap:\s*0", CSS)
    assert ".sidebar-actions-row.sidebar-unified-row > .sidebar-search-item" in CSS


def test_search_reuses_the_signed_in_canonical_conversation_endpoint():
    assert 'const SEARCH_ENDPOINT = "/api/conversations/search"' in SEARCH
    assert 'getElementById("sidebarSearchButton")' in SEARCH
    assert 'sidebarSearchButton.addEventListener("click"' in SEARCH
    assert 'auth.historyReady === true' in SEARCH
    assert "openHit(conversation.id)" in SEARCH


def test_project_and_recent_history_keep_accessible_secondary_actions():
    for needle in (
        'row.className = "project-row"',
        'button.className = "recent-item project-item"',
        'manage.className = "project-manage"',
        "row.append(button, manage)",
        'row.className = "history-row"',
        'button.className = "recent-item history-item"',
        'actions.className = "history-actions"',
        'more.className = "history-more"',
        "row.append(button, actions)",
    ):
        assert needle in APP
    assert ".project-row, .history-row" in CSS
    assert "background: transparent !important" in CSS


def test_css_loaded_last_and_both_section_headings_start_on_same_axis():
    assert 'src="./conversation-search.js"' in HTML
    assert HTML.index('href="./sidebar-unified.css"') > HTML.index(
        'href="./shared-six-panel-frame.css"'
    )
    assert "#projectsSection .section-heading-row" in CSS
    assert "#historySection > h2" in CSS
    assert "#projectsSection .section-heading-row h2 { margin: 0; }" in CSS
    assert "#workspaceNav" not in CSS
    assert "calendarNavButton" not in CSS
    assert "connectorsNavButton" not in CSS
