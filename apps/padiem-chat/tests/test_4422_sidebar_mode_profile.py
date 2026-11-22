"""Presentation-only Chat/Claw hints and account disclosure safeguards."""
from __future__ import annotations

# #8060 62차: 원문 읽기는 _support(sidebar_mode_source)가 담당하고 시험은
# 토큰화된 소스·파싱 CSS 선언/선택자·로케일 맵·HTML id로 단언한다.
from _support.sidebar_mode_source import (  # noqa: E402
    css_value,
    has,
    has_any,
    has_selector,
    index_ids,
    lacks,
    locale_map,
    section_lacks,
)


def test_mode_hints_reuse_canonical_buttons_and_routes():
    # The redundant "일반 대화" hint on New Chat was removed with the actions
    # row; Claw keeps its own hint.
    assert lacks("app", "chatNav.dataset.modeHint")
    ko, en = locale_map("ko"), locale_map("en")
    assert all(
        "nav-chat-hint" not in key and "nav-chat-hint" not in value
        for key, value in {**ko, **en}.items()
    )
    assert lacks("app", "nav-chat-hint")
    # R5 A10: the Claw mode hint and the clawNavButton entry listener moved to
    # chat-nav-module.js (deps-prefixed); app.js keeps the wire call.
    assert has("nav", 'clawNav.dataset.modeHint = deps.uiT("nav-claw-hint")')
    assert lacks("app", "clawNav.dataset.modeHint")
    assert has(
        "app",
        'newChatButton.addEventListener("click", () => conversationModule().resetConversation(true))',
    )
    assert has("nav", 'clawNavButton.addEventListener("click", openClawWorkspace)')
    assert has("app", "navModuleInstance.wireNavEntryListeners();")
    assert css_value("#clawNavButton[data-mode-hint]::after", "content") == "attr(data-mode-hint)"
    ids = index_ids()
    assert "newChatButton" in ids and "clawNavButton" in ids
    assert has_selector(".sidebar-actions-row .new-chat")
    # No extra focusable navigation entry or backend model/P01 invocation.
    assert section_lacks(
        "app", "const accountContainer", "const historySection", 'document.createElement("a")'
    )


def test_profile_reuses_existing_login_settings_contract():
    assert has("app", 'profileToggle.id = "accountProfileButton"')
    # #7780: 이름·아바타는 설정 창이 아니라 프로필 메뉴를 연다. 메뉴 안 설정이
    # 기존 settingsButton으로 같은 설정 dialog를 연다(2중 설정 흐름 없음).
    assert has("profile_menu", 'profileToggle.setAttribute("aria-controls", "profileMenu")')
    assert has("profile_menu", 'profileToggle.setAttribute("aria-haspopup", "menu")')
    assert has("app", 'profileToggle.setAttribute("aria-expanded", "false")')
    assert has("profile_menu", "lastToggle.focus()")
    assert lacks("app", "profileToggle.append(accountAvatar, accountName)")
    assert has_selector(".sidebar-account > .account-avatar")
    assert has_selector(".sidebar-account > .account-name")
    assert has("app", "accountContainer?.prepend(profileToggle)")
    assert lacks("app", "insertBefore(profileToggle, accountAvatar)")
    assert has("capability", "accountContainer.insertBefore(accountAvatar, accountName)")
    assert lacks("app", "profileToggle.append(accountAvatar")
    assert has_any(("app", "dialog"), "profilePanel.hidden = true")
    assert has_any(("app", "dialog"), 'profileSettingsAction.type = "button"')
    assert has_any(
        ("app", "dialog"),
        "settingsButton.click(); // keep the existing settings-dialog authority",
    )
    assert has_any(("app", "dialog"), "PadiemChatProfileMenu?.toggle?.()")
    assert has("app", "loginDialogModule().wireProfileToggle();")
    assert has("app", "loginDialogModule().wireProfileSettings();")
    assert has("app", "loginDialogModule().wireProfileDismiss();")
    assert has_any(("app", "auth"), 'deps.loginButton.addEventListener("click", async () => {')
    assert has_any(("app", "dialog"), 'profileSettingsAction.addEventListener("click"')
    assert has_any(("app", "dialog"), "if (deps.accountContainer?.hidden) return;")
    assert has("app", "closeProfilePanel();")
    assert has("app", "closeProfilePanel(true)")
    assert css_value(".sidebar-account .account-profile-toggle", "min-height") == "44px"
    assert css_value(".sidebar-account .account-profile-settings", "min-height") == "44px"
    for fragment in ("fetch(", "innerHTML", "localStorage"):
        assert section_lacks(
            "app", "// Presentation-only account summary.", "const historySection", fragment
        )


def test_locale_hints_and_account_actions_are_translatable():
    ko = locale_map("ko")
    en = locale_map("en")
    for key in ("nav-claw-hint", "account-profile-toggle", "account-profile-settings"):
        assert key in ko
        assert key in en
    # The search button keeps the neutral "search" label; the fake
    # "coming soon" hold promise is gone from both locale tables.
    assert "search-conversation-hold" not in ko
    assert "search-conversation-hold" not in en
    assert "업무·파일" in ko.values()
    assert "Work & files" in en.values()
    assert has("app", 'window.addEventListener("padiem:localechange"')
    assert has_any(
        ("app", "dialog"),
        'profileSettingsAction.dataset.localeKey = "account-profile-settings"',
    )
    assert has("app", 'profileToggle.dataset.localeAriaLabel = "account-profile-toggle"')
