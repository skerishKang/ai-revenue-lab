"""Owner sidebar: fixed desktop utilities, history-only scrollbar, mobile dual scroll."""
from _support.sidebar_history_scroll import (
    MEDIA_DESKTOP,
    MEDIA_MOBILE,
    app_facts,
    css_facts,
    markup_facts,
)


def _has_selector(facts, needle):
    return any(needle in selector for selector in facts["selectors"])


def test_new_scroll_rules_load_last_without_modifying_auth_or_handlers():
    markup = markup_facts()
    styles = markup["stylesheets"]
    assert "./sidebar-history-scroll.css" in styles
    assert styles.index("./sidebar-history-scroll.css") > styles.index("./sidebar-section-polish.css")
    assert {"historySection", "historyList"}.issubset(markup["ids"])
    assert "sidebar-bottom" in markup["classes"]
    assert "historyList historyEmpty" in markup["aria_controls"]
    app = app_facts()["tokens"]
    assert 'className = "history-actions-menu"' in app
    assert "row.append(button, actions)" in app
    assert "row.append(button, manage)" in app


def test_desktop_scrollport_and_pinned_account_are_explicit():
    facts = css_facts()
    assert MEDIA_DESKTOP in facts["media"]
    # #4905: keep the pinned layout while it fits and let the sidebar scroll
    # itself when it cannot, so history rows are not covered by the pinned stack.
    declarations = facts["declarations"]
    assert ("overflow", "hidden !important") in declarations
    assert ("overflow-y", "auto !important") in declarations
    assert _has_selector(facts, "#historySection:not([hidden])")
    assert ("flex", "1 1 auto") in declarations
    assert ("min-height", "156px") in declarations
    assert _has_selector(facts, "#historyList")
    assert ("overflow-y", "auto") in declarations
    assert _has_selector(facts, ".sidebar-bottom")
    assert ("margin-top", "auto") in declarations
    assert ("max-height", "min(32dvh, 290px)") in declarations


def test_mobile_drawer_can_scroll_both_level_and_recent_history():
    facts = css_facts()
    assert MEDIA_MOBILE in facts["media"]
    declarations = facts["declarations"]
    assert ("overflow-y", "auto !important") in declarations
    assert ("max-height", "100dvh") in declarations
    assert ("max-height", "min(44dvh, 360px)") in declarations
    assert ("overscroll-behavior-y", "contain") in declarations


def test_clean_rows_keep_secondary_actions_and_interactive_states():
    facts = css_facts()
    assert _has_selector(facts, ":is(.project-row, .history-row)")
    declarations = facts["declarations"]
    assert ("border", "0 !important") in declarations
    assert ("background", "transparent !important") in declarations
    assert _has_selector(facts, '.project-row:has(.project-item[aria-current="true"])')
    assert _has_selector(facts, '.history-row:has(.history-item[aria-current="page"])')
    assert _has_selector(facts, ":focus-within")
    assert _has_selector(facts, ".history-actions-menu")


def test_css_only_no_session_storage_or_server_modification():
    facts = css_facts()
    assert facts["storage_tokens"] == ()
    # #7187 R3 6차: --sidebar is defined in the token sheets for all themes.
    assert ("background", "var(--sidebar)") in facts["declarations"]
