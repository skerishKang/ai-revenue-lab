"""Presentation-only Chat/Claw hints and account disclosure safeguards."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "static"
APP = (ROOT / "app.js").read_text(encoding="utf-8")
NAV = (ROOT / "chat-nav-module.js").read_text(encoding="utf-8")
LOCALE = (ROOT / "locale.js").read_text(encoding="utf-8")
CSS = (ROOT / "sidebar-utility.css").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_mode_hints_reuse_canonical_buttons_and_routes():
    # The redundant "일반 대화" hint on New Chat was removed with the actions
    # row; Claw keeps its own hint.
    assert 'chatNav.dataset.modeHint' not in APP
    assert 'nav-chat-hint' not in APP and 'nav-chat-hint' not in LOCALE
    # R5 A10: the Claw mode hint and the clawNavButton entry listener moved to
    # chat-nav-module.js (deps-prefixed); app.js keeps the wire call.
    assert 'clawNav.dataset.modeHint = deps.uiT("nav-claw-hint")' in NAV
    assert 'clawNav.dataset.modeHint' not in APP
    assert 'newChatButton.addEventListener("click", () => resetConversation(true))' in APP
    assert 'clawNavButton.addEventListener("click", openClawWorkspace)' in NAV
    assert 'navModule().wireNavEntryListeners();' in APP
    assert 'content: attr(data-mode-hint)' in CSS
    assert 'id="newChatButton"' in HTML and 'id="clawNavButton"' in HTML
    assert ".sidebar-actions-row .new-chat" in CSS
    # No extra focusable navigation entry or backend model/P01 invocation.
    assert 'document.createElement("a")' not in APP.split("const accountContainer", 1)[1].split("const historySection", 1)[0]


def test_profile_reuses_existing_login_settings_contract():
    profile_menu_module = (ROOT / "chat-profile-menu-module.js").read_text(encoding="utf-8")
    assert 'profileToggle.id = "accountProfileButton"' in APP
    # #7780: 이름·아바타는 설정 창이 아니라 프로필 메뉴를 연다. 메뉴 안 설정이
    # 기존 settingsButton으로 같은 설정 dialog를 연다(2중 설정 흐름 없음).
    assert 'profileToggle.setAttribute("aria-controls", "profileMenu")' in profile_menu_module
    assert 'profileToggle.setAttribute("aria-haspopup", "menu")' in profile_menu_module
    assert 'profileToggle.setAttribute("aria-expanded", "false")' in APP
    assert 'lastToggle.focus()' in profile_menu_module
    assert 'profileToggle.append(accountAvatar, accountName)' not in APP
    assert '.sidebar-account > .account-avatar' in CSS
    assert '.sidebar-account > .account-name' in CSS
    assert 'accountContainer?.prepend(profileToggle)' in APP
    assert 'insertBefore(profileToggle, accountAvatar)' not in APP
    capability = (ROOT / "product-capabilities.js").read_text(encoding="utf-8")
    assert "accountContainer.insertBefore(accountAvatar, accountName)" in capability
    assert "profileToggle.append(accountAvatar" not in APP
    assert 'profilePanel.hidden = true' in APP
    assert 'profileSettingsAction.type = "button"' in APP
    assert 'settingsButton.click(); // keep the existing settings-dialog authority' in APP
    assert 'PadiemChatProfileMenu?.toggle?.()' in APP  # profile toggle opens the menu
    assert 'loginButton.addEventListener("click", async () => {' in APP
    assert 'profileSettingsAction.addEventListener("click"' in APP
    assert 'if (accountContainer?.hidden) return;' in APP
    assert "closeProfilePanel();" in APP
    assert 'closeProfilePanel(true)' in APP
    assert 'min-height: 44px' in CSS.split(".sidebar-account .account-profile-toggle {",1)[1].split("}",1)[0]
    assert 'min-height: 44px' in CSS.split(".sidebar-account .account-profile-settings {",1)[1].split("}",1)[0]
    new_path = APP.split("// Presentation-only account summary.",1)[1].split("const historySection",1)[0]
    assert "fetch(" not in new_path
    assert "innerHTML" not in new_path
    assert "localStorage" not in new_path


def test_locale_hints_and_account_actions_are_translatable():
    ko, en = LOCALE.split("en: {", 1)
    for key in ("nav-claw-hint", "account-profile-toggle", "account-profile-settings"):
        assert f'"{key}"' in ko
        assert f'"{key}"' in en
    # The search button keeps the neutral "search" label; the fake
    # "coming soon" hold promise is gone from both locale tables.
    for table in (ko, en):
        assert '"search-conversation-hold"' not in table
    assert "업무·파일" in ko
    assert "Work & files" in en
    assert 'window.addEventListener("padiem:localechange"' in APP
    assert 'profileSettingsAction.dataset.localeKey = "account-profile-settings"' in APP
    assert 'profileToggle.dataset.localeAriaLabel = "account-profile-toggle"' in APP
