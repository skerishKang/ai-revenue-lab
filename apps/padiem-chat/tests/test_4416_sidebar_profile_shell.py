"""Presentation-only desktop sidebar collapse and account avatar contract."""
from pathlib import Path
from html.parser import HTMLParser

from _android_handoff_storage_guard import assert_session_storage_is_handoff_only

BASE = Path(__file__).resolve().parents[1] / "static"
HTML = (BASE / "index.html").read_text(encoding="utf-8")
APP = (BASE / "app.js").read_text(encoding="utf-8")
#7216 R5 step 4: this contract moved into chat-auth-module.js.
MODULE = (BASE / "chat-auth-module.js").read_text(encoding="utf-8")
SIDEBAR = (BASE / "chat-sidebar-module.js").read_text(encoding="utf-8")
CSS = (BASE / "sidebar-utility.css").read_text(encoding="utf-8")
LOCALE = (BASE / "locale.js").read_text(encoding="utf-8")


class Nodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            self.elements[a["id"]] = (tag, a)


def test_desktop_controls_exist_and_are_keyboard_accessible():
    p = Nodes()
    p.feed(HTML)
    for key in ("sidebarCollapseButton", "sidebarRestoreButton"):
        tag, attrs = p.elements[key]
        assert tag == "button"
        assert attrs["type"] == "button"
        assert attrs["aria-controls"] == "sidebar"
        assert attrs["aria-expanded"] in ("true", "false")
        assert attrs["data-locale-aria-label"].startswith("sidebar-")
    assert p.elements["sidebarCollapseButton"][1]["aria-expanded"] == "true"
    assert p.elements["sidebarRestoreButton"][1]["aria-expanded"] == "false"
    # The collapse control now opens the brand row, ahead of New Chat; the
    # actions row keeps New Chat ahead of the side navigation.
    assert HTML.index('id="sidebarCollapseButton"') < HTML.index('id="newChatButton"') < HTML.index('id="clawNavButton"')
    assert "setSidebarCollapsed(true)" in APP
    assert "setSidebarCollapsed(false)" in APP
    # R5 1단계: 본문은 사이드바 모듈이 소유하고 app.js는 한 줄 전달 함수만 남긴다.
    assert "sidebarRestoreButton?.focus()" in SIDEBAR
    assert "sidebarCollapseButton?.focus()" in SIDEBAR
    assert "function setSidebarCollapsed(...a) { return sidebarModule().setSidebarCollapsed(...a); }" in APP


def test_mobile_menu_and_authority_are_unchanged():
    assert 'window.matchMedia("(max-width: 920px)").matches' in SIDEBAR
    assert 'mobileMenu.addEventListener("click", openSidebar)' in APP
    assert 'mobileClose.addEventListener("click", closeSidebar)' in APP
    assert "localStorage" not in APP
    assert "localStorage" not in SIDEBAR
    assert "sessionStorage" not in SIDEBAR
    assert_session_storage_is_handoff_only(APP)
    assert "fetch(" not in CSS.split("#4416:", 1)[1]
    assert "max-width: 920px" in CSS
    assert "min-width: 921px" in CSS
    assert "visibility: hidden;" in CSS
    assert "pointer-events: none;" in CSS


def test_auth_derived_avatar_is_safe_text_and_not_fake_account_status():
    p = Nodes()
    p.feed(HTML)
    tag, attrs = p.elements["accountAvatar"]
    assert tag == "span"
    assert attrs["aria-hidden"] == "true"
    assert "Array.from(displayName)[0]" in APP + MODULE
    assert "accountAvatar.textContent" in APP + MODULE
    assert "innerHTML" not in MODULE.split('const firstCharacter = displayName',1)[1].split('loginButton.hidden',1)[0]
    # #5479: the account area no longer disappears with the login button when
    # the session state could not be read. The rule is shared, not inlined here.
    assert 'accountContainer.hidden = presentation.accountHidden;' in APP + MODULE
    assert 'accountContainer.hidden = sessionState === "unavailable"' not in APP + MODULE
    account_button_css = CSS.rsplit(".sidebar-account .login-button {", 1)[1].split("}", 1)[0]
    assert "min-height: 44px" in account_button_css
    assert "flex: 0 0 auto" in account_button_css


def test_locale_and_scoped_layout():
    ko, en = LOCALE.split("en: {", 1)
    for key in ("sidebar-collapse", "sidebar-expand"):
        assert f'"{key}"' in ko
        assert f'"{key}"' in en
    assert 'html body .app-shell.sidebar-collapsed' in CSS
    assert "--workspace-rail: 0px" in CSS
    assert 'html[data-theme="padiem-glass"] body .app-shell.sidebar-collapsed[data-state="claw"]' in CSS
    assert "grid-template-columns: 0 minmax(0, 1fr)" in CSS
