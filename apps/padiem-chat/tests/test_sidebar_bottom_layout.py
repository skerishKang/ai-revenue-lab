from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
UI_POLISH = (ROOT / "static" / "padiem-chat-ui-polish.css").read_text(encoding="utf-8")


def test_settings_in_sidebar_bottom() -> None:
    assert 'id="settingsButton"' in HTML
    assert 'class="sidebar-bottom' in HTML
    sidebar_start = HTML.index('<aside class="sidebar"')
    sidebar_end = HTML.index('</aside>', sidebar_start)
    topbar_start = HTML.index('<header class="topbar"')
    topbar_end = HTML.index('</header>', topbar_start)
    sidebar_html = HTML[sidebar_start:sidebar_end]
    topbar_html = HTML[topbar_start:topbar_end]
    assert 'id="settingsButton"' in sidebar_html
    assert 'class="sidebar-bottom' in sidebar_html
    # not in topbar as prominent control
    assert 'id="settingsButton"' not in topbar_html
    assert "account-controls" not in topbar_html


def test_login_account_in_sidebar_bottom() -> None:
    assert 'id="loginButton"' in HTML
    assert 'id="accountName"' in HTML
    sidebar_start = HTML.index('<aside class="sidebar"')
    sidebar_end = HTML.index('</aside>', sidebar_start)
    topbar_start = HTML.index('<header class="topbar"')
    topbar_end = HTML.index('</header>', topbar_start)
    sidebar_html = HTML[sidebar_start:sidebar_end]
    topbar_html = HTML[topbar_start:topbar_end]
    assert 'id="loginButton"' in sidebar_html
    assert 'id="accountName"' in sidebar_html
    assert 'class="sidebar-account"' in sidebar_html or 'sidebar-bottom' in sidebar_html
    assert 'id="loginButton"' not in topbar_html


def test_topbar_not_prominent_settings_login() -> None:
    topbar_start = HTML.index('<header class="topbar"')
    topbar_end = HTML.index('</header>', topbar_start)
    topbar_html = HTML[topbar_start:topbar_end]
    composer_start = HTML.index('<div class="composer-tools"')
    composer_end = HTML.index('</div>', composer_start)
    composer_tools_html = HTML[composer_start:composer_end]
    assert "settingsButton" not in topbar_html
    assert "loginButton" not in topbar_html
    assert "accountName" not in topbar_html
    assert 'class="model-pill' not in topbar_html
    assert 'class="model-pill composer-tier-trigger"' in composer_tools_html


def test_settings_dialog_still_present() -> None:
    assert 'id="settingsDialog"' in HTML
    assert 'id="settingsCloseButton"' in HTML
    assert 'id="themePicker"' in HTML
    assert 'id="languagePicker"' in HTML


def test_login_affordance_present_and_reachable() -> None:
    assert 'id="loginButton"' in HTML
    assert HTML.count('id="loginButton"') == 1
    # button is not hidden by default structure (disabled but reachable)
    login_line = [l for l in HTML.splitlines() if 'id="loginButton"' in l][0]
    assert "<button" in login_line


def test_padiem_home_link_preserved() -> None:
    assert 'class="home-link" href="https://padiem.net/"' in HTML
    assert 'target="_blank"' in HTML
    assert 'rel="noopener"' in HTML


def test_visible_brand_remains_padiem_chat() -> None:
    brand_line = [l for l in HTML.splitlines() if 'class="brand"' in l][0]
    assert "Padiem Chat" in brand_line
    assert "PADIEM CHAT" not in brand_line


def test_padiem_home_is_final_sidebar_bottom_utility() -> None:
    start = HTML.index('<div class="sidebar-bottom"')
    end = HTML.index('</div>\n    </aside>', start)
    sidebar_bottom = HTML[start:end]
    settings_index = sidebar_bottom.index('id="settingsButton"')
    account_index = sidebar_bottom.index('class="sidebar-account')
    home_index = sidebar_bottom.index('class="home-link"')
    assert settings_index < account_index < home_index


def test_glass_home_frame_has_desktop_vertical_breathing_room() -> None:
    assert '@media (min-width: 921px)' in UI_POLISH
    assert '.app-shell[data-state="home"] .conversation' in UI_POLISH
    assert 'margin-top: 16px !important' in UI_POLISH
    assert 'margin-bottom: 16px !important' in UI_POLISH
    assert '.app-shell[data-state="home"] .composer-wrap' in UI_POLISH
    assert 'bottom: 16px !important' in UI_POLISH
    assert 'padding-bottom: 16px !important' in UI_POLISH


def test_glass_home_composer_vertical_padding_is_balanced() -> None:
    assert '.app-shell[data-state="home"] .composer {' in UI_POLISH
    assert 'padding: 12px 12px 11px !important' in UI_POLISH
    assert '.app-shell[data-state="home"] .composer textarea {' in UI_POLISH
    assert 'padding: 9px 9px 7px !important' in UI_POLISH
