"""Owner sidebar: fixed desktop utilities, history-only scrollbar, mobile dual scroll."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "static"
CSS = (ROOT / "sidebar-history-scroll.css").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
APP = (ROOT / "app.js").read_text(encoding="utf-8")


def test_new_scroll_rules_load_last_without_modifying_auth_or_handlers():
    assert 'href="./sidebar-history-scroll.css"' in HTML
    assert HTML.index('href="./sidebar-history-scroll.css"') > HTML.index(
        'href="./sidebar-section-polish.css"')
    assert 'id="historySection"' in HTML and 'id="historyList"' in HTML
    assert 'class="sidebar-bottom"' in HTML
    assert 'aria-controls="historyList historyEmpty"' in HTML
    assert 'className = "history-actions-menu"' in APP
    assert 'row.append(button, actions)' in APP
    assert 'row.append(button, manage)' in APP


def test_desktop_scrollport_and_pinned_account_are_explicit():
    assert '@media (min-width: 921px)' in CSS
    # #4905: the owner-ordered menus plus the pinned account/home stack can exceed
    # a short desktop viewport (measured 1280x800). `overflow-y: hidden` then let
    # #historySection collapse and its rows paint under .sidebar-bottom, so every
    # row click was intercepted by the pinned stack. Keep the pinned layout while
    # it fits and let the sidebar scroll itself when it cannot.
    assert 'overflow: hidden !important;' in CSS
    assert 'overflow-y: auto !important;' in CSS
    assert '#historySection:not([hidden])' in CSS
    assert 'flex: 1 1 auto;' in CSS
    assert 'min-height: 156px;' in CSS
    assert '#historyList' in CSS
    assert 'overflow-y: auto;' in CSS
    assert '.sidebar-bottom' in CSS
    assert 'margin-top: auto;' in CSS
    assert 'max-height: min(32dvh, 290px);' in CSS


def test_mobile_drawer_can_scroll_both_level_and_recent_history():
    assert '@media (max-width: 920px)' in CSS
    assert 'overflow-y: auto !important;' in CSS
    assert 'max-height: 100dvh;' in CSS
    assert 'max-height: min(44dvh, 360px);' in CSS
    assert 'overscroll-behavior-y: contain;' in CSS


def test_clean_rows_keep_secondary_actions_and_interactive_states():
    assert ':is(.project-row, .history-row)' in CSS
    assert 'border: 0 !important;' in CSS
    assert 'background: transparent !important;' in CSS
    assert '.project-row:has(.project-item[aria-current="true"])' in CSS
    assert '.history-row:has(.history-item[aria-current="page"])' in CSS
    assert ':focus-within' in CSS
    assert '.history-actions-menu' in CSS


def test_css_only_no_session_storage_or_server_modification():
    assert 'localStorage' not in CSS
    assert 'sessionStorage' not in CSS
    assert 'background: var(--sidebar, #384551);' in CSS
