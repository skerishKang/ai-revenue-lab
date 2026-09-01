from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def test_settings_in_sidebar_bottom() -> None:
    assert 'id="settingsButton"' in HTML
    assert 'class="sidebar-bottom' in HTML
    # settings should be inside lower-left utility area (sidebar-bottom)
    bottom_idx = HTML.index('class="sidebar-bottom"')
    bottom_area = HTML[bottom_idx : bottom_idx + 800]
    assert 'id="settingsButton"' in bottom_area
    topbar_start = HTML.index('<header class="topbar"')
    topbar_end = HTML.index('</header>', topbar_start)
    topbar_html = HTML[topbar_start:topbar_end]
    # not in topbar as prominent control
    assert 'id="settingsButton"' not in topbar_html
    assert "account-controls" not in topbar_html


def test_login_account_in_sidebar_bottom() -> None:
    assert 'id="loginButton"' in HTML
    assert 'id="accountName"' in HTML
    # both should be in lower-left utility area near sidebar-bottom, not in topbar
    assert 'class="sidebar-bottom' in HTML
    bottom_idx = HTML.index('class="sidebar-bottom"')
    # login/account should be within 800 chars after bottom start (inside bottom)
    bottom_area = HTML[bottom_idx : bottom_idx + 800]
    assert 'id="loginButton"' in bottom_area
    assert 'id="accountName"' in bottom_area
    assert 'class="sidebar-account"' in bottom_area or 'account-controls' in bottom_area
    topbar_start = HTML.index('<header class="topbar"')
    topbar_end = HTML.index('</header>', topbar_start)
    topbar_html = HTML[topbar_start:topbar_end]
    assert 'id="loginButton"' not in topbar_html


def test_topbar_not_prominent_settings_login() -> None:
    topbar_start = HTML.index('<header class="topbar"')
    topbar_end = HTML.index('</header>', topbar_start)
    topbar_html = HTML[topbar_start:topbar_end]
    assert "settingsButton" not in topbar_html
    assert "loginButton" not in topbar_html
    assert "accountName" not in topbar_html
    assert 'class="model-pill"' in topbar_html


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
