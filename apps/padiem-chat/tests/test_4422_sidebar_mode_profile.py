"""Presentation-only Chat/Claw hints and account disclosure safeguards."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "static"
APP = (ROOT / "app.js").read_text(encoding="utf-8")
LOCALE = (ROOT / "locale.js").read_text(encoding="utf-8")
CSS = (ROOT / "sidebar-utility.css").read_text(encoding="utf-8")
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


def test_mode_hints_reuse_canonical_buttons_and_routes():
    assert 'chatNav.dataset.modeHint = uiT("nav-chat-hint")' in APP
    assert 'clawNav.dataset.modeHint = uiT("nav-claw-hint")' in APP
    assert 'newChatButton.addEventListener("click", () => resetConversation(true))' in APP
    assert 'clawNavButton.addEventListener("click", openClawWorkspace)' in APP
    assert 'content: attr(data-mode-hint)' in CSS
    assert 'id="newChatButton"' in HTML and 'id="clawNavButton"' in HTML
    assert ".sidebar > .new-chat" in CSS
    # No extra focusable navigation entry or backend model/P01 invocation.
    assert 'document.createElement("a")' not in APP.split("const accountContainer", 1)[1].split("const historySection", 1)[0]


def test_profile_reuses_existing_login_settings_contract():
    assert 'profileToggle.id = "accountProfileButton"' in APP
    assert 'profileToggle.setAttribute("aria-controls", "settingsDialog")' in APP
    assert 'profileToggle.setAttribute("aria-haspopup", "dialog")' in APP
    assert 'profileToggle.setAttribute("aria-expanded", "false")' in APP
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
    assert '    settingsButton.click();\n  });' in APP  # direct profile click
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
    for key in ("nav-chat-hint", "nav-claw-hint", "account-profile-toggle", "account-profile-settings"):
        assert f'"{key}"' in ko
        assert f'"{key}"' in en
    assert "업무·파일" in ko
    assert "Work & files" in en
    assert 'window.addEventListener("padiem:localechange"' in APP
    assert 'profileSettingsAction.dataset.localeKey = "account-profile-settings"' in APP
    assert 'profileToggle.dataset.localeAriaLabel = "account-profile-toggle"' in APP
